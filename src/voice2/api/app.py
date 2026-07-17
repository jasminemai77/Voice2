from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from voice2 import __version__
from voice2.audio import mp3_bytes, wav_bytes
from voice2.domain import PerformanceProfile, SessionState, SpeechRequest
from voice2.orchestrator import SessionManager
from voice2.providers import ProviderRegistry
from voice2.runtime import HardwareDetector, ProfileManager, ResourceScheduler, VoiceStore


class ProfileUpdate(BaseModel):
    profile: PerformanceProfile
    custom: dict[str, object] = Field(default_factory=dict)


class SessionCreate(BaseModel):
    mode: str = "cascade"


class OpenAiSpeechRequest(BaseModel):
    model: str = "voice2-auto"
    input: str = Field(min_length=1, max_length=5000)
    voice: str | None = None
    response_format: str = Field(default="mp3", pattern="^(wav|mp3|pcm)$")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class AppState:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = data_dir
        self.registry = ProviderRegistry()
        self.hardware_detector = HardwareDetector(data_dir)
        self.hardware = self.hardware_detector.detect()
        self.profiles = ProfileManager(data_dir)
        self.scheduler = ResourceScheduler(concurrency=1, queue_limit=8)
        self.voices = VoiceStore(data_dir)
        self.sessions = SessionManager()
        self.last_selection = self.profiles.select(
            self.registry.manifests(), self.hardware
        )
        self.last_metrics: dict[str, Any] = {}
        self.metrics_history: deque[dict[str, Any]] = deque(maxlen=20)
        self.prewarm_status: dict[str, Any] = {"state": "idle"}
        self.prewarm_task: asyncio.Task[None] | None = None
        self._prewarm_lock = asyncio.Lock()

    def refresh_selection(self, requested: PerformanceProfile | None = None):
        self.hardware = self.hardware_detector.detect()
        self.last_selection = self.profiles.select(
            self.registry.manifests(), self.hardware, requested
        )
        return self.last_selection

    async def prewarm(self) -> None:
        async with self._prewarm_lock:
            selection = self.refresh_selection()
            provider = self.registry.tts(selection.provider_id)
            health = await provider.health()
            if health.get("loaded") and health.get("variant_id") == selection.variant.id:
                self.prewarm_status = {
                    "state": "ready",
                    "provider_id": selection.provider_id,
                    "variant_id": selection.variant.id,
                    "elapsed_seconds": 0.0,
                    "reused": True,
                }
                return
            self.prewarm_status = {
                "state": "warming",
                "provider_id": selection.provider_id,
                "variant_id": selection.variant.id,
            }
            started = time.perf_counter()
            try:
                async with self.scheduler.slot():
                    await self.registry.stop_all(except_id=selection.provider_id)
                    await provider.start(selection.variant)
                self.prewarm_status = {
                    "state": "ready",
                    "provider_id": selection.provider_id,
                    "variant_id": selection.variant.id,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "reused": False,
                }
            except Exception as exc:
                self.prewarm_status = {
                    "state": "error",
                    "provider_id": selection.provider_id,
                    "variant_id": selection.variant.id,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "error": str(exc),
                }

    def schedule_prewarm(self) -> None:
        if self.prewarm_task is None or self.prewarm_task.done():
            self.prewarm_task = asyncio.create_task(self.prewarm())

    def record_metrics(self, metrics: dict[str, Any]) -> None:
        self.last_metrics = metrics
        self.metrics_history.append(metrics)


def _error(status: int, code: str, message: str, details: dict | None = None) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message, "details": details or {}},
    )


def _content_type(output_format: str) -> str:
    return {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "pcm": "audio/L16",
    }[output_format]


async def _collect_audio(state: AppState, speech: SpeechRequest):
    selection = state.refresh_selection(speech.profile)
    provider = state.registry.tts(selection.provider_id)
    voice = state.voices.get(speech.voice_id)
    if speech.voice_id and voice is None:
        raise _error(404, "voice_not_found", "The requested local voice does not exist")
    manifest = provider.manifest()
    health_before = await provider.health()
    chunks = []
    started = time.perf_counter()
    first_chunk_at = None
    acquired_at = None
    async with state.scheduler.slot():
        acquired_at = time.perf_counter()
        try:
            async for chunk in provider.synthesize(speech, voice, selection.variant):
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
                chunks.append(chunk)
        except (RuntimeError, ValueError) as exc:
            raise _error(422, "synthesis_failed", str(exc)) from exc
    elapsed = time.perf_counter() - started
    audio_seconds = sum(chunk.duration_ms for chunk in chunks) / 1000
    metrics = {
        "provider_id": selection.provider_id,
        "variant_id": selection.variant.id,
        "ttfa_ms": round(((first_chunk_at or time.perf_counter()) - started) * 1000, 2),
        "inference_ttfa_ms": round(
            ((first_chunk_at or time.perf_counter()) - (acquired_at or started)) * 1000, 2
        ),
        "queue_wait_ms": round(((acquired_at or started) - started) * 1000, 2),
        "rtf": round(elapsed / audio_seconds, 4) if audio_seconds else None,
        "audio_seconds": round(audio_seconds, 3),
        "elapsed_seconds": round(elapsed, 3),
        "warm_before": bool(health_before.get("loaded")),
        "supports_audio_stream": manifest.supports_audio_stream,
        "delivery_mode": (
            "native_stream" if manifest.supports_audio_stream else "post_generation_chunks"
        ),
        "recorded_at_ms": int(time.time() * 1000),
    }
    state.record_metrics(metrics)
    return chunks, selection


async def _stream_audio(state: AppState, speech: SpeechRequest) -> AsyncIterator[bytes]:
    selection = state.refresh_selection(speech.profile)
    provider = state.registry.tts(selection.provider_id)
    voice = state.voices.get(speech.voice_id)
    if speech.voice_id and voice is None:
        raise _error(404, "voice_not_found", "The requested local voice does not exist")
    manifest = provider.manifest()
    health_before = await provider.health()
    started = time.perf_counter()
    first = None
    audio_ms = 0.0
    acquired_at = None
    async with state.scheduler.slot():
        acquired_at = time.perf_counter()
        try:
            async for chunk in provider.synthesize(speech, voice, selection.variant):
                first = first or time.perf_counter()
                audio_ms += chunk.duration_ms
                yield chunk.pcm_s16le
        except (RuntimeError, ValueError) as exc:
            raise _error(422, "synthesis_failed", str(exc)) from exc
    elapsed = time.perf_counter() - started
    state.record_metrics({
        "provider_id": selection.provider_id,
        "variant_id": selection.variant.id,
        "ttfa_ms": round(((first or time.perf_counter()) - started) * 1000, 2),
        "inference_ttfa_ms": round(
            ((first or time.perf_counter()) - (acquired_at or started)) * 1000, 2
        ),
        "queue_wait_ms": round(((acquired_at or started) - started) * 1000, 2),
        "rtf": round(elapsed / (audio_ms / 1000), 4) if audio_ms else None,
        "warm_before": bool(health_before.get("loaded")),
        "supports_audio_stream": manifest.supports_audio_stream,
        "delivery_mode": (
            "native_stream" if manifest.supports_audio_stream else "post_generation_chunks"
        ),
        "recorded_at_ms": int(time.time() * 1000),
    })


def create_app(data_dir: Path | None = None) -> FastAPI:
    root = data_dir or Path(os.getenv("VOICE2_DATA_DIR", ".voice2-data"))
    state = AppState(root.resolve())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        state.schedule_prewarm()
        yield
        if state.prewarm_task is not None and not state.prewarm_task.done():
            state.prewarm_task.cancel()
            await asyncio.gather(state.prewarm_task, return_exceptions=True)
        await state.registry.stop_all()

    app = FastAPI(
        title="Voice2 API",
        version=__version__,
        description="Hardware-adaptive local speech generation and realtime session API",
        lifespan=lifespan,
    )
    app.state.voice2 = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            payload = exc.detail
        else:
            payload = {"code": "http_error", "message": str(exc.detail), "details": {}}
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "version": __version__, "local_only": True}

    @app.get("/api/v1/providers")
    async def providers():
        return state.registry.manifests()

    @app.get("/api/v1/voices")
    async def voices():
        return state.voices.list()

    @app.post("/api/v1/voices", status_code=201)
    async def create_voice(
        name: Annotated[str, Form(min_length=1, max_length=80)],
        language: Annotated[str, Form(pattern="^(zh|en|auto)$")],
        transcript: Annotated[str, Form(min_length=1, max_length=1000)],
        consent_confirmed: Annotated[bool, Form()],
        audio: Annotated[UploadFile, File()],
    ):
        content = await audio.read()
        try:
            return state.voices.create(
                name=name,
                language=language,
                transcript=transcript,
                filename=audio.filename or "reference.wav",
                content=content,
                consent_confirmed=consent_confirmed,
            )
        except ValueError as exc:
            raise _error(422, "invalid_reference_audio", str(exc)) from exc

    @app.delete("/api/v1/voices/{voice_id}", status_code=204)
    async def delete_voice(voice_id: str):
        if not state.voices.delete(voice_id):
            raise _error(404, "voice_not_found", "The local voice does not exist")
        return Response(status_code=204)

    @app.post("/api/v1/speech")
    async def speech(payload: SpeechRequest):
        if payload.stream:
            return StreamingResponse(
                _stream_audio(state, payload),
                media_type="audio/L16",
                headers={"X-Voice2-Audio-Format": "pcm_s16le"},
            )
        chunks, selection = await _collect_audio(state, payload)
        if payload.response_format == "pcm":
            body = b"".join(chunk.pcm_s16le for chunk in chunks)
        elif payload.response_format == "mp3":
            body = await asyncio.to_thread(mp3_bytes, chunks)
        else:
            body = wav_bytes(chunks)
        return Response(
            content=body,
            media_type=_content_type(payload.response_format),
            headers={
                "X-Voice2-Provider": selection.provider_id,
                "X-Voice2-Variant": selection.variant.id,
            },
        )

    @app.post("/v1/audio/speech")
    async def openai_speech(payload: OpenAiSpeechRequest):
        translated = SpeechRequest(
            text=payload.input,
            voice_id=payload.voice,
            response_format=payload.response_format,
            speed=payload.speed,
        )
        return await speech(translated)

    @app.get("/api/v1/runtime/hardware")
    async def hardware():
        state.hardware = state.hardware_detector.detect()
        return state.hardware

    @app.get("/api/v1/runtime/profiles")
    async def profiles():
        selections = {}
        for profile in PerformanceProfile:
            if profile == PerformanceProfile.CUSTOM and not state.profiles.custom:
                continue
            try:
                selected = state.profiles.select(
                    state.registry.manifests(), state.hardware, profile
                )
                selections[profile.value] = {
                    "provider_id": selected.provider_id,
                    "variant": selected.variant,
                    "reason": selected.reason,
                    "realtime_expected": selected.realtime_expected,
                }
            except RuntimeError as exc:
                selections[profile.value] = {"error": str(exc)}
        return {"active": state.profiles.active, "profiles": selections}

    @app.put("/api/v1/runtime/profile")
    async def update_profile(payload: ProfileUpdate):
        state.profiles.set(payload.profile, payload.custom)
        selection = state.refresh_selection(payload.profile)
        state.schedule_prewarm()
        return {
            "active": payload.profile,
            "provider_id": selection.provider_id,
            "variant": selection.variant,
            "reason": selection.reason,
            "prewarm": state.prewarm_status,
        }

    @app.post("/api/v1/runtime/prewarm")
    async def prewarm():
        await state.prewarm()
        if state.prewarm_status.get("state") == "error":
            raise _error(422, "prewarm_failed", str(state.prewarm_status.get("error")))
        return state.prewarm_status

    @app.post("/api/v1/runtime/benchmark")
    async def benchmark():
        started = time.perf_counter()
        selection = state.refresh_selection()
        voices = state.voices.list()
        if selection.provider_id != "demo" and not voices:
            raise _error(
                422,
                "benchmark_voice_required",
                "Register a local reference voice before benchmarking this Provider",
            )
        payload = SpeechRequest(
            text="Voice2 性能检测。Performance check.",
            voice_id=voices[0].id if voices else None,
            response_format="pcm",
        )
        chunks, selection = await asyncio.wait_for(_collect_audio(state, payload), timeout=60)
        elapsed = time.perf_counter() - started
        return {
            "hardware_fingerprint": state.hardware.fingerprint,
            "provider_id": selection.provider_id,
            "variant_id": selection.variant.id,
            "elapsed_seconds": round(elapsed, 3),
            "audio_seconds": round(sum(item.duration_ms for item in chunks) / 1000, 3),
            "metrics": state.last_metrics,
            "note": (
                "Development signal results validate the pipeline; "
                "real model results are stored separately."
            ),
        }

    @app.get("/api/v1/runtime/status")
    async def runtime_status():
        selection = state.refresh_selection()
        provider = state.registry.tts(selection.provider_id)
        manifest = provider.manifest()
        return {
            "profile": state.profiles.active,
            "provider_id": selection.provider_id,
            "variant": selection.variant,
            "selection_reason": selection.reason,
            "realtime_expected": selection.realtime_expected,
            "queue": state.scheduler.status,
            "last_metrics": state.last_metrics,
            "metrics_history": list(state.metrics_history),
            "prewarm": state.prewarm_status,
            "provider_health": await provider.health(),
            "capabilities": {
                "supports_text_stream": manifest.supports_text_stream,
                "supports_audio_stream": manifest.supports_audio_stream,
                "supports_cancel": manifest.supports_cancel,
            },
            "exclusions": state.profiles.exclusions(
                state.registry.manifests(), state.hardware
            ),
            "hardware_fingerprint": state.hardware.fingerprint,
        }

    @app.post("/api/v1/sessions", status_code=201)
    async def create_session(payload: SessionCreate):
        try:
            session = state.sessions.create(payload.mode)
        except ValueError as exc:
            raise _error(422, "invalid_session_mode", str(exc)) from exc
        return {"id": session.id, "mode": session.mode, "state": session.state}

    @app.post("/api/v1/sessions/{session_id}/cancel")
    async def cancel_session(session_id: str):
        try:
            return state.sessions.cancel(session_id)
        except KeyError as exc:
            raise _error(404, "session_not_found", "The realtime session does not exist") from exc

    @app.get("/api/v1/sessions/{session_id}/metrics")
    async def session_metrics(session_id: str):
        try:
            session = state.sessions.get(session_id)
        except KeyError as exc:
            raise _error(404, "session_not_found", "The realtime session does not exist") from exc
        return {"state": session.state, "metrics": session.metrics}

    @app.websocket("/api/v1/realtime")
    async def realtime(websocket: WebSocket):
        await websocket.accept()
        session = state.sessions.create("cascade")
        await websocket.send_json(
            session.event("session.created", {"mode": session.mode}).model_dump(mode="json")
        )
        try:
            while True:
                incoming = await websocket.receive_json()
                event_type = incoming.get("type")
                if event_type in {"response.cancel", "session.interrupt"}:
                    outgoing = session.interrupt()
                elif event_type == "audio.input.append":
                    session.state = SessionState.LISTENING
                    outgoing = session.event(
                        "audio.input.ack", {"bytes": len(incoming.get("audio", ""))}
                    )
                elif event_type == "playback.ack":
                    outgoing = session.event("playback.ack", incoming.get("payload", {}))
                else:
                    outgoing = session.event(
                        "protocol.error", {"message": f"Unsupported event: {event_type}"}
                    )
                await websocket.send_json(outgoing.model_dump(mode="json"))
        except WebSocketDisconnect:
            return

    return app

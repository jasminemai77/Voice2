from __future__ import annotations

import asyncio
import json
import os
import struct
import subprocess
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from voice2.domain import (
    AudioChunk,
    ProviderKind,
    ProviderManifest,
    ProviderVariant,
    SpeechRequest,
    VoiceRecord,
)

from .base import TtsProvider

_FRAME_HEADER = struct.Struct("<I")


def _data_dir() -> Path:
    return Path(os.getenv("VOICE2_DATA_DIR", Path.home() / ".voice2-data"))


async def _read_frame(reader: asyncio.StreamReader) -> tuple[dict[str, Any], bytes]:
    header = await reader.readexactly(_FRAME_HEADER.size)
    metadata_size = _FRAME_HEADER.unpack(header)[0]
    if metadata_size > 1_048_576:
        raise RuntimeError("OpenVoice worker returned an oversized metadata frame")
    metadata = json.loads((await reader.readexactly(metadata_size)).decode("utf-8"))
    payload_size = int(metadata.pop("payload_bytes", 0))
    if payload_size < 0 or payload_size > 64 * 1024 * 1024:
        raise RuntimeError("OpenVoice worker returned an invalid audio payload size")
    payload = await reader.readexactly(payload_size) if payload_size else b""
    return metadata, payload


class OpenVoiceProvider(TtsProvider):
    """Experimental CPU fallback backed by pinned OpenVoice V1 weights."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._request_lock = asyncio.Lock()
        self._active_variant_id: str | None = None
        self._sample_rate = 22_050

    @property
    def runtime_python(self) -> Path:
        executable = "python.exe" if os.name == "nt" else "python"
        default = _data_dir() / "envs" / "openvoice" / (
            "Scripts" if os.name == "nt" else "bin"
        ) / executable
        return Path(os.getenv("VOICE2_OPENVOICE_PYTHON", str(default)))

    @property
    def source_path(self) -> Path:
        default = _data_dir() / "runtimes" / "OpenVoice"
        return Path(os.getenv("VOICE2_OPENVOICE_SOURCE", str(default)))

    @property
    def model_path(self) -> Path:
        default = _data_dir() / "models" / "OpenVoiceV1"
        return Path(os.getenv("VOICE2_OPENVOICE_MODEL", str(default)))

    @property
    def worker_path(self) -> Path:
        configured = os.getenv("VOICE2_OPENVOICE_WORKER")
        return Path(configured) if configured else Path(__file__).with_name("openvoice_worker.py")

    def manifest(self) -> ProviderManifest:
        enabled = os.getenv("VOICE2_ENABLE_OPENVOICE", "0") == "1"
        required = {
            "runtime": self.runtime_python,
            "source": self.source_path / "openvoice" / "api.py",
            "converter model": self.model_path
            / "checkpoints"
            / "converter"
            / "checkpoint.pth",
            "Chinese model": self.model_path
            / "checkpoints"
            / "base_speakers"
            / "ZH"
            / "checkpoint.pth",
            "English model": self.model_path
            / "checkpoints"
            / "base_speakers"
            / "EN"
            / "checkpoint.pth",
            "worker": self.worker_path,
        }
        missing = [] if enabled else ["set VOICE2_ENABLE_OPENVOICE=1"]
        missing.extend(
            f"{name} not found at {path}" for name, path in required.items() if not path.is_file()
        )
        return ProviderManifest(
            id="openvoice",
            name="OpenVoice V1 (experimental CPU fallback)",
            kind=ProviderKind.TTS,
            version="v1@c70fc8b",
            license="MIT",
            available=not missing,
            availability_reason="; ".join(missing) or None,
            languages=["zh", "en", "zh-en"],
            sample_rates=[22_050],
            formats=["pcm", "wav", "mp3"],
            supports_text_stream=False,
            supports_audio_stream=False,
            supports_cancel=True,
            supports_batch=False,
            variants=[
                ProviderVariant(
                    id="openvoice-cpu-fp32",
                    device="cpu",
                    precision="float32",
                    estimated_ram_mib=2048,
                    quality_score=0.62,
                    speed_score=0.7,
                    settings={
                        "threads": 8,
                        "chunk_ms": 500,
                        "speaker_cache_size": 8,
                        "experimental": True,
                    },
                )
            ],
        )

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while line := await stream.readline():
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    def _worker_environment(self) -> dict[str, str]:
        cache_root = _data_dir() / "cache"
        env = os.environ.copy()
        env["HF_HOME"] = str(cache_root / "huggingface")
        env["TORCH_HOME"] = str(cache_root / "torch")
        env["TEMP"] = str(cache_root / "tmp")
        env["TMP"] = str(cache_root / "tmp")
        env["NUMBA_DISABLE_JIT"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    async def _send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("OpenVoice worker is not running")
        self._process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        await self._process.stdin.drain()

    async def start(self, variant: ProviderVariant) -> None:
        if self._process is not None and self._process.returncode is None:
            if self._active_variant_id != variant.id:
                raise RuntimeError("Cannot switch OpenVoice variants while the worker is loaded")
            return
        manifest = self.manifest()
        if not manifest.available:
            raise RuntimeError(manifest.availability_reason)
        args = [
            str(self.runtime_python),
            str(self.worker_path),
            "--source",
            str(self.source_path),
            "--model-root",
            str(self.model_path),
            "--threads",
            str(int(variant.settings.get("threads", 8))),
            "--chunk-ms",
            str(int(variant.settings.get("chunk_ms", 500))),
            "--speaker-cache-size",
            str(int(variant.settings.get("speaker_cache_size", 8))),
        ]
        self._stderr_tail.clear()
        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._worker_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._process.stderr))
        try:
            timeout = float(os.getenv("VOICE2_PROVIDER_START_TIMEOUT_S", "120"))
            message, _ = await asyncio.wait_for(_read_frame(self._process.stdout), timeout=timeout)
            if message.get("type") != "ready":
                raise RuntimeError(message.get("message", "OpenVoice worker failed to start"))
            self._sample_rate = int(message.get("sample_rate", 22_050))
            self._active_variant_id = variant.id
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        process, self._process = self._process, None
        self._active_variant_id = None
        if process is not None and process.returncode is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(b'{"type":"shutdown"}\n')
                    await process.stdin.drain()
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except (TimeoutError, BrokenPipeError, ConnectionResetError):
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None

    async def health(self) -> dict[str, object]:
        running = self._process is not None and self._process.returncode is None
        return {
            "ready": running,
            "loaded": running,
            "variant_id": self._active_variant_id,
            "sample_rate": self._sample_rate,
            "mode": "post_generation_chunks",
        }

    def _worker_failure(self, exc: Exception) -> RuntimeError:
        detail = "\n".join(self._stderr_tail)[-4000:]
        suffix = f" Worker log:\n{detail}" if detail else ""
        return RuntimeError(f"OpenVoice worker stopped unexpectedly: {exc}.{suffix}")

    async def synthesize(
        self,
        request: SpeechRequest,
        voice: VoiceRecord | None,
        variant: ProviderVariant,
    ) -> AsyncIterator[AudioChunk]:
        if voice is None:
            raise ValueError("OpenVoice voice cloning requires a registered voice")
        completed = False
        async with self._request_lock:
            await self.start(variant)
            assert self._process is not None
            assert self._process.stdout is not None
            await self._send(
                {
                    "type": "synthesize",
                    "text": request.text,
                    "language": request.language,
                    "speed": request.speed,
                    "reference_path": voice.audio_path,
                    "reference_sha256": voice.audio_sha256,
                }
            )
            try:
                while True:
                    try:
                        message, payload = await _read_frame(self._process.stdout)
                    except (asyncio.IncompleteReadError, json.JSONDecodeError) as exc:
                        raise self._worker_failure(exc) from exc
                    message_type = message.get("type")
                    if message_type == "audio":
                        yield AudioChunk(
                            sequence=int(message["sequence"]),
                            sample_rate=int(message.get("sample_rate", self._sample_rate)),
                            pcm_s16le=payload,
                            duration_ms=float(message["duration_ms"]),
                        )
                    elif message_type == "complete":
                        completed = True
                        return
                    elif message_type == "error":
                        code = str(message.get("code", "runtime_error"))
                        raise RuntimeError(f"OPENVOICE_{code.upper()}: {message.get('message')}")
                    else:
                        raise RuntimeError(f"Unexpected OpenVoice worker message: {message_type}")
            finally:
                if not completed:
                    await self.stop()

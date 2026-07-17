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


def _default_runtime_python() -> Path:
    data_dir = Path(os.getenv("VOICE2_DATA_DIR", Path.home() / ".voice2-data"))
    executable = "python.exe" if os.name == "nt" else "python"
    return data_dir / "envs" / "voxcpm" / ("Scripts" if os.name == "nt" else "bin") / executable


async def _read_frame(reader: asyncio.StreamReader) -> tuple[dict[str, Any], bytes]:
    header = await reader.readexactly(_FRAME_HEADER.size)
    metadata_size = _FRAME_HEADER.unpack(header)[0]
    if metadata_size > 1_048_576:
        raise RuntimeError("VoxCPM worker returned an oversized metadata frame")
    metadata = json.loads((await reader.readexactly(metadata_size)).decode("utf-8"))
    payload_size = int(metadata.pop("payload_bytes", 0))
    if payload_size < 0 or payload_size > 64 * 1024 * 1024:
        raise RuntimeError("VoxCPM worker returned an invalid audio payload size")
    payload = await reader.readexactly(payload_size) if payload_size else b""
    return metadata, payload


class VoxCpmProvider(TtsProvider):
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._sample_rate = 16_000
        self._active_variant_id: str | None = None
        self._request_lock = asyncio.Lock()
        self._model_id = os.getenv("VOICE2_VOXCPM_MODEL", "openbmb/VoxCPM-0.5B")

    @property
    def runtime_python(self) -> Path:
        return Path(os.getenv("VOICE2_VOXCPM_PYTHON", str(_default_runtime_python())))

    @property
    def worker_path(self) -> Path:
        configured = os.getenv("VOICE2_VOXCPM_WORKER")
        return Path(configured) if configured else Path(__file__).with_name("voxcpm_worker.py")

    def manifest(self) -> ProviderManifest:
        enabled = os.getenv("VOICE2_ENABLE_VOXCPM", "0") == "1"
        runtime_exists = self.runtime_python.is_file()
        worker_exists = self.worker_path.is_file()
        available = enabled and runtime_exists and worker_exists
        missing = []
        if not enabled:
            missing.append("set VOICE2_ENABLE_VOXCPM=1")
        if not runtime_exists:
            missing.append(f"install the isolated runtime at {self.runtime_python}")
        if not worker_exists:
            missing.append(f"worker not found at {self.worker_path}")
        return ProviderManifest(
            id="voxcpm",
            name="VoxCPM 0.5B",
            kind=ProviderKind.TTS,
            version="0.5B@runtime-2.0.3",
            license="Apache-2.0",
            available=available,
            availability_reason=None if available else "; ".join(missing),
            languages=["zh", "en", "zh-en"],
            sample_rates=[16_000],
            formats=["pcm", "wav", "mp3"],
            supports_text_stream=False,
            supports_audio_stream=True,
            supports_cancel=True,
            supports_batch=False,
            variants=[
                ProviderVariant(
                    id="voxcpm-cuda-bf16",
                    device="cuda",
                    precision="bfloat16",
                    estimated_vram_mib=5120,
                    estimated_ram_mib=4096,
                    quality_score=0.88,
                    speed_score=0.82,
                    settings={"inference_timesteps": 10, "load_denoiser": False},
                ),
                ProviderVariant(
                    id="voxcpm-cpu",
                    device="cpu",
                    precision="float32",
                    estimated_ram_mib=8192,
                    quality_score=0.88,
                    speed_score=0.2,
                    settings={"inference_timesteps": 8, "load_denoiser": False},
                ),
            ],
        )

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while line := await stream.readline():
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    def _worker_environment(self) -> dict[str, str]:
        data_dir = Path(os.getenv("VOICE2_DATA_DIR", Path.home() / ".voice2-data"))
        cache_root = data_dir / "cache"
        env = os.environ.copy()
        env.setdefault("HF_HOME", str(cache_root / "huggingface"))
        env.setdefault("MODELSCOPE_CACHE", str(cache_root / "modelscope"))
        env.setdefault("TORCH_HOME", str(cache_root / "torch"))
        env["PYTHONUNBUFFERED"] = "1"
        return env

    async def _send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("VoxCPM worker is not running")
        self._process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        await self._process.stdin.drain()

    async def start(self, variant: ProviderVariant) -> None:
        if self._process is not None and self._process.returncode is None:
            if self._active_variant_id != variant.id:
                raise RuntimeError("Cannot switch VoxCPM variants while the worker is loaded")
            return
        manifest = self.manifest()
        if not manifest.available:
            raise RuntimeError(manifest.availability_reason)

        args = [
            str(self.runtime_python),
            str(self.worker_path),
            "--model",
            self._model_id,
            "--device",
            variant.device,
            "--cache-dir",
            str(Path(self._worker_environment()["HF_HOME"]) / "hub"),
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._stderr_tail.clear()
        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._worker_environment(),
            creationflags=creationflags,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._process.stderr))
        try:
            timeout = float(os.getenv("VOICE2_PROVIDER_START_TIMEOUT_S", "900"))
            message, _ = await asyncio.wait_for(_read_frame(self._process.stdout), timeout=timeout)
            if message.get("type") != "ready":
                raise RuntimeError(message.get("message", "VoxCPM worker failed to start"))
            self._sample_rate = int(message.get("sample_rate", 16_000))
            self._active_variant_id = variant.id
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        process = self._process
        self._process = None
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

    def _worker_failure(self, exc: Exception) -> RuntimeError:
        detail = "\n".join(self._stderr_tail)[-4000:]
        suffix = f" Worker log:\n{detail}" if detail else ""
        return RuntimeError(f"VoxCPM worker stopped unexpectedly: {exc}.{suffix}")

    async def synthesize(
        self,
        request: SpeechRequest,
        voice: VoiceRecord | None,
        variant: ProviderVariant,
    ) -> AsyncIterator[AudioChunk]:
        if voice is None:
            raise ValueError("VoxCPM voice cloning requires a registered voice")
        completed = False
        async with self._request_lock:
            await self.start(variant)
            assert self._process is not None
            assert self._process.stdout is not None
            await self._send(
                {
                    "type": "synthesize",
                    "text": request.text,
                    "prompt_wav_path": voice.audio_path,
                    "prompt_text": voice.transcript,
                    "seed": request.seed,
                    "cfg_value": 2.0,
                    "inference_timesteps": int(
                        variant.settings.get("inference_timesteps", 10)
                    ),
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
                        raise RuntimeError(f"VOXCPM_{code.upper()}: {message.get('message')}")
                    else:
                        raise RuntimeError(f"Unexpected VoxCPM worker message: {message_type}")
            finally:
                if not completed:
                    await self.stop()

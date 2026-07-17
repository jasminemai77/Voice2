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
        raise RuntimeError("CosyVoice worker returned an oversized metadata frame")
    metadata = json.loads((await reader.readexactly(metadata_size)).decode("utf-8"))
    payload_size = int(metadata.pop("payload_bytes", 0))
    if payload_size < 0 or payload_size > 64 * 1024 * 1024:
        raise RuntimeError("CosyVoice worker returned an invalid audio payload size")
    payload = await reader.readexactly(payload_size) if payload_size else b""
    return metadata, payload


class CosyVoiceProvider(TtsProvider):
    """Native streaming zero-shot TTS through an isolated CosyVoice worker."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=60)
        self._request_lock = asyncio.Lock()
        self._active_variant_id: str | None = None
        self._sample_rate = 22_050
        self._model_family = "cosyvoice"

    @property
    def runtime_python(self) -> Path:
        executable = "python.exe" if os.name == "nt" else "python"
        default = _data_dir() / "envs" / "cosyvoice" / (
            "Scripts" if os.name == "nt" else "bin"
        ) / executable
        return Path(os.getenv("VOICE2_COSYVOICE_PYTHON", str(default)))

    @property
    def source_path(self) -> Path:
        default = _data_dir() / "runtimes" / "CosyVoice"
        return Path(os.getenv("VOICE2_COSYVOICE_SOURCE", str(default)))

    @property
    def model_path(self) -> Path:
        default = _data_dir() / "models" / "CosyVoice-300M"
        return Path(os.getenv("VOICE2_COSYVOICE_MODEL", str(default)))

    @property
    def worker_path(self) -> Path:
        configured = os.getenv("VOICE2_COSYVOICE_WORKER")
        return Path(configured) if configured else Path(__file__).with_name("cosyvoice_worker.py")

    def _model_info(self) -> tuple[str, int, int, int, str]:
        if (self.model_path / "cosyvoice3.yaml").is_file():
            return "cosyvoice3", 24_000, 5120, 6144, "0.5B"
        if (self.model_path / "cosyvoice2.yaml").is_file():
            return "cosyvoice2", 24_000, 4800, 6144, "0.5B"
        return "cosyvoice", 22_050, 5376, 4096, "300M"

    def manifest(self) -> ProviderManifest:
        family, sample_rate, cuda_vram, ram_mib, size = self._model_info()
        enabled = os.getenv("VOICE2_ENABLE_COSYVOICE", "0") == "1"
        model_config = self.model_path / f"{family}.yaml"
        required = {
            "runtime": self.runtime_python,
            "source": self.source_path / "cosyvoice" / "cli" / "cosyvoice.py",
            "Matcha-TTS submodule": self.source_path / "third_party" / "Matcha-TTS",
            "model config": model_config,
            "LLM weights": self.model_path / "llm.pt",
            "flow weights": self.model_path / "flow.pt",
            "HiFT weights": self.model_path / "hift.pt",
            "speaker model": self.model_path / "campplus.onnx",
            "WeText cache": _data_dir()
            / "cache"
            / "modelscope"
            / "hub"
            / "pengzhendong"
            / "wetext",
            "worker": self.worker_path,
        }
        missing = [] if enabled else ["set VOICE2_ENABLE_COSYVOICE=1"]
        missing.extend(
            f"{name} not found at {path}" for name, path in required.items() if not path.exists()
        )
        return ProviderManifest(
            id="cosyvoice",
            name=f"CosyVoice {size} (native streaming)",
            kind=ProviderKind.TTS,
            version=f"{family}@isolated-runtime-v1",
            license="Apache-2.0",
            available=not missing,
            availability_reason="; ".join(missing) or None,
            languages=["zh", "en", "zh-en", "ja", "ko", "de", "es", "fr", "it", "ru"],
            sample_rates=[sample_rate],
            formats=["pcm", "wav", "mp3"],
            supports_text_stream=False,
            supports_audio_stream=True,
            supports_cancel=True,
            supports_batch=False,
            variants=[
                ProviderVariant(
                    id=f"{family}-cuda-fp16",
                    device="cuda",
                    precision="float16",
                    estimated_vram_mib=cuda_vram,
                    estimated_ram_mib=ram_mib,
                    quality_score=0.86 if size == "300M" else 0.91,
                    speed_score=0.8,
                    settings={
                        "stream": True,
                        "fp16": True,
                        "model_family": family,
                        "model_size": size,
                        "requires_device_benchmark": True,
                    },
                ),
                ProviderVariant(
                    id=f"{family}-cpu-fp32",
                    device="cpu",
                    precision="float32",
                    estimated_ram_mib=8192 if size == "300M" else 10240,
                    quality_score=0.86 if size == "300M" else 0.91,
                    speed_score=0.25,
                    settings={
                        "stream": True,
                        "fp16": False,
                        "model_family": family,
                        "model_size": size,
                    },
                ),
            ],
        )

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while line := await stream.readline():
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    def _worker_environment(self) -> dict[str, str]:
        cache_root = _data_dir() / "cache"
        env = os.environ.copy()
        env["HF_HOME"] = str(cache_root / "huggingface")
        env["MODELSCOPE_CACHE"] = str(cache_root / "modelscope")
        env["TORCH_HOME"] = str(cache_root / "torch")
        env["TEMP"] = str(cache_root / "tmp")
        env["TMP"] = str(cache_root / "tmp")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        return env

    async def _send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("CosyVoice worker is not running")
        self._process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        await self._process.stdin.drain()

    async def start(self, variant: ProviderVariant) -> None:
        if self._process is not None and self._process.returncode is None:
            if self._active_variant_id != variant.id:
                raise RuntimeError("Cannot switch CosyVoice variants while the worker is loaded")
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
            "--device",
            variant.device,
            "--precision",
            variant.precision,
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
            timeout = float(os.getenv("VOICE2_PROVIDER_START_TIMEOUT_S", "900"))
            message, _ = await asyncio.wait_for(_read_frame(self._process.stdout), timeout=timeout)
            if message.get("type") != "ready":
                raise RuntimeError(message.get("message", "CosyVoice worker failed to start"))
            self._sample_rate = int(message.get("sample_rate", manifest.sample_rates[0]))
            self._model_family = str(message.get("model_family", "cosyvoice"))
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
            "model_family": self._model_family,
            "mode": "native_audio_stream",
        }

    def _worker_failure(self, exc: Exception) -> RuntimeError:
        detail = "\n".join(self._stderr_tail)[-4000:]
        suffix = f" Worker log:\n{detail}" if detail else ""
        return RuntimeError(f"CosyVoice worker stopped unexpectedly: {exc}.{suffix}")

    async def synthesize(
        self,
        request: SpeechRequest,
        voice: VoiceRecord | None,
        variant: ProviderVariant,
    ) -> AsyncIterator[AudioChunk]:
        if voice is None:
            raise ValueError("CosyVoice voice cloning requires a registered voice")
        if not voice.transcript.strip():
            raise ValueError(
                "CosyVoice zero-shot cloning requires an accurate reference transcript"
            )
        completed = False
        async with self._request_lock:
            await self.start(variant)
            assert self._process is not None
            assert self._process.stdout is not None
            await self._send(
                {
                    "type": "synthesize",
                    "text": request.text,
                    "prompt_text": voice.transcript,
                    "prompt_wav_path": voice.audio_path,
                    "speed": request.speed,
                    "seed": request.seed,
                    "stream": True,
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
                        raise RuntimeError(f"COSYVOICE_{code.upper()}: {message.get('message')}")
                    else:
                        raise RuntimeError(f"Unexpected CosyVoice worker message: {message_type}")
            finally:
                if not completed:
                    await self.stop()

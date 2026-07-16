from __future__ import annotations

import asyncio
import importlib.util
import os
from collections.abc import AsyncIterator

import numpy as np

from voice2.domain import (
    AudioChunk,
    ProviderKind,
    ProviderManifest,
    ProviderVariant,
    SpeechRequest,
    VoiceRecord,
)

from .base import TtsProvider


class VoxCpmProvider(TtsProvider):
    def __init__(self) -> None:
        self._model = None
        self._model_id = os.getenv("VOICE2_VOXCPM_MODEL", "openbmb/VoxCPM-0.5B")

    def manifest(self) -> ProviderManifest:
        installed = importlib.util.find_spec("voxcpm") is not None
        enabled = os.getenv("VOICE2_ENABLE_VOXCPM", "0") == "1"
        return ProviderManifest(
            id="voxcpm",
            name="VoxCPM 0.5B",
            kind=ProviderKind.TTS,
            version="0.5B",
            license="Apache-2.0",
            available=installed and enabled,
            availability_reason=(
                None
                if installed and enabled
                else (
                    "Install Voice2 with the voxcpm extra and explicitly set "
                    "VOICE2_ENABLE_VOXCPM=1."
                )
            ),
            languages=["zh", "en"],
            sample_rates=[16000],
            formats=["pcm", "wav", "mp3"],
            supports_audio_stream=True,
            variants=[
                ProviderVariant(
                    id="voxcpm-cuda-fp16",
                    device="cuda",
                    precision="float16",
                    estimated_vram_mib=5120,
                    estimated_ram_mib=4096,
                    quality_score=0.88,
                    speed_score=0.82,
                    settings={"inference_timesteps": 10},
                ),
                ProviderVariant(
                    id="voxcpm-cpu",
                    device="cpu",
                    precision="float32",
                    estimated_ram_mib=8192,
                    quality_score=0.88,
                    speed_score=0.2,
                    settings={"inference_timesteps": 8},
                ),
            ],
        )

    async def start(self, variant: ProviderVariant) -> None:
        if self._model is not None:
            return
        if not self.manifest().available:
            raise RuntimeError(self.manifest().availability_reason)

        def load():
            from voxcpm import VoxCPM

            return VoxCPM.from_pretrained(self._model_id)

        self._model = await asyncio.to_thread(load)

    async def stop(self) -> None:
        self._model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    async def synthesize(
        self,
        request: SpeechRequest,
        voice: VoiceRecord | None,
        variant: ProviderVariant,
    ) -> AsyncIterator[AudioChunk]:
        await self.start(variant)
        if voice is None:
            raise ValueError("VoxCPM voice cloning requires a registered voice")

        def generate() -> np.ndarray:
            kwargs = {
                "text": request.text,
                "prompt_wav_path": voice.audio_path,
                "prompt_text": voice.transcript,
                "cfg_value": 2.0,
                "inference_timesteps": variant.settings.get("inference_timesteps", 10),
            }
            if request.seed >= 0:
                kwargs["seed"] = request.seed
            return np.asarray(self._model.generate(**kwargs), dtype=np.float32)

        audio = await asyncio.to_thread(generate)
        tts_model = getattr(self._model, "tts_model", None)
        sample_rate = int(
            getattr(self._model, "sample_rate", None)
            or getattr(tts_model, "sample_rate", 16000)
        )
        chunk_samples = int(sample_rate * 0.12)
        for sequence, start in enumerate(range(0, len(audio), chunk_samples)):
            part = np.clip(audio[start : start + chunk_samples], -1, 1)
            encoded = (part * 32767).astype("<i2").tobytes()
            yield AudioChunk(
                sequence=sequence,
                sample_rate=sample_rate,
                pcm_s16le=encoded,
                duration_ms=len(part) / sample_rate * 1000,
            )

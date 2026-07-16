from __future__ import annotations

import asyncio
import hashlib
import math
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


class DemoTtsProvider(TtsProvider):
    """Dependency-free contract provider; never presented as voice cloning."""

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            id="demo",
            name="Demo signal (development only)",
            kind=ProviderKind.TTS,
            version="1.0",
            license="Apache-2.0",
            available=True,
            availability_reason="Produces a synthetic test signal, not cloned speech.",
            languages=["zh", "en"],
            sample_rates=[24000],
            formats=["pcm", "wav", "mp3"],
            supports_text_stream=False,
            supports_audio_stream=True,
            variants=[
                ProviderVariant(
                    id="demo-cpu",
                    device="cpu",
                    precision="float32",
                    estimated_ram_mib=64,
                    quality_score=0.05,
                    speed_score=1.0,
                )
            ],
        )

    async def synthesize(
        self,
        request: SpeechRequest,
        voice: VoiceRecord | None,
        variant: ProviderVariant,
    ) -> AsyncIterator[AudioChunk]:
        del variant
        sample_rate = 24000
        text_units = max(1, len(request.text.strip()))
        duration = min(8.0, max(0.45, text_units * 0.055 / request.speed))
        total_samples = int(sample_rate * duration)
        key = f"{voice.audio_sha256 if voice else 'demo'}:{request.seed}".encode()
        frequency = 150 + int(hashlib.sha256(key).hexdigest()[:4], 16) % 120
        chunk_samples = int(sample_rate * 0.12)
        for sequence, start in enumerate(range(0, total_samples, chunk_samples)):
            count = min(chunk_samples, total_samples - start)
            t = (np.arange(count, dtype=np.float32) + start) / sample_rate
            envelope = np.minimum(1.0, np.minimum((t + 0.01) * 8, (duration - t + 0.01) * 8))
            carrier = np.sin(2 * math.pi * frequency * t)
            formant = 0.35 * np.sin(2 * math.pi * frequency * 2.15 * t)
            pcm = np.clip((carrier + formant) * envelope * 0.12, -1, 1)
            encoded = (pcm * 32767).astype("<i2").tobytes()
            yield AudioChunk(
                sequence=sequence,
                sample_rate=sample_rate,
                pcm_s16le=encoded,
                duration_ms=count / sample_rate * 1000,
            )
            await asyncio.sleep(0)


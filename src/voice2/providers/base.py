from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from voice2.domain import AudioChunk, ProviderManifest, ProviderVariant, SpeechRequest, VoiceRecord


class BaseProvider(ABC):
    @abstractmethod
    def manifest(self) -> ProviderManifest: ...

    async def start(self, variant: ProviderVariant) -> None:
        del variant

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"ready": True, "loaded": False}


class TtsProvider(BaseProvider, ABC):
    @abstractmethod
    async def synthesize(
        self,
        request: SpeechRequest,
        voice: VoiceRecord | None,
        variant: ProviderVariant,
    ) -> AsyncIterator[AudioChunk]: ...

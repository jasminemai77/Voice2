from __future__ import annotations

import asyncio
from importlib.metadata import entry_points

from voice2.domain import ProviderKind, ProviderManifest

from .base import BaseProvider, TtsProvider
from .cosyvoice import CosyVoiceProvider
from .demo import DemoTtsProvider
from .openvoice import OpenVoiceProvider
from .voxcpm import VoxCpmProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self.register(DemoTtsProvider())
        self.register(VoxCpmProvider())
        self.register(OpenVoiceProvider())
        self.register(CosyVoiceProvider())
        self._load_entry_points()

    def _load_entry_points(self) -> None:
        for point in entry_points(group="voice2.providers"):
            if point.name in self._providers:
                continue
            try:
                provider = point.load()()
                self.register(provider)
            except Exception:
                continue

    def register(self, provider: BaseProvider) -> None:
        self._providers[provider.manifest().id] = provider

    def manifests(self) -> list[ProviderManifest]:
        return [provider.manifest() for provider in self._providers.values()]

    def get(self, provider_id: str) -> BaseProvider:
        return self._providers[provider_id]

    def tts(self, provider_id: str) -> TtsProvider:
        provider = self.get(provider_id)
        if provider.manifest().kind != ProviderKind.TTS or not isinstance(provider, TtsProvider):
            raise TypeError(f"{provider_id} is not a TTS provider")
        return provider

    async def stop_all(self, except_id: str | None = None) -> None:
        await asyncio.gather(
            *(
                provider.stop()
                for provider_id, provider in self._providers.items()
                if provider_id != except_id
            ),
            return_exceptions=True,
        )

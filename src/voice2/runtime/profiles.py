from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from voice2.domain import HardwareProfile, PerformanceProfile, ProviderManifest, ProviderVariant


class BenchmarkResult(BaseModel):
    provider_id: str
    variant_id: str
    ttfa_ms: float
    rtf: float
    peak_vram_mib: int
    stable: bool
    realtime: bool


@dataclass(slots=True)
class RuntimeSelection:
    provider_id: str
    variant: ProviderVariant
    profile: PerformanceProfile
    reason: str
    realtime_expected: bool


class ProfileManager:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "runtime-profile.json"
        self.active = PerformanceProfile.AUTO
        self.custom: dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.active = PerformanceProfile(payload.get("active", "auto"))
            self.custom = payload.get("custom", {})
        except (OSError, ValueError, TypeError):
            self.active = PerformanceProfile.AUTO

    def set(self, profile: PerformanceProfile, custom: dict[str, object] | None = None) -> None:
        self.active = profile
        self.custom = custom or {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"active": profile.value, "custom": self.custom}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _fits(variant: ProviderVariant, hardware: HardwareProfile) -> bool:
        if variant.estimated_ram_mib > max(0, hardware.available_ram_mib - 2048):
            return False
        if variant.device == "cuda":
            return bool(
                hardware.gpus
                and variant.estimated_vram_mib <= max(gpu.safe_budget_mib for gpu in hardware.gpus)
            )
        return True

    def select(
        self,
        manifests: list[ProviderManifest],
        hardware: HardwareProfile,
        requested: PerformanceProfile | None = None,
    ) -> RuntimeSelection:
        profile = requested or self.active
        candidates: list[tuple[ProviderManifest, ProviderVariant]] = []
        for manifest in manifests:
            if not manifest.available:
                continue
            candidates.extend(
                (manifest, variant)
                for variant in manifest.variants
                if self._fits(variant, hardware)
            )
        if not candidates:
            raise RuntimeError("No provider variant fits the current safe hardware budget")

        if profile == PerformanceProfile.CUSTOM:
            provider_id = str(self.custom.get("provider_id", ""))
            variant_id = str(self.custom.get("variant_id", ""))
            for manifest, variant in candidates:
                if manifest.id == provider_id and variant.id == variant_id:
                    return RuntimeSelection(
                        provider_id=manifest.id,
                        variant=variant,
                        profile=profile,
                        reason=(
                            f"Custom selection {manifest.name}/{variant.id} passed "
                            "the current safe resource checks."
                        ),
                        realtime_expected=variant.speed_score >= 0.75,
                    )
            raise RuntimeError(
                "The custom provider variant is unavailable or exceeds the safe resource budget"
            )

        real_candidates = [item for item in candidates if item[0].id != "demo"]
        if real_candidates:
            candidates = real_candidates

        def score(item: tuple[ProviderManifest, ProviderVariant]):
            if profile == PerformanceProfile.FAST:
                return (item[1].speed_score, item[1].quality_score)
            if profile == PerformanceProfile.QUALITY:
                return (item[1].quality_score, item[1].speed_score)
            return (
                item[1].speed_score >= 0.75,
                item[1].quality_score * 0.55 + item[1].speed_score * 0.45,
            )
        manifest, variant = max(candidates, key=score)
        return RuntimeSelection(
            provider_id=manifest.id,
            variant=variant,
            profile=profile,
            reason=(
                f"Selected {manifest.name}/{variant.id}: fits the safe resource budget; "
                f"quality={variant.quality_score:.2f}, speed={variant.speed_score:.2f}."
            ),
            realtime_expected=variant.speed_score >= 0.75,
        )

    def exclusions(
        self, manifests: list[ProviderManifest], hardware: HardwareProfile
    ) -> list[dict[str, str]]:
        excluded: list[dict[str, str]] = []
        ram_budget = max(0, hardware.available_ram_mib - 2048)
        vram_budget = max((gpu.safe_budget_mib for gpu in hardware.gpus), default=0)
        for manifest in manifests:
            if not manifest.available:
                excluded.append(
                    {
                        "provider_id": manifest.id,
                        "reason": manifest.availability_reason or "Provider is unavailable",
                    }
                )
                continue
            for variant in manifest.variants:
                reason = None
                if variant.estimated_ram_mib > ram_budget:
                    reason = (
                        f"needs {variant.estimated_ram_mib} MiB RAM; "
                        f"safe available budget is {ram_budget} MiB"
                    )
                elif variant.device == "cuda" and not hardware.cuda_available:
                    reason = "requires CUDA, which is unavailable"
                elif variant.device == "cuda" and variant.estimated_vram_mib > vram_budget:
                    reason = (
                        f"needs {variant.estimated_vram_mib} MiB VRAM; "
                        f"safe budget is {vram_budget} MiB"
                    )
                if reason:
                    excluded.append(
                        {
                            "provider_id": manifest.id,
                            "variant_id": variant.id,
                            "reason": reason,
                        }
                    )
        return excluded

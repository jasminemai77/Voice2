from pathlib import Path

from voice2.domain import HardwareProfile, PerformanceProfile
from voice2.domain.models import GpuProfile
from voice2.providers import ProviderRegistry
from voice2.runtime import HardwareDetector, ProfileManager


def hardware(vram: int | None) -> HardwareProfile:
    gpus = []
    if vram is not None:
        gpus = [
            GpuProfile(
                index=0,
                name="Simulated NVIDIA GPU",
                total_vram_mib=vram,
                free_vram_mib=vram,
                safe_budget_mib=min(int(vram * 0.9), vram - 512),
            )
        ]
    return HardwareProfile(
        fingerprint="test",
        os="Windows",
        architecture="AMD64",
        cpu="test",
        physical_cores=6,
        logical_cores=12,
        total_ram_mib=16384,
        available_ram_mib=12000,
        disk_free_mib=100000,
        gpus=gpus,
        cuda_available=bool(gpus),
        supports_fp16=bool(gpus),
    )


def test_safe_gpu_budget_formula(tmp_path: Path):
    profile = HardwareDetector(tmp_path).detect()
    for gpu in profile.gpus:
        assert gpu.safe_budget_mib <= int(gpu.total_vram_mib * 0.9)
        assert gpu.safe_budget_mib <= gpu.free_vram_mib - 512


def test_bf16_hardware_detection_without_api_torch():
    ampere = GpuProfile(
        index=0,
        name="RTX 3060",
        total_vram_mib=6144,
        free_vram_mib=6144,
        safe_budget_mib=5017,
        compute_capability="8.6",
    )
    turing = ampere.model_copy(update={"name": "RTX 2060", "compute_capability": "7.5"})
    assert HardwareDetector._supports_bf16_hardware([ampere]) is True
    assert HardwareDetector._supports_bf16_hardware([turing]) is False


def test_auto_profile_always_has_local_demo_fallback(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    selected = manager.select(ProviderRegistry().manifests(), hardware(None))
    assert selected.provider_id == "demo"
    assert selected.variant.device == "cpu"


def test_profile_persists(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    manager.set(PerformanceProfile.FAST)
    assert ProfileManager(tmp_path).active == PerformanceProfile.FAST


def test_custom_profile_is_pinned_and_safety_checked(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    manager.set(
        PerformanceProfile.CUSTOM,
        {"provider_id": "demo", "variant_id": "demo-cpu"},
    )
    selected = manager.select(ProviderRegistry().manifests(), hardware(None))
    assert selected.profile == PerformanceProfile.CUSTOM
    assert selected.provider_id == "demo"

    manager.set(
        PerformanceProfile.CUSTOM,
        {"provider_id": "missing", "variant_id": "missing"},
    )
    try:
        manager.select(ProviderRegistry().manifests(), hardware(None))
    except RuntimeError as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("An invalid custom profile must not silently fall back")

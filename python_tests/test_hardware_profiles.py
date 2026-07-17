from pathlib import Path

import pytest

from voice2.domain import (
    HardwareProfile,
    PerformanceProfile,
    ProviderKind,
    ProviderManifest,
    ProviderVariant,
)
from voice2.domain.models import GpuProfile
from voice2.providers import ProviderRegistry
from voice2.runtime import HardwareDetector, ProfileManager
from voice2.runtime.profiles import BenchmarkResult


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


def test_hardware_fingerprint_ignores_transient_free_vram(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    detector = HardwareDetector(tmp_path)
    first_gpu = GpuProfile(
        index=0,
        name="RTX 3060",
        total_vram_mib=6144,
        free_vram_mib=5000,
        safe_budget_mib=4488,
        driver_version="527.99",
        compute_capability="8.6",
    )
    second_gpu = first_gpu.model_copy(
        update={"free_vram_mib": 3000, "safe_budget_mib": 2488}
    )
    monkeypatch.setattr(detector, "_gpus", lambda: [first_gpu])
    first = detector.detect()
    monkeypatch.setattr(detector, "_gpus", lambda: [second_gpu])
    second = detector.detect()
    assert first.fingerprint == second.fingerprint
    assert first.gpus[0].safe_budget_mib != second.gpus[0].safe_budget_mib


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


def test_auto_profile_always_has_local_demo_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("VOICE2_ENABLE_OPENVOICE", raising=False)
    monkeypatch.delenv("VOICE2_ENABLE_VOXCPM", raising=False)
    monkeypatch.delenv("VOICE2_ENABLE_COSYVOICE", raising=False)
    manager = ProfileManager(tmp_path)
    selected = manager.select(ProviderRegistry().manifests(), hardware(None))
    assert selected.provider_id == "demo"
    assert selected.variant.device == "cpu"


def test_real_provider_always_precedes_development_signal(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    demo = ProviderRegistry().get("demo").manifest()
    real = ProviderManifest(
        id="real-local",
        name="Real local TTS",
        kind=ProviderKind.TTS,
        version="1",
        license="MIT",
        available=True,
        variants=[
            ProviderVariant(
                id="real-cpu",
                device="cpu",
                precision="float32",
                estimated_ram_mib=1024,
                quality_score=0.6,
                speed_score=0.5,
            )
        ],
    )
    selected = manager.select([demo, real], hardware(None))
    assert selected.provider_id == "real-local"


def test_cosyvoice_cuda_variant_respects_dynamic_vram_budget(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    cosyvoice = ProviderManifest(
        id="cosyvoice",
        name="CosyVoice 300M",
        kind=ProviderKind.TTS,
        version="test",
        license="Apache-2.0",
        available=True,
        variants=[
            ProviderVariant(
                id="cosyvoice-cuda-fp16",
                device="cuda",
                precision="float16",
                estimated_vram_mib=5376,
                estimated_ram_mib=4096,
                speed_score=0.9,
            )
        ],
    )
    selected = manager.select([cosyvoice], hardware(8192))
    assert selected.provider_id == "cosyvoice"

    constrained = hardware(4096)
    constrained.gpus[0].safe_budget_mib = 3200
    exclusions = manager.exclusions([cosyvoice], constrained)
    assert exclusions == [
        {
            "provider_id": "cosyvoice",
            "variant_id": "cosyvoice-cuda-fp16",
            "reason": "needs 5376 MiB VRAM; safe budget is 3200 MiB",
        }
    ]


def test_failed_device_benchmark_excludes_variant(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    manifest = ProviderManifest(
        id="cosyvoice",
        name="CosyVoice",
        kind=ProviderKind.TTS,
        version="test",
        license="Apache-2.0",
        available=True,
        variants=[
            ProviderVariant(
                id="cuda",
                device="cuda",
                precision="float16",
                estimated_vram_mib=1024,
                estimated_ram_mib=1024,
            )
        ],
    )
    current = hardware(8192)
    manager.record_benchmark(
        current.fingerprint,
        BenchmarkResult(
            provider_id="cosyvoice",
            variant_id="cuda",
            peak_vram_mib=5672,
            stable=False,
            realtime=False,
            failure_reason="exceeded the safe VRAM budget before first audio",
        ),
    )
    assert manager.exclusions([manifest], current)[0]["reason"].startswith("exceeded")


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

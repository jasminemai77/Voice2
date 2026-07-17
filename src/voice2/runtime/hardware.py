from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from importlib import metadata
from pathlib import Path

import psutil

from voice2.domain.models import GpuProfile, HardwareProfile

MIB = 1024 * 1024


class HardwareDetector:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    @staticmethod
    def _package_version(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _cpu_features() -> list[str]:
        features: set[str] = set()
        if platform.system() == "Windows":
            try:
                output = subprocess.check_output(
                    ["wmic", "cpu", "get", "Caption"], text=True, timeout=2
                ).lower()
                for feature in ("avx2", "avx", "sse4"):
                    if feature in output:
                        features.add(feature)
            except (OSError, subprocess.SubprocessError):
                pass
        identifier = os.getenv("PROCESSOR_IDENTIFIER", "").lower()
        for feature in ("avx2", "avx", "sse4"):
            if feature in identifier:
                features.add(feature)
        return sorted(features)

    @staticmethod
    def _gpus() -> list[GpuProfile]:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return []
        query = (
            "index,name,memory.total,memory.free,driver_version,compute_cap,display_active"
        )
        try:
            output = subprocess.check_output(
                [
                    executable,
                    f"--query-gpu={query}",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        gpus: list[GpuProfile] = []
        for line in output.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) < 7:
                continue
            total = int(float(fields[2]))
            free = int(float(fields[3]))
            budget = max(0, min(int(total * 0.9), free - 512))
            gpus.append(
                GpuProfile(
                    index=int(fields[0]),
                    name=fields[1],
                    total_vram_mib=total,
                    free_vram_mib=free,
                    safe_budget_mib=budget,
                    driver_version=fields[4],
                    compute_capability=fields[5],
                    display_active=fields[6].lower() in {"enabled", "yes", "1"},
                )
            )
        return gpus

    @staticmethod
    def _supports_bf16_hardware(gpus: list[GpuProfile]) -> bool:
        for gpu in gpus:
            try:
                major = int(str(gpu.compute_capability).split(".", maxsplit=1)[0])
            except (TypeError, ValueError):
                continue
            if major >= 8:
                return True
        return False

    def detect(self) -> HardwareProfile:
        memory = psutil.virtual_memory()
        disk_root = self.data_dir.parent if self.data_dir.parent.exists() else Path.cwd()
        disk = shutil.disk_usage(disk_root)
        gpus = self._gpus()
        torch_version = self._package_version("torch")
        cuda_available = False
        cuda_version = None
        bf16 = self._supports_bf16_hardware(gpus)
        sdpa = False
        if torch_version:
            try:
                import torch

                cuda_available = bool(torch.cuda.is_available())
                cuda_version = torch.version.cuda
                bf16 = bool(bf16 or (cuda_available and torch.cuda.is_bf16_supported()))
                sdpa = hasattr(torch.nn.functional, "scaled_dot_product_attention")
            except (ImportError, RuntimeError):
                pass
        raw = {
            "os": platform.platform(),
            "architecture": platform.machine(),
            "cpu": platform.processor() or os.getenv("PROCESSOR_IDENTIFIER", "unknown"),
            "cores": psutil.cpu_count(logical=False) or 1,
            "logical": psutil.cpu_count(logical=True) or 1,
            "gpus": [gpu.model_dump(mode="json") for gpu in gpus],
            "torch": torch_version,
            "onnx": self._package_version("onnxruntime"),
        }
        fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:20]
        return HardwareProfile(
            fingerprint=fingerprint,
            os=raw["os"],
            architecture=raw["architecture"],
            cpu=re.sub(r"\s+", " ", str(raw["cpu"])).strip(),
            physical_cores=raw["cores"],
            logical_cores=raw["logical"],
            cpu_features=self._cpu_features(),
            total_ram_mib=int(memory.total / MIB),
            available_ram_mib=int(memory.available / MIB),
            disk_free_mib=int(disk.free / MIB),
            gpus=gpus,
            cuda_available=cuda_available or bool(gpus),
            cuda_version=cuda_version,
            torch_version=torch_version,
            onnxruntime_version=self._package_version("onnxruntime"),
            supports_fp16=bool(gpus),
            supports_bf16=bf16,
            supports_int8=True,
            supports_sdpa=sdpa,
        )

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ProviderKind(StrEnum):
    VAD = "vad"
    ASR = "asr"
    LLM = "llm"
    TTS = "tts"
    SPEECH_TO_SPEECH = "speech_to_speech"
    TOOL = "tool"
    TRANSPORT = "transport"


class SessionState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class PerformanceProfile(StrEnum):
    AUTO = "auto"
    FAST = "fast"
    QUALITY = "quality"
    CUSTOM = "custom"


class ProviderVariant(BaseModel):
    id: str
    device: str
    precision: str
    estimated_vram_mib: int = 0
    estimated_ram_mib: int = 512
    quality_score: float = Field(default=0.5, ge=0, le=1)
    speed_score: float = Field(default=0.5, ge=0, le=1)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProviderManifest(BaseModel):
    id: str
    name: str
    kind: ProviderKind
    version: str
    license: str
    available: bool
    availability_reason: str | None = None
    languages: list[str] = Field(default_factory=list)
    sample_rates: list[int] = Field(default_factory=lambda: [24000])
    formats: list[str] = Field(default_factory=lambda: ["pcm", "wav"])
    supports_text_stream: bool = False
    supports_audio_stream: bool = True
    supports_cancel: bool = True
    supports_batch: bool = False
    supports_tools: bool = False
    variants: list[ProviderVariant] = Field(default_factory=list)


class GpuProfile(BaseModel):
    index: int
    name: str
    total_vram_mib: int
    free_vram_mib: int
    safe_budget_mib: int
    driver_version: str | None = None
    compute_capability: str | None = None
    display_active: bool | None = None


class HardwareProfile(BaseModel):
    fingerprint: str
    os: str
    architecture: str
    cpu: str
    physical_cores: int
    logical_cores: int
    cpu_features: list[str] = Field(default_factory=list)
    total_ram_mib: int
    available_ram_mib: int
    disk_free_mib: int
    gpus: list[GpuProfile] = Field(default_factory=list)
    cuda_available: bool = False
    cuda_version: str | None = None
    torch_version: str | None = None
    onnxruntime_version: str | None = None
    supports_fp16: bool = False
    supports_bf16: bool = False
    supports_int8: bool = True
    supports_sdpa: bool = False
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VoiceRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    language: str
    transcript: str
    audio_path: str
    audio_sha256: str
    duration_seconds: float | None = None
    consent_confirmed: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice_id: str | None = None
    language: str = "auto"
    response_format: str = Field(default="wav", pattern="^(wav|mp3|pcm)$")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    seed: int = -1
    stream: bool = False
    profile: PerformanceProfile | None = None


class AudioChunk(BaseModel):
    sequence: int
    sample_rate: int
    channels: int = 1
    pcm_s16le: bytes
    duration_ms: float


class RealtimeEvent(BaseModel):
    type: str
    session_id: str
    turn_id: str
    sequence: int
    timestamp_ms: int
    trace_id: str
    provider_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


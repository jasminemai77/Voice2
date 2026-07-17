import io
import wave
from pathlib import Path

import numpy as np
import soundfile
from fastapi.testclient import TestClient

from voice2.api import create_app


def reference_wav(seconds: int = 5) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 16000 * seconds)
    return buffer.getvalue()


def reference_flac(seconds: int = 5) -> bytes:
    buffer = io.BytesIO()
    soundfile.write(buffer, np.zeros(16_000 * seconds), 16_000, format="FLAC")
    return buffer.getvalue()


def test_health_hardware_and_speech(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/v1/health").status_code == 200
    hardware = client.get("/api/v1/runtime/hardware")
    assert hardware.status_code == 200
    assert hardware.json()["total_ram_mib"] > 0

    speech = client.post(
        "/api/v1/speech",
        json={"text": "测试 Voice2", "response_format": "wav"},
    )
    assert speech.status_code == 200
    assert speech.headers["content-type"].startswith("audio/wav")
    assert speech.content[:4] == b"RIFF"

    status = client.get("/api/v1/runtime/status")
    assert status.status_code == 200
    runtime = status.json()
    assert runtime["last_metrics"]["queue_wait_ms"] >= 0
    assert runtime["last_metrics"]["inference_ttfa_ms"] >= 0
    assert runtime["last_metrics"]["delivery_mode"] in {
        "native_stream",
        "post_generation_chunks",
    }
    assert "supports_audio_stream" in runtime["capabilities"]
    assert isinstance(runtime["exclusions"], list)

    prewarm = client.post("/api/v1/runtime/prewarm")
    assert prewarm.status_code == 200
    assert prewarm.json()["state"] == "ready"


def test_voice_consent_and_lifecycle(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    denied = client.post(
        "/api/v1/voices",
        data={
            "name": "Test",
            "language": "zh",
            "transcript": "参考文本",
            "consent_confirmed": "false",
        },
        files={"audio": ("reference.wav", reference_wav(), "audio/wav")},
    )
    assert denied.status_code == 422

    created = client.post(
        "/api/v1/voices",
        data={
            "name": "Test",
            "language": "zh",
            "transcript": "参考文本",
            "consent_confirmed": "true",
        },
        files={"audio": ("reference.wav", reference_wav(), "audio/wav")},
    )
    assert created.status_code == 201
    assert created.json()["duration_seconds"] == 5
    voice_id = created.json()["id"]
    assert len(client.get("/api/v1/voices").json()) == 1
    assert client.delete(f"/api/v1/voices/{voice_id}").status_code == 204


def test_all_reference_formats_are_decoded_and_duration_checked(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    common = {
        "name": "Test",
        "language": "zh",
        "transcript": "reference text",
        "consent_confirmed": "true",
    }
    too_short = client.post(
        "/api/v1/voices",
        data=common,
        files={"audio": ("short.flac", reference_flac(4), "audio/flac")},
    )
    assert too_short.status_code == 422

    valid = client.post(
        "/api/v1/voices",
        data=common,
        files={"audio": ("valid.flac", reference_flac(6), "audio/flac")},
    )
    assert valid.status_code == 201
    assert valid.json()["duration_seconds"] == 6

    invalid = client.post(
        "/api/v1/voices",
        data=common,
        files={"audio": ("invalid.mp3", b"not audio", "audio/mpeg")},
    )
    assert invalid.status_code == 422

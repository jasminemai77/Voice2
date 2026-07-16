import io
import wave
from pathlib import Path

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
    voice_id = created.json()["id"]
    assert len(client.get("/api/v1/voices").json()) == 1
    assert client.delete(f"/api/v1/voices/{voice_id}").status_code == 204

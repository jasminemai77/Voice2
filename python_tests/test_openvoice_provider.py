from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from voice2.domain import ProviderVariant, SpeechRequest, VoiceRecord
from voice2.providers.openvoice import OpenVoiceProvider


def _voice(tmp_path: Path) -> VoiceRecord:
    audio = tmp_path / "reference.wav"
    audio.write_bytes(b"RIFFfake")
    return VoiceRecord(
        name="test",
        language="zh",
        transcript="test reference",
        audio_path=str(audio),
        audio_sha256="0" * 64,
        consent_confirmed=True,
    )


def _configure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, worker_source: str
) -> OpenVoiceProvider:
    worker = tmp_path / "fake_openvoice_worker.py"
    worker.write_text(worker_source, encoding="utf-8")
    source = tmp_path / "source" / "openvoice"
    source.mkdir(parents=True)
    (source / "api.py").write_text("# test", encoding="utf-8")
    model = tmp_path / "model" / "checkpoints" / "converter"
    model.mkdir(parents=True)
    (model / "checkpoint.pth").write_bytes(b"test")
    for language in ("ZH", "EN"):
        base = tmp_path / "model" / "checkpoints" / "base_speakers" / language
        base.mkdir(parents=True)
        (base / "checkpoint.pth").write_bytes(b"test")
    monkeypatch.setenv("VOICE2_ENABLE_OPENVOICE", "1")
    monkeypatch.setenv("VOICE2_OPENVOICE_PYTHON", sys.executable)
    monkeypatch.setenv("VOICE2_OPENVOICE_WORKER", str(worker))
    monkeypatch.setenv("VOICE2_OPENVOICE_SOURCE", str(source.parent))
    monkeypatch.setenv("VOICE2_OPENVOICE_MODEL", str(tmp_path / "model"))
    return OpenVoiceProvider()


def test_openvoice_requires_explicit_enablement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE2_ENABLE_OPENVOICE", raising=False)
    manifest = OpenVoiceProvider().manifest()
    assert manifest.available is False
    assert "VOICE2_ENABLE_OPENVOICE=1" in str(manifest.availability_reason)
    assert manifest.supports_audio_stream is False


@pytest.mark.asyncio
async def test_openvoice_worker_emits_ordered_pcm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _configure(
        monkeypatch,
        tmp_path,
        """
import json, struct, sys
header = struct.Struct('<I')
def emit(meta, payload=b''):
    meta['payload_bytes'] = len(payload)
    encoded = json.dumps(meta).encode()
    sys.stdout.buffer.write(header.pack(len(encoded)) + encoded + payload)
    sys.stdout.buffer.flush()
emit({'type': 'ready', 'sample_rate': 22050})
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request['type'] == 'shutdown':
        break
    first = {'type': 'audio', 'sequence': 0, 'sample_rate': 22050, 'duration_ms': 10}
    second = {'type': 'audio', 'sequence': 1, 'sample_rate': 22050, 'duration_ms': 10}
    emit(first, b'\\x00\\x00' * 220)
    emit(second, b'\\x01\\x00' * 220)
    emit({'type': 'complete'})
""",
    )
    variant = ProviderVariant(id="test-cpu", device="cpu", precision="float32")
    chunks = [
        chunk
        async for chunk in provider.synthesize(
            SpeechRequest(text="test"), _voice(tmp_path), variant
        )
    ]
    await provider.stop()
    assert [chunk.sequence for chunk in chunks] == [0, 1]
    assert all(len(chunk.pcm_s16le) == 440 for chunk in chunks)


@pytest.mark.asyncio
async def test_openvoice_oom_is_structured_and_stops_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _configure(
        monkeypatch,
        tmp_path,
        """
import json, struct, sys
header = struct.Struct('<I')
def emit(meta):
    meta['payload_bytes'] = 0
    encoded = json.dumps(meta).encode()
    sys.stdout.buffer.write(header.pack(len(encoded)) + encoded)
    sys.stdout.buffer.flush()
emit({'type': 'ready', 'sample_rate': 22050})
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request['type'] == 'shutdown':
        break
    emit({'type': 'error', 'code': 'oom', 'message': 'simulated'})
""",
    )
    variant = ProviderVariant(id="test-cpu", device="cpu", precision="float32")
    with pytest.raises(RuntimeError, match="OPENVOICE_OOM"):
        _ = [
            chunk
            async for chunk in provider.synthesize(
                SpeechRequest(text="test"), _voice(tmp_path), variant
            )
        ]
    assert provider._process is None


@pytest.mark.asyncio
async def test_openvoice_cancel_terminates_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _configure(
        monkeypatch,
        tmp_path,
        """
import json, struct, sys, time
header = struct.Struct('<I')
def emit(meta, payload=b''):
    meta['payload_bytes'] = len(payload)
    encoded = json.dumps(meta).encode()
    sys.stdout.buffer.write(header.pack(len(encoded)) + encoded + payload)
    sys.stdout.buffer.flush()
emit({'type': 'ready', 'sample_rate': 22050})
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request['type'] == 'shutdown':
        break
    emit({'type': 'audio', 'sequence': 0, 'duration_ms': 10}, b'\\x00\\x00' * 220)
    time.sleep(30)
""",
    )
    variant = ProviderVariant(id="test-cpu", device="cpu", precision="float32")
    stream = provider.synthesize(SpeechRequest(text="test"), _voice(tmp_path), variant)
    assert (await anext(stream)).sequence == 0
    await asyncio.wait_for(stream.aclose(), timeout=3.0)
    assert provider._process is None

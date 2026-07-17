from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from voice2.domain import ProviderVariant, SpeechRequest, VoiceRecord
from voice2.providers.voxcpm import VoxCpmProvider


def _voice(tmp_path: Path) -> VoiceRecord:
    audio = tmp_path / "reference.wav"
    audio.write_bytes(b"RIFFfake")
    return VoiceRecord(
        name="test",
        language="zh",
        transcript="测试参考文本",
        audio_path=str(audio),
        audio_sha256="0" * 64,
        consent_confirmed=True,
    )


def test_voxcpm_requires_explicit_enablement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE2_ENABLE_VOXCPM", raising=False)
    manifest = VoxCpmProvider().manifest()
    assert manifest.available is False
    assert "VOICE2_ENABLE_VOXCPM=1" in str(manifest.availability_reason)


@pytest.mark.asyncio
async def test_voxcpm_external_worker_streams_ordered_pcm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = tmp_path / "fake_worker.py"
    worker.write_text(
        """
import json, struct, sys
header = struct.Struct('<I')
def emit(meta, payload=b''):
    meta['payload_bytes'] = len(payload)
    encoded = json.dumps(meta).encode()
    sys.stdout.buffer.write(header.pack(len(encoded)) + encoded + payload)
    sys.stdout.buffer.flush()
emit({'type': 'ready', 'sample_rate': 16000})
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request['type'] == 'shutdown':
        break
    first = {'type': 'audio', 'sequence': 0, 'sample_rate': 16000, 'duration_ms': 10}
    second = {'type': 'audio', 'sequence': 1, 'sample_rate': 16000, 'duration_ms': 10}
    emit(first, b'\\x00\\x00' * 160)
    emit(second, b'\\x01\\x00' * 160)
    emit({'type': 'complete'})
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VOICE2_ENABLE_VOXCPM", "1")
    monkeypatch.setenv("VOICE2_VOXCPM_PYTHON", sys.executable)
    monkeypatch.setenv("VOICE2_VOXCPM_WORKER", str(worker))
    provider = VoxCpmProvider()
    variant = ProviderVariant(
        id="test-cpu", device="cpu", precision="float32", estimated_ram_mib=1
    )
    chunks = [
        chunk
        async for chunk in provider.synthesize(
            SpeechRequest(text="测试"), _voice(tmp_path), variant
        )
    ]
    await provider.stop()
    assert [chunk.sequence for chunk in chunks] == [0, 1]
    assert all(len(chunk.pcm_s16le) == 320 for chunk in chunks)


@pytest.mark.asyncio
async def test_voxcpm_oom_is_structured_and_stops_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = tmp_path / "oom_worker.py"
    worker.write_text(
        """
import json, struct, sys
header = struct.Struct('<I')
def emit(meta):
    meta['payload_bytes'] = 0
    encoded = json.dumps(meta).encode()
    sys.stdout.buffer.write(header.pack(len(encoded)) + encoded)
    sys.stdout.buffer.flush()
emit({'type': 'ready', 'sample_rate': 16000})
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request['type'] == 'shutdown':
        break
    emit({'type': 'error', 'code': 'oom', 'message': 'simulated'})
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VOICE2_ENABLE_VOXCPM", "1")
    monkeypatch.setenv("VOICE2_VOXCPM_PYTHON", sys.executable)
    monkeypatch.setenv("VOICE2_VOXCPM_WORKER", str(worker))
    provider = VoxCpmProvider()
    variant = ProviderVariant(id="test", device="cpu", precision="float32")
    with pytest.raises(RuntimeError, match="VOXCPM_OOM"):
        _ = [
            chunk
            async for chunk in provider.synthesize(
                SpeechRequest(text="测试"), _voice(tmp_path), variant
            )
        ]
    assert provider._process is None


@pytest.mark.asyncio
async def test_voxcpm_cancel_terminates_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = tmp_path / "slow_worker.py"
    worker.write_text(
        """
import json, struct, sys, time
header = struct.Struct('<I')
def emit(meta, payload=b''):
    meta['payload_bytes'] = len(payload)
    encoded = json.dumps(meta).encode()
    sys.stdout.buffer.write(header.pack(len(encoded)) + encoded + payload)
    sys.stdout.buffer.flush()
emit({'type': 'ready', 'sample_rate': 16000})
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request['type'] == 'shutdown':
        break
    emit({'type': 'audio', 'sequence': 0, 'duration_ms': 10}, b'\\x00\\x00' * 160)
    time.sleep(30)
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VOICE2_ENABLE_VOXCPM", "1")
    monkeypatch.setenv("VOICE2_VOXCPM_PYTHON", sys.executable)
    monkeypatch.setenv("VOICE2_VOXCPM_WORKER", str(worker))
    provider = VoxCpmProvider()
    variant = ProviderVariant(id="test", device="cpu", precision="float32")
    stream = provider.synthesize(SpeechRequest(text="测试"), _voice(tmp_path), variant)
    first = await anext(stream)
    assert first.sequence == 0
    await asyncio.wait_for(stream.aclose(), timeout=3.0)
    assert provider._process is None

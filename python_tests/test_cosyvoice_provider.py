from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from voice2.domain import ProviderVariant, SpeechRequest, VoiceRecord
from voice2.providers.cosyvoice import CosyVoiceProvider


def _voice(tmp_path: Path, transcript: str = "测试参考文本") -> VoiceRecord:
    audio = tmp_path / "reference.wav"
    audio.write_bytes(b"RIFFfake")
    return VoiceRecord(
        name="test",
        language="zh",
        transcript=transcript,
        audio_path=str(audio),
        audio_sha256="0" * 64,
        consent_confirmed=True,
    )


def _configure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, worker_source: str
) -> CosyVoiceProvider:
    worker = tmp_path / "fake_cosyvoice_worker.py"
    worker.write_text(worker_source, encoding="utf-8")
    source = tmp_path / "source"
    (source / "cosyvoice" / "cli").mkdir(parents=True)
    (source / "cosyvoice" / "cli" / "cosyvoice.py").write_text("# test", encoding="utf-8")
    (source / "third_party" / "Matcha-TTS").mkdir(parents=True)
    model = tmp_path / "model"
    model.mkdir()
    for name in ("cosyvoice.yaml", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx"):
        (model / name).write_bytes(b"test")
    wetext = tmp_path / "data" / "cache" / "modelscope" / "hub" / "pengzhendong" / "wetext"
    wetext.mkdir(parents=True)
    monkeypatch.setenv("VOICE2_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VOICE2_ENABLE_COSYVOICE", "1")
    monkeypatch.setenv("VOICE2_COSYVOICE_PYTHON", sys.executable)
    monkeypatch.setenv("VOICE2_COSYVOICE_WORKER", str(worker))
    monkeypatch.setenv("VOICE2_COSYVOICE_SOURCE", str(source))
    monkeypatch.setenv("VOICE2_COSYVOICE_MODEL", str(model))
    return CosyVoiceProvider()


def test_cosyvoice_requires_explicit_enablement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE2_ENABLE_COSYVOICE", raising=False)
    manifest = CosyVoiceProvider().manifest()
    assert manifest.available is False
    assert "VOICE2_ENABLE_COSYVOICE=1" in str(manifest.availability_reason)
    assert manifest.supports_audio_stream is True
    assert manifest.supports_text_stream is False


@pytest.mark.asyncio
async def test_cosyvoice_worker_emits_ordered_native_pcm(
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
emit({'type': 'ready', 'sample_rate': 22050, 'model_family': 'cosyvoice'})
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request['type'] == 'shutdown':
        break
    assert request['stream'] is True
    meta = {'type': 'audio', 'sequence': 0, 'sample_rate': 22050, 'duration_ms': 10}
    emit(meta, b'\\x00\\x00' * 220)
    meta = {'type': 'audio', 'sequence': 1, 'sample_rate': 22050, 'duration_ms': 10}
    emit(meta, b'\\x01\\x00' * 220)
    emit({'type': 'complete'})
""",
    )
    variant = ProviderVariant(id="test-cuda", device="cuda", precision="float16")
    chunks = [
        chunk
        async for chunk in provider.synthesize(
            SpeechRequest(text="这是流式测试"), _voice(tmp_path), variant
        )
    ]
    await provider.stop()
    assert [chunk.sequence for chunk in chunks] == [0, 1]
    assert all(chunk.sample_rate == 22_050 for chunk in chunks)
    assert all(len(chunk.pcm_s16le) == 440 for chunk in chunks)


@pytest.mark.asyncio
async def test_cosyvoice_requires_reference_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _configure(monkeypatch, tmp_path, "raise SystemExit(0)")
    variant = ProviderVariant(id="test", device="cpu", precision="float32")
    with pytest.raises(ValueError, match="accurate reference transcript"):
        _ = [
            chunk
            async for chunk in provider.synthesize(
                SpeechRequest(text="测试"), _voice(tmp_path, transcript=" "), variant
            )
        ]


@pytest.mark.asyncio
async def test_cosyvoice_oom_is_structured_and_stops_worker(
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
    variant = ProviderVariant(id="test", device="cuda", precision="float16")
    with pytest.raises(RuntimeError, match="COSYVOICE_OOM"):
        _ = [
            chunk
            async for chunk in provider.synthesize(
                SpeechRequest(text="测试"), _voice(tmp_path), variant
            )
        ]
    assert provider._process is None


@pytest.mark.asyncio
async def test_cosyvoice_cancel_terminates_worker(
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
    variant = ProviderVariant(id="test", device="cuda", precision="float16")
    stream = provider.synthesize(SpeechRequest(text="测试"), _voice(tmp_path), variant)
    assert (await anext(stream)).sequence == 0
    await asyncio.wait_for(stream.aclose(), timeout=3.0)
    assert provider._process is None

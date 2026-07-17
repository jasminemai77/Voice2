from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import struct
import sys
import traceback
from collections import OrderedDict
from pathlib import Path
from typing import Any, BinaryIO

_FRAME_HEADER = struct.Struct("<I")


def _emit(output: BinaryIO, metadata: dict[str, Any], payload: bytes = b"") -> None:
    envelope = dict(metadata)
    envelope["payload_bytes"] = len(payload)
    encoded = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    output.write(_FRAME_HEADER.pack(len(encoded)))
    output.write(encoded)
    output.write(payload)
    output.flush()


def _language(text: str, requested: str) -> str:
    normalized = requested.lower().replace("_", "-")
    if normalized.startswith("zh") or normalized in {"chinese", "zh-en"}:
        return "zh"
    if normalized.startswith("en") or normalized == "english":
        return "en"
    return "zh" if any("\u3400" <= char <= "\u9fff" for char in text) else "en"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--chunk-ms", type=int, default=500)
    parser.add_argument("--speaker-cache-size", type=int, default=8)
    args = parser.parse_args()
    sys.path.insert(0, args.source)
    Path(os.environ.get("TEMP", ".")).mkdir(parents=True, exist_ok=True)
    protocol = sys.stdout.buffer

    try:
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import soundfile as sf
            import torch
            from openvoice.api import BaseSpeakerTTS, OpenVoiceBaseClass, ToneColorConverter
            from openvoice.mel_processing import spectrogram_torch
            from scipy.signal import resample_poly

            torch.set_num_threads(max(1, min(args.threads, os.cpu_count() or args.threads)))
            checkpoints = Path(args.model_root) / "checkpoints"

            def load_weights(model: Any, path: Path) -> None:
                checkpoint = torch.load(path, map_location="cpu", weights_only=True)
                missing, unexpected = model.model.load_state_dict(checkpoint["model"], strict=False)
                if missing or unexpected:
                    raise RuntimeError(
                        f"checkpoint mismatch: missing={missing}, unexpected={unexpected}"
                    )

            converter = ToneColorConverter.__new__(ToneColorConverter)
            OpenVoiceBaseClass.__init__(
                converter, str(checkpoints / "converter" / "config.json"), device="cpu"
            )
            converter.watermark_model = None
            converter.version = getattr(converter.hps, "_version_", "v1")
            load_weights(converter, checkpoints / "converter" / "checkpoint.pth")

            models: dict[str, Any] = {}
            source_embeddings: dict[str, Any] = {}
            for language, folder, embedding in (
                ("zh", "ZH", "zh_default_se.pth"),
                ("en", "EN", "en_default_se.pth"),
            ):
                root = checkpoints / "base_speakers" / folder
                model = BaseSpeakerTTS(str(root / "config.json"), device="cpu")
                load_weights(model, root / "checkpoint.pth")
                models[language] = model
                source_embeddings[language] = torch.load(
                    root / embedding, map_location="cpu", weights_only=True
                )

            sample_rate = int(converter.hps.data.sampling_rate)
            target_cache: OrderedDict[str, Any] = OrderedDict()

            def load_audio(path: str, *, max_seconds: float | None = None) -> Any:
                audio, input_rate = sf.read(path, dtype="float32", always_2d=True)
                audio = audio.mean(axis=1)
                if max_seconds is not None:
                    audio = audio[: int(input_rate * max_seconds)]
                if input_rate != sample_rate:
                    divisor = math.gcd(input_rate, sample_rate)
                    audio = resample_poly(audio, sample_rate // divisor, input_rate // divisor)
                return np.asarray(audio, dtype=np.float32)

            def make_spec(audio: Any) -> Any:
                y = torch.from_numpy(audio).unsqueeze(0)
                hps = converter.hps
                return spectrogram_torch(
                    y,
                    hps.data.filter_length,
                    hps.data.sampling_rate,
                    hps.data.hop_length,
                    hps.data.win_length,
                    center=False,
                )

        _emit(protocol, {"type": "ready", "sample_rate": sample_rate})
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit(protocol, {"type": "error", "code": "load_failed", "message": str(exc)})
        return 1

    for line in sys.stdin.buffer:
        try:
            request = json.loads(line.decode("utf-8"))
            if request.get("type") == "shutdown":
                return 0
            if request.get("type") != "synthesize":
                raise ValueError(f"Unsupported command: {request.get('type')}")
            selected = _language(str(request["text"]), str(request.get("language", "auto")))
            reference_path = str(request["reference_path"])
            cache_key = str(request.get("reference_sha256") or reference_path)
            with contextlib.redirect_stdout(sys.stderr), torch.no_grad():
                target_se = target_cache.get(cache_key)
                if target_se is None:
                    reference = load_audio(reference_path, max_seconds=30.0)
                    if len(reference) < sample_rate:
                        raise ValueError(
                            "Reference audio must contain at least one second of audio"
                        )
                    reference_spec = make_spec(reference)
                    target_se = converter.model.ref_enc(
                        reference_spec.transpose(1, 2)
                    ).unsqueeze(-1)
                    target_cache[cache_key] = target_se
                    while len(target_cache) > max(1, args.speaker_cache_size):
                        target_cache.popitem(last=False)
                else:
                    target_cache.move_to_end(cache_key)
                base = models[selected].tts(
                    str(request["text"]),
                    None,
                    speaker="default",
                    language="Chinese" if selected == "zh" else "English",
                    speed=float(request.get("speed", 1.0)),
                )
                base_rate = int(models[selected].hps.data.sampling_rate)
                if base_rate != sample_rate:
                    divisor = math.gcd(base_rate, sample_rate)
                    base = resample_poly(base, sample_rate // divisor, base_rate // divisor)
                source_spec = make_spec(np.asarray(base, dtype=np.float32))
                lengths = torch.LongTensor([source_spec.size(-1)])
                audio = converter.model.voice_conversion(
                    source_spec,
                    lengths,
                    sid_src=source_embeddings[selected],
                    sid_tgt=target_se,
                    tau=0.3,
                )[0][0, 0].cpu().float().numpy()
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2", copy=False).tobytes()
            chunk_bytes = max(2, int(sample_rate * max(100, args.chunk_ms) / 1000) * 2)
            for sequence, offset in enumerate(range(0, len(pcm), chunk_bytes)):
                payload = pcm[offset : offset + chunk_bytes]
                _emit(
                    protocol,
                    {
                        "type": "audio",
                        "sequence": sequence,
                        "sample_rate": sample_rate,
                        "duration_ms": len(payload) / 2 / sample_rate * 1000,
                    },
                    payload,
                )
            _emit(protocol, {"type": "complete"})
        except (MemoryError, torch.cuda.OutOfMemoryError) as exc:
            _emit(protocol, {"type": "error", "code": "oom", "message": str(exc)})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            code = "oom" if "out of memory" in str(exc).lower() else "runtime_error"
            _emit(protocol, {"type": "error", "code": code, "message": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

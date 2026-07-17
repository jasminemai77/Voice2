from __future__ import annotations

import argparse
import contextlib
import json
import struct
import sys
import traceback
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


def _sample_rate(model: Any) -> int:
    return int(
        getattr(model, "sample_rate", None)
        or getattr(getattr(model, "tts_model", None), "sample_rate", 16_000)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--cache-dir", required=True)
    args = parser.parse_args()
    protocol = sys.stdout.buffer

    try:
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import torch
            from voxcpm import VoxCPM

            model = VoxCPM.from_pretrained(
                args.model,
                load_denoiser=False,
                cache_dir=str(Path(args.cache_dir)),
                device=args.device,
            )
        sample_rate = _sample_rate(model)
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
            kwargs = {
                "text": request["text"],
                "prompt_wav_path": request["prompt_wav_path"],
                "prompt_text": request["prompt_text"],
                "cfg_value": float(request.get("cfg_value", 2.0)),
                "inference_timesteps": int(request.get("inference_timesteps", 10)),
            }
            if int(request.get("seed", -1)) >= 0:
                kwargs["seed"] = int(request["seed"])
            with contextlib.redirect_stdout(sys.stderr):
                chunks = model.generate_streaming(**kwargs)
                for sequence, chunk in enumerate(chunks):
                    audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
                    audio = np.clip(audio, -1.0, 1.0)
                    pcm = (audio * 32767).astype("<i2", copy=False).tobytes()
                    _emit(
                        protocol,
                        {
                            "type": "audio",
                            "sequence": sequence,
                            "sample_rate": sample_rate,
                            "duration_ms": len(audio) / sample_rate * 1000,
                        },
                        pcm,
                    )
            _emit(protocol, {"type": "complete"})
        except torch.cuda.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            _emit(protocol, {"type": "error", "code": "oom", "message": str(exc)})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            _emit(protocol, {"type": "error", "code": "runtime_error", "message": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

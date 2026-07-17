from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
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


def _family(model_root: Path) -> str:
    if (model_root / "cosyvoice3.yaml").is_file():
        return "cosyvoice3"
    if (model_root / "cosyvoice2.yaml").is_file():
        return "cosyvoice2"
    return "cosyvoice"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--precision", required=True)
    args = parser.parse_args()
    protocol = sys.stdout.buffer
    source = Path(args.source).resolve()
    model_root = Path(args.model_root).resolve()
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / "third_party" / "Matcha-TTS"))

    try:
        with contextlib.redirect_stdout(sys.stderr):
            import modelscope
            import numpy as np
            import torch
            from modelscope import snapshot_download as modelscope_snapshot_download

            def local_snapshot_download(*download_args: Any, **download_kwargs: Any) -> str:
                download_kwargs["local_files_only"] = True
                return modelscope_snapshot_download(*download_args, **download_kwargs)

            modelscope.snapshot_download = local_snapshot_download
            from cosyvoice.cli.cosyvoice import AutoModel

            if args.device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA variant selected but torch.cuda.is_available() is false")
            model_family = _family(model_root)
            model_options = {
                "model_dir": str(model_root),
                "load_trt": False,
                "fp16": args.device == "cuda" and args.precision == "float16",
            }
            if model_family != "cosyvoice3":
                model_options["load_jit"] = False
            if model_family != "cosyvoice":
                model_options["load_vllm"] = False
            model = AutoModel(**model_options)
        sample_rate = int(model.sample_rate)
        _emit(
            protocol,
            {
                "type": "ready",
                "sample_rate": sample_rate,
                "model_family": model_family,
                "device": args.device,
                "precision": args.precision,
            },
        )
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
            seed = int(request.get("seed", -1))
            if seed >= 0:
                random.seed(seed)
                np.random.seed(seed)
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)
            with contextlib.redirect_stdout(sys.stderr):
                chunks = model.inference_zero_shot(
                    request["text"],
                    request["prompt_text"],
                    request["prompt_wav_path"],
                    stream=bool(request.get("stream", True)),
                    speed=float(request.get("speed", 1.0)),
                )
                for sequence, chunk in enumerate(chunks):
                    audio = chunk["tts_speech"].detach().float().cpu().numpy().reshape(-1)
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
        except (KeyError, TypeError, ValueError) as exc:
            _emit(protocol, {"type": "error", "code": "invalid_input", "message": str(exc)})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            _emit(protocol, {"type": "error", "code": "runtime_error", "message": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

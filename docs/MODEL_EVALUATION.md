# Model evaluation

VoxCPM-0.5B is the first optional adapter because it targets Chinese and English zero-shot cloning with an approximately 5 GiB VRAM class footprint. CosyVoice 300M-25Hz is the next streaming candidate. GPT-SoVITS and OpenVoice V2 remain isolated fallback research paths.

The adapter uses the pinned VoxCPM 2.0.3 runtime in an independent Python 3.10 model process. The API process never imports PyTorch or model code. `VOICE2_VOXCPM_PYTHON` selects the runtime executable and `VOICE2_VOXCPM_MODEL` remains pinned to `openbmb/VoxCPM-0.5B` by default. Provider enablement is explicit through `VOICE2_ENABLE_VOXCPM=1`; hardware selection can still reject it when the measured safe VRAM budget is below 5120 MiB.

The first local evaluation snapshot is Hugging Face revision `f67d35a3848e0bec0fdb8c33e6fc92cf293ee72f`. Its 0.5B configuration declares BF16 weights. The downloaded snapshot is kept outside Git under `G:\Voice2Data\models\VoxCPM-0.5B`; the three LFS payload hashes must match Hub metadata before use.

Evaluate every candidate on the same consented references and text set:

- Chinese, English, mixed text, numbers, names and long punctuation.
- Speaker similarity, intelligibility, naturalness, prosody and failure artifacts.
- Cold load, hot TTFA, RTF, peak RAM/VRAM, disk and model download size.
- Stream continuity, cancellation, deterministic seed behavior and 100-run stability.
- CPU-only, 4/6/8/12 GiB simulated budgets and partially occupied GPU.

Do not combine results across model versions, precisions, drivers or hardware fingerprints.

# Model evaluation

VoxCPM-0.5B is the first optional adapter because it targets Chinese and English zero-shot cloning with an approximately 5 GiB VRAM class footprint. CosyVoice 300M-25Hz is the next streaming candidate. GPT-SoVITS and OpenVoice V2 remain isolated fallback research paths.

Evaluate every candidate on the same consented references and text set:

- Chinese, English, mixed text, numbers, names and long punctuation.
- Speaker similarity, intelligibility, naturalness, prosody and failure artifacts.
- Cold load, hot TTFA, RTF, peak RAM/VRAM, disk and model download size.
- Stream continuity, cancellation, deterministic seed behavior and 100-run stability.
- CPU-only, 4/6/8/12 GiB simulated budgets and partially occupied GPU.

Do not combine results across model versions, precisions, drivers or hardware fingerprints.


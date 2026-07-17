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

## CosyVoice native-streaming adapter

The adapter pins official CosyVoice source commit `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`,
Matcha-TTS submodule `dd9105b34bf2be2230f4aa1e4769fb586a3c824e`, and the
Apache-2.0 CosyVoice-300M model revision
`24c40509c3c5ea6fe06b5f8790ff99e3714a6bee`. The 12 model files total
2,624,562,297 bytes and remain outside Git.

The Windows worker runs in an independent Python 3.10 environment with PyTorch and
torchaudio 2.3.1+cu121. It exposes upstream `stream=True` audio chunks through the same
framed worker protocol as other local Providers. ModelScope WeText resources are
downloaded during setup and forced to local-files-only during model loading and
synthesis.

On the current RTX 3060 Laptop 6 GiB device, static model loading increased GPU memory
by about 2,363 MiB. Actual generation was not safe: the full 25.4-second reference
reached about 5,859 MiB total GPU use, and a carefully aligned 7.76-second prompt still
reached 5,672 MiB before the first audio chunk. The guard terminated both runs before
OOM. TTFA, RTF and quality are therefore not reported. The manifest now reserves
5,376 MiB for this Windows CUDA variant and the local failed benchmark prevents it
from being automatically selected. CPU inference was not attempted because the
8,192 MiB estimate exceeded the available-RAM-minus-2-GiB safety budget.

## OpenVoice experimental CPU fallback

OpenVoice runtime commit `74a1d147` and the official MyShell OpenVoice V1 model commit
`c70fc8b939bd1d8213994ff7c88e32be39708271` form the first low-resource fallback. The
model repository is MIT-labelled and its Git LFS objects must pass `git lfs fsck`. It is
disabled unless `VOICE2_ENABLE_OPENVOICE=1` is set.

The Windows runtime uses Python 3.10, PyTorch 2.5.1 CPU inference, librosa 0.10.2 for
compatibility, and `NUMBA_DISABLE_JIT=1` for deterministic startup. Voice2 reads and
resamples reference audio with soundfile/scipy rather than the upstream librosa loader.
The worker loads checkpoints with `weights_only=True`, disables the optional watermark
model, and never downloads a remote model during synthesis.

One short functional run on the current machine measured a 1.632 s three-model load,
about 1.62 GiB final RSS, Chinese base RTF 0.840, English base RTF 0.411, and converter
RTF 0.445 with eight CPU threads. The target was the upstream example reference and is
not voice-quality evidence. OpenVoice V1 is non-streaming: emitted PCM chunks become
available only after synthesis and conversion complete.

The integrated API-to-worker check produced four ordered PCM chunks. A cold request
took 10.874 s for 1.741 s of audio (RTF 6.244), while the immediately following request
on the same resident worker took 1.443 s for 1.730 s of audio (RTF 0.834). This confirms
the speaker-embedding cache and resident-model path, but also makes startup prewarming
mandatory for interactive use.

A second evaluation used a consented 25.4-second real MP3 reference with an accurate
local transcript and Chinese, numeric, English and repeated Chinese prompts. All nine
requests succeeded. The eight hot requests had mean RTF 0.775 and maximum RTF 0.884;
the cold request had RTF 3.528. Model-internal speaker-embedding cosine similarity had
mean 0.8944 and minimum 0.8712. This diagnostic helps catch regressions but is not a
substitute for blinded listening, intelligibility, naturalness, or impersonation-risk
review. Private inputs, generated samples and the detailed report remain outside Git.

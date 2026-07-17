# Hardware and performance

## OpenVoice experimental CPU fallback

The fallback reserves 2048 MiB RAM and uses at most eight CPU inference threads by
default. Its initial short functional benchmark reached RTF 0.840 for Chinese base
synthesis, 0.411 for English base synthesis, and 0.445 for tone conversion. These are
single-run measurements, not P95 acceptance results. The Provider advertises
`supports_audio_stream=false` because chunking occurs after full synthesis; it must not
be selected when true low-TTFA streaming is required.

Application startup warms the selected Provider asynchronously without delaying the
UI. Manual prewarming is also available through the runtime API and performance panel.
The first integrated cross-process check measured a 10.874-second cold request and a
1.443-second hot request on the same resident worker. The hot request generated 1.730
seconds of audio for RTF 0.834. Post-generation PCM chunking does not count as model
streaming or low TTFA.

Voice2 detects current free resources at selection time. It does not assume all cards
with the same name have the same usable capacity.

- GPU safe budget: `min(total VRAM x 90%, current free VRAM - 512 MiB)`.
- System RAM retains a 2 GiB reserve.
- Variants that do not fit are filtered before loading.
- RTX 3060 6 GiB defaults to one active inference request and a bounded queue of eight.
- `Auto` prefers stable realtime candidates then quality; `Fast` ranks speed;
  `Quality` ranks quality; `Custom` remains safety checked.
- A real local Provider always precedes the development signal when it fits the safe
  budget. The demo remains an explicit custom choice and last-resort development path.

The short benchmark validates the pipeline and reports TTFA/RTF. The demo signal is not
valid evidence of voice quality or model speed. Production claims require cold/hot
measurements with a real Provider, representative Chinese/English/mixed text, peak
VRAM sampling, 100-run reliability, interruption latency, and a 30-minute soak test.

If no stable local variant reaches `RTF <= 1`, show the measured fastest result as
non-realtime. Never silently use a remote service.

## Consented real-reference snapshot

A local 25.4-second MP3 reference was evaluated without committing the source,
transcript, generated audio, or report. Nine of nine requests succeeded with ordered
chunks and no clipped samples. Excluding the cold request, hot RTF averaged 0.775 and
the slowest hot run was 0.884. The cold Chinese run had RTF 3.528. Hot first-audio
latency averaged 3.20 seconds, so this fallback meets the short-run throughput target
on the current CPU but not the interactive TTFA target.

One later lifecycle verification confirmed that startup selected OpenVoice rather than
the development signal, completed prewarming in 9.814 seconds, and served the first
request from a loaded worker. That short request measured RTF 1.190, demonstrating why
the UI reports each observation and does not infer realtime performance from a mean.
These are engineering measurements on one hardware fingerprint, not P95 acceptance or
voice-quality claims.

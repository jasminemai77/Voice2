# Hardware and performance

Voice2 detects current free resources at selection time. It does not assume all cards with the same name have the same usable capacity.

- GPU safe budget: `min(total VRAM × 90%, current free VRAM − 512 MiB)`.
- System RAM retains a 2 GiB reserve.
- Variants that do not fit are filtered before loading.
- RTX 3060 6 GiB defaults to one active inference request and a bounded queue of eight.
- `Auto` prefers stable realtime candidates then quality; `Fast` ranks speed; `Quality` ranks quality; `Custom` remains safety checked.

The current short benchmark validates the pipeline and reports TTFA/RTF. The demo signal is not valid evidence of voice quality or model speed. Production claims require cold/hot measurements with a real Provider, representative Chinese/English/mixed text, peak VRAM sampling, 100-run reliability, interruption latency, and a 30-minute soak test.

If no stable local variant reaches `RTF ≤ 1`, show the measured fastest result as non-realtime. Never silently use a remote service.


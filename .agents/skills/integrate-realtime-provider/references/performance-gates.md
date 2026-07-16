# Performance and resource gates

Use current-device measurements; GPU model names alone are not evidence.

## Safe budgets

- GPU: `min(total VRAM × 90%, current free VRAM − 512 MiB)`; add margin on an active display GPU.
- Reserve at least 2 GiB of system RAM.
- Default concurrency is one on a 6 GiB GPU. Extra work waits in a bounded fair queue.

## RTX 3060 6 GiB target

- Hot first playable audio P95 below 2 seconds.
- RTF P95 at or below 1.0 for 5–20 second outputs.
- 100-run success rate at least 99%.
- Interrupt-to-silence P95 below 150 ms.
- No sustained backlog, crosstalk, late cancelled audio, or OOM during a 30-minute session.

If no stable configuration reaches realtime, select the measured fastest local variant and mark it non-realtime. Never claim quality or latency from the development signal Provider.


# Voice2 Agent instructions

## Scope and architecture

- Preserve the modular monolith, independent model processes, and asynchronous event pipeline direction.
- `domain` contains framework-free data and events. It must not import FastAPI, model runtimes, or Provider adapters.
- `orchestrator` owns state, cancellation, interruption, backpressure, and Provider coordination.
- `providers` adapt external runtimes. Providers never call one another directly.
- `runtime` owns hardware detection, safe budgets, model lifecycle, scheduling, and benchmark persistence.
- `api` translates versioned HTTP/WebSocket contracts only. Keep business decisions outside route handlers when they grow.
- `clients`/`app` consume public APIs and must not access model files directly.

## Resource and privacy rules

- Reserve at least 2 GiB RAM. GPU safe budget is `min(total × 90%, free − 512 MiB)` before additional display margin.
- A single 6 GiB GPU defaults to concurrency one and a bounded queue.
- Never silently upload reference audio, call remote TTS, or enable a remote Provider.
- Never switch models or precision during an active stream. Stop a streaming OOM; retry non-streaming at most once with a validated local fallback.
- Label Fake and demo output. Do not report it as speech quality evidence.

## Provider changes

Use `.agents/skills/integrate-realtime-provider/SKILL.md`. Every Provider requires license review, a complete manifest, safe resource variants, contract tests, real-device benchmarks, and documentation updates.

## Quality gates

```powershell
python -m pytest
python -m ruff check .
npm run lint
npm test
```

Run targeted tests first, then the full suite. Do not commit models, audio, secrets, local databases, tuning caches, benchmark outputs, generated installers, or Python/Node/Rust build products.


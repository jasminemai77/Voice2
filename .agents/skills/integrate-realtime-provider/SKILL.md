---
name: integrate-realtime-provider
description: Integrate or update Voice2 VAD, ASR, LLM, TTS, speech-to-speech, tool, or transport providers. Use when adding Provider adapters, manifests, runtime variants, streaming or cancellation behavior, hardware estimates, benchmarks, licensing records, or Provider contract tests under src/voice2/providers.
---

# Integrate Realtime Provider

Add providers without coupling model code to the orchestrator, API, or other providers. Preserve local-first behavior, bounded resources, cancellation, and truthful performance reporting.

## Workflow

1. Read `references/provider-contract.md` and `references/performance-gates.md`.
2. Verify upstream code and model licenses. Record runtime and weight licenses in `THIRD_PARTY_NOTICES.md`. Do not bundle noncommercial weights in a default install.
3. Implement a lazy adapter in `src/voice2/providers/`. Keep heavy or optional imports inside `start()` or equivalent lazy paths.
4. Return a complete `ProviderManifest`. Declare languages, formats, streaming and cancellation capabilities, backend constraints, and resource variants. Never mark a Provider available unless dependency and explicit enablement conditions are satisfied.
5. Register the adapter through the `voice2.providers` Python entry-point group. Do not add Provider-specific branches to the orchestrator or API.
6. Enforce the shared `ResourceScheduler`. Do not allocate GPU memory before the scheduler grants a slot. Make cancellation release work and queues promptly.
7. Add contract tests with a Fake Provider. Test unavailable dependencies, safe-budget rejection, stream ordering, cancellation, malformed input, and OOM behavior.
8. Run the validation commands below. Save real-device results with the hardware fingerprint; never commit generated benchmark data.
9. Update architecture, compatibility, API, evaluation, and security documentation when behavior changes.

## Validation Commands

```powershell
python .agents/skills/integrate-realtime-provider/scripts/provider_contract.py --provider demo
python .agents/skills/integrate-realtime-provider/scripts/hardware_report.py
python .agents/skills/integrate-realtime-provider/scripts/benchmark_api.py --url http://127.0.0.1:8765
python -m pytest
python -m ruff check .
```

Run `vram_sample.py` beside a real CUDA benchmark. Treat OOM, leaked tasks, unbounded queues, cancelled audio arriving late, or an undisclosed license restriction as a failed integration.

## Constraints

- Keep reference audio and speaker features local unless the user explicitly configures and authorizes a remote Provider.
- Do not silently change Provider, precision, or model during a streaming response.
- Stop streaming requests on OOM with a structured error. Retry a non-streaming request at most once using the next validated local tier.
- Label synthetic or Fake Providers clearly; never present them as cloned speech.
- Prefer PCM on the hot path and perform file encoding off the inference loop.
- Preserve compatibility of versioned events and APIs; add fields instead of changing existing meanings.


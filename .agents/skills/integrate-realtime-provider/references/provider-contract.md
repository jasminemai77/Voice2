# Voice2 Provider contract

All adapters implement `BaseProvider`; TTS adapters implement `TtsProvider`. The domain layer must not import an adapter or model runtime.

## Manifest checklist

- Stable ID, display name, adapter/runtime version, and SPDX license expression.
- Kind: `vad`, `asr`, `llm`, `tts`, `speech_to_speech`, `tool`, or `transport`.
- Languages, sample rates, encodings, text/audio streaming, cancellation, batch, and tool capabilities.
- Variants with device, precision, estimated RAM/VRAM, quality score, speed score, and tunable settings.
- Availability computed without loading weights, with an explanation of missing dependencies or explicit enablement.

## Runtime behavior

- `start()` loads lazily after resource admission and is idempotent.
- `stop()` releases model handles and accelerator caches.
- Streaming chunks use increasing sequence numbers and correct duration/sample-rate metadata.
- Convert input errors to `ValueError` and runtime/model failures to `RuntimeError`.
- A Provider never invokes another Provider directly. Exchange data through orchestrator events only.

## Realtime event envelope

Every event contains `session_id`, `turn_id`, `sequence`, `timestamp_ms`, `trace_id`, optional `provider_id`, and `payload`. Consumers discard late events belonging to cancelled turn IDs.

## Entry point

```toml
[project.entry-points."voice2.providers"]
my_provider = "package.module:MyProvider"
```


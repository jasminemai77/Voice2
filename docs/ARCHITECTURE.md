# Architecture

Voice2 currently uses a modular monolith with model adapters isolated behind asynchronous Provider contracts. The web and Tauri clients call the same versioned local API.

```text
Web / Tauri
    │ REST + WebSocket
FastAPI ── domain events ── Orchestrator
                              │
                      ResourceScheduler
                              │
         VAD | ASR | LLM | TTS | S2S | Transport Providers
                              │
                     local model runtimes
```

`domain` defines voice, hardware, speech, session, audio chunk, manifest and event models. `runtime` owns hardware detection, resource selection, storage and the bounded scheduler. `orchestrator` owns session and turn identity. `providers` are lazy adapters. `api` is a transport layer.

VoxCPM, OpenVoice and CosyVoice run in independent Python model processes. CosyVoice
uses the same framed PCM protocol but marks its delivery as native audio streaming.
Failed per-hardware benchmarks are persisted outside Git and participate in selection;
a Provider that fits its static estimate can still be excluded after an unsafe real run.

Providers register through Python entry points. Future cascade sessions use `VAD → ASR → LLM → TTS`; native Speech-to-Speech can bypass the cascade but uses the same scheduler, event envelope, cancellation and transport.

The current session skeleton rotates `turn_id` on interruption. Full duplex implementation must stop playback, cancel downstream tasks, clear buffered audio, persist only acknowledged playback context, and discard events for cancelled turns.

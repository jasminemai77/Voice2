# API v1

Default base URL: `http://127.0.0.1:8765`. OpenAPI is available at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/voices` | Register a consented local reference voice |
| GET | `/api/v1/voices` | List local voices |
| DELETE | `/api/v1/voices/{voice_id}` | Delete voice metadata and audio |
| POST | `/api/v1/speech` | Generate WAV, MP3, PCM, or stream PCM |
| POST | `/v1/audio/speech` | OpenAI-style speech endpoint |
| GET | `/api/v1/providers` | Provider capabilities and availability |
| GET | `/api/v1/runtime/hardware` | Sanitized device profile |
| GET | `/api/v1/runtime/profiles` | Available selections |
| PUT | `/api/v1/runtime/profile` | Select Auto/Fast/Quality/Custom |
| POST | `/api/v1/runtime/benchmark` | Run a bounded local short benchmark |
| POST | `/api/v1/runtime/prewarm` | Load the selected local Provider in the background |
| GET | `/api/v1/runtime/status` | Active model, queue, warm state, capabilities, exclusions and recent metrics |
| POST | `/api/v1/sessions` | Create cascade or S2S session |
| POST | `/api/v1/sessions/{id}/cancel` | Interrupt and rotate the turn |
| GET | `/api/v1/sessions/{id}/metrics` | Session metrics |
| WS | `/api/v1/realtime` | Versioned realtime event channel |

Errors use `{ "code", "message", "details" }`. New v1 fields are additive. Streaming speech emits mono signed 16-bit little-endian PCM and includes `X-Voice2-Audio-Format`.

`runtime/status` separates total TTFA, inference TTFA and scheduler queue wait. It also
labels delivery as `native_stream` or `post_generation_chunks`, records whether the
model was already warm, and reports why otherwise registered Providers were excluded.
The recent metrics list is bounded in memory and contains no reference transcript or
audio.

# Third-party notices

Voice2 source code is Apache-2.0. This file records evaluated integrations; inclusion
here does not mean weights are bundled.

| Component | Role | Upstream license | Default distribution |
|---|---|---|---|
| VoxCPM runtime 2.0.3 / VoxCPM-0.5B revision `f67d35a3848e0bec0fdb8c33e6fc92cf293ee72f` | Optional zero-shot TTS | Apache-2.0 | Runtime and verified weights are local-only; neither is bundled or committed |
| CosyVoice source `074ca6dc` / Matcha-TTS `dd9105b` / CosyVoice-300M revision `24c40509c3c5ea6fe06b5f8790ff99e3714a6bee` | Optional native-streaming zero-shot TTS | Apache-2.0 | Runtime, WeText resources and weights are local-only; neither is bundled or committed |
| GPT-SoVITS | Research/backup adapter | MIT | Not bundled |
| OpenVoice runtime `74a1d147` / V1 weights `c70fc8b` | Experimental CPU zero-shot fallback | MIT | Pinned source and verified Git LFS weights are local-only; neither is bundled or committed |
| MeloTTS `2091453` | Evaluated base TTS for OpenVoice V2 | MIT | Not bundled or enabled; eager multilingual downloads make the current upstream unsuitable for the offline Windows fallback |
| Silero VAD | Planned VAD | MIT | Not bundled |
| faster-whisper | Planned ASR | MIT | Not bundled |
| llama.cpp | Planned local LLM runtime | MIT | Not bundled |
| Pipecat | Architecture reference | BSD-2-Clause | Not bundled |
| LiveKit Agents | Planned transport reference | Apache-2.0 | Not bundled |
| FastAPI | HTTP/WebSocket framework | MIT | Python dependency |
| React / Next.js / vinext | Web client/runtime | MIT | Node dependency |
| Tauri | Windows desktop shell | Apache-2.0/MIT | Build dependency |

Before release, lock exact versions, preserve their notices, generate an SBOM, and
verify each selected model repository because code and weights can use different terms.

# Security, privacy and consent

Voice cloning can enable impersonation. Voice2 requires an explicit consent checkbox before storing a reference. Users must have authority to use the voice and remain responsible for generated content.

Reference audio, transcripts, features, generated audio and tuning results stay below `VOICE2_DATA_DIR` and are ignored by Git. The server listens on loopback by default. Do not expose it to a LAN or the internet without authentication, TLS, rate limiting and an explicit data-retention policy.

Voice registration decodes WAV, MP3 and FLAC metadata before accepting the file. A
renamed or corrupt payload is rejected, and the decoded duration must be between 5 and
30 seconds for every supported format. Filename extensions are not treated as proof of
audio validity.

Remote Providers are disabled by default and must require explicit configuration and per-use or durable authorization. Never place secrets in manifests, logs or URLs. Treat model checkpoints as untrusted supply-chain inputs: use pinned sources, checksums, safe tensor formats where possible, isolated loading and license review.

CosyVoice model and WeText resources are downloaded only during explicit setup. The
worker forces Hugging Face offline mode and patches ModelScope resource resolution to
`local_files_only=True`; generation must fail clearly when a required local resource is
missing rather than contacting a remote service. Reference audio and transcript paths
are passed only to the local worker process.

Report security issues privately to the repository owner rather than posting exploitable voice samples publicly.

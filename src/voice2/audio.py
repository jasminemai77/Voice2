from __future__ import annotations

import io
import wave

from voice2.domain import AudioChunk


def wav_bytes(chunks: list[AudioChunk]) -> bytes:
    if not chunks:
        raise ValueError("No audio was generated")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(chunks[0].channels)
        output.setsampwidth(2)
        output.setframerate(chunks[0].sample_rate)
        output.writeframes(b"".join(chunk.pcm_s16le for chunk in chunks))
    return buffer.getvalue()


def mp3_bytes(chunks: list[AudioChunk]) -> bytes:
    if not chunks:
        raise ValueError("No audio was generated")
    import lameenc

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(96)
    encoder.set_in_sample_rate(chunks[0].sample_rate)
    encoder.set_channels(chunks[0].channels)
    encoder.set_quality(3)
    return encoder.encode(b"".join(chunk.pcm_s16le for chunk in chunks)) + encoder.flush()


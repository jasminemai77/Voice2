from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

from voice2.domain import VoiceRecord


class VoiceStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "voices"
        self.index_path = self.root / "index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._voices: dict[str, VoiceRecord] = {}
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._voices = {item["id"]: VoiceRecord.model_validate(item) for item in payload}
        except (OSError, ValueError, TypeError, KeyError):
            self._voices = {}

    def _save(self) -> None:
        self.index_path.write_text(
            json.dumps(
                [voice.model_dump(mode="json") for voice in self._voices.values()],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _wav_duration(path: Path) -> float | None:
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() / wav.getframerate()
        except (wave.Error, OSError, ZeroDivisionError):
            return None

    def create(
        self,
        *,
        name: str,
        language: str,
        transcript: str,
        filename: str,
        content: bytes,
        consent_confirmed: bool,
    ) -> VoiceRecord:
        if not consent_confirmed:
            raise ValueError("Voice-owner consent must be confirmed")
        if not 0 < len(content) <= 25 * 1024 * 1024:
            raise ValueError("Reference audio must be between 1 byte and 25 MiB")
        extension = Path(filename).suffix.lower()
        if extension not in {".wav", ".mp3", ".flac"}:
            raise ValueError("Reference audio must be WAV, MP3, or FLAC")
        digest = hashlib.sha256(content).hexdigest()
        record = VoiceRecord(
            name=name.strip(),
            language=language,
            transcript=transcript.strip(),
            audio_path="",
            audio_sha256=digest,
            consent_confirmed=True,
        )
        destination = self.root / f"{record.id}{extension}"
        destination.write_bytes(content)
        record.audio_path = str(destination.resolve())
        record.duration_seconds = self._wav_duration(destination) if extension == ".wav" else None
        if record.duration_seconds is not None and not 5 <= record.duration_seconds <= 30:
            destination.unlink(missing_ok=True)
            raise ValueError("WAV reference audio must be 5 to 30 seconds")
        self._voices[record.id] = record
        self._save()
        return record

    def list(self) -> list[VoiceRecord]:
        return list(self._voices.values())

    def get(self, voice_id: str | None) -> VoiceRecord | None:
        return self._voices.get(voice_id) if voice_id else None

    def delete(self, voice_id: str) -> bool:
        voice = self._voices.pop(voice_id, None)
        if voice is None:
            return False
        Path(voice.audio_path).unlink(missing_ok=True)
        self._save()
        return True


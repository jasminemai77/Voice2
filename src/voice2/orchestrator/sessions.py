from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import uuid4

from voice2.domain import RealtimeEvent, SessionState


@dataclass(slots=True)
class Session:
    id: str
    mode: str
    state: SessionState = SessionState.IDLE
    turn_id: str = field(default_factory=lambda: uuid4().hex)
    sequence: int = 0
    cancelled_turns: set[str] = field(default_factory=set)
    metrics: dict[str, float | int] = field(default_factory=dict)

    def event(self, event_type: str, payload: dict | None = None) -> RealtimeEvent:
        self.sequence += 1
        return RealtimeEvent(
            type=event_type,
            session_id=self.id,
            turn_id=self.turn_id,
            sequence=self.sequence,
            timestamp_ms=int(time.time() * 1000),
            trace_id=uuid4().hex,
            payload=payload or {},
        )

    def interrupt(self) -> RealtimeEvent:
        self.cancelled_turns.add(self.turn_id)
        self.state = SessionState.INTERRUPTED
        event = self.event("session.interrupted", {"cancelled_turn_id": self.turn_id})
        self.turn_id = uuid4().hex
        self.state = SessionState.LISTENING
        return event


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, mode: str = "cascade") -> Session:
        if mode not in {"cascade", "speech_to_speech"}:
            raise ValueError("mode must be cascade or speech_to_speech")
        session = Session(id=uuid4().hex, mode=mode)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session:
        return self._sessions[session_id]

    def cancel(self, session_id: str) -> RealtimeEvent:
        return self.get(session_id).interrupt()


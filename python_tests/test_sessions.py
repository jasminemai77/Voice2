from voice2.domain import SessionState
from voice2.orchestrator import SessionManager


def test_interrupt_rotates_turn_and_enters_listening():
    manager = SessionManager()
    session = manager.create()
    old_turn = session.turn_id
    event = manager.cancel(session.id)
    assert event.type == "session.interrupted"
    assert old_turn in session.cancelled_turns
    assert session.turn_id != old_turn
    assert session.state == SessionState.LISTENING


def test_sequence_is_monotonic():
    session = SessionManager().create()
    first = session.event("one")
    second = session.event("two")
    assert second.sequence == first.sequence + 1


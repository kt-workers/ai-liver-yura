from subsystems.streaming.adapters.repositories.in_memory_main_segment_repository import (
    InMemoryStreamMainSegmentRepository,
)
from subsystems.streaming.adapters.repositories.in_memory_opening_repository import (
    InMemoryStreamOpeningRepository,
)
from subsystems.streaming.adapters.repositories.in_memory_session_repository import (
    InMemoryStreamSessionRepository,
)
from subsystems.streaming.application import StreamLifecycleGate
from subsystems.streaming.domain import LifecycleOperation, StreamSession


def test_lifecycle_gate_rejects_unknown_session() -> None:
    gate = StreamLifecycleGate(
        sessions=InMemoryStreamSessionRepository(),
        openings=InMemoryStreamOpeningRepository(),
        main_segments=InMemoryStreamMainSegmentRepository(),
    )
    result = gate.evaluate(LifecycleOperation.START_COMMENT_POLLING, "missing")
    assert not result.allowed
    assert result.reason_code == "lifecycle.stale_session"


def test_lifecycle_gate_rejects_comment_before_live() -> None:
    sessions = InMemoryStreamSessionRepository()
    session = sessions.create(StreamSession("trace", "broadcast", "title"))
    gate = StreamLifecycleGate(
        sessions=sessions,
        openings=InMemoryStreamOpeningRepository(),
        main_segments=InMemoryStreamMainSegmentRepository(),
    )
    result = gate.evaluate(LifecycleOperation.EVALUATE_COMMENT, session.session_id)
    assert not result.allowed
    assert result.reason_code == "lifecycle.not_live"

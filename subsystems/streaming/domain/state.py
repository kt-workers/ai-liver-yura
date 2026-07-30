"""Minimal lifecycle rules used by the deterministic Fake Runtime."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.streaming import StreamingOperationType, StreamingStatus

_TRANSITIONS: dict[
    tuple[StreamingStatus, StreamingOperationType],
    StreamingStatus,
] = {
    (StreamingStatus.IDLE, StreamingOperationType.PREPARE): StreamingStatus.READY,
    (StreamingStatus.ENDED, StreamingOperationType.PREPARE): StreamingStatus.READY,
    (StreamingStatus.READY, StreamingOperationType.START): StreamingStatus.LIVE,
    (StreamingStatus.LIVE, StreamingOperationType.STOP): StreamingStatus.ENDED,
    (
        StreamingStatus.READY,
        StreamingOperationType.EMERGENCY_STOP,
    ): StreamingStatus.ENDED,
    (
        StreamingStatus.LIVE,
        StreamingOperationType.EMERGENCY_STOP,
    ): StreamingStatus.ENDED,
}


@dataclass(frozen=True, slots=True)
class StreamingSubsystemState:
    """Small state value without real streaming session behavior."""

    status: StreamingStatus = StreamingStatus.IDLE

    def transition(
        self,
        operation_type: StreamingOperationType,
    ) -> StreamingSubsystemState | None:
        next_status = _TRANSITIONS.get((self.status, operation_type))
        if next_status is None:
            return None
        return StreamingSubsystemState(status=next_status)

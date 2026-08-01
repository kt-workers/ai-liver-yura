"""Safe, observable connection state for the Core Streaming boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from app.integrations.streaming.versioning import StreamingApiVersion


class StreamingConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    CLOSING = "closing"


@dataclass(frozen=True, slots=True)
class StreamingConnectionSnapshot:
    state: StreamingConnectionState
    observed_at: datetime
    last_connected_at: datetime | None = None
    last_disconnected_at: datetime | None = None
    failure_code: str | None = None
    retryable: bool = False
    retry_count: int = 0
    api_version: StreamingApiVersion | None = None
    last_cursor: str | None = None


class StreamingConnectionTracker:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self._snapshot = StreamingConnectionSnapshot(
            state=StreamingConnectionState.DISCONNECTED,
            observed_at=now,
            last_disconnected_at=now,
        )

    @property
    def snapshot(self) -> StreamingConnectionSnapshot:
        return self._snapshot

    def transition(
        self,
        state: StreamingConnectionState,
        *,
        failure_code: str | None = None,
        retryable: bool = False,
        api_version: StreamingApiVersion | None = None,
        cursor: str | None = None,
    ) -> StreamingConnectionSnapshot:
        now = datetime.now(timezone.utc)
        if state in {
            StreamingConnectionState.DEGRADED,
            StreamingConnectionState.UNAVAILABLE,
        }:
            retry_count = self._snapshot.retry_count + 1
        elif state is StreamingConnectionState.CONNECTED:
            retry_count = 0
        else:
            retry_count = self._snapshot.retry_count
        self._snapshot = replace(
            self._snapshot,
            state=state,
            observed_at=now,
            last_connected_at=(
                now
                if state is StreamingConnectionState.CONNECTED
                else self._snapshot.last_connected_at
            ),
            last_disconnected_at=(
                now
                if state
                in {
                    StreamingConnectionState.DISCONNECTED,
                    StreamingConnectionState.UNAVAILABLE,
                }
                else self._snapshot.last_disconnected_at
            ),
            failure_code=failure_code,
            retryable=retryable,
            retry_count=retry_count,
            api_version=api_version or self._snapshot.api_version,
            last_cursor=cursor or self._snapshot.last_cursor,
        )
        return self._snapshot

from app.integrations.streaming import (
    StreamingConnectionState,
    StreamingConnectionTracker,
)


def test_connection_state_tracks_bounded_public_failure_information() -> None:
    tracker = StreamingConnectionTracker()
    tracker.transition(StreamingConnectionState.CONNECTING)
    first = tracker.transition(
        StreamingConnectionState.UNAVAILABLE,
        failure_code="streaming.unavailable",
        retryable=True,
    )
    second = tracker.transition(
        StreamingConnectionState.DEGRADED,
        failure_code="streaming.timeout",
        retryable=True,
    )
    assert first.retry_count == 1
    assert second.retry_count == 2
    assert second.failure_code == "streaming.timeout"
    assert not hasattr(second, "exception")
    assert not hasattr(second, "endpoint")


def test_connected_state_resets_retry_count() -> None:
    tracker = StreamingConnectionTracker()
    tracker.transition(StreamingConnectionState.UNAVAILABLE, retryable=True)
    connected = tracker.transition(StreamingConnectionState.CONNECTED)
    assert connected.retry_count == 0
    assert connected.last_connected_at is not None

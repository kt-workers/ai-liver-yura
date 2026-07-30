from __future__ import annotations

from types import SimpleNamespace

from app.integrations.streaming import StreamingErrorCode, StreamingStatus
from subsystems.streaming.adapters.obs import (
    ObsAdapterError,
    ObsStatusMapper,
    to_streaming_error,
)


def test_obs_output_states_are_normalized_to_public_statuses() -> None:
    values = {
        "idle": StreamingStatus.READY,
        "starting": StreamingStatus.STARTING,
        "active": StreamingStatus.LIVE,
        "stopping": StreamingStatus.STOPPING,
        "disconnected": StreamingStatus.UNAVAILABLE,
        "failed": StreamingStatus.ERROR,
        "future_state": StreamingStatus.DEGRADED,
    }

    assert {
        value: ObsStatusMapper.streaming_status(value) for value in values
    } == values
    assert (
        ObsStatusMapper.output_status(
            SimpleNamespace(
                output_active=True,
                output_reconnecting=False,
                output_state="OBS_WEBSOCKET_OUTPUT_STARTED",
            )
        )
        == "active"
    )


def test_obs_errors_are_normalized_without_raw_exception_or_secret() -> None:
    authentication = to_streaming_error(
        RuntimeError("authentication password rejected: super-secret")
    )
    timeout = to_streaming_error(TimeoutError())
    invalid_state = to_streaming_error(
        ObsAdapterError("start_rejected", "obs.stream_start_rejected")
    )
    unsupported = to_streaming_error(
        ObsAdapterError("unsupported_operation", "obs.operation_unsupported")
    )

    assert authentication.code is StreamingErrorCode.UNAVAILABLE
    assert "super-secret" not in repr(authentication)
    assert timeout.code is StreamingErrorCode.TIMEOUT
    assert timeout.retryable is True
    assert invalid_state.code is StreamingErrorCode.CONFLICT
    assert unsupported.code is StreamingErrorCode.UNSUPPORTED_OPERATION

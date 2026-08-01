from __future__ import annotations

from app.integrations.streaming import StreamingStatus


class ObsStatusMapper:
    @staticmethod
    def output_status(response: object) -> str:
        active = bool(getattr(response, "output_active", False))
        reconnecting = bool(getattr(response, "output_reconnecting", False))
        state = str(getattr(response, "output_state", "")).upper()
        if reconnecting or "RECONNECT" in state:
            return "reconnecting"
        if state in {"OBS_WEBSOCKET_OUTPUT_STARTING", "STARTING"}:
            return "starting"
        if state in {"OBS_WEBSOCKET_OUTPUT_STOPPING", "STOPPING"}:
            return "stopping"
        if "ERROR" in state or "FAIL" in state:
            return "failed"
        if active or state in {"OBS_WEBSOCKET_OUTPUT_STARTED", "ACTIVE", "STARTED"}:
            return "active"
        if state in {"OBS_WEBSOCKET_OUTPUT_STOPPED", "IDLE", "STOPPED", ""} and not active:
            return "idle"
        return "unknown"

    @staticmethod
    def streaming_status(value: str) -> StreamingStatus:
        """Normalize an internal OBS output state for the public boundary."""

        return {
            "idle": StreamingStatus.READY,
            "starting": StreamingStatus.STARTING,
            "active": StreamingStatus.LIVE,
            "stopping": StreamingStatus.STOPPING,
            "disconnected": StreamingStatus.UNAVAILABLE,
            "failed": StreamingStatus.ERROR,
            "reconnecting": StreamingStatus.DEGRADED,
        }.get(value, StreamingStatus.DEGRADED)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.plugins.youtube_streaming.domain.health import utc_now
from subsystems.streaming.adapters.youtube.contracts import (
    YouTubeBroadcastSummary as YouTubeBroadcastSummary,
)
from subsystems.streaming.adapters.youtube.contracts import (
    YouTubeStreamSnapshot as YouTubeStreamSnapshot,
)


@dataclass(frozen=True, slots=True)
class StreamPreparationCommand:
    command_id: str
    trace_id: str
    session_id: str
    selected_broadcast_id: str
    requested_at: datetime = field(default_factory=utc_now)
    requested_by: str = "pyqt_management_ui"
    expected_state_version: int = 0
    run_of_show_id: str = "default"


@dataclass(frozen=True, slots=True)
class ObsPreparationSnapshot:
    connected: bool
    output_status: str
    current_scene: str
    current_scene_collection: str
    audio_source_states: dict[str, bool]
    avatar_source_visible: bool
    obs_version: str | None = None
    websocket_version: str | None = None
    audio_source_details: dict[str, dict[str, object]] = field(default_factory=dict)
    avatar_source_exists: bool = True
    avatar_source_paths: tuple[str, ...] = ()
    adapter_type: str = "fake"

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BodyRuntimeSnapshot:
    """常駐Body Runtimeの安全な診断スナップショット。"""

    running: bool
    tick_count: int
    active_activity_id: str | None
    pending_expression_count: int
    active_speech_id: str | None
    last_performance_id: str | None
    last_error: str | None

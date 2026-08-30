"""#341が所有する身体結合の追跡用契約。身体状態の正本は持たない。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.contracts.common import require_aware, require_identifier, require_revision


class BodyExecutionSessionStatus(str, Enum):
    ADMITTED = "admitted"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    EXECUTING = "executing"
    INTERRUPTING = "interrupting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    FAILED = "failed"


_TERMINAL_STATUSES = frozenset(
    {
        BodyExecutionSessionStatus.COMPLETED,
        BodyExecutionSessionStatus.CANCELLED,
        BodyExecutionSessionStatus.SUPERSEDED,
        BodyExecutionSessionStatus.REJECTED,
        BodyExecutionSessionStatus.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class BodyIntegrationTrace:
    """意思決定から身体実行までを結ぶ識別子と改訂番号の組。"""

    trace_id: str
    decision_id: str
    intent_id: str
    command_id: str
    motion_plan_id: str | None
    body_model_id: str
    source_context_revision: int
    goal_revision: int
    attention_revision: int
    body_state_revision_start: int
    expression_revision_start: int
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "trace_id",
            "decision_id",
            "intent_id",
            "command_id",
            "body_model_id",
        ):
            require_identifier(getattr(self, name), name)
        if self.motion_plan_id is not None:
            require_identifier(self.motion_plan_id, "motion_plan_id")
        for name in (
            "source_context_revision",
            "goal_revision",
            "attention_revision",
            "body_state_revision_start",
            "expression_revision_start",
        ):
            require_revision(getattr(self, name), name)
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class BodyExecutionSession:
    """結合の進行を表す読取モデルであり、身体状態を書き換えない。"""

    session_id: str
    trace: BodyIntegrationTrace
    status: BodyExecutionSessionStatus
    active_plan_id: str | None
    current_body_state_revision: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.session_id, "session_id")
        if not isinstance(self.trace, BodyIntegrationTrace):
            raise ValueError("traceが不正です")
        if not isinstance(self.status, BodyExecutionSessionStatus):
            raise ValueError("statusが不正です")
        if self.active_plan_id is not None:
            require_identifier(self.active_plan_id, "active_plan_id")
        require_revision(self.current_body_state_revision, "current_body_state_revision")
        if self.current_body_state_revision < self.trace.body_state_revision_start:
            raise ValueError("現在の身体状態改訂番号を開始時より前にできません")
        if self.started_at is not None:
            require_aware(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware(self.completed_at, "completed_at")
        if self.started_at is not None and self.completed_at is not None:
            if self.completed_at < self.started_at:
                raise ValueError("完了時刻を開始時刻より前にできません")
        if self.terminal_reason is not None:
            if not isinstance(self.terminal_reason, str) or not self.terminal_reason.strip():
                raise ValueError("terminal_reasonは空でない文字列でなければなりません")
        if self.status in _TERMINAL_STATUSES:
            if self.completed_at is None:
                raise ValueError("終了状態には完了時刻が必要です")
        elif self.completed_at is not None or self.terminal_reason is not None:
            raise ValueError("終了していない状態に完了情報は設定できません")
        if self.status in {
            BodyExecutionSessionStatus.PLAN_READY,
            BodyExecutionSessionStatus.EXECUTING,
            BodyExecutionSessionStatus.INTERRUPTING,
            BodyExecutionSessionStatus.COMPLETED,
        } and self.active_plan_id is None:
            raise ValueError("計画を使う状態にはactive_plan_idが必要です")

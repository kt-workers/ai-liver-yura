"""#334が所有するBrain結合の相関情報と読取専用の追跡契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum

from app.domain.contracts.common import require_aware, require_identifier, require_revision


class BrainIntegrationLane(str, Enum):
    FOREGROUND_INTERACTION = "foreground_interaction"
    COGNITIVE_NORMAL = "cognitive_normal"
    SPEECH_PREPARATION = "speech_preparation"
    BACKGROUND_REFLECTION = "background_reflection"


class BrainIntegrationModule(str, Enum):
    INPUT_MEANING = "input_meaning"
    APPRAISAL = "appraisal"
    ATTENTION = "attention"
    EXECUTIVE = "executive"
    GOAL_COMMITMENT = "goal_commitment"
    GOAL_PLANNING = "goal_planning"
    ACTIVITY_EXECUTION = "activity_execution"
    SPEECH_SEMANTICS = "speech_semantics"
    CHARACTER_LANGUAGE = "character_language"
    SEMANTIC_VERIFICATION = "semantic_verification"
    SPEECH_PERFORMANCE = "speech_performance"
    SPEECH_PRESENTATION = "speech_presentation"
    MEMORY = "memory"
    REFLECTION = "reflection"


class BrainWorkPriority(IntEnum):
    BACKGROUND = 0
    NORMAL = 1
    FOREGROUND = 2
    DIRECT_USER = 3


class BrainWorkStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    FAILED = "failed"


class BrainIntegrationTerminalOutcome(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    FAILED = "failed"


_TERMINAL_WORK_STATUSES = frozenset(
    {
        BrainWorkStatus.COMPLETED,
        BrainWorkStatus.CANCELLED,
        BrainWorkStatus.TIMED_OUT,
        BrainWorkStatus.STALE,
        BrainWorkStatus.SUPERSEDED,
        BrainWorkStatus.REJECTED,
        BrainWorkStatus.FAILED,
    }
)


def _identifiers(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{field_name} は配列でなければなりません")
    result = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{field_name} は空でない識別子の配列でなければなりません")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} は重複してはいけません")
    return result


@dataclass(frozen=True, slots=True)
class BrainWorkEnvelope:
    """Module間で渡す相関と改訂番号であり、判断内容の正本は持たない。"""

    trace_id: str
    trigger_id: str
    source_event_ids: tuple[str, ...]
    source_context_revision: int
    goal_revision: int | None
    attention_revision: int | None
    priority: BrainWorkPriority
    created_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.trace_id, "trace_id")
        require_identifier(self.trigger_id, "trigger_id")
        object.__setattr__(
            self,
            "source_event_ids",
            _identifiers(self.source_event_ids, "source_event_ids"),
        )
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.goal_revision, "goal_revision", optional=True)
        require_revision(self.attention_revision, "attention_revision", optional=True)
        if not isinstance(self.priority, BrainWorkPriority):
            raise ValueError("priority が不正です")
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class BrainRevisionEvent:
    """所有者が確定した改訂番号の観測記録であり、改訂を変更しない。"""

    revision_event_id: str
    owner: BrainIntegrationModule
    revision: int
    recorded_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.revision_event_id, "revision_event_id")
        if not isinstance(self.owner, BrainIntegrationModule):
            raise ValueError("owner が不正です")
        require_revision(self.revision, "revision")
        require_aware(self.recorded_at, "recorded_at")


@dataclass(frozen=True, slots=True)
class BrainWorkInterval:
    """個別Module作業の読取記録であり、キューや状態の所有者ではない。"""

    work_id: str
    module: BrainIntegrationModule
    lane: BrainIntegrationLane
    status: BrainWorkStatus
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    source_context_revision: int | None = None
    goal_revision: int | None = None
    attention_revision: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.work_id, "work_id")
        if not isinstance(self.module, BrainIntegrationModule):
            raise ValueError("module が不正です")
        if not isinstance(self.lane, BrainIntegrationLane):
            raise ValueError("lane が不正です")
        if not isinstance(self.status, BrainWorkStatus):
            raise ValueError("status が不正です")
        for field_name in ("queued_at", "started_at", "completed_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_aware(value, field_name)
        if (
            self.queued_at is not None
            and self.started_at is not None
            and self.started_at < self.queued_at
        ):
            raise ValueError("開始時刻を待機時刻より前にできません")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("完了時刻を開始時刻より前にできません")
        if self.status in _TERMINAL_WORK_STATUSES:
            if self.completed_at is None:
                raise ValueError("終了状態には完了時刻が必要です")
        elif self.completed_at is not None:
            raise ValueError("終了していない状態に完了時刻は設定できません")
        for field_name in (
            "source_context_revision",
            "goal_revision",
            "attention_revision",
        ):
            require_revision(getattr(self, field_name), field_name, optional=True)


@dataclass(frozen=True, slots=True)
class BrainIntegrationTrace:
    """#334の結合経路を観測する読取モデルであり、各Moduleの状態を変更しない。"""

    trace_id: str
    root_trigger_id: str
    source_event_ids: tuple[str, ...]
    intervals: tuple[BrainWorkInterval, ...]
    revision_events: tuple[BrainRevisionEvent, ...]
    decision_ids: tuple[str, ...] = ()
    goal_transition_ids: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    speech_candidate_ids: tuple[str, ...] = ()
    terminal_outcome: BrainIntegrationTerminalOutcome | None = None

    def __post_init__(self) -> None:
        require_identifier(self.trace_id, "trace_id")
        require_identifier(self.root_trigger_id, "root_trigger_id")
        for field_name in (
            "source_event_ids",
            "decision_ids",
            "goal_transition_ids",
            "activity_ids",
            "speech_candidate_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _identifiers(getattr(self, field_name), field_name),
            )
        intervals = tuple(self.intervals)
        if any(not isinstance(item, BrainWorkInterval) for item in intervals):
            raise ValueError("intervals に不正な値があります")
        if len({item.work_id for item in intervals}) != len(intervals):
            raise ValueError("intervals の work_id は重複してはいけません")
        object.__setattr__(self, "intervals", intervals)
        revision_events = tuple(self.revision_events)
        if any(not isinstance(item, BrainRevisionEvent) for item in revision_events):
            raise ValueError("revision_events に不正な値があります")
        if len({item.revision_event_id for item in revision_events}) != len(revision_events):
            raise ValueError("revision_events の識別子は重複してはいけません")
        object.__setattr__(self, "revision_events", revision_events)
        if self.terminal_outcome is not None:
            if not isinstance(
                self.terminal_outcome,
                BrainIntegrationTerminalOutcome,
            ):
                raise ValueError("terminal_outcome が不正です")
            if any(item.status not in _TERMINAL_WORK_STATUSES for item in intervals):
                raise ValueError(
                    "未終了の作業がある追跡記録に終了結果は設定できません"
                )

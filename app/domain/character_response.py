from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from app.domain.avatar_performance import AvatarGazeIntent
from app.domain.body import (
    BodyAttentionIntent,
    EmbodiedExpressionIntent,
    SpeechEmphasis,
)
from app.domain.character_utterance import LinguisticPerformance
from app.domain.interaction_intention import InteractionIntention
from app.shared.contracts.expression import VoiceIntent as VoiceIntent


class ActivityExecutionStatus(str, Enum):
    NOT_STARTED = "not_started"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELED = "canceled"
    WAITING_INPUT = "waiting_input"


class ResponseClaim(str, Enum):
    ACTIVITY_REQUESTED = "activity_requested"
    ACTIVITY_STARTED = "activity_started"
    ACTIVITY_RUNNING = "activity_running"
    ACTIVITY_CONTINUED = "activity_continued"
    ACTIVITY_COMPLETED = "activity_completed"
    ACTIVITY_SUCCEEDED = "activity_succeeded"
    ACTIVITY_FAILED = "activity_failed"
    ACTIVITY_REJECTED = "activity_rejected"
    ACTIVITY_CANCELED = "activity_canceled"
    EXTERNAL_RESULT_OBTAINED = "external_result_obtained"
    CAPABILITY_AVAILABLE = "capability_available"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    # 既存Character出力との互換表現。
    ACTIVITY_CONTINUES = "activity_continues"
    EXECUTION_UNAVAILABLE = "execution_unavailable"
    CONVERSATION_ONLY = "conversation_only"


class ClaimType(str, Enum):
    """発話本文と実行事実を照合するActivity非依存の主張種別。"""

    ACTIVITY_REQUESTED = "activity_requested"
    ACTIVITY_STARTED = "activity_started"
    ACTIVITY_RUNNING = "activity_running"
    ACTIVITY_CONTINUED = "activity_continued"
    ACTIVITY_COMPLETED = "activity_completed"
    ACTIVITY_SUCCEEDED = "activity_succeeded"
    ACTIVITY_FAILED = "activity_failed"
    ACTIVITY_REJECTED = "activity_rejected"
    ACTIVITY_CANCELED = "activity_canceled"
    EXTERNAL_RESULT_OBTAINED = "external_result_obtained"
    CAPABILITY_AVAILABLE = "capability_available"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CONVERSATION_ONLY = "conversation_only"


@dataclass(frozen=True, slots=True)
class Claim:
    """Characterの自己申告とは独立して扱う構造化された事実主張。"""

    claim_type: ClaimType
    activity_type: str | None
    operation: str | None
    status: ActivityExecutionStatus | None
    target: str | None
    confidence: float
    evidence: str


@dataclass(frozen=True, slots=True)
class ActivityExecutionResult:
    activity_type: str
    operation: str | None
    status: ActivityExecutionStatus
    capability: str | None = None
    provider: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    constraints: dict[str, object] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    result_id: str = field(default_factory=lambda: str(uuid4()))
    source_event_id: str | None = None
    activity_turn_id: str | None = None
    ongoing_activity_id: str | None = None
    trace_id: str | None = None
    parent_trace_id: str | None = None
    behavior_plan_id: str | None = None


@dataclass(frozen=True, slots=True)
class OngoingActivityContext:
    ongoing_activity_id: str
    ongoing_activity_type: str
    ongoing_status: str
    goal: str
    expected_input: str
    turn_count: int
    constraints: dict[str, object] = field(default_factory=dict)
    plugin_context_summary: dict[str, object] = field(default_factory=dict)
    previous_output_status: str | None = None
    previous_output_summary: str | None = None


@dataclass(frozen=True, slots=True)
class ReactionSegment:
    """表現意図が変化する区間だけを表すエンジン非依存の出力単位。"""

    speech: str
    expression: str = "smile"
    gesture: str | None = None
    voice_intent: VoiceIntent = field(default_factory=VoiceIntent)
    pause_after_seconds: float = 0.0
    expression_intensity: float = 1.0
    gesture_intensity: float = 1.0
    gaze: AvatarGazeIntent | None = None
    embodied_expression: EmbodiedExpressionIntent | None = None
    attention_intent: BodyAttentionIntent | None = None
    speech_emphasis: tuple[SpeechEmphasis, ...] = ()

    def __post_init__(self) -> None:
        if not self.speech.strip():
            raise ValueError("reaction segment speechは空にできません。")
        if not self.expression.strip():
            raise ValueError("reaction segment expressionは空にできません。")
        if not 0.0 <= self.pause_after_seconds <= 3.0:
            raise ValueError("pause_after_secondsは0.0以上3.0以下にしてください。")
        for field_name, value in (
            ("expression_intensity", self.expression_intensity),
            ("gesture_intensity", self.gesture_intensity),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name}は数値にしてください。")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{field_name}は0.0以上1.0以下にしてください。")
            object.__setattr__(self, field_name, float(value))
        object.__setattr__(self, "speech_emphasis", tuple(self.speech_emphasis))
        if len(self.speech_emphasis) > 16:
            raise ValueError("speech_emphasisは16件以下にしてください。")


@dataclass(frozen=True, slots=True)
class ReactionPlan:
    """Characterが生成した順序付き高レベル表現計画。"""

    segments: tuple[ReactionSegment, ...]

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("ReactionPlanには1件以上のsegmentが必要です。")
        if len(self.segments) > 8:
            raise ValueError("ReactionPlanのsegmentは8件以下にしてください。")

    @property
    def speech(self) -> str:
        return "".join(segment.speech for segment in self.segments)


@dataclass(frozen=True, slots=True)
class ResponseContext:
    user_input: str
    activity_type: str
    operation: str | None
    status: ActivityExecutionStatus
    failure_reason: str | None
    result_summary: str
    allowed_claims: tuple[ResponseClaim, ...]
    forbidden_claims: tuple[ResponseClaim, ...]
    activity_goal: str
    speech_act: str = "statement"
    conversation_phase: str = "active"
    initiative_level: float = 0.5
    input_authority_role: str = "user"
    instruction_trusted: bool = False
    emotion: dict[str, object] = field(default_factory=dict)
    stimulus: dict[str, object] = field(default_factory=dict)
    relationship: dict[str, object] = field(default_factory=dict)
    situation: dict[str, object] = field(default_factory=dict)
    memory: dict[str, object] = field(default_factory=dict)
    ongoing_activity: OngoingActivityContext | None = None
    ongoing_input_decision: str | None = None
    current_activity_status: str | None = None
    current_activity_preserved: bool = False
    current_activity_paused: bool = False
    current_activity_stopped: bool = False
    requested_new_activity: str | None = None
    transition_result: str | None = None
    topic: str | None = None
    planning_reason: str | None = None
    constraints: dict[str, object] = field(default_factory=dict)
    drive: dict[str, float] = field(default_factory=dict)
    recent_speech_summary: str = ""
    recent_conversation_summary: str = ""
    recent_topic_summary: str = ""
    interrupted_topic_relation: str | None = None
    stream_status: str | None = None
    confirmation_id: str | None = None
    confirmation_type: str | None = None
    confirmation_candidate_activity_type: str | None = None
    confirmation_candidate_operation: str | None = None
    confirmation_question: str | None = None
    confirmation_resolution: str | None = None
    interaction_intention: InteractionIntention | None = field(
        default=None,
        init=False,
    )

    def __post_init__(self) -> None:
        candidates = (
            self.memory.get("interaction_intention"),
            self.constraints.get("_interaction_intention"),
        )
        for candidate in candidates:
            intention = InteractionIntention.from_context(candidate)
            if intention is not None:
                object.__setattr__(self, "interaction_intention", intention)
                break


@dataclass(frozen=True, slots=True)
class CharacterResponse:
    speech: str
    expression: str = "smile"
    gesture: str | None = None
    voice_intent: VoiceIntent = field(default_factory=VoiceIntent)
    pause_after_seconds: float = 0.0
    claims: tuple[ResponseClaim, ...] = ()
    claim_details: tuple[Claim, ...] = ()
    reaction_plan: ReactionPlan | None = None
    linguistic_performance: LinguisticPerformance | None = None
    semantic_realizations: tuple[str, ...] = ()

    def effective_reaction_plan(self) -> ReactionPlan:
        if self.reaction_plan is not None:
            return self.reaction_plan
        return ReactionPlan(
            (
                ReactionSegment(
                    speech=self.speech,
                    expression=self.expression,
                    gesture=self.gesture,
                    voice_intent=self.voice_intent,
                    pause_after_seconds=self.pause_after_seconds,
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class ResponseValidationResult:
    accepted: bool
    reason: str
    invalid_claims: tuple[ResponseClaim, ...] = ()
    extracted_claims: tuple[Claim, ...] = ()
    claim_differences: tuple[str, ...] = ()

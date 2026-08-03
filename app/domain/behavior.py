from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from app.domain.activities import ActivityResult
from app.domain.activity_constraints import (
    ConstraintValidationError,
    ValidatedConstraints,
)
from app.domain.trace_context import TraceContext
from app.shared.contracts.activity import (
    ActivityAuthorityRequirement as ActivityAuthorityRequirement,
)
from app.shared.contracts.activity import (
    ActivityDefinition as ActivityDefinition,
)
from app.shared.contracts.activity import (
    ActivityMatcher as ActivityMatcher,
)
from app.shared.contracts.activity import (
    ActivityMatcherContext as ActivityMatcherContext,
)
from app.shared.contracts.activity import (
    ActivityOperation as ActivityOperation,
)
from app.shared.contracts.activity import (
    ActivitySafetyRequirement as ActivitySafetyRequirement,
)
from app.shared.contracts.activity import (
    ActivitySafetyRiskClass as ActivitySafetyRiskClass,
)
from app.shared.contracts.activity import (
    BehaviorDecision as BehaviorDecision,
)
from app.shared.contracts.activity import (
    DeterministicActivityMatch as DeterministicActivityMatch,
)
from app.shared.contracts.activity import (
    OngoingActivityPlanningContext as OngoingActivityPlanningContext,
)
from app.shared.contracts.activity import (
    OngoingInputDecision as OngoingInputDecision,
)
from app.shared.contracts.activity import (
    SpeechAct as SpeechAct,
)

if TYPE_CHECKING:
    from app.domain.morals import ActivityCandidateSemanticEquivalenceEvidence


@dataclass(frozen=True, slots=True)
class OngoingInputInterpretation:
    decision: OngoingInputDecision
    confidence: float
    reason: str
    current_activity_type: str
    requested_activity_type: str | None = None


@dataclass(frozen=True, slots=True)
class TargetInterest:
    """現在の対象へ向いている関心と、未知が残っている度合い。"""

    target_type: str
    target_id: str
    interest_intensity: float
    knowledge_gap: float
    satiation: float
    reason: str = ""

    def __post_init__(self) -> None:
        normalized_type = self.target_type.strip()
        normalized_id = self.target_id.strip()
        if not normalized_type:
            raise ValueError("target_type must not be empty")
        if not normalized_id:
            raise ValueError("target_id must not be empty")
        for name, value in (
            ("interest_intensity", self.interest_intensity),
            ("knowledge_gap", self.knowledge_gap),
            ("satiation", self.satiation),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")
        object.__setattr__(self, "target_type", normalized_type)
        object.__setattr__(self, "target_id", normalized_id)
        object.__setattr__(self, "interest_intensity", float(self.interest_intensity))
        object.__setattr__(self, "knowledge_gap", float(self.knowledge_gap))
        object.__setattr__(self, "satiation", float(self.satiation))
        object.__setattr__(self, "reason", self.reason.strip()[:160])

    @property
    def question_signal(self) -> float:
        return round(
            self.interest_intensity * self.knowledge_gap * (1.0 - self.satiation),
            6,
        )


@dataclass(frozen=True, slots=True)
class SituationAnalysis:
    """外部Eventの客観的な意味構造。実行可否や発話本文は含めない。"""

    activity_candidate: str | None
    operation: ActivityOperation | None
    goal: str
    constraints: dict[str, object] = field(default_factory=dict)
    speech_act: SpeechAct = SpeechAct.STATEMENT
    conversation_phase: str | None = None
    initiative_level: float | None = None
    active_interests: tuple[TargetInterest, ...] = ()
    negated: bool = False
    hypothetical: bool = False
    past_reference: bool = False
    knowledge_question: bool = False
    confidence: float = 1.0
    reason: str = ""
    evaluator_type: str = "deterministic"
    ongoing_input_decision: OngoingInputDecision | None = None
    constraint_errors: tuple[ConstraintValidationError, ...] = ()
    constraints_schema_version: str | None = None
    matcher_id: str | None = None
    matcher_type: str | None = None
    matcher_evidence: str | None = None
    semantic_equivalence_evidence: (
        ActivityCandidateSemanticEquivalenceEvidence | None
    ) = None


@dataclass(frozen=True, slots=True)
class ActivityPlan:
    decision: BehaviorDecision
    activity_type: str
    goal: str
    required_capability: str | None = None
    provider_plugin_id: str | None = None
    operation: ActivityOperation | None = None
    constraints: dict[str, object] = field(default_factory=dict)
    planner_constraints: tuple[str, ...] = ()
    speech_act: SpeechAct = SpeechAct.STATEMENT
    conversation_phase: str | None = None
    initiative_level: float | None = None
    active_interests: tuple[TargetInterest, ...] = ()
    negated: bool = False
    hypothetical: bool = False
    past_reference: bool = False
    knowledge_question: bool = False
    confidence: float = 1.0
    reason: str = ""
    planner_type: str = "deterministic"
    ongoing_input_decision: OngoingInputDecision | None = None
    current_activity_type: str | None = None
    current_activity_preserved: bool = False
    current_activity_paused: bool = False
    current_activity_stopped: bool = False
    requested_new_activity: str | None = None
    current_activity_capability: str | None = None
    current_activity_provider_plugin_id: str | None = None
    topic: str | None = None
    planning_reason: str | None = None
    autonomous_action: str | None = None
    constraint_errors: tuple[ConstraintValidationError, ...] = ()
    constraints_schema_version: str | None = None
    validated_constraints: ValidatedConstraints | None = None
    behavior_plan_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str | None = None
    parent_trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityPlanEvaluation:
    plan: ActivityPlan
    accepted: bool
    result: ActivityResult
    fallback_required: bool = False


@dataclass(frozen=True, slots=True)
class BehaviorPlanningContext:
    user_text: str
    source_event_id: str
    available_capabilities: frozenset[str]
    event_type: str = "user_text"
    request_kind: str | None = None
    authority_role: str = "user"
    instruction_trusted: bool = False
    activity_definitions: tuple[ActivityDefinition, ...] = ()
    active_activity_definition: ActivityDefinition | None = None
    ongoing_activity_type: str | None = None
    ongoing_activity: OngoingActivityPlanningContext | None = None
    drive: dict[str, float] = field(default_factory=dict)
    emotion: dict[str, object] = field(default_factory=dict)
    relationship: dict[str, object] = field(default_factory=dict)
    motivation: dict[str, object] = field(default_factory=dict)
    moral: dict[str, object] = field(default_factory=dict)
    situation: dict[str, object] = field(default_factory=dict)
    memory: dict[str, object] = field(default_factory=dict)
    conversation_history: tuple[dict[str, object], ...] = ()
    related_knowledge: tuple[dict[str, object], ...] = ()
    last_activity_result: ActivityResult | None = None
    trace_context: TraceContext | None = None

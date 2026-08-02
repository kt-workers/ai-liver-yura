from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class BehaviorDecision(str, Enum):
    START_ACTIVITY = "start_activity"
    CONTINUE_ACTIVITY = "continue_activity"
    CONVERSATION = "conversation"
    ASK_CONFIRMATION = "ask_confirmation"
    WAIT = "wait"
    NO_ACTION = "no_action"
    SWITCH_ACTIVITY = "switch_activity"


class ActivityOperation(str, Enum):
    START = "start"
    CONTINUE = "continue"
    STOP = "stop"
    EXPLAIN = "explain"
    DISCUSS = "discuss"


class SpeechAct(str, Enum):
    """入力表面ではなく、文脈を含む意味上の会話機能。"""

    GREETING = "greeting"
    STATEMENT = "statement"
    QUESTION = "question"
    ANSWER = "answer"
    ACKNOWLEDGEMENT = "acknowledgement"
    CLOSING = "closing"
    REQUEST = "request"
    PROPOSAL = "proposal"
    COMMAND = "command"


class OngoingInputDecision(str, Enum):
    CONTINUE_CURRENT = "continue_current"
    STOP_CURRENT = "stop_current"
    PAUSE_CURRENT = "pause_current"
    RESUME_CURRENT = "resume_current"
    CONVERSATION_ABOUT_CURRENT = "conversation_about_current"
    CONVERSATION_UNRELATED = "conversation_unrelated"
    START_OTHER_ACTIVITY = "start_other_activity"
    SWITCH_ACTIVITY = "switch_activity"
    ASK_CONFIRMATION = "ask_confirmation"
    NO_ACTION = "no_action"


@dataclass(frozen=True, slots=True)
class ActivityAuthorityRequirement:
    """Activity候補が宣言するAuthority要件の正規契約。"""

    policy_id: str
    allowed_roles: tuple[str, ...]
    trusted_instruction_required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str):
            raise TypeError("policy_id must be str")
        normalized_policy_id = self.policy_id.strip()
        if not normalized_policy_id:
            raise ValueError("policy_id must not be empty")
        if not isinstance(self.allowed_roles, tuple):
            raise TypeError("allowed_roles must be tuple")
        normalized_roles: list[str] = []
        for role in self.allowed_roles:
            if not isinstance(role, str):
                raise TypeError("allowed_roles must contain str values")
            normalized_role = role.strip().lower()
            if not normalized_role:
                raise ValueError("allowed_roles must not contain empty values")
            normalized_roles.append(normalized_role)
        if not normalized_roles:
            raise ValueError("allowed_roles must not be empty")
        if len(set(normalized_roles)) != len(normalized_roles):
            raise ValueError("allowed_roles must not contain duplicates")
        if not isinstance(self.trusted_instruction_required, bool):
            raise TypeError("trusted_instruction_required must be bool")
        object.__setattr__(self, "policy_id", normalized_policy_id)
        object.__setattr__(self, "allowed_roles", tuple(sorted(normalized_roles)))

    def permits(self, authority_role: str, instruction_trusted: bool) -> bool:
        normalized_role = authority_role.strip().lower()
        return normalized_role in self.allowed_roles and (
            not self.trusted_instruction_required or instruction_trusted
        )


class ActivitySafetyRiskClass(str, Enum):
    """候補Safety要件の比較に使用する宣言上のRisk class。"""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class ActivitySafetyRequirement:
    """候補Safety要件の比較に使用する宣言上のRisk class。"""

    policy_id: str
    risk_class: ActivitySafetyRiskClass

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str):
            raise TypeError("policy_id must be str")
        normalized_policy_id = self.policy_id.strip()
        if not normalized_policy_id:
            raise ValueError("policy_id must not be empty")
        if not isinstance(self.risk_class, ActivitySafetyRiskClass):
            raise TypeError("risk_class must be ActivitySafetyRiskClass")
        object.__setattr__(self, "policy_id", normalized_policy_id)


@dataclass(frozen=True, slots=True)
class OngoingActivityPlanningContext:
    ongoing_activity_id: str
    activity_type: str
    status: str
    goal: str
    constraints: dict[str, object]
    expected_input: str
    turn_count: int
    current_operation: str | None = None
    plugin_state_summary: dict[str, object] = field(default_factory=dict)
    recent_turns: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class DeterministicActivityMatch:
    operation: ActivityOperation
    goal: str
    constraints: dict[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    reason: str = "deterministic_match"
    activity_type: str | None = None
    evidence: str | None = None
    matcher_id: str = "anonymous_matcher"
    matcher_type: str = "plugin"
    priority: int = 300


@dataclass(frozen=True, slots=True)
class ActivityMatcherContext:
    user_input: str
    normalized_input: str
    activity_definition: ActivityDefinition
    registered_activity_definitions: tuple[ActivityDefinition, ...]
    ongoing_activity: OngoingActivityPlanningContext | None = None
    conversation_context: dict[str, object] = field(default_factory=dict)


class ActivityMatcher(Protocol):
    def match(
        self, context: ActivityMatcherContext
    ) -> DeterministicActivityMatch | None: ...


@dataclass(frozen=True, slots=True)
class ActivityDefinition:
    activity_type: str
    display_name: str
    required_capability: str | None
    provider_plugin_id: str | None
    start_markers: tuple[str, ...] = ()
    stop_markers: tuple[str, ...] = ()
    description: str = ""
    supported_operations: tuple[ActivityOperation, ...] = (ActivityOperation.START,)
    semantic_descriptions: tuple[str, ...] = ()
    constraints_schema: dict[str, object] = field(default_factory=dict)
    constraints_schema_version: str = "1"
    matcher: ActivityMatcher | None = None
    matchers: tuple[ActivityMatcher, ...] = ()
    authority_requirement: ActivityAuthorityRequirement | None = None
    safety_requirement: ActivitySafetyRequirement | None = None

    def __post_init__(self) -> None:
        if self.authority_requirement is not None and not isinstance(
            self.authority_requirement,
            ActivityAuthorityRequirement,
        ):
            raise TypeError(
                "authority_requirement must be ActivityAuthorityRequirement or None"
            )
        if self.safety_requirement is not None and not isinstance(
            self.safety_requirement,
            ActivitySafetyRequirement,
        ):
            raise TypeError(
                "safety_requirement must be ActivitySafetyRequirement or None"
            )


class ActivityPlanView(Protocol):
    @property
    def decision(self) -> BehaviorDecision: ...

    @property
    def activity_type(self) -> str: ...

    @property
    def operation(self) -> ActivityOperation | None: ...

    @property
    def constraints(self) -> dict[str, object]: ...

    @property
    def validated_constraints(self) -> Mapping[str, object] | None: ...

    @property
    def confidence(self) -> float: ...

    @property
    def required_capability(self) -> str | None: ...

    @property
    def provider_plugin_id(self) -> str | None: ...

    @property
    def reason(self) -> str: ...

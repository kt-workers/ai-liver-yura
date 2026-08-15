from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TypeVar, cast

from app.domain.appraisal import AppraisalFactsSnapshot, InternalStateSnapshot
from app.domain.contracts import CapabilityDescriptor, CapabilityRequirement, RevisionVector
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
    timestamp_to_json,
    utc_instant,
)
from app.domain.input_meaning import StructuredInputMeaning


class ExecutiveOutcome(str, Enum):
    RESPOND = "respond"
    ACT = "act"
    WAIT = "wait"
    IGNORE = "ignore"
    CONTINUE_ACTIVITY = "continue_activity"
    DEFER = "defer"
    REFUSE = "refuse"
    SILENCE = "silence"


class ExecutivePriority(str, Enum):
    FOREGROUND = "foreground"
    NORMAL = "normal"
    BACKGROUND = "background"


class ExecutiveInterruptibility(str, Enum):
    INTERRUPTIBLE = "interruptible"
    SOFT_CANCEL_ONLY = "soft_cancel_only"
    NON_INTERRUPTIBLE = "non_interruptible"


class ExecutiveFactKind(str, Enum):
    GOAL = "goal"
    COMMITMENT = "commitment"
    MEMORY_EVIDENCE = "memory_evidence"
    RELATIONSHIP = "relationship"
    ACTIVITY = "activity"
    EXECUTION = "execution"
    TURN = "turn"
    ATTENTION = "attention"
    SPEECH = "speech"
    BODY = "body"
    TIME = "time"
    ENVIRONMENT = "environment"


class ExecutiveIntentKind(str, Enum):
    SPEECH = "speech"
    BODY = "body"
    ACTIVITY = "activity"
    ATTENTION = "attention"


class GoalTransitionOperation(str, Enum):
    CREATE = "create"
    ACTIVATE = "activate"
    REPRIORITIZE = "reprioritize"
    SUSPEND = "suspend"
    RESUME = "resume"
    COMPLETE = "complete"
    FAIL = "fail"
    ABANDON = "abandon"
    SUPERSEDE = "supersede"


class CommitmentTransitionOperation(str, Enum):
    CREATE = "create"
    ACTIVATE = "activate"
    SUSPEND = "suspend"
    RESUME = "resume"
    RELEASE = "release"
    FULFILL = "fulfill"
    VIOLATE = "violate"


T = TypeVar("T")


def _owned(values: object, expected: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    result = tuple(values)
    if any(not isinstance(item, expected) for item in result):
        raise ValueError(f"{name} contains an invalid value")
    return cast(tuple[T, ...], result)


def _ids(values: object, name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    result = _owned(values, str, name)
    if non_empty and not result:
        raise ValueError(f"{name} must not be empty")
    if any(not item.strip() for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    return result


@dataclass(frozen=True, slots=True)
class ExecutiveFactRef:
    fact_id: str
    kind: ExecutiveFactKind
    revision: int
    payload: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.fact_id, "fact_id")
        if not isinstance(self.kind, ExecutiveFactKind):
            raise ValueError("kind must be ExecutiveFactKind")
        require_revision(self.revision, "revision")
        payload = freeze_json(self.payload)
        if not isinstance(payload, Mapping):
            raise ValueError("fact payload must be an object")
        object.__setattr__(self, "payload", payload)

    def to_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind.value,
            "revision": self.revision,
            "payload": thaw_json(self.payload),
        }


@dataclass(frozen=True, slots=True)
class PreconditionFact:
    precondition_id: str
    subject_ref: str
    predicate: str
    actual: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.precondition_id, "precondition_id")
        require_identifier(self.subject_ref, "subject_ref")
        require_identifier(self.predicate, "predicate")
        object.__setattr__(self, "actual", freeze_json(self.actual))

    def to_dict(self) -> dict[str, object]:
        return {
            "precondition_id": self.precondition_id,
            "subject_ref": self.subject_ref,
            "predicate": self.predicate,
            "actual": thaw_json(self.actual),
        }


@dataclass(frozen=True, slots=True)
class ExecutivePreconditionRequirement:
    precondition_id: str
    expected: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.precondition_id, "precondition_id")
        object.__setattr__(self, "expected", freeze_json(self.expected))

    def to_dict(self) -> dict[str, object]:
        return {
            "precondition_id": self.precondition_id,
            "expected": thaw_json(self.expected),
        }


@dataclass(frozen=True, slots=True)
class ExecutiveFreshnessStamp:
    revisions: RevisionVector
    internal_state_revision: int
    appraisal_facts_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions must be RevisionVector")
        require_revision(self.internal_state_revision, "internal_state_revision")
        require_revision(self.appraisal_facts_revision, "appraisal_facts_revision")


@dataclass(frozen=True, slots=True)
class AuthoritativeIntentRequirements:
    intent_id: str
    capabilities: tuple[CapabilityRequirement, ...] = ()
    preconditions: tuple[ExecutivePreconditionRequirement, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.intent_id, "intent_id")
        object.__setattr__(
            self, "capabilities", _owned(self.capabilities, CapabilityRequirement, "capabilities")
        )
        object.__setattr__(
            self,
            "preconditions",
            _owned(self.preconditions, ExecutivePreconditionRequirement, "preconditions"),
        )
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities must be unique")
        ids = [item.precondition_id for item in self.preconditions]
        if len(ids) != len(set(ids)):
            raise ValueError("precondition ids must be unique")


@dataclass(frozen=True, slots=True)
class ExecutiveCommitState:
    freshness: ExecutiveFreshnessStamp
    capabilities: tuple[CapabilityDescriptor, ...]
    preconditions: tuple[PreconditionFact, ...]
    requirements: tuple[AuthoritativeIntentRequirements, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.freshness, ExecutiveFreshnessStamp):
            raise ValueError("freshness must be ExecutiveFreshnessStamp")
        for name, item_type in (
            ("capabilities", CapabilityDescriptor),
            ("preconditions", PreconditionFact),
            ("requirements", AuthoritativeIntentRequirements),
        ):
            object.__setattr__(self, name, _owned(getattr(self, name), item_type, name))
        for values, attribute, name in (
            (self.capabilities, "capability_id", "capability ids"),
            (self.preconditions, "precondition_id", "precondition ids"),
            (self.requirements, "intent_id", "requirement intent ids"),
        ):
            identifiers = [getattr(item, attribute) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} must be unique")


@dataclass(frozen=True, slots=True)
class ExecutiveContextSnapshot:
    trigger_id: str
    source_event_ids: tuple[str, ...]
    source_context_revision: int
    goal_revision: int
    attention_revision: int
    meaning: StructuredInputMeaning | None
    internal_state: InternalStateSnapshot
    facts: tuple[ExecutiveFactRef, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    preconditions: tuple[PreconditionFact, ...]
    captured_at: datetime
    appraisal_facts: AppraisalFactsSnapshot

    def __post_init__(self) -> None:
        require_identifier(self.trigger_id, "trigger_id")
        object.__setattr__(
            self,
            "source_event_ids",
            _ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        for name in ("source_context_revision", "goal_revision", "attention_revision"):
            require_revision(getattr(self, name), name)
        if self.meaning is not None:
            if not isinstance(self.meaning, StructuredInputMeaning):
                raise ValueError("meaning must be StructuredInputMeaning")
            if self.meaning.source_event_id not in self.source_event_ids:
                raise ValueError("meaning source event must belong to snapshot")
            if self.meaning.source_context_revision != self.source_context_revision:
                raise ValueError("meaning revision must match snapshot")
        if not isinstance(self.internal_state, InternalStateSnapshot):
            raise ValueError("internal_state must be InternalStateSnapshot")
        if self.internal_state.source_context_revision != self.source_context_revision:
            raise ValueError("internal state context revision must match snapshot")
        if not isinstance(self.appraisal_facts, AppraisalFactsSnapshot):
            raise ValueError("appraisal_facts must be AppraisalFactsSnapshot")
        if self.appraisal_facts.source_context_revision != self.source_context_revision:
            raise ValueError("appraisal facts context revision must match snapshot")
        if self.appraisal_facts.internal_state_revision != self.internal_state.revision:
            raise ValueError("appraisal facts state revision must match internal state")
        for name, item_type in (
            ("facts", ExecutiveFactRef),
            ("capabilities", CapabilityDescriptor),
            ("preconditions", PreconditionFact),
        ):
            values = _owned(getattr(self, name), item_type, name)
            object.__setattr__(self, name, values)
        for name, values, attribute in (
            ("facts", self.facts, "fact_id"),
            ("capabilities", self.capabilities, "capability_id"),
            ("preconditions", self.preconditions, "precondition_id"),
        ):
            identifiers = [getattr(item, attribute) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} ids must be unique")
        require_aware(self.captured_at, "captured_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "trigger_id": self.trigger_id,
            "source_event_ids": list(self.source_event_ids),
            "source_context_revision": self.source_context_revision,
            "goal_revision": self.goal_revision,
            "attention_revision": self.attention_revision,
            "meaning": None if self.meaning is None else self.meaning.to_dict(),
            "internal_state": self.internal_state.to_dict(),
            "facts": [item.to_dict() for item in self.facts],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "preconditions": [item.to_dict() for item in self.preconditions],
            "captured_at": timestamp_to_json(self.captured_at),
            "appraisal_facts": self.appraisal_facts.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SpeechIntentPayload:
    semantic_goal_ref: str
    target_ref: str | None = None
    constraint_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.semantic_goal_ref, "semantic_goal_ref")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        object.__setattr__(self, "constraint_refs", _ids(self.constraint_refs, "constraint_refs"))

    def reference_ids(self) -> tuple[str, ...]:
        return (
            (self.semantic_goal_ref,)
            + (() if self.target_ref is None else (self.target_ref,))
            + self.constraint_refs
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "semantic_goal_ref": self.semantic_goal_ref,
            "target_ref": self.target_ref,
            "constraint_refs": list(self.constraint_refs),
        }


@dataclass(frozen=True, slots=True)
class BodyIntentPayload:
    motion_goal_ref: str
    target_ref: str | None = None
    constraint_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.motion_goal_ref, "motion_goal_ref")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        object.__setattr__(self, "constraint_refs", _ids(self.constraint_refs, "constraint_refs"))

    def reference_ids(self) -> tuple[str, ...]:
        return (
            (self.motion_goal_ref,)
            + (() if self.target_ref is None else (self.target_ref,))
            + self.constraint_refs
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "motion_goal_ref": self.motion_goal_ref,
            "target_ref": self.target_ref,
            "constraint_refs": list(self.constraint_refs),
        }


@dataclass(frozen=True, slots=True)
class ActivityIntentPayload:
    activity_type: str
    target_ref: str | None = None
    constraint_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.activity_type, "activity_type")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        object.__setattr__(self, "constraint_refs", _ids(self.constraint_refs, "constraint_refs"))

    def reference_ids(self) -> tuple[str, ...]:
        return (() if self.target_ref is None else (self.target_ref,)) + self.constraint_refs

    def to_dict(self) -> dict[str, object]:
        return {
            "activity_type": self.activity_type,
            "target_ref": self.target_ref,
            "constraint_refs": list(self.constraint_refs),
        }


@dataclass(frozen=True, slots=True)
class AttentionIntentPayload:
    target_ref: str
    mode: str
    constraint_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.target_ref, "target_ref")
        require_identifier(self.mode, "mode")
        object.__setattr__(self, "constraint_refs", _ids(self.constraint_refs, "constraint_refs"))

    def reference_ids(self) -> tuple[str, ...]:
        return (self.target_ref,) + self.constraint_refs

    def to_dict(self) -> dict[str, object]:
        return {
            "target_ref": self.target_ref,
            "mode": self.mode,
            "constraint_refs": list(self.constraint_refs),
        }


IntentPayload = (
    SpeechIntentPayload | BodyIntentPayload | ActivityIntentPayload | AttentionIntentPayload
)


@dataclass(frozen=True, slots=True)
class ExecutiveIntent:
    intent_id: str
    kind: ExecutiveIntentKind
    purpose: str
    payload: IntentPayload
    evidence_refs: tuple[str, ...] = ()
    required_capabilities: tuple[CapabilityRequirement, ...] = ()
    preconditions: tuple[ExecutivePreconditionRequirement, ...] = ()
    forbidden_claim_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.intent_id, "intent_id")
        require_identifier(self.purpose, "purpose")
        if not isinstance(self.kind, ExecutiveIntentKind):
            raise ValueError("kind must be ExecutiveIntentKind")
        expected_payload = {
            ExecutiveIntentKind.SPEECH: SpeechIntentPayload,
            ExecutiveIntentKind.BODY: BodyIntentPayload,
            ExecutiveIntentKind.ACTIVITY: ActivityIntentPayload,
            ExecutiveIntentKind.ATTENTION: AttentionIntentPayload,
        }[self.kind]
        if not isinstance(self.payload, expected_payload):
            raise ValueError("intent payload type does not match intent kind")
        for name in ("evidence_refs", "forbidden_claim_refs"):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        object.__setattr__(
            self,
            "preconditions",
            _owned(
                self.preconditions,
                ExecutivePreconditionRequirement,
                "preconditions",
            ),
        )
        precondition_ids = [item.precondition_id for item in self.preconditions]
        if len(precondition_ids) != len(set(precondition_ids)):
            raise ValueError("intent precondition ids must be unique")
        requirements = _owned(
            self.required_capabilities, CapabilityRequirement, "required_capabilities"
        )
        object.__setattr__(self, "required_capabilities", requirements)

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "kind": self.kind.value,
            "purpose": self.purpose,
            "payload": self.payload.to_dict(),
            "evidence_refs": list(self.evidence_refs),
            "required_capabilities": [item.to_dict() for item in self.required_capabilities],
            "preconditions": [item.to_dict() for item in self.preconditions],
            "forbidden_claim_refs": list(self.forbidden_claim_refs),
        }


@dataclass(frozen=True, slots=True)
class GoalTransitionPayload:
    semantic_goal_ref: str | None = None
    priority: int | None = None
    superseding_goal_ref: str | None = None
    goal_kind: str | None = None
    target_ref: str | None = None
    commitment_refs: tuple[str, ...] = ()
    precondition_ids: tuple[str, ...] = ()
    completion_condition_refs: tuple[str, ...] = ()
    interruption_policy: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "semantic_goal_ref",
            "superseding_goal_ref",
            "goal_kind",
            "target_ref",
            "interruption_policy",
        ):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        if self.priority is not None and (
            type(self.priority) is not int or not 0 <= self.priority <= 100
        ):
            raise ValueError("priority must be an int between 0 and 100")
        if self.goal_kind is not None and self.goal_kind not in {
            "general",
            "activity",
            "social",
            "exploration",
            "maintenance",
        }:
            raise ValueError("goal_kind has an invalid value")
        if self.interruption_policy is not None and self.interruption_policy not in {
            "interruptible",
            "resumable",
            "protected",
        }:
            raise ValueError("interruption_policy has an invalid value")
        for name in (
            "commitment_refs",
            "precondition_ids",
            "completion_condition_refs",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))

    def _has_create_values(self) -> bool:
        return any(
            value
            for value in (
                self.semantic_goal_ref,
                self.goal_kind,
                self.target_ref,
                self.commitment_refs,
                self.precondition_ids,
                self.completion_condition_refs,
                self.interruption_policy,
            )
        )

    def validate_for(self, operation: GoalTransitionOperation) -> None:
        if operation is GoalTransitionOperation.CREATE:
            if (
                self.semantic_goal_ref is None
                or self.priority is None
                or self.goal_kind is None
                or self.interruption_policy is None
                or self.superseding_goal_ref is not None
            ):
                raise ValueError(
                    "create requires semantic goal, kind, priority and interruption policy"
                )
        elif operation is GoalTransitionOperation.REPRIORITIZE:
            if (
                self.priority is None
                or self._has_create_values()
                or self.superseding_goal_ref is not None
            ):
                raise ValueError("reprioritize requires only priority")
        elif operation is GoalTransitionOperation.SUPERSEDE:
            if (
                self.superseding_goal_ref is None
                or self.priority is not None
                or self._has_create_values()
            ):
                raise ValueError("supersede requires only superseding_goal_ref")
        elif (
            self.priority is not None
            or self.superseding_goal_ref is not None
            or self._has_create_values()
        ):
            raise ValueError("goal transition operation does not accept payload values")

    def reference_ids(self) -> tuple[str, ...]:
        return (
            tuple(
                value
                for value in (
                    self.semantic_goal_ref,
                    self.superseding_goal_ref,
                    self.target_ref,
                )
                if value is not None
            )
            + self.commitment_refs
            + self.precondition_ids
            + self.completion_condition_refs
        )

    def goal_fact_reference_ids(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (self.semantic_goal_ref, self.superseding_goal_ref)
            if value is not None
        )

    def commitment_fact_reference_ids(self) -> tuple[str, ...]:
        return self.commitment_refs

    def bounded_reference_ids(self) -> tuple[str, ...]:
        return (
            (() if self.target_ref is None else (self.target_ref,))
            + self.precondition_ids
            + self.completion_condition_refs
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "semantic_goal_ref": self.semantic_goal_ref,
            "priority": self.priority,
            "superseding_goal_ref": self.superseding_goal_ref,
            "goal_kind": self.goal_kind,
            "target_ref": self.target_ref,
            "commitment_refs": list(self.commitment_refs),
            "precondition_ids": list(self.precondition_ids),
            "completion_condition_refs": list(self.completion_condition_refs),
            "interruption_policy": self.interruption_policy,
        }


@dataclass(frozen=True, slots=True)
class GoalTransitionIntent:
    intent_id: str
    operation: GoalTransitionOperation
    goal_ref: str | None
    goal_spec_ref: str | None
    expected_goal_revision: int
    payload: GoalTransitionPayload
    reason_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.intent_id, "intent_id")
        if not isinstance(self.operation, GoalTransitionOperation):
            raise ValueError("operation must be GoalTransitionOperation")
        for name in ("goal_ref", "goal_spec_ref"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        if self.operation is GoalTransitionOperation.CREATE:
            if self.goal_spec_ref is None or self.goal_ref is not None:
                raise ValueError("create requires goal_spec_ref without goal_ref")
        elif self.goal_ref is None:
            raise ValueError("non-create goal transition requires goal_ref")
        require_revision(self.expected_goal_revision, "expected_goal_revision")
        if not isinstance(self.payload, GoalTransitionPayload):
            raise ValueError("payload must be GoalTransitionPayload")
        self.payload.validate_for(self.operation)
        object.__setattr__(
            self, "reason_refs", _ids(self.reason_refs, "reason_refs", non_empty=True)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "operation": self.operation.value,
            "goal_ref": self.goal_ref,
            "goal_spec_ref": self.goal_spec_ref,
            "expected_goal_revision": self.expected_goal_revision,
            "payload": self.payload.to_dict(),
            "reason_refs": list(self.reason_refs),
        }


@dataclass(frozen=True, slots=True)
class CommitmentTransitionPayload:
    semantic_commitment_ref: str | None = None
    counterparty_ref: str | None = None
    related_goal_refs: tuple[str, ...] = ()
    strength: int | None = None
    priority: int | None = None
    due_condition_refs: tuple[str, ...] = ()
    release_condition_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.semantic_commitment_ref is not None:
            require_identifier(self.semantic_commitment_ref, "semantic_commitment_ref")
        if self.counterparty_ref is not None:
            require_identifier(self.counterparty_ref, "counterparty_ref")
        for name in (
            "related_goal_refs",
            "due_condition_refs",
            "release_condition_refs",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        for name in ("strength", "priority"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 0 <= value <= 100):
                raise ValueError(f"{name} must be an int between 0 and 100")

    def validate_for(self, operation: CommitmentTransitionOperation) -> None:
        if operation is CommitmentTransitionOperation.CREATE:
            if (
                self.semantic_commitment_ref is None
                or self.strength is None
                or self.priority is None
            ):
                raise ValueError("create requires semantic ref, strength and priority")
        elif (
            self.semantic_commitment_ref is not None
            or self.counterparty_ref is not None
            or bool(self.related_goal_refs)
            or self.strength is not None
            or self.priority is not None
            or bool(self.due_condition_refs)
            or bool(self.release_condition_refs)
        ):
            raise ValueError("commitment transition operation does not accept payload values")

    def reference_ids(self) -> tuple[str, ...]:
        return (
            (() if self.semantic_commitment_ref is None else (self.semantic_commitment_ref,))
            + (() if self.counterparty_ref is None else (self.counterparty_ref,))
            + self.related_goal_refs
            + self.due_condition_refs
            + self.release_condition_refs
        )

    def commitment_fact_reference_ids(self) -> tuple[str, ...]:
        return () if self.semantic_commitment_ref is None else (self.semantic_commitment_ref,)

    def goal_fact_reference_ids(self) -> tuple[str, ...]:
        return self.related_goal_refs

    def bounded_reference_ids(self) -> tuple[str, ...]:
        return (
            (() if self.counterparty_ref is None else (self.counterparty_ref,))
            + self.due_condition_refs
            + self.release_condition_refs
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "semantic_commitment_ref": self.semantic_commitment_ref,
            "counterparty_ref": self.counterparty_ref,
            "related_goal_refs": list(self.related_goal_refs),
            "strength": self.strength,
            "priority": self.priority,
            "due_condition_refs": list(self.due_condition_refs),
            "release_condition_refs": list(self.release_condition_refs),
        }


@dataclass(frozen=True, slots=True)
class CommitmentTransitionIntent:
    intent_id: str
    operation: CommitmentTransitionOperation
    commitment_ref: str | None
    commitment_spec_ref: str | None
    expected_goal_revision: int
    payload: CommitmentTransitionPayload
    reason_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.intent_id, "intent_id")
        if not isinstance(self.operation, CommitmentTransitionOperation):
            raise ValueError("operation must be CommitmentTransitionOperation")
        for name in ("commitment_ref", "commitment_spec_ref"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        if self.operation is CommitmentTransitionOperation.CREATE:
            if self.commitment_spec_ref is None or self.commitment_ref is not None:
                raise ValueError("create requires commitment_spec_ref without commitment_ref")
        elif self.commitment_ref is None:
            raise ValueError("non-create commitment transition requires commitment_ref")
        require_revision(self.expected_goal_revision, "expected_goal_revision")
        if not isinstance(self.payload, CommitmentTransitionPayload):
            raise ValueError("payload must be CommitmentTransitionPayload")
        self.payload.validate_for(self.operation)
        object.__setattr__(
            self, "reason_refs", _ids(self.reason_refs, "reason_refs", non_empty=True)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "operation": self.operation.value,
            "commitment_ref": self.commitment_ref,
            "commitment_spec_ref": self.commitment_spec_ref,
            "expected_goal_revision": self.expected_goal_revision,
            "payload": self.payload.to_dict(),
            "reason_refs": list(self.reason_refs),
        }


@dataclass(frozen=True, slots=True)
class ExecutiveDecisionCandidate:
    candidate_id: str
    trigger_id: str
    source_event_ids: tuple[str, ...]
    source_context_revision: int
    goal_revision: int
    attention_revision: int
    outcome: ExecutiveOutcome
    priority: ExecutivePriority
    interruptibility: ExecutiveInterruptibility
    intents: tuple[ExecutiveIntent, ...]
    goal_transition_intents: tuple[GoalTransitionIntent, ...]
    commitment_transition_intents: tuple[CommitmentTransitionIntent, ...]
    rationale_refs: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.candidate_id, "candidate_id")
        require_identifier(self.trigger_id, "trigger_id")
        object.__setattr__(
            self,
            "source_event_ids",
            _ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        for name in ("source_context_revision", "goal_revision", "attention_revision"):
            require_revision(getattr(self, name), name)
        for name, enum_type in (
            ("outcome", ExecutiveOutcome),
            ("priority", ExecutivePriority),
            ("interruptibility", ExecutiveInterruptibility),
        ):
            if not isinstance(getattr(self, name), enum_type):
                raise ValueError(f"{name} has an invalid value")
        for name, item_type in (
            ("intents", ExecutiveIntent),
            ("goal_transition_intents", GoalTransitionIntent),
            ("commitment_transition_intents", CommitmentTransitionIntent),
        ):
            object.__setattr__(self, name, _owned(getattr(self, name), item_type, name))
        all_ids = [
            item.intent_id
            for values in (
                self.intents,
                self.goal_transition_intents,
                self.commitment_transition_intents,
            )
            for item in values
        ]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("all intent ids must be unique")
        if any(
            item.expected_goal_revision != self.goal_revision
            for values in (
                self.goal_transition_intents,
                self.commitment_transition_intents,
            )
            for item in values
        ):
            raise ValueError("transition revision must match candidate goal_revision")
        passive = {
            ExecutiveOutcome.WAIT,
            ExecutiveOutcome.IGNORE,
            ExecutiveOutcome.DEFER,
            ExecutiveOutcome.SILENCE,
        }
        if self.outcome in passive and (
            self.intents or self.goal_transition_intents or self.commitment_transition_intents
        ):
            raise ValueError("passive outcome cannot contain intents")
        intent_kinds = {item.kind for item in self.intents}
        if (
            self.outcome is ExecutiveOutcome.RESPOND
            and ExecutiveIntentKind.SPEECH not in intent_kinds
        ):
            raise ValueError("respond outcome requires speech intent")
        if self.outcome is ExecutiveOutcome.ACT and not intent_kinds.intersection(
            {ExecutiveIntentKind.ACTIVITY, ExecutiveIntentKind.BODY}
        ):
            raise ValueError("act outcome requires activity or body intent")
        object.__setattr__(
            self, "rationale_refs", _ids(self.rationale_refs, "rationale_refs", non_empty=True)
        )
        require_aware(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "trigger_id": self.trigger_id,
            "source_event_ids": list(self.source_event_ids),
            "source_context_revision": self.source_context_revision,
            "goal_revision": self.goal_revision,
            "attention_revision": self.attention_revision,
            "outcome": self.outcome.value,
            "priority": self.priority.value,
            "interruptibility": self.interruptibility.value,
            "intents": [item.to_dict() for item in self.intents],
            "goal_transition_intents": [item.to_dict() for item in self.goal_transition_intents],
            "commitment_transition_intents": [
                item.to_dict() for item in self.commitment_transition_intents
            ],
            "rationale_refs": list(self.rationale_refs),
            "created_at": timestamp_to_json(self.created_at),
        }


@dataclass(frozen=True, slots=True)
class CommittedExecutiveDecision:
    decision_id: str
    candidate: ExecutiveDecisionCandidate
    validated_preconditions: tuple[PreconditionFact, ...]
    committed_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.decision_id, "decision_id")
        if not isinstance(self.candidate, ExecutiveDecisionCandidate):
            raise ValueError("candidate must be ExecutiveDecisionCandidate")
        object.__setattr__(
            self,
            "validated_preconditions",
            _owned(
                self.validated_preconditions,
                PreconditionFact,
                "validated_preconditions",
            ),
        )
        require_aware(self.committed_at, "committed_at")
        if utc_instant(self.committed_at) < utc_instant(self.candidate.created_at):
            raise ValueError("committed_at cannot predate candidate")

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "candidate": self.candidate.to_dict(),
            "validated_preconditions": [item.to_dict() for item in self.validated_preconditions],
            "committed_at": timestamp_to_json(self.committed_at),
        }

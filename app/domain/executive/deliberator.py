from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeVar, cast

from app.domain.contracts import CapabilityRequirement, RevisionVector
from app.domain.contracts.common import JsonValue, freeze_json, require_aware, utc_instant
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMPriority,
    LLMRoleDescriptor,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
    validate_role_exchange,
)
from app.usecases.ports.llm import LLMRolePort

from .authority import ExecutiveDecisionAuthority
from .contracts import (
    ActivityIntentPayload,
    AttentionIntentPayload,
    BodyIntentPayload,
    CommitmentTransitionIntent,
    CommitmentTransitionOperation,
    CommitmentTransitionPayload,
    CommittedExecutiveDecision,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePreconditionRequirement,
    ExecutivePriority,
    GoalTransitionIntent,
    GoalTransitionOperation,
    GoalTransitionPayload,
    IntentPayload,
    SpeechIntentPayload,
)

ROLE_ID = "executive_deliberation"
INPUT_SCHEMA = "executive.context.v1"
OUTPUT_SCHEMA = "executive.candidate.v1"


@dataclass(frozen=True, slots=True)
class ExecutivePolicy:
    execution: LLMExecutionPolicy


class ExecutiveLiveStatePort(Protocol):
    async def current_for_commit(
        self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
    ) -> ExecutiveCommitState: ...


def descriptor(policy: ExecutivePolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        ROLE_ID,
        "bounded contextから意識的なGoal・Action候補を選ぶ",
        INPUT_SCHEMA,
        OUTPUT_SCHEMA,
        "executive_candidate_only",
        LLMActivationPolicy.REQUIRED,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.execution,
    )


def build_request(
    snapshot: ExecutiveContextSnapshot,
    *,
    request_id: str,
    trace_id: str,
    created_at: datetime,
    policy: ExecutivePolicy,
) -> LLMRoleRequest:
    require_aware(created_at, "created_at")
    if utc_instant(created_at) < utc_instant(snapshot.captured_at):
        raise ValueError("request creation cannot predate context snapshot")
    value = cast(JsonValue, snapshot.to_dict())
    return LLMRoleRequest(
        request_id,
        ROLE_ID,
        StructuredPayload(INPUT_SCHEMA, value),
        snapshot.source_event_ids,
        RevisionVector(
            snapshot.source_context_revision, snapshot.goal_revision, snapshot.attention_revision
        ),
        (),
        LLMPriority.FOREGROUND if snapshot.meaning is not None else LLMPriority.BACKGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        policy.execution,
        created_at,
        trace_id,
    )


def parse_candidate(
    value: object, snapshot: ExecutiveContextSnapshot, *, created_at: datetime
) -> ExecutiveDecisionCandidate:
    if not isinstance(value, Mapping):
        raise ValueError("executive candidate must be an object")
    required = {
        "candidate_id",
        "trigger_id",
        "source_event_ids",
        "source_context_revision",
        "goal_revision",
        "attention_revision",
        "outcome",
        "priority",
        "interruptibility",
        "intents",
        "goal_transition_intents",
        "commitment_transition_intents",
        "rationale_refs",
    }
    if set(value) != required:
        raise ValueError("executive candidate fields do not match schema")
    return ExecutiveDecisionCandidate(
        _string(value["candidate_id"], "candidate_id"),
        _string(value["trigger_id"], "trigger_id"),
        _strings(value["source_event_ids"], "source_event_ids"),
        _revision(value["source_context_revision"], "source_context_revision"),
        _revision(value["goal_revision"], "goal_revision"),
        _revision(value["attention_revision"], "attention_revision"),
        _enum(ExecutiveOutcome, value["outcome"], "outcome"),
        _enum(ExecutivePriority, value["priority"], "priority"),
        _enum(ExecutiveInterruptibility, value["interruptibility"], "interruptibility"),
        tuple(_intent(item) for item in _array(value["intents"], "intents")),
        tuple(
            _goal_transition(item)
            for item in _array(value["goal_transition_intents"], "goal_transition_intents")
        ),
        tuple(
            _commitment_transition(item)
            for item in _array(
                value["commitment_transition_intents"], "commitment_transition_intents"
            )
        ),
        _strings(value["rationale_refs"], "rationale_refs"),
        created_at,
    )


def commit_result(
    request: LLMRoleRequest,
    result: LLMRoleResult,
    *,
    snapshot: ExecutiveContextSnapshot,
    current: ExecutiveCommitState,
    authority: ExecutiveDecisionAuthority,
    decision_id: str,
    policy: ExecutivePolicy,
) -> CommittedExecutiveDecision:
    failure = validate_role_exchange(descriptor(policy), request, result)
    if failure is not None:
        raise ValueError(failure.code.value)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise ValueError("executive result is not committable")
    if request.input.value != freeze_json(snapshot.to_dict()):
        raise ValueError("executive context does not match request snapshot")
    candidate = parse_candidate(result.output.value, snapshot, created_at=result.completed_at)
    return authority.commit(
        candidate,
        snapshot,
        current=current,
        decision_id=decision_id,
        committed_at=result.completed_at,
    )


class ExecutiveDeliberator:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: ExecutiveLiveStatePort,
        policy: ExecutivePolicy,
        authority: ExecutiveDecisionAuthority,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._policy = policy
        self._authority = authority

    async def deliberate(
        self,
        snapshot: ExecutiveContextSnapshot,
        *,
        request_id: str,
        trace_id: str,
        decision_id: str,
        created_at: datetime,
    ) -> CommittedExecutiveDecision:
        request = build_request(
            snapshot,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)
        failure = validate_role_exchange(descriptor(self._policy), request, result)
        if failure is not None:
            raise ValueError(failure.code.value)
        if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
            raise ValueError("executive result is not committable")
        candidate = parse_candidate(result.output.value, snapshot, created_at=result.completed_at)
        current = await self._live_state.current_for_commit(snapshot, candidate)
        return commit_result(
            request,
            result,
            snapshot=snapshot,
            current=current,
            authority=self._authority,
            decision_id=decision_id,
            policy=self._policy,
        )


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    return tuple(_string(item, name) for item in _array(value, name))


def _revision(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return value


E = TypeVar("E", bound=Enum)


def _enum(enum_type: type[E], value: object, name: str) -> E:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"{name} has an invalid value") from error


def _object(value: object, name: str, fields: set[str]) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or set(value) != fields
        or any(not isinstance(key, str) for key in value)
    ):
        raise ValueError(f"{name} fields do not match schema")
    return cast(Mapping[str, object], value)


def _requirement(value: object) -> CapabilityRequirement:
    item = _object(
        value, "capability requirement", {"capability_type", "operation", "allow_degraded"}
    )
    allow_degraded = item["allow_degraded"]
    if not isinstance(allow_degraded, bool):
        raise ValueError("allow_degraded must be bool")
    return CapabilityRequirement(
        _string(item["capability_type"], "capability_type"),
        _string(item["operation"], "operation"),
        allow_degraded,
    )


def _intent(value: object) -> ExecutiveIntent:
    fields = {
        "intent_id",
        "kind",
        "purpose",
        "payload",
        "evidence_refs",
        "required_capabilities",
        "preconditions",
        "forbidden_claim_refs",
    }
    item = _object(value, "executive intent", fields)
    kind = _enum(ExecutiveIntentKind, item["kind"], "kind")
    return ExecutiveIntent(
        _string(item["intent_id"], "intent_id"),
        kind,
        _string(item["purpose"], "purpose"),
        _intent_payload(kind, item["payload"]),
        _strings(item["evidence_refs"], "evidence_refs"),
        tuple(
            _requirement(entry)
            for entry in _array(item["required_capabilities"], "required_capabilities")
        ),
        tuple(
            _precondition_requirement(entry)
            for entry in _array(item["preconditions"], "preconditions")
        ),
        _strings(item["forbidden_claim_refs"], "forbidden_claim_refs"),
    )


def _optional_string(value: object, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _intent_payload(kind: ExecutiveIntentKind, value: object) -> IntentPayload:
    if kind is ExecutiveIntentKind.SPEECH:
        item = _object(
            value, "speech payload", {"semantic_goal_ref", "target_ref", "constraint_refs"}
        )
        return SpeechIntentPayload(
            _string(item["semantic_goal_ref"], "semantic_goal_ref"),
            _optional_string(item["target_ref"], "target_ref"),
            _strings(item["constraint_refs"], "constraint_refs"),
        )
    if kind is ExecutiveIntentKind.BODY:
        item = _object(value, "body payload", {"motion_goal_ref", "target_ref", "constraint_refs"})
        return BodyIntentPayload(
            _string(item["motion_goal_ref"], "motion_goal_ref"),
            _optional_string(item["target_ref"], "target_ref"),
            _strings(item["constraint_refs"], "constraint_refs"),
        )
    if kind is ExecutiveIntentKind.ACTIVITY:
        item = _object(
            value, "activity payload", {"activity_type", "target_ref", "constraint_refs"}
        )
        return ActivityIntentPayload(
            _string(item["activity_type"], "activity_type"),
            _optional_string(item["target_ref"], "target_ref"),
            _strings(item["constraint_refs"], "constraint_refs"),
        )
    item = _object(value, "attention payload", {"target_ref", "mode", "constraint_refs"})
    return AttentionIntentPayload(
        _string(item["target_ref"], "target_ref"),
        _string(item["mode"], "mode"),
        _strings(item["constraint_refs"], "constraint_refs"),
    )


def _precondition_requirement(value: object) -> ExecutivePreconditionRequirement:
    item = _object(
        value,
        "precondition requirement",
        {"precondition_id", "expected"},
    )
    return ExecutivePreconditionRequirement(
        _string(item["precondition_id"], "precondition_id"),
        cast(JsonValue, item["expected"]),
    )


def _goal_transition(value: object) -> GoalTransitionIntent:
    item = _object(
        value,
        "goal transition",
        {
            "intent_id",
            "operation",
            "goal_ref",
            "goal_spec_ref",
            "expected_goal_revision",
            "payload",
            "reason_refs",
        },
    )
    goal_ref, spec_ref = item["goal_ref"], item["goal_spec_ref"]
    if goal_ref is not None:
        goal_ref = _string(goal_ref, "goal_ref")
    if spec_ref is not None:
        spec_ref = _string(spec_ref, "goal_spec_ref")
    operation = _enum(GoalTransitionOperation, item["operation"], "operation")
    return GoalTransitionIntent(
        _string(item["intent_id"], "intent_id"),
        operation,
        goal_ref,
        spec_ref,
        _revision(item["expected_goal_revision"], "expected_goal_revision"),
        _goal_payload(item["payload"]),
        _strings(item["reason_refs"], "reason_refs"),
    )


def _commitment_transition(value: object) -> CommitmentTransitionIntent:
    item = _object(
        value,
        "commitment transition",
        {
            "intent_id",
            "operation",
            "commitment_ref",
            "commitment_spec_ref",
            "expected_goal_revision",
            "payload",
            "reason_refs",
        },
    )
    commitment_ref, spec_ref = item["commitment_ref"], item["commitment_spec_ref"]
    if commitment_ref is not None:
        commitment_ref = _string(commitment_ref, "commitment_ref")
    if spec_ref is not None:
        spec_ref = _string(spec_ref, "commitment_spec_ref")
    operation = _enum(CommitmentTransitionOperation, item["operation"], "operation")
    return CommitmentTransitionIntent(
        _string(item["intent_id"], "intent_id"),
        operation,
        commitment_ref,
        spec_ref,
        _revision(item["expected_goal_revision"], "expected_goal_revision"),
        _commitment_payload(item["payload"]),
        _strings(item["reason_refs"], "reason_refs"),
    )


def _goal_payload(value: object) -> GoalTransitionPayload:
    item = _object(
        value,
        "goal transition payload",
        {
            "semantic_goal_ref",
            "priority",
            "superseding_goal_ref",
            "goal_kind",
            "target_ref",
            "commitment_refs",
            "precondition_ids",
            "completion_condition_refs",
            "interruption_policy",
        },
    )
    priority = item["priority"]
    if priority is not None:
        priority = _revision(priority, "priority")
    return GoalTransitionPayload(
        _optional_string(item["semantic_goal_ref"], "semantic_goal_ref"),
        priority,
        _optional_string(item["superseding_goal_ref"], "superseding_goal_ref"),
        _optional_string(item["goal_kind"], "goal_kind"),
        _optional_string(item["target_ref"], "target_ref"),
        _strings(item["commitment_refs"], "commitment_refs"),
        _strings(item["precondition_ids"], "precondition_ids"),
        _strings(item["completion_condition_refs"], "completion_condition_refs"),
        _optional_string(item["interruption_policy"], "interruption_policy"),
    )


def _commitment_payload(value: object) -> CommitmentTransitionPayload:
    item = _object(
        value,
        "commitment transition payload",
        {
            "semantic_commitment_ref",
            "counterparty_ref",
            "related_goal_refs",
            "strength",
            "priority",
            "due_condition_refs",
            "release_condition_refs",
        },
    )
    strength, priority = item["strength"], item["priority"]
    if strength is not None:
        strength = _revision(strength, "strength")
    if priority is not None:
        priority = _revision(priority, "priority")
    return CommitmentTransitionPayload(
        _optional_string(item["semantic_commitment_ref"], "semantic_commitment_ref"),
        _optional_string(item["counterparty_ref"], "counterparty_ref"),
        _strings(item["related_goal_refs"], "related_goal_refs"),
        strength,
        priority,
        _strings(item["due_condition_refs"], "due_condition_refs"),
        _strings(item["release_condition_refs"], "release_condition_refs"),
    )

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeVar, cast

from app.domain.contracts import RevisionVector
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

from .authority import SpeechSemanticAuthority
from .contracts import (
    DeterministicSpeechDirective,
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticPlan,
)

ROLE_ID = "speech_semantics"
INPUT_SCHEMA = "yura.speech-semantics.context.v1"
OUTPUT_SCHEMA = "yura.speech-semantics.candidate.v1"


@dataclass(frozen=True, slots=True)
class SpeechSemanticsPolicy:
    execution: LLMExecutionPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.execution, LLMExecutionPolicy):
            raise ValueError("execution must be LLMExecutionPolicy")


class SpeechSemanticsLiveStatePort(Protocol):
    async def current_revisions(
        self, snapshot: SpeechSemanticContextSnapshot
    ) -> RevisionVector: ...


def descriptor(policy: SpeechSemanticsPolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        ROLE_ID,
        "bounded factから発話内容candidateを構成する",
        INPUT_SCHEMA,
        OUTPUT_SCHEMA,
        "speech_semantic_candidate_only",
        LLMActivationPolicy.CONDITIONAL,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.execution,
    )


def build_request(
    snapshot: SpeechSemanticContextSnapshot,
    *,
    request_id: str,
    trace_id: str,
    created_at: datetime,
    policy: SpeechSemanticsPolicy,
) -> LLMRoleRequest:
    if not isinstance(snapshot, SpeechSemanticContextSnapshot):
        raise ValueError("snapshot must be SpeechSemanticContextSnapshot")
    require_aware(created_at, "created_at")
    if utc_instant(created_at) < utc_instant(snapshot.captured_at):
        raise ValueError("request creation cannot predate speech semantic snapshot")
    return LLMRoleRequest(
        request_id,
        ROLE_ID,
        StructuredPayload(INPUT_SCHEMA, cast(JsonValue, snapshot.to_dict())),
        snapshot.source_event_ids,
        snapshot.revisions,
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        policy.execution,
        created_at,
        trace_id,
    )


def candidate_from_directive(
    snapshot: SpeechSemanticContextSnapshot,
    directive: DeterministicSpeechDirective,
    *,
    candidate_id: str,
    created_at: datetime,
) -> SpeechSemanticCandidate:
    if snapshot.deterministic_directive != directive:
        raise ValueError("directive does not match speech semantic snapshot")
    return SpeechSemanticCandidate(
        candidate_id,
        snapshot.decision.decision_id,
        snapshot.intent_id,
        snapshot.source_event_ids,
        snapshot.revisions,
        directive.propositions,
        directive.self_disclosure,
        directive.question_budget,
        directive.new_direction_budget,
        directive.truth_constraint_refs,
        directive.relationship_constraint_refs,
        directive.discourse_constraint_refs,
        created_at,
    )


E = TypeVar("E", bound=Enum)


def parse_candidate(value: object, *, created_at: datetime) -> SpeechSemanticCandidate:
    if not isinstance(value, Mapping):
        raise ValueError("speech semantic candidate must be an object")
    required = {
        "candidate_id",
        "decision_id",
        "intent_id",
        "source_event_ids",
        "revisions",
        "propositions",
        "self_disclosure",
        "question_budget",
        "new_direction_budget",
        "truth_constraint_refs",
        "relationship_constraint_refs",
        "discourse_constraint_refs",
    }
    if set(value) != required:
        raise ValueError("speech semantic candidate fields do not match schema")
    revisions = _mapping(value["revisions"], "revisions")
    if set(revisions) != {
        "source_context_revision",
        "goal_revision",
        "attention_revision",
    }:
        raise ValueError("speech semantic revision fields do not match schema")
    return SpeechSemanticCandidate(
        _string(value["candidate_id"], "candidate_id"),
        _string(value["decision_id"], "decision_id"),
        _string(value["intent_id"], "intent_id"),
        _strings(value["source_event_ids"], "source_event_ids"),
        RevisionVector(
            _revision(revisions["source_context_revision"], "source_context_revision"),
            _revision(revisions["goal_revision"], "goal_revision"),
            _revision(revisions["attention_revision"], "attention_revision"),
        ),
        tuple(_proposition(item) for item in _array(value["propositions"], "propositions")),
        _enum(SelfDisclosurePolicy, value["self_disclosure"], "self_disclosure"),
        _revision(value["question_budget"], "question_budget"),
        _revision(value["new_direction_budget"], "new_direction_budget"),
        _strings(value["truth_constraint_refs"], "truth_constraint_refs"),
        _strings(value["relationship_constraint_refs"], "relationship_constraint_refs"),
        _strings(value["discourse_constraint_refs"], "discourse_constraint_refs"),
        created_at,
    )


def commit_result(
    request: LLMRoleRequest,
    result: LLMRoleResult,
    *,
    snapshot: SpeechSemanticContextSnapshot,
    current_revisions: RevisionVector,
    authority: SpeechSemanticAuthority,
    plan_id: str,
    policy: SpeechSemanticsPolicy,
) -> SpeechSemanticPlan:
    failure = validate_role_exchange(descriptor(policy), request, result)
    if failure is not None:
        raise ValueError(failure.code.value)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise ValueError("speech semantic result is not committable")
    if request.input.value != freeze_json(snapshot.to_dict()):
        raise ValueError("speech semantic snapshot does not match request")
    if request.source_event_ids != snapshot.source_event_ids:
        raise ValueError("request source events do not match speech semantic snapshot")
    if request.revisions != snapshot.revisions:
        raise ValueError("request revisions do not match speech semantic snapshot")
    candidate = parse_candidate(result.output.value, created_at=result.completed_at)
    return authority.commit(
        candidate,
        snapshot,
        current_revisions=current_revisions,
        plan_id=plan_id,
        committed_at=result.completed_at,
    )


class SpeechSemanticsPlanner:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: SpeechSemanticsLiveStatePort,
        authority: SpeechSemanticAuthority,
        policy: SpeechSemanticsPolicy,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._authority = authority
        self._policy = policy

    async def plan(
        self,
        snapshot: SpeechSemanticContextSnapshot,
        *,
        request_id: str,
        trace_id: str,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> SpeechSemanticPlan:
        directive = snapshot.deterministic_directive
        if directive is not None:
            candidate = candidate_from_directive(
                snapshot,
                directive,
                candidate_id=candidate_id,
                created_at=created_at,
            )
            current = await self._live_state.current_revisions(snapshot)
            return self._authority.commit(
                candidate,
                snapshot,
                current_revisions=current,
                plan_id=plan_id,
                committed_at=created_at,
            )
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
            raise ValueError("speech semantic result is not committable")
        parse_candidate(result.output.value, created_at=result.completed_at)
        current = await self._live_state.current_revisions(snapshot)
        return commit_result(
            request,
            result,
            snapshot=snapshot,
            current_revisions=current,
            authority=self._authority,
            plan_id=plan_id,
            policy=self._policy,
        )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


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


def _enum(enum_type: type[E], value: object, name: str) -> E:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"{name} has an invalid value") from error


def _proposition(value: object) -> SpeechProposition:
    item = _mapping(value, "proposition")
    required = {
        "proposition_id",
        "subject_ref",
        "predicate",
        "value",
        "disposition",
        "polarity",
        "certainty",
        "degree",
        "evidence_fact_refs",
    }
    if set(item) != required:
        raise ValueError("speech proposition fields do not match schema")
    degree = item["degree"]
    if degree is not None and type(degree) not in (int, float):
        raise ValueError("degree must be a number or null")
    return SpeechProposition(
        _string(item["proposition_id"], "proposition_id"),
        _string(item["subject_ref"], "subject_ref"),
        _string(item["predicate"], "predicate"),
        cast(JsonValue, item["value"]),
        _enum(SpeechPropositionDisposition, item["disposition"], "disposition"),
        _enum(SemanticPolarity, item["polarity"], "polarity"),
        _enum(SemanticCertainty, item["certainty"], "certainty"),
        _strings(item["evidence_fact_refs"], "evidence_fact_refs"),
        cast(float | None, degree),
    )

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeVar, cast

from app.domain.contracts.common import JsonValue, freeze_json, require_aware, utc_instant
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMRoleDescriptor,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
    validate_role_exchange,
)
from app.usecases.ports.llm import LLMRolePort

from .authority import CharacterLanguageAuthority
from .contracts import (
    CharacterLanguageCommitState,
    CharacterLanguageContextSnapshot,
    CharacterUtterance,
    CharacterUtteranceCandidate,
    CharacterUtteranceSegment,
    LinguisticBoundary,
    LinguisticEmphasis,
    LinguisticHesitation,
)

ROLE_ID = "character_language"
INPUT_SCHEMA = "character.language.context.v2"
OUTPUT_SCHEMA = "character.language.candidate.v1"


@dataclass(frozen=True, slots=True)
class CharacterLanguagePolicy:
    execution: LLMExecutionPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.execution, LLMExecutionPolicy):
            raise ValueError("execution は LLMExecutionPolicy でなければなりません")


class CharacterLanguageLiveStatePort(Protocol):
    async def current_state(
        self, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageCommitState: ...


def descriptor(policy: CharacterLanguagePolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        ROLE_ID,
        "確定済み発話意味をCharacterらしい表現候補へ実現する",
        INPUT_SCHEMA,
        OUTPUT_SCHEMA,
        "character_utterance_candidate_only",
        LLMActivationPolicy.CONDITIONAL,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.execution,
    )


def build_request(
    snapshot: CharacterLanguageContextSnapshot,
    *,
    created_at: datetime,
    policy: CharacterLanguagePolicy,
) -> LLMRoleRequest:
    if not isinstance(snapshot, CharacterLanguageContextSnapshot):
        raise ValueError("snapshot は CharacterLanguageContextSnapshot でなければなりません")
    require_aware(created_at, "created_at")
    if utc_instant(created_at) < utc_instant(snapshot.captured_at):
        raise ValueError("request作成時刻はsnapshotより前にできません")
    return LLMRoleRequest(
        snapshot.request_id,
        ROLE_ID,
        StructuredPayload(INPUT_SCHEMA, cast(JsonValue, snapshot.to_dict())),
        snapshot.source_event_ids,
        snapshot.revisions,
        (),
        snapshot.llm_priority,
        snapshot.interruptibility,
        LLMStalePolicy.REJECT,
        policy.execution,
        created_at,
        snapshot.trace_id,
    )


E = TypeVar("E", bound=Enum)


def parse_candidate(value: object, *, created_at: datetime) -> CharacterUtteranceCandidate:
    item = _mapping(value, "Character Language candidate")
    required = {
        "candidate_id",
        "request_id",
        "semantic_plan_id",
        "source_decision_id",
        "source_intent_id",
        "source_event_ids",
        "revisions",
        "character_id",
        "character_schema_version",
        "character_definition_revision",
        "segments",
        "question_budget_used",
        "new_direction_budget_used",
    }
    if set(item) != required:
        raise ValueError("Character Language candidate fieldがschemaと一致しません")
    revisions = _mapping(item["revisions"], "revisions")
    if set(revisions) != {"source_context_revision", "goal_revision", "attention_revision"}:
        raise ValueError("revision fieldがschemaと一致しません")
    from app.domain.contracts import RevisionVector

    return CharacterUtteranceCandidate(
        _string(item["candidate_id"], "candidate_id"),
        _string(item["request_id"], "request_id"),
        _string(item["semantic_plan_id"], "semantic_plan_id"),
        _string(item["source_decision_id"], "source_decision_id"),
        _string(item["source_intent_id"], "source_intent_id"),
        _strings(item["source_event_ids"], "source_event_ids"),
        RevisionVector(
            _revision(revisions["source_context_revision"], "source_context_revision"),
            _optional_revision(revisions["goal_revision"], "goal_revision"),
            _optional_revision(revisions["attention_revision"], "attention_revision"),
        ),
        _string(item["character_id"], "character_id"),
        _revision(item["character_schema_version"], "character_schema_version"),
        _revision(item["character_definition_revision"], "character_definition_revision"),
        tuple(_segment(part) for part in _array(item["segments"], "segments")),
        _revision(item["question_budget_used"], "question_budget_used"),
        _revision(item["new_direction_budget_used"], "new_direction_budget_used"),
        created_at,
    )


def commit_result(
    request: LLMRoleRequest,
    result: LLMRoleResult,
    *,
    snapshot: CharacterLanguageContextSnapshot,
    current: CharacterLanguageCommitState,
    authority: CharacterLanguageAuthority,
    utterance_id: str,
    policy: CharacterLanguagePolicy,
) -> CharacterUtterance:
    failure = validate_role_exchange(descriptor(policy), request, result)
    if failure is not None:
        raise ValueError(failure.code.value)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise ValueError("Character Language resultはcommitできません")
    if request.input.value != freeze_json(snapshot.to_dict()):
        raise ValueError("request inputがsnapshotと一致しません")
    if (
        request.source_event_ids != snapshot.source_event_ids
        or request.revisions != snapshot.revisions
    ):
        raise ValueError("request provenanceがsnapshotと一致しません")
    candidate = parse_candidate(result.output.value, created_at=result.completed_at)
    return authority.commit(
        candidate,
        snapshot,
        current=current,
        utterance_id=utterance_id,
        committed_at=result.completed_at,
    )


class CharacterLanguageRealizer:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: CharacterLanguageLiveStatePort,
        authority: CharacterLanguageAuthority,
        policy: CharacterLanguagePolicy,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._authority = authority
        self._policy = policy

    async def realize(
        self,
        snapshot: CharacterLanguageContextSnapshot,
        *,
        utterance_id: str,
        created_at: datetime,
    ) -> CharacterUtterance:
        request = build_request(snapshot, created_at=created_at, policy=self._policy)
        result = await self._port.invoke(request)
        failure = validate_role_exchange(descriptor(self._policy), request, result)
        if failure is not None:
            raise ValueError(failure.code.value)
        if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
            raise ValueError("Character Language resultはcommitできません")
        parse_candidate(result.output.value, created_at=result.completed_at)
        current = await self._live_state.current_state(snapshot)
        return commit_result(
            request,
            result,
            snapshot=snapshot,
            current=current,
            authority=self._authority,
            utterance_id=utterance_id,
            policy=self._policy,
        )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} はobjectでなければなりません")
    return cast(Mapping[str, object], value)


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} はarrayでなければなりません")
    return tuple(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} は空でない文字列でなければなりません")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    return tuple(_string(item, name) for item in _array(value, name))


def _revision(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} は0以上の整数でなければなりません")
    return value


def _optional_revision(value: object, name: str) -> int | None:
    return None if value is None else _revision(value, name)


def _enum(enum_type: type[E], value: object, name: str) -> E:
    if not isinstance(value, str):
        raise ValueError(f"{name} は文字列でなければなりません")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"{name} が不正です") from error


def _segment(value: object) -> CharacterUtteranceSegment:
    item = _mapping(value, "segment")
    required = {
        "segment_id",
        "text",
        "realization_refs",
        "boundary_after",
        "emphasis",
        "hesitation",
    }
    if set(item) != required:
        raise ValueError("segment fieldがschemaと一致しません")
    return CharacterUtteranceSegment(
        _string(item["segment_id"], "segment_id"),
        _string(item["text"], "text"),
        _strings(item["realization_refs"], "realization_refs"),
        _enum(LinguisticBoundary, item["boundary_after"], "boundary_after"),
        _enum(LinguisticEmphasis, item["emphasis"], "emphasis"),
        _enum(LinguisticHesitation, item["hesitation"], "hesitation"),
    )

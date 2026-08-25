from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

from app.domain.contracts import RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
)
from app.domain.semantic_verification import (
    BlindUtteranceObservation,
    SemanticVerificationContextSnapshot,
    SemanticVerificationPolicy,
    blind_instructions,
    build_blind_request,
    build_relation_request,
    relation_instructions,
)

NOW = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
REVISIONS = RevisionVector(1, 1, 1)


def _policy() -> SemanticVerificationPolicy:
    execution = LLMExecutionPolicy(
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        20,
        1,
        1200,
    )
    return SemanticVerificationPolicy(execution, execution)


def _snapshot() -> SemanticVerificationContextSnapshot:
    segment = SimpleNamespace(segment_id="segment-1", text="今日は雨だよ。")
    utterance = SimpleNamespace(
        utterance_id="utterance-1",
        candidate=SimpleNamespace(segments=(segment,)),
    )
    semantic_plan = SimpleNamespace(
        plan_id="plan-1",
        to_dict=lambda: {"plan_id": "plan-1"},
    )
    value = SimpleNamespace(
        verification_id="verification-1",
        blind_request_id="blind-request-1",
        relation_request_id="relation-request-1",
        utterance=utterance,
        semantic_plan=semantic_plan,
        source_event_ids=("event-1",),
        revisions=REVISIONS,
        llm_priority=LLMPriority.FOREGROUND,
        interruptibility=LLMInterruptibility.INTERRUPTIBLE,
        captured_at=NOW,
        trace_id="trace-1",
        pair_dict=lambda: {"semantic_plan_id": "plan-1", "utterance_id": "utterance-1"},
    )
    return cast(SemanticVerificationContextSnapshot, value)


def test_blind_provider_payload_exposes_exact_request_identity() -> None:
    request = build_blind_request(
        _snapshot(),
        created_at=NOW,
        policy=_policy(),
    )
    payload = cast(dict[str, JsonValue], request.input.to_dict()["value"])

    assert payload["request_id"] == request.request_id == "blind-request-1"
    assert "exact" in blind_instructions().lower()


def test_relation_input_keeps_trusted_identity_without_provider_output_echo() -> None:
    blind_value = SimpleNamespace(
        candidate=SimpleNamespace(utterance_id="utterance-1"),
        committed_at=NOW,
        to_dict=lambda: {"observation_id": "blind-observation-1"},
    )
    blind = cast(BlindUtteranceObservation, blind_value)

    request = build_relation_request(
        _snapshot(),
        blind,
        created_at=NOW,
        policy=_policy(),
    )
    payload = cast(dict[str, JsonValue], request.input.to_dict()["value"])
    instructions = relation_instructions()

    assert payload["request_id"] == request.request_id == "relation-request-1"
    assert "Role B Providerの出力責務ではありません" in instructions
    assert (
        "出力のrequest_id / semantic_plan_id / utterance_id / blind_observation_id"
        not in instructions
    )

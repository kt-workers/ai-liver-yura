"""Reflection V1のstrict wire・正規LLM境界・既存採用guardを検証する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from app.domain.contracts.common import freeze_json
from app.domain.llm import (
    LLMActivationPolicy,
    LLMFailureCode,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMPriority,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    LLMTokenUsage,
    StructuredPayload,
)
from app.domain.memory import MemoryContent
from app.domain.memory.contracts import MemoryRelationKind
from app.domain.memory_reflection import (
    ReflectionCandidateStatus,
    ReflectionCoordinator,
    ReflectionRelationHint,
    ReflectionSourceKind,
)
from app.domain.memory_reflection.contracts import (
    MemoryCandidateProposal,
    ReflectionContextSnapshot,
)
from app.domain.memory_reflection.llm_roles import (
    PROPOSAL_INPUT_SCHEMA,
    PROPOSAL_OUTPUT_SCHEMA,
    PROPOSAL_ROLE_ID,
    SUPPORT_INPUT_SCHEMA,
    SUPPORT_OUTPUT_SCHEMA,
    SUPPORT_ROLE_ID,
    LLMReflectionProposalPort,
    LLMReflectionSupportPort,
    ReflectionLLMError,
    ReflectionLLMRolePolicy,
    build_proposal_request,
    build_support_request,
    parse_proposals,
    parse_support,
    proposal_descriptor,
    proposal_to_wire,
    proposal_to_wire_v2,
    support_descriptor,
)
from tests.domain.llm.test_contracts import policy as execution
from tests.domain.memory_reflection.policy_fixtures import reflection_operational_policy
from tests.domain.memory_reflection.test_memory_reflection import (
    NOW,
    authority,
    context,
    proposal,
    source,
)


def role_policy() -> ReflectionLLMRolePolicy:
    return ReflectionLLMRolePolicy(
        execution(), replace(execution(), timeout_seconds=11), reflection_operational_policy()
    )


def snapshot() -> ReflectionContextSnapshot:
    return context(source("s", ReflectionSourceKind.PRESENTATION_FACT))


def candidate() -> MemoryCandidateProposal:
    return replace(proposal("s"), rationale_evidence_refs=("s",))


def support_wire() -> dict[str, Any]:
    return {
        "proposal_id": "proposal-1",
        "support_relation": "supported",
        "evidence_refs": ["s"],
        "unsupported_content_refs": [],
        "contradiction_refs": [],
        "confidence": 0.8,
    }


class RolePort:
    def __init__(self, output: object | None = None) -> None:
        self.output = output
        self.requests: list[LLMRoleRequest] = []
        self.change: dict[str, Any] = {}

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.requests.append(request)
        is_proposal = request.role_id == PROPOSAL_ROLE_ID
        output = (
            self.output
            if self.output is not None
            else (
                {"proposals": [proposal_to_wire_v2(candidate())]} if is_proposal else support_wire()
            )
        )
        result = LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.SUCCEEDED,
            request.revisions,
            NOW,
            request.trace_id,
            request.execution_policy.model_class,
            1,
            LLMTokenUsage(1, 1),
            StructuredPayload(
                PROPOSAL_OUTPUT_SCHEMA if is_proposal else SUPPORT_OUTPUT_SCHEMA,
                freeze_json(output),
            ),
            started_at=NOW,
        )
        return replace(result, **self.change)


@pytest.mark.parametrize("interruptible", [True, False])
def test_descriptor_and_request_exact_mapping(interruptible: bool) -> None:
    c, p, policy = snapshot(), candidate(), role_policy()
    c = replace(c, trigger=replace(c.trigger, interruptible=interruptible))
    request = build_proposal_request(c, created_at=NOW, policy=policy)
    support = build_support_request(c, p, created_at=NOW, policy=policy)
    assert request.request_id == f"{c.reflection_id}:proposal"
    assert request.input.schema_id == PROPOSAL_INPUT_SCHEMA
    assert request.input.value == freeze_json(c.to_dict())
    assert support.request_id == f"{c.reflection_id}:support:{p.proposal_id}"
    assert support.input.schema_id == SUPPORT_INPUT_SCHEMA
    assert support.input.value == freeze_json(
        {"context": c.to_dict(), "proposal": proposal_to_wire_v2(p)}
    )
    for r, d, e in [
        (request, proposal_descriptor(policy), policy.proposal_execution),
        (support, support_descriptor(policy), policy.support_execution),
    ]:
        assert r.execution_policy is e and d.default_execution_policy is e
        assert d.activation is LLMActivationPolicy.BACKGROUND
        assert d.failure_policy is LLMFailurePolicy.FAIL_CLOSED
        assert r.priority is LLMPriority.BACKGROUND and r.stale_policy is LLMStalePolicy.REVALIDATE
        assert r.interruptibility is (
            LLMInterruptibility.INTERRUPTIBLE
            if interruptible
            else LLMInterruptibility.NON_INTERRUPTIBLE
        )
        assert (
            r.source_event_ids == ()
            and r.revisions.source_context_revision == c.source_context_revision
        )
        assert r.revisions.goal_revision is r.revisions.attention_revision is None
        assert r.created_at == NOW and r.trace_id == c.trace_id
    assert proposal_descriptor(policy).role_id == PROPOSAL_ROLE_ID
    assert support_descriptor(policy).role_id == SUPPORT_ROLE_ID
    assert proposal_descriptor(policy).authority_scope == "memory_candidate_proposal_only"
    assert (
        support_descriptor(policy).authority_scope == "memory_reflection_support_observation_only"
    )


@pytest.mark.parametrize(
    "value",
    [None, True, 12, 0.5, "日本語", [1, None, {"x": False}], {"z": [1, 2], "a": {"日本語": 3.5}}],
)
def test_lossless_json_and_temporal_round_trip(value: Any) -> None:
    p = replace(
        candidate(),
        content=MemoryContent("episode", value),
        temporal=replace(candidate().temporal, valid_from=NOW, observed_at=NOW),
    )
    result = parse_proposals(
        {"proposals": [proposal_to_wire(p)]}, snapshot(), role_policy().operational
    )
    assert result == (p,)
    assert result[0].deterministic_capture is False
    assert build_support_request(
        snapshot(), p, created_at=NOW, policy=role_policy()
    ).input.value == freeze_json(
        {"context": snapshot().to_dict(), "proposal": proposal_to_wire_v2(result[0])}
    )


@pytest.mark.parametrize(
    "path,value",
    [
        (("extra",), True),
        (("deterministic_capture",), True),
        (("assertion_semantics",), None),
        (("proposed_kind",), "unknown"),
        (("persistence_hint",), "unknown"),
        (("temporal", "freshness"), "unknown"),
        (("temporal", "observed_at"), "yesterday"),
        (("temporal", "observed_at"), "2026-08-25T00:00:00"),
        (("content", "value_json"), "{"),
        (("content", "value_json"), "NaN"),
        (("content", "value_json"), "Infinity"),
        (("content", "value_json"), "1e999"),
        (("content", "value_json"), '{"a":1,"a":2}'),
        (("source_refs",), ["outside"]),
        (("source_refs",), ["s", "s"]),
        (("rationale_evidence_refs",), ["outside"]),
        (("suggested_related_memory_ids",), ["outside"]),
        (("confidence_hint",), True),
        (("confidence_hint",), 1.1),
    ],
)
def test_malformed_proposal_fail_closed(path: tuple[str, ...], value: object) -> None:
    p: dict[str, Any] = proposal_to_wire(candidate())
    obj = p
    for field in path[:-1]:
        obj = obj[field]
    obj[path[-1]] = value
    with pytest.raises(ReflectionLLMError):
        parse_proposals({"proposals": [p]}, snapshot(), role_policy().operational)


@pytest.mark.parametrize("field", list(proposal_to_wire(candidate())))
def test_missing_proposal_fields_rejected(field: str) -> None:
    wire = proposal_to_wire(candidate())
    del wire[field]
    with pytest.raises(ReflectionLLMError):
        parse_proposals({"proposals": [wire]}, snapshot(), role_policy().operational)


@pytest.mark.parametrize("wire", [{}, {"proposals": [], "extra": 1}, {"proposals": None}])
def test_root_rejected(wire: dict[str, Any]) -> None:
    with pytest.raises(ReflectionLLMError):
        parse_proposals(wire, snapshot(), role_policy().operational)


def test_relation_provenance_and_strict_shape() -> None:
    hint = ReflectionRelationHint("memory-1", 2, MemoryRelationKind.CONTRADICTS, ("s",), 0.8)
    p = replace(candidate(), suggested_related_memory_ids=("memory-1",), relation_hints=(hint,))
    assert parse_proposals(
        {"proposals": [proposal_to_wire(p)]}, snapshot(), role_policy().operational
    ) == (p,)
    for key, value in [
        ("related_memory_revision", 3),
        ("relation_kind", "unknown"),
        ("evidence_refs", ["outside"]),
        ("related_memory_revision", True),
    ]:
        wire: dict[str, Any] = proposal_to_wire(p)
        wire["relation_hints"][0][key] = value
        with pytest.raises(ReflectionLLMError):
            parse_proposals({"proposals": [wire]}, snapshot(), role_policy().operational)


@pytest.mark.parametrize(
    "relation", ["supported", "partially_supported", "unsupported", "ambiguous", "contradicted"]
)
def test_support_closed_relations(relation: str) -> None:
    wire = support_wire()
    wire["support_relation"] = relation
    if relation == "contradicted":
        wire["contradiction_refs"] = ["s"]
    assert (
        parse_support(
            wire, snapshot(), candidate(), role_policy().operational
        ).support_relation.value
        == relation
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("proposal_id", "wrong"),
        ("support_relation", "unknown"),
        ("evidence_refs", ["outside"]),
        ("evidence_refs", []),
        ("unsupported_content_refs", ["s"]),
        ("contradiction_refs", ["s"]),
        ("assertion_semantics", None),
        ("confidence", False),
    ],
)
def test_support_invalid(key: str, value: object) -> None:
    wire = support_wire()
    wire[key] = value
    with pytest.raises(ReflectionLLMError):
        parse_support(wire, snapshot(), candidate(), role_policy().operational)


@pytest.mark.parametrize("field", list(support_wire()))
def test_support_missing(field: str) -> None:
    wire = support_wire()
    del wire[field]
    with pytest.raises(ReflectionLLMError):
        parse_support(wire, snapshot(), candidate(), role_policy().operational)


def test_bounds_and_deterministic_boundary() -> None:
    c, p = snapshot(), candidate()
    policy = role_policy()
    two = {"proposals": [proposal_to_wire(p), proposal_to_wire(replace(p, proposal_id="p2"))]}
    assert len(parse_proposals(two, c, policy.operational)) == 2
    for op in [
        replace(policy.operational, max_proposals_per_reflection=1),
        replace(policy.operational, max_context_estimated_tokens=1),
        replace(policy.operational, policy_revision=99),
    ]:
        with pytest.raises(ReflectionLLMError):
            parse_proposals(two, c, op)
    with pytest.raises(ReflectionLLMError):
        parse_proposals({"proposals": [proposal_to_wire(p)] * 2}, c, policy.operational)
    with pytest.raises(ValueError):
        proposal_to_wire(replace(p, deterministic_capture=True))
    for when in (NOW.replace(tzinfo=None), NOW - timedelta(seconds=1)):
        with pytest.raises(ValueError):
            build_proposal_request(c, created_at=when, policy=policy)


@pytest.mark.asyncio
async def test_ports_use_injected_clock_and_zero_candidates() -> None:
    port = RolePort({"proposals": []})
    result = await LLMReflectionProposalPort(port, role_policy(), now=lambda: NOW).propose(
        snapshot()
    )
    assert result == () and port.requests[0].created_at == NOW
    port = RolePort()
    p = (await LLMReflectionProposalPort(port, role_policy(), now=lambda: NOW).propose(snapshot()))[
        0
    ]
    result2 = await LLMReflectionSupportPort(port, role_policy(), now=lambda: NOW).observe(
        snapshot(), p
    )
    assert result2.proposal_id == p.proposal_id
    assert port.requests[1].input.value == freeze_json(
        {"context": snapshot().to_dict(), "proposal": proposal_to_wire_v2(p)}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "wrong"},
        {"role_id": "wrong"},
        {"trace_id": "wrong"},
        {"output": StructuredPayload("wrong.schema", freeze_json({"proposals": []}))},
        {"completed_at": NOW - timedelta(seconds=1), "started_at": NOW - timedelta(seconds=1)},
    ],
)
async def test_exchange_mismatch_is_not_a_candidate(change: dict[str, Any]) -> None:
    port = RolePort()
    port.change = change
    with pytest.raises(ReflectionLLMError):
        await LLMReflectionProposalPort(port, role_policy(), now=lambda: NOW).propose(snapshot())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [
        (LLMRoleStatus.STALE, LLMFailureCode.STALE),
        (LLMRoleStatus.CANCELLED, LLMFailureCode.CANCELLED),
        (LLMRoleStatus.FAILED, LLMFailureCode.PROVIDER_UNAVAILABLE),
        (LLMRoleStatus.REJECTED, LLMFailureCode.REJECTED),
    ],
)
async def test_failure_codes_preserved(status: LLMRoleStatus, code: LLMFailureCode) -> None:
    port = RolePort()
    port.change = {
        "status": status,
        "output": None,
        "failure": LLMRoleFailure(code, "試験による失敗"),
    }
    with pytest.raises(ReflectionLLMError) as e:
        await LLMReflectionProposalPort(port, role_policy(), now=lambda: NOW).propose(snapshot())
    assert e.value.code is code


@pytest.mark.asyncio
async def test_external_cancellation_propagates() -> None:
    class Waiting:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await LLMReflectionProposalPort(Waiting(), role_policy(), now=lambda: NOW).propose(
            snapshot()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,predicate,accepted",
    [
        (ReflectionSourceKind.INPUT_MEANING, "actual_speech", False),
        (ReflectionSourceKind.PRESENTATION_FACT, "actual_speech", True),
        (ReflectionSourceKind.ACTIVITY_RESULT, "executed_activity", False),
        (ReflectionSourceKind.EXECUTION_FACT, "executed_activity", True),
    ],
)
async def test_existing_actual_fact_guards(
    kind: ReflectionSourceKind, predicate: str, accepted: bool
) -> None:
    c = context(source("s", kind))
    p = replace(candidate(), content=replace(candidate().content, predicate=predicate))
    proposal_port = RolePort({"proposals": [proposal_to_wire_v2(p)]})
    owner = ReflectionCoordinator(
        LLMReflectionProposalPort(proposal_port, role_policy(), now=lambda: NOW),
        LLMReflectionSupportPort(RolePort(), role_policy(), now=lambda: NOW),
        authority(),
        operational_policy=role_policy().operational,
        max_pending_tasks=2,
    )
    try:
        result = await owner.submit(c)
        assert (result.results[0].candidate is not None) is accepted
        if not accepted:
            assert result.results[0].status is ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    finally:
        await owner.shutdown()

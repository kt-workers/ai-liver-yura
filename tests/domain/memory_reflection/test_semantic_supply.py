"""#667のV1凍結、V2意味搬送、supportとconfidenceの責務境界。"""

from dataclasses import replace
from itertools import product
from typing import cast

import pytest

from app.domain.contracts.common import freeze_json
from app.domain.memory.contracts import (
    MemoryAssertionCertainty,
    MemoryAssertionPolarity,
    MemoryAssertionSemantics,
    MemoryAssertionTemporalMeaning,
)
from app.domain.memory_reflection import (
    ReflectionCandidateStatus,
    ReflectionCoordinator,
    context_to_wire_v2,
)
from app.domain.memory_reflection.llm_roles import (
    PROPOSAL_OUTPUT_SCHEMA,
    PROPOSAL_OUTPUT_SCHEMA_V1,
    PROPOSAL_OUTPUT_SCHEMA_V2,
    SUPPORT_INPUT_SCHEMA,
    SUPPORT_INPUT_SCHEMA_V1,
    SUPPORT_INPUT_SCHEMA_V2,
    SUPPORT_OUTPUT_SCHEMA,
    LLMReflectionProposalPort,
    LLMReflectionSupportPort,
    ReflectionLLMError,
    build_support_request_v2,
    parse_proposals_v1,
    parse_proposals_v2,
    proposal_to_wire_v1,
    proposal_to_wire_v2,
    proposal_to_wire_v3,
)
from app.domain.memory_reflection.schemas import (
    proposal_output_schema_v1,
    proposal_output_schema_v2,
)
from tests.domain.memory_reflection.test_llm_roles import (
    RolePort,
    candidate,
    role_policy,
    snapshot,
    support_wire,
)
from tests.domain.memory_reflection.test_memory_reflection import NOW, authority

SEMANTICS = MemoryAssertionSemantics(
    MemoryAssertionPolarity.AFFIRM,
    MemoryAssertionCertainty.CERTAIN,
    MemoryAssertionTemporalMeaning.HISTORICAL,
)


@pytest.mark.parametrize(
    "semantics",
    [None]
    + [
        MemoryAssertionSemantics(*x)
        for x in product(
            MemoryAssertionPolarity,
            MemoryAssertionCertainty,
            MemoryAssertionTemporalMeaning,
        )
    ],
)
def test_v2_all_facets_round_trip(semantics: MemoryAssertionSemantics | None) -> None:
    p = replace(candidate(), assertion_semantics=semantics)
    wire = proposal_to_wire_v2(p)
    parsed = parse_proposals_v2({"proposals": [wire]}, snapshot(), role_policy().operational)
    assert parsed == (p,)
    assert proposal_to_wire_v2(parsed[0]) == wire
    request = build_support_request_v2(snapshot(), parsed[0], created_at=NOW, policy=role_policy())
    assert request.input.schema_id == "memory.reflection.support.v2"
    assert request.input.value == freeze_json({"context": snapshot().to_dict(), "proposal": wire})


def test_v1_is_frozen_and_generations_are_distinct() -> None:
    assert PROPOSAL_OUTPUT_SCHEMA_V1 == "memory.reflection.candidates.v1"
    assert PROPOSAL_OUTPUT_SCHEMA_V2 == "memory.reflection.candidates.v2"
    assert PROPOSAL_OUTPUT_SCHEMA == "memory.reflection.candidates.v3"
    assert SUPPORT_INPUT_SCHEMA_V1 == "memory.reflection.support.v1"
    assert SUPPORT_INPUT_SCHEMA_V2 == "memory.reflection.support.v2"
    assert SUPPORT_INPUT_SCHEMA == "memory.reflection.support.v3"
    assert SUPPORT_OUTPUT_SCHEMA == "memory.reflection.support.observation.v1"
    wire = proposal_to_wire_v1(candidate())
    assert "assertion_semantics" not in wire
    assert parse_proposals_v1({"proposals": [wire]}, snapshot(), role_policy().operational) == (
        candidate(),
    )
    assert proposal_output_schema_v1() != proposal_output_schema_v2()
    wire["assertion_semantics"] = None
    with pytest.raises(ReflectionLLMError):
        parse_proposals_v1({"proposals": [wire]}, snapshot(), role_policy().operational)
    with pytest.raises(ValueError):
        proposal_to_wire_v1(replace(candidate(), assertion_semantics=SEMANTICS))


@pytest.mark.parametrize(
    "value",
    [
        False,
        "affirm",
        {},
        {"polarity": "affirm"},
        {**SEMANTICS.to_dict(), "polarity": "unknown"},
        {**SEMANTICS.to_dict(), "certainty": "unknown"},
        {**SEMANTICS.to_dict(), "temporal_meaning": "unknown"},
        {**SEMANTICS.to_dict(), "extra": True},
    ],
)
def test_invalid_semantic_wire_rejected(value: object) -> None:
    wire = proposal_to_wire_v2(candidate())
    wire["assertion_semantics"] = value
    with pytest.raises(ReflectionLLMError):
        parse_proposals_v2({"proposals": [wire]}, snapshot(), role_policy().operational)


def test_missing_semantics_and_invalid_domain_type_rejected() -> None:
    with pytest.raises(ReflectionLLMError):
        parse_proposals_v2(
            {"proposals": [proposal_to_wire_v1(candidate())]}, snapshot(), role_policy().operational
        )
    with pytest.raises(ValueError):
        replace(
            candidate(), assertion_semantics=cast(MemoryAssertionSemantics, SEMANTICS.to_dict())
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("proposal_confidence", [0.1, 0.5, 1.0])
@pytest.mark.parametrize("support_confidence", [0.1, 0.5, 1.0])
async def test_confidence_never_changes_assertion_certainty(
    proposal_confidence: float, support_confidence: float
) -> None:
    p = replace(candidate(), assertion_semantics=SEMANTICS, confidence_hint=proposal_confidence)
    support = support_wire()
    support["confidence"] = support_confidence
    policy = role_policy()
    owner = ReflectionCoordinator(
        LLMReflectionProposalPort(
            RolePort({"proposals": [proposal_to_wire_v3(p)]}), policy, now=lambda: NOW
        ),
        LLMReflectionSupportPort(RolePort(support), policy, now=lambda: NOW),
        authority(),
        operational_policy=policy.operational,
        max_pending_tasks=2,
    )
    try:
        result = (await owner.submit(snapshot())).results[0]
        assert result.candidate is not None
        assert result.candidate.assertion_semantics == SEMANTICS
        assert result.candidate.confidence.value == min(proposal_confidence, support_confidence)
    finally:
        await owner.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "relation", ["partially_supported", "unsupported", "ambiguous", "contradicted"]
)
async def test_unsupported_facets_are_not_downgraded_and_accepted(relation: str) -> None:
    p = replace(candidate(), assertion_semantics=SEMANTICS)
    wire = support_wire()
    wire["support_relation"] = relation
    if relation == "contradicted":
        wire["contradiction_refs"] = ["s"]
    support_role = RolePort(wire)
    policy = role_policy()
    owner = ReflectionCoordinator(
        LLMReflectionProposalPort(
            RolePort({"proposals": [proposal_to_wire_v3(p)]}), policy, now=lambda: NOW
        ),
        LLMReflectionSupportPort(support_role, policy, now=lambda: NOW),
        authority(),
        operational_policy=policy.operational,
        max_pending_tasks=2,
    )
    try:
        result = (await owner.submit(snapshot())).results[0]
        assert result.candidate is None
        assert p.assertion_semantics is SEMANTICS
        assert support_role.requests[0].input.value == freeze_json(
            {
                "context": context_to_wire_v2(snapshot()),
                "proposal": proposal_to_wire_v3(p),
            }
        )
    finally:
        await owner.shutdown()


def test_deterministic_without_upstream_mapping_keeps_none() -> None:
    p = replace(candidate(), deterministic_capture=True)
    accepted = authority().accept_trusted_deterministic_capture(snapshot(), p)
    assert accepted.candidate is not None and accepted.candidate.assertion_semantics is None
    rejected = authority().accept_trusted_deterministic_capture(
        snapshot(), replace(p, assertion_semantics=SEMANTICS)
    )
    assert rejected.status is ReflectionCandidateStatus.REJECTED_POLICY
    assert rejected.candidate is None


@pytest.mark.parametrize(
    "source_kind,predicate,accepted",
    [
        ("input_meaning", "actual_speech", False),
        ("presentation_fact", "actual_speech", True),
        ("activity_result", "executed_activity", False),
        ("execution_fact", "executed_activity", True),
    ],
)
def test_explicit_facets_cannot_bypass_actual_fact_guard(
    source_kind: str, predicate: str, accepted: bool
) -> None:
    from app.domain.memory_reflection import ReflectionSourceKind
    from app.domain.memory_reflection.llm_roles import parse_support
    from tests.domain.memory_reflection.test_memory_reflection import context, source

    c = context(source("s", ReflectionSourceKind(source_kind)))
    p = replace(
        candidate(),
        content=replace(candidate().content, predicate=predicate),
        assertion_semantics=SEMANTICS,
    )
    support = parse_support(support_wire(), c, p, role_policy().operational)
    result = authority().accept(c, p, support)
    assert (result.candidate is not None) is accepted
    if not accepted:
        assert result.status is ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE

"""#673の世代固定、型付き主体の根拠、容量、採用へのexact搬送を検証する。"""

from dataclasses import replace
from typing import Any

import pytest

from app.domain.contracts.common import freeze_json
from app.domain.contracts.semantic_subject import SemanticSubjectIdentity, SemanticSubjectKind
from app.domain.llm import LLMFailureCode
from app.domain.memory import MemoryKind
from app.domain.memory.ranking import estimate_memory_token_units
from app.domain.memory_reflection import (
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionSourceKind,
    context_to_wire_v2,
    estimate_reflection_context_tokens_v1,
    estimate_reflection_context_tokens_v2,
    source_to_wire_v2,
)
from app.domain.memory_reflection.contracts import MemoryCandidateProposal
from app.domain.memory_reflection.llm_roles import (
    LLMReflectionProposalPort,
    LLMReflectionSupportPort,
    ReflectionLLMError,
    build_proposal_request,
    build_proposal_request_v1,
    build_support_request,
    build_support_request_v1,
    build_support_request_v2,
    parse_proposals_v1,
    parse_proposals_v2,
    parse_proposals_v3,
    parse_support,
    proposal_to_wire_v1,
    proposal_to_wire_v2,
    proposal_to_wire_v3,
)
from app.domain.memory_reflection.operational import (
    ReflectionOperationalError,
    ReflectionOperationalFailureCode,
)
from tests.domain.memory_reflection.test_llm_roles import (
    RolePort,
    candidate,
    role_policy,
    snapshot,
    support_wire,
)
from tests.domain.memory_reflection.test_memory_reflection import NOW, authority, context, source
from tests.domain.memory_reflection.test_semantic_supply import SEMANTICS


def typed_pair(
    kind: SemanticSubjectKind,
) -> tuple[ReflectionContextSnapshot, MemoryCandidateProposal]:
    identity = SemanticSubjectIdentity(
        kind, "user:1" if kind is SemanticSubjectKind.REFERENCE else "yura"
    )
    c = context(
        replace(source("s", ReflectionSourceKind.PRESENTATION_FACT), subject_identity=identity)
    )
    p = replace(
        candidate(),
        content=replace(candidate().content, subject_ref=identity.subject_ref),
        subject_identity=identity,
        assertion_semantics=SEMANTICS,
    )
    return c, p


@pytest.mark.parametrize("kind", list(SemanticSubjectKind))
def test_context_generations_and_legacy_requests_are_frozen(kind: SemanticSubjectKind) -> None:
    c, p = typed_pair(kind)
    old = snapshot()
    assert c.to_dict() == old.to_dict()
    assert c.primary_sources[0].to_dict() == old.primary_sources[0].to_dict()
    assert "subject_identity" not in c.primary_sources[0].to_dict()
    wire: Any = context_to_wire_v2(c)
    assert wire["primary_sources"][0]["subject_identity"] == {
        "kind": kind.value,
        "subject_ref": p.content.subject_ref,
    }
    assert source_to_wire_v2(old.primary_sources[0])["subject_identity"] is None
    request = build_proposal_request(c, created_at=NOW, policy=role_policy())
    assert request.input.schema_id == "memory.reflection.context.v2"
    assert request.input.value == freeze_json(wire)
    legacy = build_proposal_request_v1(c, created_at=NOW, policy=role_policy())
    assert legacy.input.schema_id == "memory.reflection.context.v1"
    assert legacy.input.value == freeze_json(old.to_dict())
    for version, builder, serializer in (
        (1, build_support_request_v1, proposal_to_wire_v1),
        (2, build_support_request_v2, proposal_to_wire_v2),
    ):
        result = builder(c, candidate(), created_at=NOW, policy=role_policy())
        assert result.input.schema_id == f"memory.reflection.support.v{version}"
        assert result.input.value == freeze_json(
            {"context": old.to_dict(), "proposal": serializer(candidate())}
        )
        with pytest.raises(ValueError):
            serializer(p)


@pytest.mark.parametrize("bad", [{"kind": "SELF", "subject_ref": "yura"}, "yura", False])
def test_dto_rejects_untyped_identity(bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(snapshot().primary_sources[0], subject_identity=bad)
    with pytest.raises(ValueError):
        replace(candidate(), subject_identity=bad)


@pytest.mark.parametrize("ref", [None, "different"])
def test_proposal_identity_requires_exact_content_ref(ref: str | None) -> None:
    _, p = typed_pair(SemanticSubjectKind.SELF)
    with pytest.raises(ValueError):
        replace(p, content=replace(p.content, subject_ref=ref))


@pytest.mark.asyncio
@pytest.mark.parametrize("support", [False, True])
async def test_actual_v2_tokens_reject_before_role_request(support: bool) -> None:
    c, p = typed_pair(SemanticSubjectKind.SELF)
    original = c.to_dict()
    v1 = estimate_reflection_context_tokens_v1(c)
    v2 = estimate_reflection_context_tokens_v2(c)
    assert v2 == estimate_memory_token_units(context_to_wire_v2(c)) > v1
    assert v2 - 1 >= estimate_reflection_context_tokens_v2(snapshot())
    policy = replace(
        role_policy(),
        operational=replace(role_policy().operational, max_context_estimated_tokens=v2 - 1),
    )
    assert build_proposal_request_v1(c, created_at=NOW, policy=policy)
    with pytest.raises(ReflectionOperationalError) as error:
        if support:
            build_support_request(c, p, created_at=NOW, policy=policy)
        else:
            build_proposal_request(c, created_at=NOW, policy=policy)
    assert error.value.code is ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE
    port = RolePort()
    with pytest.raises(ReflectionLLMError) as failure:
        if support:
            await LLMReflectionSupportPort(port, policy, now=lambda: NOW).observe(c, p)
        else:
            await LLMReflectionProposalPort(port, policy, now=lambda: NOW).propose(c)
    assert failure.value.code is LLMFailureCode.POLICY_VIOLATION
    assert port.requests == [] and c.to_dict() == original
    exact = replace(
        policy, operational=replace(policy.operational, max_context_estimated_tokens=v2)
    )
    assert build_proposal_request(c, created_at=NOW, policy=exact).input.value == freeze_json(
        context_to_wire_v2(c)
    )


@pytest.mark.parametrize(
    "serializer,parser",
    [(proposal_to_wire_v1, parse_proposals_v1), (proposal_to_wire_v2, parse_proposals_v2)],
)
def test_old_proposal_generations_reject_identity(serializer: Any, parser: Any) -> None:
    wire = serializer(candidate())
    assert "subject_identity" not in wire
    assert parser({"proposals": [wire]}, snapshot(), role_policy().operational) == (candidate(),)
    wire["subject_identity"] = None
    with pytest.raises(ReflectionLLMError) as error:
        parser({"proposals": [wire]}, snapshot(), role_policy().operational)
    assert error.value.code is LLMFailureCode.SCHEMA_INVALID


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"kind": "unknown", "subject_ref": "yura"},
        {"kind": "SELF", "subject_ref": "yura", "extra": 1},
        {"kind": "SELF", "subject_ref": "other"},
        {"kind": "SELF", "subject_ref": ""},
        {"kind": "SELF", "subject_ref": "  "},
        {"kind": "SELF"},
        False,
    ],
)
def test_v3_invalid_identity_is_schema_failure(value: object) -> None:
    c, p = typed_pair(SemanticSubjectKind.SELF)
    wire = proposal_to_wire_v3(p)
    wire["subject_identity"] = value
    with pytest.raises(ReflectionLLMError) as error:
        parse_proposals_v3({"proposals": [wire]}, c, role_policy().operational)
    assert error.value.code is LLMFailureCode.SCHEMA_INVALID


def test_v3_identity_required_but_null_is_valid() -> None:
    wire = proposal_to_wire_v3(candidate())
    assert wire["subject_identity"] is None
    assert parse_proposals_v3({"proposals": [wire]}, snapshot(), role_policy().operational) == (
        candidate(),
    )
    del wire["subject_identity"]
    with pytest.raises(ReflectionLLMError):
        parse_proposals_v3({"proposals": [wire]}, snapshot(), role_policy().operational)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(SemanticSubjectKind))
async def test_typed_source_reaches_accepted_candidate_exactly(kind: SemanticSubjectKind) -> None:
    c, p = typed_pair(kind)
    proposals = RolePort({"proposals": [proposal_to_wire_v3(p)]})
    parsed = (
        await LLMReflectionProposalPort(proposals, role_policy(), now=lambda: NOW).propose(c)
    )[0]
    assert parsed == p
    supports = RolePort()
    support = await LLMReflectionSupportPort(supports, role_policy(), now=lambda: NOW).observe(
        c, parsed
    )
    assert supports.requests[0].input.schema_id == "memory.reflection.support.v3"
    assert supports.requests[0].input.value == freeze_json(
        {"context": context_to_wire_v2(c), "proposal": proposal_to_wire_v3(p)}
    )
    accepted = authority().accept(c, parsed, support)
    assert accepted.candidate is not None
    assert accepted.candidate.subject_identity == p.subject_identity
    assert accepted.candidate.assertion_semantics == SEMANTICS


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("kind", list(MemoryKind))
@pytest.mark.parametrize("text", ["私", "自分", "ゆら", "display_name: yura"])
def test_raw_content_never_supplies_identity(
    confidence: float, kind: MemoryKind, text: str
) -> None:
    c, p = typed_pair(SemanticSubjectKind.SELF)
    c = replace(
        c,
        primary_sources=(
            replace(
                c.primary_sources[0],
                subject_identity=None,
                source_excerpt=text,
                semantic_payload={"kind": "SELF", "subject_ref": "yura", "text": text},
            ),
        ),
    )
    p = replace(
        p,
        proposed_kind=kind,
        confidence_hint=confidence,
        content=replace(p.content, predicate=text, value={"kind": "SELF", "text": text}),
    )
    with pytest.raises(ReflectionLLMError) as error:
        parse_proposals_v3({"proposals": [proposal_to_wire_v3(p)]}, c, role_policy().operational)
    assert error.value.code is LLMFailureCode.POLICY_VIOLATION
    support = parse_support(support_wire(), snapshot(), candidate(), role_policy().operational)
    rejected = authority().accept(c, p, support)
    assert rejected.status is ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    unresolved = replace(p, subject_identity=None)
    assert parse_proposals_v3(
        {"proposals": [proposal_to_wire_v3(unresolved)]}, c, role_policy().operational
    ) == (unresolved,)
    accepted = authority().accept(c, unresolved, support)
    assert accepted.candidate is not None and accepted.candidate.subject_identity is None


@pytest.mark.parametrize("other_kind", [None, SemanticSubjectKind.REFERENCE])
def test_matching_source_must_be_selected_by_proposal_and_support(
    other_kind: SemanticSubjectKind | None,
) -> None:
    c, p = typed_pair(SemanticSubjectKind.SELF)
    other = None if other_kind is None else SemanticSubjectIdentity(other_kind, "yura")
    c = context(
        c.primary_sources[0],
        replace(source("z", ReflectionSourceKind.PRESENTATION_FACT), subject_identity=other),
    )
    ungrounded = replace(p, source_refs=("z",), rationale_evidence_refs=("z",))
    with pytest.raises(ReflectionLLMError):
        parse_proposals_v3(
            {"proposals": [proposal_to_wire_v3(ungrounded)]}, c, role_policy().operational
        )
    support = parse_support(support_wire(), c, p, role_policy().operational)
    assert (
        authority().accept(c, ungrounded, replace(support, evidence_refs=("z",))).status
        is ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    )
    both = replace(p, source_refs=("s", "z"))
    wire = {**support_wire(), "evidence_refs": ["z"]}
    with pytest.raises(ReflectionLLMError) as error:
        parse_support(wire, c, both, role_policy().operational, context_v2=True)
    assert error.value.code is LLMFailureCode.POLICY_VIOLATION
    rejected = authority().accept(c, both, replace(support, evidence_refs=("z",)))
    assert rejected.status is ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    assert both.subject_identity == p.subject_identity


@pytest.mark.parametrize("kind", list(SemanticSubjectKind))
def test_deterministic_capture_requires_typed_evidence_and_preserves_semantics_boundary(
    kind: SemanticSubjectKind,
) -> None:
    c, p = typed_pair(kind)
    p = replace(p, deterministic_capture=True, assertion_semantics=None)
    accepted = authority().accept_trusted_deterministic_capture(c, p)
    assert (
        accepted.candidate is not None and accepted.candidate.subject_identity == p.subject_identity
    )
    assert (
        authority().accept_trusted_deterministic_capture(snapshot(), p).status
        is ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    )
    assert (
        authority()
        .accept_trusted_deterministic_capture(c, replace(p, assertion_semantics=SEMANTICS))
        .status
        is ReflectionCandidateStatus.REJECTED_POLICY
    )
    unresolved = authority().accept_trusted_deterministic_capture(
        snapshot(), replace(p, subject_identity=None)
    )
    assert unresolved.candidate is not None and unresolved.candidate.subject_identity is None


@pytest.mark.parametrize(
    "relation,status",
    [
        ("partially_supported", ReflectionCandidateStatus.REJECTED_POLICY),
        ("unsupported", ReflectionCandidateStatus.REJECTED_UNSUPPORTED),
        ("ambiguous", ReflectionCandidateStatus.REJECTED_AMBIGUOUS),
        ("contradicted", ReflectionCandidateStatus.REJECTED_CONTRADICTED),
    ],
)
def test_other_support_relations_preserve_typed_proposal(
    relation: str, status: ReflectionCandidateStatus
) -> None:
    c, p = typed_pair(SemanticSubjectKind.SELF)
    wire = {**support_wire(), "support_relation": relation}
    if relation == "contradicted":
        wire["contradiction_refs"] = ["s"]
    observed = parse_support(wire, c, p, role_policy().operational, context_v2=True)
    result = authority().accept(c, p, observed)
    assert result.status is status and result.candidate is None
    assert p.subject_identity == c.primary_sources[0].subject_identity
    assert p.assertion_semantics == SEMANTICS


@pytest.mark.asyncio
@pytest.mark.parametrize("same", [True, False])
@pytest.mark.parametrize("first_kind", [None, SemanticSubjectKind.REFERENCE])
async def test_v2_identity_generation_coalescing(
    same: bool,
    first_kind: SemanticSubjectKind | None,
) -> None:
    import asyncio

    from tests.domain.memory_reflection.test_memory_reflection import (
        FakeProposalPort,
        FakeSupportPort,
        coordinator,
    )

    second_context, _ = typed_pair(SemanticSubjectKind.SELF)
    identity = None if first_kind is None else SemanticSubjectIdentity(first_kind, "yura")
    first_context = (
        second_context
        if same
        else replace(
            second_context,
            primary_sources=(
                replace(second_context.primary_sources[0], subject_identity=identity),
            ),
        )
    )
    assert first_context.to_dict() == second_context.to_dict()
    assert (context_to_wire_v2(first_context) == context_to_wire_v2(second_context)) is same
    gate = asyncio.Event()
    provider = FakeProposalPort((), gate)
    runtime = coordinator(provider, FakeSupportPort())
    try:
        first = runtime.submit(first_context)
        second = runtime.submit(replace(second_context))
        await asyncio.sleep(0)
        assert (first is second) is same
        assert provider.calls == (1 if same else 2)
        gate.set()
        await asyncio.gather(first, second)
        assert runtime.pending_task_count == 0
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_kind", [None, SemanticSubjectKind.REFERENCE])
async def test_cross_identity_cancel_isolation(first_kind: SemanticSubjectKind | None) -> None:
    import asyncio

    from tests.domain.memory_reflection.test_memory_reflection import (
        FakeProposalPort,
        FakeSupportPort,
        coordinator,
    )

    second_context, _ = typed_pair(SemanticSubjectKind.SELF)
    identity = None if first_kind is None else SemanticSubjectIdentity(first_kind, "yura")
    first_context = replace(
        second_context,
        primary_sources=(replace(second_context.primary_sources[0], subject_identity=identity),),
    )
    assert first_context.to_dict() == second_context.to_dict()
    gate = asyncio.Event()
    provider = FakeProposalPort((), gate)
    runtime = coordinator(provider, FakeSupportPort())
    try:
        second = runtime.submit(second_context)
        await asyncio.sleep(0)
        await runtime.cancel(first_context)
        assert not second.done()
        first = runtime.submit(first_context)
        await asyncio.sleep(0)
        assert provider.calls == 2
        await runtime.cancel(first_context)
        assert first.cancelled()
        assert not second.done()
        gate.set()
        await second
        assert runtime.pending_task_count == 0
    finally:
        await runtime.shutdown()

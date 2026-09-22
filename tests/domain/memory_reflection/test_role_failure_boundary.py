"""production RoleからCoordinator公開resultまでのtyped failure保持。"""

from dataclasses import replace

import pytest

from app.domain.llm import LLMFailureCode, LLMRoleFailure, LLMRoleStatus
from app.domain.memory.contracts import MemoryRelationKind
from app.domain.memory_reflection import (
    ReflectionCandidateResult,
    ReflectionCandidateStatus,
    ReflectionRelationHint,
    ReflectionRoleFailureInfo,
    ReflectionRoleStage,
)
from app.domain.memory_reflection.contracts import (
    MemoryCandidateProposal,
    ReflectionContextSnapshot,
    ReflectionSupportObservation,
)
from app.domain.memory_reflection.llm_roles import (
    LLMReflectionProposalPort,
    LLMReflectionSupportPort,
    ReflectionLLMError,
    parse_proposals,
    parse_support,
    proposal_to_wire,
    proposal_to_wire_v3,
)
from app.domain.memory_reflection.runtime import ReflectionCoordinator
from tests.domain.memory_reflection.test_llm_roles import (
    RolePort,
    candidate,
    role_policy,
    snapshot,
    support_wire,
)
from tests.domain.memory_reflection.test_memory_reflection import NOW, authority

CODES = [
    LLMFailureCode.SCHEMA_INVALID,
    LLMFailureCode.PROVIDER_UNAVAILABLE,
    LLMFailureCode.PROVIDER_ERROR,
    LLMFailureCode.TIMEOUT,
    LLMFailureCode.CANCELLED,
    LLMFailureCode.STALE,
    LLMFailureCode.SUPERSEDED,
    LLMFailureCode.REJECTED,
    LLMFailureCode.POLICY_VIOLATION,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["proposal", "support"])
@pytest.mark.parametrize("code", CODES)
async def test_production_failure_survives_coordinator(stage: str, code: LLMFailureCode) -> None:
    failed = RolePort()
    status = {
        LLMFailureCode.TIMEOUT: LLMRoleStatus.TIMED_OUT,
        LLMFailureCode.CANCELLED: LLMRoleStatus.CANCELLED,
        LLMFailureCode.STALE: LLMRoleStatus.STALE,
        LLMFailureCode.SUPERSEDED: LLMRoleStatus.SUPERSEDED,
        LLMFailureCode.REJECTED: LLMRoleStatus.REJECTED,
    }.get(code, LLMRoleStatus.FAILED)
    failed.change = {"status": status, "output": None, "failure": LLMRoleFailure(code, "故障注入")}
    policy = role_policy()
    owner = ReflectionCoordinator(
        LLMReflectionProposalPort(
            failed if stage == "proposal" else RolePort(), policy, now=lambda: NOW
        ),
        LLMReflectionSupportPort(
            failed if stage == "support" else RolePort(), policy, now=lambda: NOW
        ),
        authority(),
        operational_policy=policy.operational,
        max_pending_tasks=2,
    )
    try:
        result = (await owner.submit(snapshot())).results[0]
        assert result.candidate is None
        assert result.role_failure == ReflectionRoleFailureInfo(ReflectionRoleStage(stage), code)
        assert result.status is (
            ReflectionCandidateStatus.REFLECTION_ROLE_FAILED
            if stage == "proposal"
            else ReflectionCandidateStatus.SUPPORT_ROLE_FAILED
        )
    finally:
        await owner.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["proposal", "support"])
async def test_unknown_runtime_error_keeps_legacy_fallback(stage: str) -> None:
    class UnknownProposal(LLMReflectionProposalPort):
        async def propose(
            self, context: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            raise RuntimeError("未知の注入Port失敗")

    class UnknownSupport(LLMReflectionSupportPort):
        async def observe(
            self, context: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
        ) -> ReflectionSupportObservation:
            raise RuntimeError("未知の注入Port失敗")

    policy = role_policy()
    proposal_type = UnknownProposal if stage == "proposal" else LLMReflectionProposalPort
    support_type = UnknownSupport if stage == "support" else LLMReflectionSupportPort
    owner = ReflectionCoordinator(
        proposal_type(RolePort(), policy, now=lambda: NOW),
        support_type(RolePort(), policy, now=lambda: NOW),
        authority(),
        operational_policy=policy.operational,
        max_pending_tasks=2,
    )
    try:
        result = (await owner.submit(snapshot())).results[0]
        assert result.candidate is None and result.role_failure is None
        assert result.status is (
            ReflectionCandidateStatus.REFLECTION_PROVIDER_UNAVAILABLE
            if stage == "proposal"
            else ReflectionCandidateStatus.SUPPORT_PROVIDER_UNAVAILABLE
        )
    finally:
        await owner.shutdown()


@pytest.mark.parametrize("kind", ["count", "relation", "evidence", "support", "generation"])
def test_d10_failure_is_policy_or_stale(kind: str) -> None:
    p, c, op = candidate(), snapshot(), role_policy().operational
    wire = proposal_to_wire(p)
    if kind == "count":
        op = replace(op, max_proposals_per_reflection=1)
        value = {"proposals": [wire, proposal_to_wire(replace(p, proposal_id="p2"))]}
    elif kind == "generation":
        op = replace(op, policy_revision=op.policy_revision + 1)
        value = {"proposals": [wire]}
    else:
        op = replace(op, max_evidence_refs_per_proposal=1, max_relation_hints_per_proposal=1)
        if kind == "relation":
            wire["relation_hints"] = [
                {
                    "related_memory_id": f"m{i}",
                    "related_memory_revision": 1,
                    "relation_kind": "supports",
                    "evidence_refs": ["s"],
                    "confidence": 0.8,
                }
                for i in range(2)
            ]
        else:
            wire["rationale_evidence_refs"] = ["s", "s2"]
        value = {"proposals": [wire]}
    with pytest.raises(ReflectionLLMError) as error:
        if kind == "support":
            support = support_wire()
            support["evidence_refs"] = ["s", "s2"]
            parse_support(support, c, p, op)
        else:
            parse_proposals(value, c, op)
    assert error.value.code is (
        LLMFailureCode.STALE if kind == "generation" else LLMFailureCode.POLICY_VIOLATION
    )


def test_public_result_requires_code_only_for_role_failure() -> None:
    with pytest.raises(ValueError):
        ReflectionCandidateResult("p", ReflectionCandidateStatus.REFLECTION_ROLE_FAILED, None, ())
    with pytest.raises(ValueError):
        ReflectionCandidateResult(
            "p",
            ReflectionCandidateStatus.SUPPORT_ROLE_FAILED,
            None,
            (),
            role_failure=ReflectionRoleFailureInfo(
                ReflectionRoleStage.PROPOSAL, LLMFailureCode.STALE
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["proposal", "support"])
async def test_parser_failure_is_public_schema_invalid(stage: str) -> None:
    policy = role_policy()
    owner = ReflectionCoordinator(
        LLMReflectionProposalPort(
            RolePort({"unknown": True}) if stage == "proposal" else RolePort(),
            policy,
            now=lambda: NOW,
        ),
        LLMReflectionSupportPort(
            RolePort({"unknown": True}) if stage == "support" else RolePort(),
            policy,
            now=lambda: NOW,
        ),
        authority(),
        operational_policy=policy.operational,
        max_pending_tasks=2,
    )
    try:
        result = (await owner.submit(snapshot())).results[0]
        assert result.candidate is None
        assert result.role_failure == ReflectionRoleFailureInfo(
            ReflectionRoleStage(stage), LLMFailureCode.SCHEMA_INVALID
        )
    finally:
        await owner.shutdown()


@pytest.mark.asyncio
async def test_accepted_candidate_has_no_role_failure() -> None:
    policy = role_policy()
    owner = ReflectionCoordinator(
        LLMReflectionProposalPort(RolePort(), policy, now=lambda: NOW),
        LLMReflectionSupportPort(RolePort(), policy, now=lambda: NOW),
        authority(),
        operational_policy=policy.operational,
        max_pending_tasks=2,
    )
    try:
        result = (await owner.submit(snapshot())).results[0]
        assert result.candidate is not None
        assert result.role_failure is None
    finally:
        await owner.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage,change,generic",
    [
        ("proposal", "policy", False),
        ("proposal", "policy", True),
        ("support", "policy", False),
        ("support", "policy", True),
        ("support", "retracted", False),
        ("support", "missing", False),
        ("support", "relation", False),
        ("support", "bounds", False),
    ],
)
async def test_failure_await_revalidates_owner_disposition(
    stage: str, change: str, generic: bool
) -> None:
    import asyncio

    from app.domain.llm import LLMRoleRequest, LLMRoleResult

    entered, release = asyncio.Event(), asyncio.Event()
    code = (
        LLMFailureCode.SCHEMA_INVALID
        if stage == "support" and change == "policy"
        else LLMFailureCode.PROVIDER_UNAVAILABLE
    )

    class PausedRole(RolePort):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            entered.set()
            await release.wait()
            if generic:
                raise RuntimeError("未知のPort失敗")
            self.change = {
                "status": LLMRoleStatus.FAILED,
                "output": None,
                "failure": LLMRoleFailure(code, "故障注入"),
            }
            return await super().invoke(request)

    policy = role_policy()
    current: ReflectionContextSnapshot | None = snapshot()
    p = candidate()
    if change == "relation":
        p = replace(
            p,
            suggested_related_memory_ids=("memory-1",),
            relation_hints=(
                ReflectionRelationHint("memory-1", 2, MemoryRelationKind.CONTRADICTS, ("s",), 0.8),
            ),
        )
    normal_proposal = RolePort({"proposals": [proposal_to_wire_v3(p)]})
    owner = ReflectionCoordinator(
        LLMReflectionProposalPort(
            PausedRole() if stage == "proposal" else normal_proposal, policy, now=lambda: NOW
        ),
        LLMReflectionSupportPort(
            PausedRole() if stage == "support" else RolePort(), policy, now=lambda: NOW
        ),
        authority(),
        operational_policy=policy.operational,
        max_pending_tasks=2,
        live_context=lambda _: current,
    )
    try:
        task = owner.submit(snapshot())
        await asyncio.wait_for(entered.wait(), timeout=2)
        if change == "policy":
            await owner.update_operational_policy(replace(policy.operational, policy_revision=2))
        elif change == "retracted":
            current = replace(
                snapshot(),
                primary_sources=tuple(
                    replace(s, retracted=True) for s in snapshot().primary_sources
                ),
            )
        elif change == "missing":
            current = None
        elif change == "relation":
            current = replace(
                snapshot(),
                related_memory_view=tuple(
                    replace(m, revision=m.revision + 1) for m in snapshot().related_memory_view
                ),
            )
        else:
            current = replace(
                snapshot(),
                primary_sources=tuple(
                    replace(
                        s,
                        source_excerpt="x" * (policy.operational.max_source_excerpt_codepoints + 1),
                    )
                    for s in snapshot().primary_sources
                ),
            )
        release.set()
        result = (await task).results[0]
        assert result.status is (
            ReflectionCandidateStatus.REJECTED_POLICY
            if change == "bounds"
            else ReflectionCandidateStatus.REJECTED_STALE
        )
        assert result.candidate is None
        assert result.role_failure == (
            None if generic else ReflectionRoleFailureInfo(ReflectionRoleStage(stage), code)
        )
    finally:
        release.set()
        await owner.shutdown()

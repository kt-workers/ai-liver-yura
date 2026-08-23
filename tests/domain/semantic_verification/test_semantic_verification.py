from __future__ import annotations

import ast
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from app.domain.character.contracts import CharacterLanguageProfile
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageCommitState,
    CharacterLanguageContextSnapshot,
    CharacterUtterance,
    CharacterUtteranceCandidate,
    CharacterUtteranceSegment,
    LinguisticBoundary,
    LinguisticEmphasis,
    LinguisticHesitation,
)
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePriority,
    SpeechIntentPayload,
)
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from app.domain.semantic_verification import (
    BLIND_ROLE_ID,
    RELATION_ROLE_ID,
    BlindInteractionAct,
    BlindSemanticUnit,
    BlindSemanticUnitKind,
    BlindUnitAccounting,
    BlindUnitAccountingRelation,
    BlindUtteranceObservationCandidate,
    CertaintyRelation,
    DegreeRelation,
    ExecutionRelation,
    PlanRelationObservationCandidate,
    PolarityRelation,
    PropositionRelation,
    PropositionSemanticObservation,
    SelfDisclosureRelation,
    SemanticAcceptanceState,
    SemanticRejectionCategory,
    SemanticVerificationAuthority,
    SemanticVerificationContextSnapshot,
    SemanticVerificationEligibilityView,
    SemanticVerificationError,
    SemanticVerificationFailureCode,
    SemanticVerificationPolicy,
    SemanticVerifier,
    SpeechActBudgetObservation,
    UtteranceEvidenceRef,
    build_blind_request,
)
from app.domain.speech_semantics import (
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
    SpeechSemanticPlan,
)

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
REVISIONS = RevisionVector(10, 4, 2)
TEXT = "今はそこまで楽しいって感じじゃないかな。"


def execution_policy() -> LLMExecutionPolicy:
    return LLMExecutionPolicy(
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        20,
        1,
        1200,
    )


def verification_policy() -> SemanticVerificationPolicy:
    policy = execution_policy()
    return SemanticVerificationPolicy(policy, policy)


def _decision() -> CommittedExecutiveDecision:
    assert REVISIONS.goal_revision is not None
    assert REVISIONS.attention_revision is not None
    intent = ExecutiveIntent(
        "intent-speech",
        ExecutiveIntentKind.SPEECH,
        "現在のjoyについて答える",
        SpeechIntentPayload("fact-required"),
        (),
        (),
        (),
        (),
    )
    candidate = ExecutiveDecisionCandidate(
        "decision-candidate",
        "trigger-1",
        ("event-1",),
        REVISIONS.source_context_revision,
        REVISIONS.goal_revision,
        REVISIONS.attention_revision,
        ExecutiveOutcome.RESPOND,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (intent,),
        (),
        (),
        ("fact-required",),
        NOW,
    )
    return CommittedExecutiveDecision("decision-1", candidate, (), NOW)


def _semantic_plan() -> SpeechSemanticPlan:
    required_fact = SpeechSemanticFact(
        "fact-required",
        SpeechSemanticFactKind.SELF,
        "yura",
        "current_joy",
        {"state": "not_positive"},
        polarity=SemanticPolarity.NEGATE,
        certainty=SemanticCertainty.CERTAIN,
        degree=0.2,
    )
    forbidden_fact = SpeechSemanticFact(
        "fact-forbidden",
        SpeechSemanticFactKind.GENERAL,
        "yura",
        "unsupported_experience",
        {"value": True},
    )
    context = SpeechSemanticContextSnapshot(
        _decision(),
        "intent-speech",
        (required_fact, forbidden_fact),
        (),
        (),
        SelfDisclosurePolicy.FACT_GROUNDED,
        0,
        0,
        NOW,
    )
    required = SpeechProposition(
        "prop-required",
        "yura",
        "current_joy",
        {"state": "not_positive"},
        SpeechPropositionDisposition.REQUIRED,
        SemanticPolarity.NEGATE,
        SemanticCertainty.CERTAIN,
        ("fact-required",),
        degree=0.2,
    )
    forbidden = SpeechProposition(
        "prop-forbidden",
        "yura",
        "unsupported_experience",
        {"value": True},
        SpeechPropositionDisposition.FORBIDDEN,
        SemanticPolarity.AFFIRM,
        SemanticCertainty.CERTAIN,
        ("fact-forbidden",),
    )
    candidate = SpeechSemanticCandidate(
        "semantic-candidate",
        "decision-1",
        "intent-speech",
        ("event-1",),
        REVISIONS,
        (required, forbidden),
        SelfDisclosurePolicy.FACT_GROUNDED,
        0,
        0,
        (),
        (),
        (),
        NOW,
    )
    return SpeechSemanticAuthority().commit(
        candidate,
        context,
        current_revisions=REVISIONS,
        plan_id="plan-1",
        committed_at=NOW,
    )


def _utterance(
    plan: SpeechSemanticPlan | None = None,
    *,
    text: str = TEXT,
) -> CharacterUtterance:
    plan = plan or _semantic_plan()
    profile = CharacterLanguageProfile("yura", 1, 1, ())
    context = CharacterLanguageContextSnapshot(
        "character-request",
        plan,
        profile,
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        NOW,
        "character-trace",
    )
    source = plan.candidate
    candidate = CharacterUtteranceCandidate(
        "utterance-candidate",
        context.request_id,
        plan.plan_id,
        source.decision_id,
        source.intent_id,
        source.source_event_ids,
        source.revisions,
        profile.character_id,
        profile.schema_version,
        profile.definition_revision,
        (
            CharacterUtteranceSegment(
                "segment-1",
                text,
                ("prop-required",),
                LinguisticBoundary.SENTENCE,
                LinguisticEmphasis.NEUTRAL,
                LinguisticHesitation.NONE,
            ),
        ),
        0,
        0,
        NOW + timedelta(seconds=1),
    )
    current = CharacterLanguageCommitState(REVISIONS, plan, True, profile, ())
    return CharacterLanguageAuthority().commit(
        candidate,
        context,
        current=current,
        utterance_id="utterance-1",
        committed_at=NOW + timedelta(seconds=1),
    )


def _snapshot(*, text: str = TEXT) -> SemanticVerificationContextSnapshot:
    plan = _semantic_plan()
    utterance = _utterance(plan, text=text)
    return SemanticVerificationContextSnapshot(
        "verification-1",
        "verify-blind-1",
        "verify-relation-1",
        plan,
        utterance,
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        NOW + timedelta(seconds=1),
        "verify-trace",
    )


def _evidence(quote: str = TEXT) -> UtteranceEvidenceRef:
    return UtteranceEvidenceRef("segment-1", quote, 0)


def _unit(
    *,
    unit_id: str = "unit-required",
    quote: str = TEXT,
    acts: tuple[BlindInteractionAct, ...] = (),
) -> BlindSemanticUnit:
    return BlindSemanticUnit(
        unit_id,
        BlindSemanticUnitKind.MATERIAL_SEMANTIC_CONTENT,
        acts,
        (_evidence(quote),),
    )


def _blind_candidate(
    snapshot: SemanticVerificationContextSnapshot,
    *,
    units: tuple[BlindSemanticUnit, ...] | None = None,
) -> BlindUtteranceObservationCandidate:
    return BlindUtteranceObservationCandidate(
        "blind-candidate",
        snapshot.blind_request_id,
        snapshot.utterance.utterance_id,
        units or (_unit(),),
        NOW + timedelta(seconds=2),
    )


def _proposition_observations(
    *,
    required_support: tuple[str, ...] = ("unit-required",),
) -> tuple[PropositionSemanticObservation, ...]:
    return (
        PropositionSemanticObservation(
            "prop-required",
            PropositionRelation.ENTAILED,
            PolarityRelation.PRESERVED,
            CertaintyRelation.PRESERVED,
            DegreeRelation.PRESERVED,
            ExecutionRelation.NOT_APPLICABLE,
            (_evidence(),),
            required_support,
        ),
        PropositionSemanticObservation(
            "prop-forbidden",
            PropositionRelation.MISSING,
            PolarityRelation.NOT_APPLICABLE,
            CertaintyRelation.NOT_APPLICABLE,
            DegreeRelation.NOT_APPLICABLE,
            ExecutionRelation.NOT_APPLICABLE,
            (),
            (),
        ),
    )


def _relation_candidate(
    snapshot: SemanticVerificationContextSnapshot,
    blind_id: str,
    *,
    observations: tuple[PropositionSemanticObservation, ...] | None = None,
    accounting: tuple[BlindUnitAccounting, ...] | None = None,
    budget: SpeechActBudgetObservation | None = None,
) -> PlanRelationObservationCandidate:
    return PlanRelationObservationCandidate(
        "relation-candidate",
        snapshot.relation_request_id,
        snapshot.semantic_plan.plan_id,
        snapshot.utterance.utterance_id,
        blind_id,
        observations or _proposition_observations(),
        accounting
        or (
            BlindUnitAccounting(
                "unit-required",
                BlindUnitAccountingRelation.SUPPORTED_BY_PLAN,
                ("prop-required",),
                (_evidence(),),
            ),
        ),
        budget or SpeechActBudgetObservation(0, 0),
        SelfDisclosureRelation.WITHIN_POLICY,
        NOW + timedelta(seconds=3),
    )


def _eligible(
    snapshot: SemanticVerificationContextSnapshot,
    *,
    revisions: RevisionVector = REVISIONS,
) -> SemanticVerificationEligibilityView:
    return SemanticVerificationEligibilityView(
        snapshot.semantic_plan.plan_id,
        snapshot.utterance.utterance_id,
        revisions,
        True,
        False,
        False,
    )


def test_blind_request_does_not_leak_plan_or_character_self_proof() -> None:
    snapshot = _snapshot()
    request = build_blind_request(
        snapshot,
        created_at=snapshot.captured_at,
        policy=verification_policy(),
    )
    payload = str(request.input.value)
    assert "semantic_plan" not in payload
    assert "prop-required" not in payload
    assert "realization_refs" not in payload
    assert TEXT in payload


def test_closed_reconciliation_accepts_preserved_required_and_missing_forbidden() -> None:
    snapshot = _snapshot()
    authority = SemanticVerificationAuthority()
    blind = authority.commit_blind(
        _blind_candidate(snapshot),
        snapshot,
        observation_id="blind-observation",
        committed_at=NOW + timedelta(seconds=2),
    )
    relation = authority.commit_relation(
        _relation_candidate(snapshot, blind.observation_id),
        snapshot,
        blind,
        observation_id="relation-observation",
        committed_at=NOW + timedelta(seconds=3),
    )
    observation, acceptance = authority.reconcile(
        snapshot,
        blind,
        relation,
        observation_id="semantic-observation",
        acceptance_id="acceptance-1",
        committed_at=NOW + timedelta(seconds=3),
    )
    assert acceptance.state is SemanticAcceptanceState.ACCEPTED
    assert acceptance.rejection_categories == ()
    assert not hasattr(observation, "rejection_categories")


def test_material_content_can_also_be_directed_question() -> None:
    snapshot = _snapshot()
    authority = SemanticVerificationAuthority()
    blind = authority.commit_blind(
        _blind_candidate(
            snapshot,
            units=(
                _unit(acts=(BlindInteractionAct.DIRECTED_QUESTION,)),
            ),
        ),
        snapshot,
        observation_id="blind-observation",
        committed_at=NOW + timedelta(seconds=2),
    )
    relation = authority.commit_relation(
        _relation_candidate(
            snapshot,
            blind.observation_id,
            budget=SpeechActBudgetObservation(1, 0),
        ),
        snapshot,
        blind,
        observation_id="relation-observation",
        committed_at=NOW + timedelta(seconds=3),
    )
    _, acceptance = authority.reconcile(
        snapshot,
        blind,
        relation,
        observation_id="semantic-observation",
        acceptance_id="acceptance-1",
        committed_at=NOW + timedelta(seconds=3),
    )
    assert acceptance.state is SemanticAcceptanceState.REJECTED
    assert (
        SemanticRejectionCategory.QUESTION_BUDGET_EXCEEDED
        in acceptance.rejection_categories
    )


def test_material_content_cannot_be_downgraded_to_style() -> None:
    snapshot = _snapshot()
    authority = SemanticVerificationAuthority()
    blind = authority.commit_blind(
        _blind_candidate(snapshot),
        snapshot,
        observation_id="blind-observation",
        committed_at=NOW + timedelta(seconds=2),
    )
    candidate = _relation_candidate(
        snapshot,
        blind.observation_id,
        accounting=(
            BlindUnitAccounting(
                "unit-required",
                BlindUnitAccountingRelation.PERMITTED_NON_MATERIAL_STYLE,
                (),
                (_evidence(),),
            ),
        ),
    )
    with pytest.raises(ValueError, match="降格"):
        authority.commit_relation(
            candidate,
            snapshot,
            blind,
            observation_id="relation-observation",
            committed_at=NOW + timedelta(seconds=3),
        )


def test_supported_accounting_must_match_entailed_proposition_support() -> None:
    snapshot = _snapshot()
    authority = SemanticVerificationAuthority()
    blind = authority.commit_blind(
        _blind_candidate(snapshot),
        snapshot,
        observation_id="blind-observation",
        committed_at=NOW + timedelta(seconds=2),
    )
    candidate = _relation_candidate(
        snapshot,
        blind.observation_id,
        accounting=(
            BlindUnitAccounting(
                "unit-required",
                BlindUnitAccountingRelation.SUPPORTED_BY_PLAN,
                ("prop-forbidden",),
                (_evidence(),),
            ),
        ),
    )
    with pytest.raises(ValueError, match="一致しません"):
        authority.commit_relation(
            candidate,
            snapshot,
            blind,
            observation_id="relation-observation",
            committed_at=NOW + timedelta(seconds=3),
        )


def test_evidence_must_exist_in_actual_utterance() -> None:
    snapshot = _snapshot()
    candidate = _blind_candidate(
        snapshot,
        units=(
            _unit(quote="存在しない引用"),
        ),
    )
    with pytest.raises(ValueError, match="ground"):
        SemanticVerificationAuthority().commit_blind(
            candidate,
            snapshot,
            observation_id="blind-observation",
            committed_at=NOW + timedelta(seconds=2),
        )


def test_unsupported_extra_material_content_is_rejected() -> None:
    extra_text = "昨日は買い物した"
    text = f"{TEXT}{extra_text}。"
    snapshot = _snapshot(text=text)
    authority = SemanticVerificationAuthority()
    blind = authority.commit_blind(
        _blind_candidate(
            snapshot,
            units=(
                _unit(),
                _unit(unit_id="unit-extra", quote=extra_text),
            ),
        ),
        snapshot,
        observation_id="blind-observation",
        committed_at=NOW + timedelta(seconds=2),
    )
    relation = authority.commit_relation(
        _relation_candidate(
            snapshot,
            blind.observation_id,
            accounting=(
                BlindUnitAccounting(
                    "unit-required",
                    BlindUnitAccountingRelation.SUPPORTED_BY_PLAN,
                    ("prop-required",),
                    (_evidence(),),
                ),
                BlindUnitAccounting(
                    "unit-extra",
                    BlindUnitAccountingRelation.UNSUPPORTED_EXTRA,
                    (),
                    (_evidence(extra_text),),
                ),
            ),
        ),
        snapshot,
        blind,
        observation_id="relation-observation",
        committed_at=NOW + timedelta(seconds=3),
    )
    _, acceptance = authority.reconcile(
        snapshot,
        blind,
        relation,
        observation_id="semantic-observation",
        acceptance_id="acceptance-1",
        committed_at=NOW + timedelta(seconds=3),
    )
    assert acceptance.state is SemanticAcceptanceState.REJECTED
    assert (
        SemanticRejectionCategory.UNSUPPORTED_EXTRA_CLAIM
        in acceptance.rejection_categories
    )


class _SequencePort:
    def __init__(self, snapshot: SemanticVerificationContextSnapshot) -> None:
        self.snapshot = snapshot
        self.requests: list[LLMRoleRequest] = []

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.requests.append(request)
        return self._result_for(request)

    def _result_for(self, request: LLMRoleRequest) -> LLMRoleResult:
        if request.role_id == BLIND_ROLE_ID:
            value: object = {
                "candidate_id": "blind-candidate",
                "request_id": request.request_id,
                "utterance_id": self.snapshot.utterance.utterance_id,
                "units": [
                    {
                        "unit_id": "unit-required",
                        "kind": "material_semantic_content",
                        "interaction_acts": [],
                        "evidence_refs": [
                            {
                                "segment_id": "segment-1",
                                "quote": TEXT,
                                "occurrence_index": 0,
                            }
                        ],
                    }
                ],
            }
            schema = "semantic.verification.blind.candidate.v1"
            when = NOW + timedelta(seconds=2)
        else:
            assert request.role_id == RELATION_ROLE_ID
            value = {
                "candidate_id": "relation-candidate",
                "request_id": request.request_id,
                "semantic_plan_id": self.snapshot.semantic_plan.plan_id,
                "utterance_id": self.snapshot.utterance.utterance_id,
                "blind_observation_id": "blind-observation",
                "proposition_observations": [
                    {
                        "proposition_id": "prop-required",
                        "relation": "entailed",
                        "polarity_relation": "preserved",
                        "certainty_relation": "preserved",
                        "degree_relation": "preserved",
                        "execution_relation": "not_applicable",
                        "evidence_refs": [
                            {
                                "segment_id": "segment-1",
                                "quote": TEXT,
                                "occurrence_index": 0,
                            }
                        ],
                        "supporting_blind_unit_ids": ["unit-required"],
                    },
                    {
                        "proposition_id": "prop-forbidden",
                        "relation": "missing",
                        "polarity_relation": "not_applicable",
                        "certainty_relation": "not_applicable",
                        "degree_relation": "not_applicable",
                        "execution_relation": "not_applicable",
                        "evidence_refs": [],
                        "supporting_blind_unit_ids": [],
                    },
                ],
                "blind_unit_accounting": [
                    {
                        "blind_unit_id": "unit-required",
                        "relation": "supported_by_plan",
                        "proposition_ids": ["prop-required"],
                        "evidence_refs": [
                            {
                                "segment_id": "segment-1",
                                "quote": TEXT,
                                "occurrence_index": 0,
                            }
                        ],
                    }
                ],
                "budget_observation": {
                    "directed_question_count": 0,
                    "new_direction_count": 0,
                },
                "self_disclosure_relation": "within_policy",
            }
            schema = "semantic.verification.relation.candidate.v1"
            when = NOW + timedelta(seconds=3)
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.SUCCEEDED,
            request.revisions,
            when,
            request.trace_id,
            LLMModelClass.BALANCED,
            1,
            LLMTokenUsage(10, 10),
            StructuredPayload(schema, cast(JsonValue, value)),
            started_at=request.created_at,
        )


class _BlockingSequencePort(_SequencePort):
    def __init__(self, snapshot: SemanticVerificationContextSnapshot) -> None:
        super().__init__(snapshot)
        self.blind_started = asyncio.Event()
        self.blind_release = asyncio.Event()
        self.relation_started = asyncio.Event()
        self.relation_release = asyncio.Event()

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.requests.append(request)
        if request.role_id == BLIND_ROLE_ID:
            self.blind_started.set()
            await self.blind_release.wait()
        else:
            assert request.role_id == RELATION_ROLE_ID
            self.relation_started.set()
            await self.relation_release.wait()
        return self._result_for(request)


class _LiveState:
    def __init__(
        self,
        snapshot: SemanticVerificationContextSnapshot,
        states: list[SemanticVerificationEligibilityView] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.states = states or [_eligible(snapshot)] * 3
        self.calls = 0

    async def current_state(
        self,
        snapshot: SemanticVerificationContextSnapshot,
    ) -> SemanticVerificationEligibilityView:
        assert snapshot is self.snapshot
        state = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        return state


@pytest.mark.asyncio
async def test_verifier_runs_blind_before_plan_relation_and_accepts() -> None:
    snapshot = _snapshot()
    port = _SequencePort(snapshot)
    live = _LiveState(snapshot)
    run = await SemanticVerifier(
        port,
        live,
        SemanticVerificationAuthority(),
        verification_policy(),
    ).verify(
        snapshot,
        blind_observation_id="blind-observation",
        relation_observation_id="relation-observation",
        semantic_observation_id="semantic-observation",
        acceptance_id="acceptance-1",
        created_at=snapshot.captured_at,
    )
    assert [item.role_id for item in port.requests] == [
        BLIND_ROLE_ID,
        RELATION_ROLE_ID,
    ]
    assert run.acceptance.state is SemanticAcceptanceState.ACCEPTED
    relation_payload = str(port.requests[1].input.value)
    assert "unit-required" in relation_payload
    assert "semantic_plan" in relation_payload


@pytest.mark.asyncio
async def test_stale_after_blind_does_not_invoke_plan_relation() -> None:
    snapshot = _snapshot()
    port = _SequencePort(snapshot)
    stale = replace(_eligible(snapshot), revisions=RevisionVector(11, 4, 2))
    live = _LiveState(snapshot, [_eligible(snapshot), stale])
    verifier = SemanticVerifier(
        port,
        live,
        SemanticVerificationAuthority(),
        verification_policy(),
    )
    with pytest.raises(SemanticVerificationError) as captured:
        await verifier.verify(
            snapshot,
            blind_observation_id="blind-observation",
            relation_observation_id="relation-observation",
            semantic_observation_id="semantic-observation",
            acceptance_id="acceptance-1",
            created_at=snapshot.captured_at,
        )
    assert captured.value.code is SemanticVerificationFailureCode.STALE
    assert [item.role_id for item in port.requests] == [BLIND_ROLE_ID]


@pytest.mark.asyncio
async def test_slow_provider_awaits_do_not_block_unrelated_tasks() -> None:
    snapshot = _snapshot()
    port = _BlockingSequencePort(snapshot)
    verifier = SemanticVerifier(
        port,
        _LiveState(snapshot),
        SemanticVerificationAuthority(),
        verification_policy(),
    )
    verification = asyncio.create_task(
        verifier.verify(
            snapshot,
            blind_observation_id="blind-observation",
            relation_observation_id="relation-observation",
            semantic_observation_id="semantic-observation",
            acceptance_id="acceptance-1",
            created_at=snapshot.captured_at,
        )
    )

    await asyncio.wait_for(port.blind_started.wait(), timeout=1)
    blind_heartbeat = asyncio.Event()
    asyncio.create_task(_heartbeat(blind_heartbeat))
    await asyncio.wait_for(blind_heartbeat.wait(), timeout=1)
    assert not verification.done()

    port.blind_release.set()
    await asyncio.wait_for(port.relation_started.wait(), timeout=1)
    relation_heartbeat = asyncio.Event()
    asyncio.create_task(_heartbeat(relation_heartbeat))
    await asyncio.wait_for(relation_heartbeat.wait(), timeout=1)
    assert not verification.done()

    port.relation_release.set()
    run = await verification
    assert run.acceptance.state is SemanticAcceptanceState.ACCEPTED
    assert [item.role_id for item in port.requests] == [BLIND_ROLE_ID, RELATION_ROLE_ID]


async def _heartbeat(completed: asyncio.Event) -> None:
    completed.set()


def test_semantic_module_has_no_finite_lexical_authority_scaffolding() -> None:
    root = Path("app/domain/semantic_verification")
    forbidden_name_fragments = (
        "keyword",
        "marker",
        "phrase",
        "synonym",
        "antonym",
    )
    violations: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "re" for alias in node.names):
                    violations.append(f"{path}: import re")
            elif isinstance(node, ast.ImportFrom) and node.module == "re":
                violations.append(f"{path}: from re")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    lowered = target.id.lower()
                    if any(fragment in lowered for fragment in forbidden_name_fragments):
                        violations.append(f"{path}: {target.id}")
    assert violations == []

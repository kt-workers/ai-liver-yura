import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.contracts import ExecutionStatus, RevisionVector
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
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from app.domain.speech_semantics import (
    DeterministicSpeechDirective,
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticClaimKind,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
    SpeechSemanticPlan,
    SpeechSemanticsPlanner,
    SpeechSemanticsPolicy,
    SpeechTruthConstraint,
    SpeechTruthRule,
    build_request,
    commit_result,
    parse_candidate,
)

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
REVISIONS = RevisionVector(7, 5, 3)


def policy() -> SpeechSemanticsPolicy:
    return SpeechSemanticsPolicy(
        LLMExecutionPolicy(
            LLMModelClass.BALANCED,
            LLMReasoningEffort.MEDIUM,
            10,
            1,
            1000,
        )
    )


def decision(
    *, intent_id: str = "intent-speech", source_event_id: str = "event-1"
) -> CommittedExecutiveDecision:
    intent = ExecutiveIntent(
        intent_id,
        ExecutiveIntentKind.SPEECH,
        "応答内容を準備する",
        SpeechIntentPayload(
            "fact-goal",
            constraint_refs=("truth-match", "relationship-soft", "discourse-answer"),
        ),
        ("fact-desire",),
        (),
        (),
        ("fact-forbidden",),
    )
    candidate = ExecutiveDecisionCandidate(
        f"candidate-{intent_id}",
        f"trigger-{intent_id}",
        (source_event_id,),
        7,
        5,
        3,
        ExecutiveOutcome.RESPOND,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (intent,),
        (),
        (),
        ("fact-goal",),
        NOW,
    )
    return CommittedExecutiveDecision(f"decision-{intent_id}", candidate, (), NOW)


def facts() -> tuple[SpeechSemanticFact, ...]:
    return (
        SpeechSemanticFact(
            "fact-goal",
            SpeechSemanticFactKind.GENERAL,
            "user",
            "answer",
            {"topic_ref": "topic-1"},
        ),
        SpeechSemanticFact(
            "fact-desire",
            SpeechSemanticFactKind.SELF,
            "yura",
            "interest",
            {"topic_ref": "project-yura"},
            degree=0.8,
        ),
        SpeechSemanticFact(
            "fact-forbidden",
            SpeechSemanticFactKind.GENERAL,
            "claim",
            "unsupported",
            {"forbidden": True},
        ),
        SpeechSemanticFact(
            "fact-execution",
            SpeechSemanticFactKind.EXECUTION,
            "command-1",
            "execution.status",
            {"status": "completed"},
            claim_kind=SemanticClaimKind.EXECUTION_STATUS,
            execution_status=ExecutionStatus.COMPLETED,
        ),
    )


def propositions() -> tuple[SpeechProposition, ...]:
    return (
        SpeechProposition(
            "p-goal",
            "user",
            "answer",
            {"topic_ref": "topic-1"},
            SpeechPropositionDisposition.REQUIRED,
            SemanticPolarity.AFFIRM,
            SemanticCertainty.CERTAIN,
            ("fact-goal",),
        ),
        SpeechProposition(
            "p-desire",
            "yura",
            "interest",
            {"topic_ref": "project-yura"},
            SpeechPropositionDisposition.OPTIONAL,
            SemanticPolarity.AFFIRM,
            SemanticCertainty.CERTAIN,
            ("fact-desire",),
            0.8,
        ),
        SpeechProposition(
            "p-forbidden",
            "claim",
            "unsupported",
            {"forbidden": True},
            SpeechPropositionDisposition.FORBIDDEN,
            SemanticPolarity.AFFIRM,
            SemanticCertainty.CERTAIN,
            ("fact-forbidden",),
        ),
        SpeechProposition(
            "p-execution",
            "command-1",
            "execution.status",
            {"status": "completed"},
            SpeechPropositionDisposition.REQUIRED,
            SemanticPolarity.AFFIRM,
            SemanticCertainty.CERTAIN,
            ("fact-execution",),
            claim_kind=SemanticClaimKind.EXECUTION_STATUS,
            execution_status=ExecutionStatus.COMPLETED,
        ),
    )


def directive() -> DeterministicSpeechDirective:
    return DeterministicSpeechDirective(
        propositions(),
        SelfDisclosurePolicy.FACT_GROUNDED,
        1,
        0,
        ("truth-match",),
        ("relationship-soft",),
        ("discourse-answer",),
    )


def context(
    *,
    deterministic: bool = True,
    intent_id: str = "intent-speech",
    source_event_id: str = "event-1",
) -> SpeechSemanticContextSnapshot:
    return SpeechSemanticContextSnapshot(
        decision(intent_id=intent_id, source_event_id=source_event_id),
        intent_id,
        facts(),
        (SpeechTruthConstraint("truth-match", "fact-execution", SpeechTruthRule.REQUIRE_MATCH),),
        ("relationship-soft", "discourse-answer"),
        SelfDisclosurePolicy.FACT_GROUNDED,
        1,
        1,
        NOW,
        directive() if deterministic else None,
    )


def candidate(*, candidate_id: str = "semantic-candidate-1") -> SpeechSemanticCandidate:
    item = context()
    value = item.deterministic_directive
    assert value is not None
    return SpeechSemanticCandidate(
        candidate_id,
        item.decision.decision_id,
        item.intent_id,
        item.source_event_ids,
        item.revisions,
        value.propositions,
        value.self_disclosure,
        value.question_budget,
        value.new_direction_budget,
        value.truth_constraint_refs,
        value.relationship_constraint_refs,
        value.discourse_constraint_refs,
        NOW,
    )


def candidate_json(item: SpeechSemanticCandidate | None = None) -> dict[str, object]:
    value = (item or candidate()).to_dict()
    value.pop("created_at")
    return value


def result_for(request: LLMRoleRequest, value: object) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW + timedelta(seconds=2),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(10, 10),
        StructuredPayload("yura.speech-semantics.candidate.v1", cast(JsonValue, value)),
        started_at=NOW + timedelta(seconds=1),
    )


def test_contracts_are_immutable_and_plan_requires_authority() -> None:
    raw = {"nested": ["owned"]}
    fact = SpeechSemanticFact(
        "fact-1",
        SpeechSemanticFactKind.GENERAL,
        "subject",
        "predicate",
        cast(JsonValue, raw),
    )
    raw["nested"].append("mutated")
    assert fact.to_dict()["value"] == {"nested": ["owned"]}
    with pytest.raises(ValueError, match="SpeechSemanticAuthority"):
        SpeechSemanticPlan("plan-1", candidate(), NOW)
    with pytest.raises(ValueError, match="invalid value"):
        replace(
            propositions()[0],
            disposition=cast(SpeechPropositionDisposition, "required"),
        )
    with pytest.raises(ValueError, match="degree field"):
        replace(propositions()[0], value={"degree": 0.5})
    with pytest.raises(ValueError, match="execution status"):
        replace(
            propositions()[0],
            claim_kind=SemanticClaimKind.EXECUTION_STATUS,
        )
    plan = SpeechSemanticAuthority().commit(
        candidate(),
        context(),
        current_revisions=REVISIONS,
        plan_id="plan-proof",
        committed_at=NOW,
    )
    with pytest.raises(ValueError, match="SpeechSemanticAuthority"):
        replace(plan, candidate=replace(candidate(), candidate_id="forged"))


def test_snapshot_rejects_unbounded_intent_and_directive_references() -> None:
    item = context()
    bad_decision = item.decision
    bad_intent = replace(
        bad_decision.candidate.intents[0],
        payload=SpeechIntentPayload("fact-missing"),
    )
    bad_candidate = replace(bad_decision.candidate, intents=(bad_intent,))
    with pytest.raises(ValueError, match="outside snapshot"):
        replace(item, decision=replace(bad_decision, candidate=bad_candidate))
    bad_proposition = replace(propositions()[0], evidence_fact_refs=("fact-missing",))
    with pytest.raises(ValueError, match="outside snapshot"):
        replace(
            item,
            deterministic_directive=replace(directive(), propositions=(bad_proposition,)),
        )


def test_authority_commits_valid_plan_and_rejects_all_revision_staleness() -> None:
    item = context()
    for revisions in (
        RevisionVector(8, 5, 3),
        RevisionVector(7, 6, 3),
        RevisionVector(7, 5, 4),
    ):
        with pytest.raises(ValueError, match="stale"):
            SpeechSemanticAuthority().commit(
                candidate(),
                item,
                current_revisions=revisions,
                plan_id="plan-stale",
                committed_at=NOW,
            )
    plan = SpeechSemanticAuthority().commit(
        candidate(),
        item,
        current_revisions=REVISIONS,
        plan_id="plan-1",
        committed_at=NOW,
    )
    assert plan.candidate.propositions[0].disposition is SpeechPropositionDisposition.REQUIRED


def test_authoritative_budget_truth_and_forbidden_claims_cannot_be_omitted() -> None:
    item = context()
    owner = SpeechSemanticAuthority()
    with pytest.raises(ValueError, match="question budget"):
        owner.commit(
            replace(candidate(), question_budget=2),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-budget",
            committed_at=NOW,
        )
    with pytest.raises(ValueError, match="truth constraints"):
        owner.commit(
            replace(candidate(), truth_constraint_refs=()),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-truth",
            committed_at=NOW,
        )
    without_forbidden = tuple(
        value for value in candidate().propositions if value.proposition_id != "p-forbidden"
    )
    with pytest.raises(ValueError, match="forbidden Executive claim"):
        owner.commit(
            replace(candidate(), propositions=without_forbidden),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-forbidden",
            committed_at=NOW,
        )
    hidden_required = tuple(
        replace(value, disposition=SpeechPropositionDisposition.FORBIDDEN)
        if value.proposition_id in {"p-goal", "p-desire"}
        else value
        for value in candidate().propositions
    )
    with pytest.raises(ValueError, match="required speech intent fact"):
        owner.commit(
            replace(candidate(), propositions=hidden_required),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-hidden-required",
            committed_at=NOW,
        )
    substituted_forbidden = tuple(
        replace(value, predicate="different-claim")
        if value.proposition_id == "p-forbidden"
        else value
        for value in candidate().propositions
    )
    with pytest.raises(ValueError, match="forbidden Executive claim"):
        owner.commit(
            replace(candidate(), propositions=substituted_forbidden),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-substituted-forbidden",
            committed_at=NOW,
        )
    with pytest.raises(ValueError, match="omits Executive speech constraint"):
        owner.commit(
            replace(candidate(), relationship_constraint_refs=()),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-constraint",
            committed_at=NOW,
        )
    forbidden_context = replace(
        item,
        self_disclosure_policy=SelfDisclosurePolicy.FORBIDDEN,
        deterministic_directive=None,
    )
    with pytest.raises(ValueError, match="self disclosure"):
        owner.commit(
            candidate(),
            forbidden_context,
            current_revisions=REVISIONS,
            plan_id="plan-disclosure",
            committed_at=NOW,
        )
    with pytest.raises(ValueError, match="proposition is forbidden"):
        owner.commit(
            replace(candidate(), self_disclosure=SelfDisclosurePolicy.FORBIDDEN),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-hidden-disclosure",
            committed_at=NOW,
        )


def test_execution_truth_rejects_mismatch_unknown_loss_and_completion_fabrication() -> None:
    item = context()
    wrong = replace(
        candidate().propositions[-1],
        value={"status": "failed"},
    )
    with pytest.raises(ValueError, match="does not match"):
        SpeechSemanticAuthority().commit(
            replace(candidate(), propositions=(*candidate().propositions[:-1], wrong)),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-wrong",
            committed_at=NOW,
        )

    uncertain = replace(candidate().propositions[-1], certainty=SemanticCertainty.UNKNOWN)
    with pytest.raises(ValueError, match="does not match"):
        SpeechSemanticAuthority().commit(
            replace(candidate(), propositions=(*candidate().propositions[:-1], uncertain)),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-certainty",
            committed_at=NOW,
        )

    degree_changed = replace(candidate().propositions[-1], degree=0.5)
    with pytest.raises(ValueError, match="does not match"):
        SpeechSemanticAuthority().commit(
            replace(candidate(), propositions=(*candidate().propositions[:-1], degree_changed)),
            item,
            current_revisions=REVISIONS,
            plan_id="plan-degree",
            committed_at=NOW,
        )

    unknown_fact = replace(
        facts()[-1],
        value={"status": "started"},
        execution_status=ExecutionStatus.STARTED,
        polarity=SemanticPolarity.UNKNOWN,
        certainty=SemanticCertainty.UNKNOWN,
    )
    unknown_context = replace(
        item,
        facts=(*facts()[:-1], unknown_fact),
        truth_constraints=(
            SpeechTruthConstraint(
                "truth-match", "fact-execution", SpeechTruthRule.PRESERVE_UNKNOWN
            ),
        ),
        deterministic_directive=None,
    )
    with pytest.raises(ValueError, match="remain unknown"):
        SpeechSemanticAuthority().commit(
            candidate(),
            unknown_context,
            current_revisions=REVISIONS,
            plan_id="plan-unknown",
            committed_at=NOW,
        )
    half_unknown = replace(
        candidate().propositions[-1],
        value={"status": "started"},
        execution_status=ExecutionStatus.STARTED,
        polarity=SemanticPolarity.UNKNOWN,
        certainty=SemanticCertainty.CERTAIN,
    )
    with pytest.raises(ValueError, match="remain unknown"):
        SpeechSemanticAuthority().commit(
            replace(candidate(), propositions=(*candidate().propositions[:-1], half_unknown)),
            unknown_context,
            current_revisions=REVISIONS,
            plan_id="plan-half-unknown",
            committed_at=NOW,
        )
    preserved_unknown = replace(
        half_unknown,
        certainty=SemanticCertainty.UNKNOWN,
    )
    SpeechSemanticAuthority().commit(
        replace(candidate(), propositions=(*candidate().propositions[:-1], preserved_unknown)),
        unknown_context,
        current_revisions=REVISIONS,
        plan_id="plan-preserved-unknown",
        committed_at=NOW,
    )

    started_fact = replace(
        facts()[-1],
        predicate="execution.started",
        value={"status": "started"},
        execution_status=ExecutionStatus.STARTED,
    )
    completion_context = replace(
        item,
        facts=(*facts()[:-1], started_fact),
        truth_constraints=(
            SpeechTruthConstraint(
                "truth-match",
                "fact-execution",
                SpeechTruthRule.FORBID_COMPLETION_CLAIM,
            ),
        ),
        deterministic_directive=None,
    )
    completed_claim = replace(
        candidate().propositions[-1],
        predicate="execution.finished",
        value={"status": "completed"},
    )
    with pytest.raises(ValueError, match="completion claim"):
        SpeechSemanticAuthority().commit(
            replace(candidate(), propositions=(*candidate().propositions[:-1], completed_claim)),
            completion_context,
            current_revisions=REVISIONS,
            plan_id="plan-completion",
            committed_at=NOW,
        )


def test_complex_exchange_is_strict_and_commits_current_result() -> None:
    item = context(deterministic=False)
    request = build_request(
        item,
        request_id="request-1",
        trace_id="trace-1",
        created_at=NOW,
        policy=policy(),
    )
    parsed = parse_candidate(candidate_json(), created_at=NOW + timedelta(seconds=2))
    assert parsed.intent_id == item.intent_id
    plan = commit_result(
        request,
        result_for(request, candidate_json()),
        snapshot=item,
        current_revisions=REVISIONS,
        authority=SpeechSemanticAuthority(),
        plan_id="plan-complex",
        policy=policy(),
    )
    assert plan.plan_id == "plan-complex"
    malformed = candidate_json()
    malformed["final_utterance"] = "権限外の最終台詞"
    with pytest.raises(ValueError, match="fields do not match"):
        parse_candidate(malformed, created_at=NOW)
    wrong_request = replace(request, revisions=RevisionVector(8, 5, 3))
    with pytest.raises(ValueError, match="request revisions"):
        commit_result(
            wrong_request,
            result_for(wrong_request, candidate_json()),
            snapshot=item,
            current_revisions=REVISIONS,
            authority=SpeechSemanticAuthority(),
            plan_id="plan-wrong-request",
            policy=policy(),
        )


@pytest.mark.asyncio
async def test_simple_path_skips_llm_and_reads_live_revision_before_commit() -> None:
    class Port:
        called = False

        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            self.called = True
            raise AssertionError("simple path must not invoke LLM")

    class Live:
        calls = 0

        async def current_revisions(
            self, snapshot: SpeechSemanticContextSnapshot
        ) -> RevisionVector:
            self.calls += 1
            return snapshot.revisions

    port, live = Port(), Live()
    plan = await SpeechSemanticsPlanner(port, live, SpeechSemanticAuthority(), policy()).plan(
        context(),
        request_id="unused-request",
        trace_id="trace-1",
        candidate_id="simple-candidate",
        plan_id="simple-plan",
        created_at=NOW,
    )
    assert plan.plan_id == "simple-plan"
    assert not port.called
    assert live.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_revisions",
    [
        RevisionVector(8, 5, 3),
        RevisionVector(7, 6, 3),
        RevisionVector(7, 5, 4),
    ],
)
async def test_complex_path_reloads_live_revision_after_llm_await(
    changed_revisions: RevisionVector,
) -> None:
    invoked = asyncio.Event()
    release = asyncio.Event()

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            invoked.set()
            await release.wait()
            return result_for(request, candidate_json())

    class Live:
        revisions = REVISIONS

        async def current_revisions(
            self, snapshot: SpeechSemanticContextSnapshot
        ) -> RevisionVector:
            return self.revisions

    live = Live()
    planner = SpeechSemanticsPlanner(Port(), live, SpeechSemanticAuthority(), policy())
    task = asyncio.create_task(
        planner.plan(
            context(deterministic=False),
            request_id="request-1",
            trace_id="trace-1",
            candidate_id="unused-candidate",
            plan_id="complex-plan",
            created_at=NOW,
        )
    )
    await invoked.wait()
    live.revisions = changed_revisions
    release.set()
    with pytest.raises(ValueError, match="stale"):
        await task


def test_same_intent_competition_is_atomic() -> None:
    owner = SpeechSemanticAuthority()

    def attempt(index: int) -> str:
        try:
            owner.commit(
                candidate(candidate_id=f"candidate-{index}"),
                context(),
                current_revisions=REVISIONS,
                plan_id=f"plan-{index}",
                committed_at=NOW,
            )
            return "committed"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, range(2)))
    assert outcomes.count("committed") == 1
    assert outcomes.count("rejected") == 1


@pytest.mark.asyncio
async def test_slow_complex_path_does_not_block_unrelated_simple_path() -> None:
    invoked = asyncio.Event()
    release = asyncio.Event()

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            invoked.set()
            await release.wait()
            return result_for(request, candidate_json())

    class Live:
        async def current_revisions(
            self, snapshot: SpeechSemanticContextSnapshot
        ) -> RevisionVector:
            return snapshot.revisions

    planner = SpeechSemanticsPlanner(Port(), Live(), SpeechSemanticAuthority(), policy())
    slow = asyncio.create_task(
        planner.plan(
            context(deterministic=False),
            request_id="slow-request",
            trace_id="slow-trace",
            candidate_id="unused",
            plan_id="slow-plan",
            created_at=NOW,
        )
    )
    await invoked.wait()
    fast = await asyncio.wait_for(
        planner.plan(
            context(
                intent_id="intent-fast",
                source_event_id="event-fast",
            ),
            request_id="unused-fast",
            trace_id="fast-trace",
            candidate_id="fast-candidate",
            plan_id="fast-plan",
            created_at=NOW,
        ),
        timeout=0.2,
    )
    assert fast.plan_id == "fast-plan"
    release.set()
    assert (await slow).plan_id == "slow-plan"

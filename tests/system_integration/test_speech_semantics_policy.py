"""採用済みV1値と、既存Ownerを使うproduction注入境界の試験。"""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.composition.speech_semantics_policy import (
    SpeechSemanticPolicyBinding,
    bind_speech_semantics_policy_v1,
    build_speech_semantics_meaning_policy_v1,
    build_speech_semantics_policy_owner_v1,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.executive import CommittedExecutiveDecision, SpeechIntentPayload
from app.domain.speech_semantics import (
    SelfDisclosurePolicy,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
)
from app.domain.speech_semantics.production import SpeechSemanticPolicyOwner
from app.domain.speech_semantics_vocabulary import (
    CommunicativeActKind,
    CommunicativeSubjectBinding,
    CommunicativeTargetMode,
    SemanticCertainty,
    SemanticClaimKind,
    SemanticPolarity,
    SpeechSemanticContextError,
    SpeechSemanticFactKind,
)
from app.domain.speech_semantics_vocabulary import (
    SpeechSemanticContextFailureCode as C,
)
from app.domain.speech_semantics_vocabulary import (
    SpeechSourceContractKind as Contract,
)
from tests.domain.executive.test_executive import NOW, candidate, live_state, snapshot
from tests.domain.speech_semantics.test_production_context import inputs, policies
from tests.helpers.executive_requirements import fence_clock, make_authority
from tests.helpers.goal_semantics import semantic_spec

EXPECTED_IDS = {
    CommunicativeActKind.GREETING: "yura.communicative.greeting",
    CommunicativeActKind.ACKNOWLEDGEMENT: "yura.communicative.acknowledgement",
    CommunicativeActKind.GRATITUDE: "yura.communicative.gratitude",
    CommunicativeActKind.APOLOGY: "yura.communicative.apology",
    CommunicativeActKind.REQUEST: "yura.communicative.request",
    CommunicativeActKind.COMMITMENT: "yura.communicative.commitment",
    CommunicativeActKind.CONSENT: "yura.communicative.consent",
    CommunicativeActKind.REFUSAL: "yura.communicative.refusal",
    CommunicativeActKind.FAREWELL: "yura.communicative.farewell",
}


def binding() -> SpeechSemanticPolicyBinding:
    test_policies = policies()
    _, _, port = inputs()
    owner = build_speech_semantics_policy_owner_v1(
        projection=test_policies.projection, truth=test_policies.truth, bounds_policy=BOUNDS
    )
    return bind_speech_semantics_policy_v1(
        owner, sources=port, read_source_bindings=lambda facts: snapshot().speech_source_bindings
    )


def committed(
    value: SpeechSemanticPolicyBinding, ref: str, evidence: tuple[str, ...] = ()
) -> CommittedExecutiveDecision:
    captured = snapshot()
    catalog, sources = value.executive_evidence.capture_speech_sources(captured.facts)
    captured = replace(captured, communicative_goal_catalog=catalog, speech_source_bindings=sources)
    proposed = candidate()
    intent = replace(
        proposed.intents[0],
        payload=SpeechIntentPayload(ref),
        evidence_refs=evidence,
        forbidden_claim_refs=(),
    )
    proposed = replace(proposed, intents=(intent,))
    current = replace(
        live_state(),
        communicative_goal_catalog=value.owner.catalog_view(),
        speech_source_bindings=sources,
    )
    with fence_clock(lambda: NOW):
        return make_authority(captured).commit(
            proposed, captured, current=current, decision_id="production-v1"
        )


def speech_candidate(
    context: SpeechSemanticContextSnapshot, question: int, direction: int
) -> SpeechSemanticCandidate:
    return SpeechSemanticCandidate(
        "v1-speech",
        context.decision.decision_id,
        context.intent_id,
        context.source_event_ids,
        context.revisions,
        tuple(
            SpeechProposition(
                "v1-" + f.fact_id,
                f.subject_ref,
                f.predicate,
                f.value,
                SpeechPropositionDisposition.REQUIRED,
                f.polarity,
                f.certainty,
                (f.fact_id,),
                f.degree,
                f.claim_kind,
                f.execution_status,
            )
            for f in context.facts
        ),
        SelfDisclosurePolicy.FORBIDDEN,
        question,
        direction,
        tuple(c.constraint_id for c in context.truth_constraints),
        (),
        (),
        NOW,
    )


def test_exact_production_v1_values_and_immutable_catalog() -> None:
    value = build_speech_semantics_meaning_policy_v1(bounds_policy=BOUNDS)
    assert value.policy_id == "yura.speech-semantics.meaning"
    assert value.revision == 1
    assert value.self_disclosure_policy is SelfDisclosurePolicy.FORBIDDEN
    assert value.max_question_budget == value.max_new_direction_budget == 1
    catalog = value.communicative_goal_catalog
    assert (catalog.policy_id, catalog.policy_revision) == (value.policy_id, 1)
    assert (catalog.bounds_policy_id, catalog.bounds_policy_revision) == (BOUNDS.policy_id, 2)
    assert len(catalog.definitions) == len(set(d.definition_id for d in catalog.definitions)) == 9
    assert {d.act_kind for d in catalog.definitions} == set(CommunicativeActKind)
    assert {d.act_kind: d.definition_id for d in catalog.definitions} == EXPECTED_IDS
    with pytest.raises(FrozenInstanceError):
        setattr(value, "revision", 2)  # noqa: B010
    for definition in catalog.definitions:
        assert definition.definition_revision == 1
        shape = definition.semantic_shape
        assert (shape.subject_ref, shape.predicate) == ("current-interaction", "communicative-act")
        assert shape.value == {"kind": definition.act_kind.value}
        assert (shape.polarity, shape.certainty, shape.claim_kind) == (
            SemanticPolarity.AFFIRM,
            SemanticCertainty.CERTAIN,
            SemanticClaimKind.GENERAL,
        )
        assert shape.degree is None and shape.evidence_index is None
        assert shape.subject_binding is CommunicativeSubjectBinding.LITERAL
        assert definition.target_requirement.mode is CommunicativeTargetMode.NONE
        assert definition.target_requirement.source_contracts == ()
        required = definition.evidence_requirement
        if definition.act_kind is CommunicativeActKind.GRATITUDE:
            assert required.minimum_count == 1
            assert set(required.source_contracts) == {
                Contract.GOAL,
                Contract.COMMITMENT,
                Contract.EXECUTION,
                Contract.MEMORY,
                Contract.ATTENTION,
            }
        elif definition.act_kind is CommunicativeActKind.COMMITMENT:
            assert required.minimum_count == 1
            assert required.source_contracts == (Contract.COMMITMENT,)
        else:
            assert required.minimum_count == 0 and required.source_contracts == ()


@pytest.mark.parametrize("question,direction", [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 2)])
def test_v1_budgets_are_ceilings_through_public_authority(question: int, direction: int) -> None:
    value = binding()
    decision = committed(value, "yura.communicative.greeting")
    context = value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    proposed = speech_candidate(context, question, direction)
    authority = SpeechSemanticAuthority()
    if max(question, direction) > 1:
        with pytest.raises(ValueError, match="budget exceeds authoritative maximum"):
            authority.commit(
                proposed,
                context,
                current_revisions=context.revisions,
                plan_id="v1-plan",
                committed_at=NOW,
            )
        assert authority.snapshot("v1-plan") is None
    else:
        with fence_clock(lambda: NOW):
            plan = authority.commit(
                proposed,
                context,
                current_revisions=context.revisions,
                plan_id="v1-plan",
                committed_at=NOW,
            )
        assert plan.candidate.question_budget == question
        assert plan.candidate.new_direction_budget == direction
        assert plan.candidate.self_disclosure is SelfDisclosurePolicy.FORBIDDEN


@pytest.mark.parametrize(
    "kind",
    [
        k
        for k in CommunicativeActKind
        if k not in {CommunicativeActKind.GRATITUDE, CommunicativeActKind.COMMITMENT}
    ],
)
def test_seven_acts_construct_without_external_fact_claim(kind: CommunicativeActKind) -> None:
    value = binding()
    decision = committed(value, EXPECTED_IDS[kind])
    built = value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    assert len(built.facts) == 1
    assert built.facts[0].kind is SpeechSemanticFactKind.DISCOURSE
    assert built.facts[0].value == {"kind": kind.value}
    assert built.facts[0].evidence_refs == ()


@pytest.mark.parametrize(
    "kind,evidence",
    [
        (CommunicativeActKind.GRATITUDE, ()),
        (CommunicativeActKind.COMMITMENT, ()),
        (CommunicativeActKind.COMMITMENT, ("goal-1",)),
    ],
)
def test_evidence_requirements_reject_missing_or_wrong_typed_evidence(
    kind: CommunicativeActKind, evidence: tuple[str, ...]
) -> None:
    value = binding()
    decision = committed(value, EXPECTED_IDS[kind], evidence)
    with pytest.raises(SpeechSemanticContextError) as error:
        value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    assert error.value.code is C.SOURCE_NOT_FOUND


def test_gratitude_preserves_authoritative_evidence_separately() -> None:
    value = binding()
    decision = committed(value, "yura.communicative.gratitude", ("goal-1",))
    built = value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    assert len(built.facts) == 2
    act = next(f for f in built.facts if f.kind is SpeechSemanticFactKind.DISCOURSE)
    assert act.value == {"kind": "gratitude"} and act.evidence_refs == ("goal-1",)
    evidence = next(p for p in built.fact_provenance if p.fact_id == "goal-1")
    assert evidence.source_owner == "test-speech-source"


@pytest.mark.parametrize("fault", ["missing", "policy_id", "revision", "fixture"])
def test_injection_rejects_missing_wrong_or_fixture_policy(fault: str) -> None:
    value = binding().owner.publication().value
    assert value.meaning is not None
    meaning = value.meaning
    if fault == "missing":
        value = replace(value, meaning=None)
    elif fault == "policy_id":
        value = replace(
            value,
            meaning=replace(
                meaning,
                policy_id="wrong-policy",
                communicative_goal_catalog=replace(
                    meaning.communicative_goal_catalog, policy_id="wrong-policy"
                ),
            ),
        )
    elif fault == "revision":
        value = replace(
            value,
            meaning=replace(
                meaning,
                revision=2,
                communicative_goal_catalog=replace(
                    meaning.communicative_goal_catalog, policy_revision=2
                ),
            ),
        )
    else:
        value = replace(
            value,
            meaning=replace(meaning, self_disclosure_policy=SelfDisclosurePolicy.FACT_GROUNDED),
        )
    _, _, sources = inputs()
    with pytest.raises(SpeechSemanticContextError) as error:
        bind_speech_semantics_policy_v1(
            SpeechSemanticPolicyOwner(value), sources=sources, read_source_bindings=lambda facts: ()
        )
    assert error.value.code is (
        C.SEMANTIC_POLICY_UNAVAILABLE if fault == "missing" else C.SEMANTIC_POLICY_STALE
    )


def test_unknown_definition_is_not_inferred_or_replaced() -> None:
    with pytest.raises(SpeechSemanticContextError) as error:
        committed(binding(), "yura.communicative.unknown")
    assert error.value.code is C.SOURCE_NOT_FOUND


def test_same_owner_supplies_current_catalog_and_builder_rejects_stale() -> None:
    value = binding()
    decision = committed(value, "yura.communicative.greeting")
    built = value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    before = value.owner.publication().value
    assert before.meaning is not None
    after = replace(
        before,
        meaning=replace(
            before.meaning,
            revision=2,
            communicative_goal_catalog=replace(
                before.meaning.communicative_goal_catalog, policy_revision=2
            ),
        ),
    )
    value.owner.update(after)
    catalog, _ = value.executive_evidence.capture_speech_sources(())
    assert catalog == value.owner.catalog_view() and catalog is not None
    assert catalog.policy_revision == 2
    with pytest.raises(SpeechSemanticContextError) as error:
        value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    assert error.value.code is C.SEMANTIC_POLICY_STALE
    assert built.generation is not None
    with pytest.raises(SpeechSemanticContextError):
        built.generation.require_current()


def test_production_factory_does_not_import_test_policy() -> None:
    import app.composition.speech_semantics_policy as production_module

    assert production_module.__file__ is not None
    tree = ast.parse(Path(production_module.__file__).read_text())
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    assert all(module != "tests" and not module.startswith("tests.") for module in modules)


def test_commitment_uses_native_commitment_state_evidence() -> None:
    from app.domain.contracts.finalization import AuthorityReadPublication
    from app.domain.executive.speech_references import ExecutiveSpeechReferenceResolution
    from app.domain.goals import CommitmentState, CommitmentStatus
    from app.domain.speech_semantics import SpeechSemanticFact
    from app.domain.speech_semantics.production import (
        SourceValue,
        SpeechSemanticContextSourcePort,
        SpeechSemanticFactProjectionRule,
        SpeechSemanticSourceRegistration,
    )
    from tests.helpers.speech_bindings import OWNER

    state = CommitmentState(
        "commitment-1",
        "test-promised-action",
        None,
        ("event-1",),
        "source-decision",
        (),
        CommitmentStatus.ACTIVE,
        50,
        50,
        (),
        (),
        NOW,
        NOW,
        5,
        semantic_commitment_spec=semantic_spec("test-promised-action"),
    )

    def read(identity: str) -> AuthorityReadPublication[SourceValue] | None:
        return (
            AuthorityReadPublication(state, (OWNER.participant.token(),))
            if identity == state.commitment_id
            else None
        )

    def project(
        source: SourceValue, resolution: ExecutiveSpeechReferenceResolution
    ) -> SpeechSemanticFact:
        assert isinstance(source, CommitmentState)
        return SpeechSemanticFact(
            resolution.selected_ref,
            SpeechSemanticFactKind.GENERAL,
            source.commitment_id,
            "test-commitment-status",
            source.status.value,
        )

    test_policies = policies()
    projection = replace(
        test_policies.projection,
        rules=(
            SpeechSemanticFactProjectionRule(
                Contract.COMMITMENT, project, lambda value: isinstance(value, CommitmentState)
            ),
        ),
    )
    owner = build_speech_semantics_policy_owner_v1(
        projection=projection, truth=test_policies.truth, bounds_policy=BOUNDS
    )
    port = SpeechSemanticContextSourcePort(
        (SpeechSemanticSourceRegistration("test-speech-source", Contract.COMMITMENT, read),)
    )
    value = bind_speech_semantics_policy_v1(
        owner, sources=port, read_source_bindings=lambda facts: snapshot().speech_source_bindings
    )
    decision = committed(value, "yura.communicative.commitment", ("commitment-1",))
    built = value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    assert len(built.facts) == 2
    act = next(f for f in built.facts if f.kind is SpeechSemanticFactKind.DISCOURSE)
    assert act.value == {"kind": "commitment"}
    assert act.evidence_refs == ("commitment-1",)
    assert (
        next(p for p in built.fact_provenance if p.fact_id == "commitment-1").source_contract
        == Contract.COMMITMENT.value
    )


def test_later_missing_policy_never_becomes_implicit_default() -> None:
    value = binding()
    decision = committed(value, "yura.communicative.greeting")
    value.owner.update(replace(value.owner.publication().value, meaning=None))
    assert value.executive_evidence.capture_speech_sources(())[0] is None
    with pytest.raises(SpeechSemanticContextError) as error:
        value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    assert error.value.code is C.SEMANTIC_POLICY_UNAVAILABLE


def test_v1_forbids_candidate_self_disclosure_even_when_grounded() -> None:
    value = binding()
    decision = committed(value, "yura.communicative.greeting")
    built = value.context_builder.build(decision, "intent-speech", captured_at=NOW)
    proposed = replace(
        speech_candidate(built, 0, 0), self_disclosure=SelfDisclosurePolicy.FACT_GROUNDED
    )
    with pytest.raises(ValueError):
        SpeechSemanticAuthority().commit(
            proposed,
            built,
            current_revisions=built.revisions,
            plan_id="forbidden",
            committed_at=NOW,
        )

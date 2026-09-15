"""#661の試験専用方針で、実値を採用せずproduction機構を検証する。"""

from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.finalization import AuthorityReadPublication
from app.domain.executive.contracts import (
    CommittedExecutiveDecision,
    ExecutiveBoundsProvenance,
    ExecutiveFactKind,
    ExecutiveFactRef,
    SpeechIntentPayload,
)
from app.domain.executive.speech_references import (
    ExecutiveSpeechReferenceResolution,
    ExecutiveSpeechSourceBinding,
    resolve_speech_references,
)
from app.domain.executive.speech_references import ExecutiveSpeechReferenceRole as Role
from app.domain.executive.speech_references import ExecutiveSpeechResolutionKind as Kind
from app.domain.goals import GoalKind, GoalState, GoalStatus, InterruptionPolicy
from app.domain.goals.semantic_views import GoalCommitmentSemanticView
from app.domain.speech_semantics.contracts import SpeechSemanticFact, SpeechTruthConstraint
from app.domain.speech_semantics.production import (
    SourceValue,
    SpeechSemanticConstraintSource,
    SpeechSemanticContextBuilder,
    SpeechSemanticContextSourcePort,
    SpeechSemanticFactProjectionPolicy,
    SpeechSemanticFactProjectionRule,
    SpeechSemanticPolicyOwner,
    SpeechSemanticProductionPolicies,
    SpeechSemanticSourceRegistration,
    SpeechTruthConstraintProjectionPolicy,
    SpeechTruthConstraintProjectionRule,
)
from app.domain.speech_semantics_vocabulary import (
    CommunicativeActDefinition,
    CommunicativeActKind,
    CommunicativeEvidenceRequirement,
    CommunicativeSemanticShape,
    CommunicativeSubjectBinding,
    CommunicativeTargetMode,
    CommunicativeTargetRequirement,
    SemanticCertainty,
    SemanticClaimKind,
    SemanticPolarity,
    SpeechSemanticContextError,
    SpeechSemanticFactKind,
    SpeechTruthRule,
    require_meaning_policy,
)
from app.domain.speech_semantics_vocabulary import SpeechSemanticContextFailureCode as C
from app.domain.speech_semantics_vocabulary import SpeechSourceContractKind as Contract
from tests.domain.executive.test_executive import NOW, candidate, live_state, snapshot
from tests.domain.speech_semantics.policy_fixture import explicit_meaning_policy
from tests.domain.speech_semantics.test_speech_semantics import candidate as semantic_candidate
from tests.domain.speech_semantics.test_speech_semantics import context, policy
from tests.helpers.goal_semantics import semantic_spec
from tests.helpers.speech_bindings import OWNER


def definition() -> CommunicativeActDefinition:
    return CommunicativeActDefinition(
        "test-act",
        1,
        CommunicativeActKind.GRATITUDE,
        CommunicativeSemanticShape(
            "speaker",
            "test-gratitude",
            True,
            SemanticPolarity.AFFIRM,
            SemanticCertainty.CERTAIN,
            None,
            SemanticClaimKind.GENERAL,
            CommunicativeSubjectBinding.TARGET,
            None,
        ),
        CommunicativeTargetRequirement(CommunicativeTargetMode.REQUIRED, (Contract.GOAL,)),
        CommunicativeEvidenceRequirement((Contract.GOAL,), 1),
    )


def project_goal(
    value: SourceValue, resolution: ExecutiveSpeechReferenceResolution
) -> SpeechSemanticFact:
    assert isinstance(value, GoalCommitmentSemanticView)
    return SpeechSemanticFact(
        resolution.selected_ref,
        SpeechSemanticFactKind.GENERAL,
        value.state_id,
        "test-goal-status",
        value.lifecycle_status.value,
        polarity=SemanticPolarity.AFFIRM,
        certainty=SemanticCertainty.CERTAIN,
    )


def matches_goal(value: SourceValue) -> bool:
    return isinstance(value, GoalCommitmentSemanticView)


def policies() -> SpeechSemanticProductionPolicies:
    meaning = explicit_meaning_policy()
    meaning = replace(
        meaning,
        communicative_goal_catalog=replace(
            meaning.communicative_goal_catalog, definitions=(definition(),)
        ),
    )
    projection = SpeechSemanticFactProjectionPolicy(
        "test-projection",
        1,
        (SpeechSemanticFactProjectionRule(Contract.GOAL, project_goal, matches_goal),),
    )
    truth = SpeechTruthConstraintProjectionPolicy(
        "test-projection",
        1,
        tuple(
            SpeechTruthConstraintProjectionRule(
                kind,
                SemanticClaimKind.GENERAL,
                None,
                SemanticPolarity.AFFIRM,
                SemanticCertainty.CERTAIN,
                SpeechTruthRule.REQUIRE_MATCH,
            )
            for kind in (SpeechSemanticFactKind.GENERAL, SpeechSemanticFactKind.DISCOURSE)
        ),
    )
    return SpeechSemanticProductionPolicies(meaning, projection, truth, BOUNDS)


def inputs() -> tuple[
    CommittedExecutiveDecision, SpeechSemanticPolicyOwner, SpeechSemanticContextSourcePort
]:
    owner = SpeechSemanticPolicyOwner(policies())
    base = snapshot()
    source = ExecutiveSpeechSourceBinding(
        "goal-1",
        Kind.UPSTREAM_FACT,
        "test-speech-source",
        Contract.GOAL,
        "goal-1",
        5,
        "goal-1",
        ExecutiveFactKind.GOAL,
        5,
        (OWNER.participant.token(),),
    )
    constraint_source = ExecutiveSpeechSourceBinding(
        "test-constraint",
        Kind.TYPED_CONSTRAINT,
        "test-speech-source",
        Contract.TRUTH_CONSTRAINT,
        "test-constraint",
        1,
        source_tokens=(OWNER.participant.token(),),
    )
    bindings = (source, constraint_source)
    captured = replace(
        base, communicative_goal_catalog=owner.catalog_view(), speech_source_bindings=bindings
    )
    intent = replace(
        candidate().intents[0],
        payload=SpeechIntentPayload("test-act", "goal-1", ("test-constraint",)),
        evidence_refs=("goal-1",),
        forbidden_claim_refs=("goal-1",),
    )
    proposed = replace(candidate(), intents=(intent,))
    current = replace(
        live_state(),
        communicative_goal_catalog=owner.catalog_view(),
        speech_source_bindings=bindings,
    )
    resolutions = resolve_speech_references(proposed, captured, current)
    committed = CommittedExecutiveDecision(
        "test-committed",
        proposed,
        (),
        NOW,
        ExecutiveBoundsProvenance.from_policy(BOUNDS),
        speech_reference_resolutions=resolutions,
    )
    goal = GoalState(
        "goal-1",
        GoalKind.SOCIAL,
        "semantic",
        None,
        "test-decision",
        GoalStatus.ACTIVE,
        50,
        (),
        (),
        (),
        (),
        InterruptionPolicy.PROTECTED,
        NOW,
        NOW,
        5,
        semantic_goal_spec=semantic_spec("semantic"),
    )
    constraint = SpeechSemanticConstraintSource(
        "test-constraint",
        1,
        SpeechTruthConstraint("test-constraint", "goal-1", SpeechTruthRule.REQUIRE_MATCH),
    )
    values: dict[str, SourceValue] = {
        "goal-1": GoalCommitmentSemanticView(goal),
        "test-constraint": constraint,
    }

    def read(identity: str) -> AuthorityReadPublication[SourceValue] | None:
        value = values.get(identity)
        return (
            None if value is None else AuthorityReadPublication(value, (OWNER.participant.token(),))
        )

    port = SpeechSemanticContextSourcePort(
        tuple(
            SpeechSemanticSourceRegistration("test-speech-source", kind, read)
            for kind in (Contract.GOAL, Contract.TRUTH_CONSTRAINT)
        )
    )
    return committed, owner, port


def test_all_roles_build_without_original_snapshot_and_preserve_provenance() -> None:
    decision, owner, port = inputs()
    assert tuple(r.role for r in decision.speech_reference_resolutions) == tuple(Role)
    built = SpeechSemanticContextBuilder(port, owner.publication).build(
        decision, "intent-speech", captured_at=NOW
    )
    act = next(f for f in built.facts if f.kind is SpeechSemanticFactKind.DISCOURSE)
    assert act.subject_ref == "goal-1"
    assert act.evidence_refs == ("goal-1",)
    provenance = next(p for p in built.fact_provenance if p.fact_id == "test-act")
    assert (provenance.definition_ref, provenance.source_revision, provenance.target_ref) == (
        "test-act",
        1,
        "goal-1",
    )
    assert built.truth_constraints[0].constraint_id == "test-constraint"
    assert built.generation is not None
    built.generation.require_current()


@pytest.mark.parametrize("fault", ["missing", "duplicate", "extra"])
def test_exact_resolution_keys_reject(fault: str) -> None:
    decision, owner, port = inputs()
    refs = decision.speech_reference_resolutions
    changed = (
        refs[:-1]
        if fault == "missing"
        else refs + ((refs[0] if fault == "duplicate" else replace(refs[0], intent_id="other")),)
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        SpeechSemanticContextBuilder(port, owner.publication).build(
            replace(decision, speech_reference_resolutions=changed),
            "intent-speech",
            captured_at=NOW,
        )
    assert error.value.code is C.SOURCE_IDENTITY_MISMATCH


@pytest.mark.parametrize(
    "fault,code",
    [
        ("missing", C.SEMANTIC_POLICY_UNAVAILABLE),
        ("projection", C.UNSUPPORTED_PROJECTION),
        ("truth", C.TRUTH_RULE_UNRESOLVED),
    ],
)
def test_missing_mechanism_rejects(fault: str, code: C) -> None:
    decision, _, port = inputs()
    value = policies()
    if fault == "missing":
        value = replace(value, meaning=None)
    elif fault == "projection":
        value = replace(value, projection=replace(value.projection, rules=()))
    else:
        value = replace(value, truth=replace(value.truth, rules=()))
    owner = SpeechSemanticPolicyOwner(value)
    with pytest.raises(SpeechSemanticContextError) as error:
        SpeechSemanticContextBuilder(port, owner.publication).build(
            decision, "intent-speech", captured_at=NOW
        )
    assert error.value.code is code


def test_unsupported_source_and_stale_revision_reject() -> None:
    decision, _, port = inputs()
    resolution = decision.speech_reference_resolutions[1]
    with pytest.raises(SpeechSemanticContextError) as error:
        SpeechSemanticContextSourcePort(()).resolve(resolution)
    assert error.value.code is C.UNSUPPORTED_SOURCE_CONTRACT
    assert resolution.source is not None
    stale = replace(
        resolution, source=replace(resolution.source, source_revision=6, fact_revision=6)
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        port.resolve(stale)
    assert error.value.code is C.SOURCE_REVISION_MISMATCH


def test_policy_change_invalidates_built_generation() -> None:
    decision, owner, port = inputs()
    built = SpeechSemanticContextBuilder(port, owner.publication).build(
        decision, "intent-speech", captured_at=NOW
    )
    owner.update(replace(policies(), meaning=None))
    assert built.generation is not None
    with pytest.raises(SpeechSemanticContextError) as error:
        built.generation.require_current()
    assert error.value.code is C.CONTEXT_STALE


@pytest.mark.parametrize("value", [True, -1])
def test_meaning_budget_rejects_invalid_integer(value: int) -> None:
    with pytest.raises(ValueError):
        replace(explicit_meaning_policy(), max_question_budget=value)


def test_explicit_empty_is_not_missing_and_immutable() -> None:
    explicit = explicit_meaning_policy()
    assert require_meaning_policy(explicit, BOUNDS) is explicit
    with pytest.raises(FrozenInstanceError):
        setattr(explicit, "revision", 2)  # noqa: B010
    with pytest.raises(SpeechSemanticContextError) as error:
        require_meaning_policy(None, BOUNDS)
    assert error.value.code is C.SEMANTIC_POLICY_UNAVAILABLE
    with pytest.raises(SpeechSemanticContextError):
        replace(explicit, max_question_budget=17).validate_bounds(BOUNDS)


@pytest.mark.parametrize("field,value", [("policy_id", ""), ("revision", True), ("revision", -1)])
def test_meaning_identifier_revision_validation(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        if field == "policy_id":
            replace(explicit_meaning_policy(), policy_id=cast(str, value))
        else:
            replace(explicit_meaning_policy(), revision=cast(int, value))


@pytest.mark.parametrize("fault", ["count", "definition_bytes", "catalog_bytes", "stale_bounds"])
def test_catalog_limits_and_generation(fault: str) -> None:
    value = policies().meaning
    assert value is not None
    catalog = value.communicative_goal_catalog
    bounds = BOUNDS
    if fault == "count":
        catalog = replace(
            catalog,
            definitions=tuple(replace(definition(), definition_id=f"test-{n}") for n in range(65)),
        )
    elif fault == "definition_bytes":
        catalog = replace(
            catalog,
            definitions=(
                replace(
                    definition(),
                    semantic_shape=replace(definition().semantic_shape, value="あ" * 4096),
                ),
            ),
        )
    elif fault == "catalog_bytes":
        bounds = replace(
            bounds,
            communicative_catalog=replace(bounds.communicative_catalog, max_catalog_json_bytes=10),
        )
    else:
        bounds = replace(bounds, policy_revision=bounds.policy_revision + 1)
    with pytest.raises(SpeechSemanticContextError) as error:
        catalog.validate_bounds(bounds)
    assert error.value.code is (C.CONTEXT_STALE if fault == "stale_bounds" else C.CONTEXT_TOO_LARGE)


def test_missing_policy_cannot_build_request_or_plan() -> None:
    from app.domain.speech_semantics.authority import SpeechSemanticAuthority
    from app.domain.speech_semantics.planner import build_request

    with pytest.raises(SpeechSemanticContextError) as error:
        build_request(
            context(),
            request_id="test",
            trace_id="test",
            created_at=NOW,
            policy=replace(policy(), meaning_policy=None),
        )
    assert error.value.code is C.SEMANTIC_POLICY_UNAVAILABLE
    with pytest.raises(SpeechSemanticContextError) as error:
        SpeechSemanticAuthority().commit(
            semantic_candidate(),
            replace(context(), meaning_policy=None),
            current_revisions=context().revisions,
            plan_id="test",
            committed_at=NOW,
        )
    assert error.value.code is C.SEMANTIC_POLICY_UNAVAILABLE


def test_payload_never_supplies_missing_source() -> None:
    proposed = candidate()
    captured = replace(
        snapshot(),
        speech_source_bindings=(),
        facts=tuple(
            replace(f, payload={"source_owner": "invented", "kind": "goal", "revision": f.revision})
            for f in snapshot().facts
        ),
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        resolve_speech_references(proposed, captured, live_state())
    assert error.value.code is C.SOURCE_NOT_FOUND


def test_executive_schema_versions_and_context_byte_bound() -> None:
    from app.domain.executive.deliberator import INPUT_SCHEMA, OUTPUT_SCHEMA, build_request
    from app.domain.executive.speech_references import ExecutiveContextError
    from tests.domain.executive.test_executive import policy as executive_policy

    assert INPUT_SCHEMA == "executive.context.v2"
    assert OUTPUT_SCHEMA == "executive.candidate.v2"
    limits = replace(BOUNDS, executive=replace(BOUNDS.executive, max_context_json_bytes=10))
    with pytest.raises(ExecutiveContextError):
        build_request(
            snapshot(),
            request_id="test",
            trace_id="test",
            created_at=NOW,
            policy=replace(executive_policy(), bounds=limits),
        )


def test_provenance_cannot_be_removed_or_revised() -> None:
    decision, owner, port = inputs()
    built = SpeechSemanticContextBuilder(port, owner.publication).build(
        decision, "intent-speech", captured_at=NOW
    )
    for entries in (
        (),
        built.fact_provenance + (built.fact_provenance[0],),
        (replace(built.fact_provenance[0], source_revision=999),) + built.fact_provenance[1:],
    ):
        with pytest.raises(SpeechSemanticContextError):
            replace(built, fact_provenance=entries)


def test_catalog_collision_stale_and_role_misuse_reject() -> None:
    _, owner, _ = inputs()
    view = owner.catalog_view()
    assert view is not None
    captured = replace(snapshot(), communicative_goal_catalog=view)
    proposed = replace(
        candidate(),
        intents=(replace(candidate().intents[0], payload=SpeechIntentPayload("test-act")),),
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        resolve_speech_references(proposed, captured, live_state())
    assert error.value.code is C.SEMANTIC_POLICY_STALE
    collision = replace(
        captured,
        facts=captured.facts + (ExecutiveFactRef("test-act", ExecutiveFactKind.GOAL, 1, {}),),
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        resolve_speech_references(
            proposed, collision, replace(live_state(), communicative_goal_catalog=view)
        )
    assert error.value.code is C.SOURCE_IDENTITY_MISMATCH
    decision, _, _ = inputs()
    with pytest.raises(ValueError):
        replace(decision.speech_reference_resolutions[0], role=Role.TARGET)


def test_source_change_during_projection_rejects() -> None:
    decision, _, port = inputs()
    value = policies()

    def mutate(
        value: SourceValue, resolution: ExecutiveSpeechReferenceResolution
    ) -> SpeechSemanticFact:
        with OWNER.participant.mutation():
            pass
        return project_goal(value, resolution)

    owner = SpeechSemanticPolicyOwner(
        replace(
            value,
            projection=replace(
                value.projection,
                rules=(SpeechSemanticFactProjectionRule(Contract.GOAL, mutate, matches_goal),),
            ),
        )
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        SpeechSemanticContextBuilder(port, owner.publication).build(
            decision, "intent-speech", captured_at=NOW
        )
    assert error.value.code is C.CONTEXT_STALE


def test_kind_binding_mismatch_and_ambiguous_truth_reject() -> None:
    decision, owner, port = inputs()
    source = decision.speech_reference_resolutions[1].source
    assert source is not None
    with pytest.raises(SpeechSemanticContextError) as error:
        replace(source, fact_kind=ExecutiveFactKind.MEMORY_EVIDENCE)
    assert error.value.code is C.SOURCE_KIND_MISMATCH
    value = owner.publication().value
    owner = SpeechSemanticPolicyOwner(
        replace(value, truth=replace(value.truth, rules=value.truth.rules * 2))
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        SpeechSemanticContextBuilder(port, owner.publication).build(
            decision, "intent-speech", captured_at=NOW
        )
    assert error.value.code is C.TRUTH_RULE_UNRESOLVED


def test_projection_ambiguous_and_constraint_fact_identity() -> None:
    decision, owner, port = inputs()
    value = owner.publication().value
    ambiguous = SpeechSemanticPolicyOwner(
        replace(value, projection=replace(value.projection, rules=value.projection.rules * 2))
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        SpeechSemanticContextBuilder(port, ambiguous.publication).build(
            decision, "intent-speech", captured_at=NOW
        )
    assert error.value.code is C.UNSUPPORTED_PROJECTION
    intent = decision.candidate.intents[0]
    changed = replace(intent, payload=SpeechIntentPayload("test-act", "goal-1", ("goal-1",)))
    resolutions = decision.speech_reference_resolutions
    replacement = replace(resolutions[1], role=Role.CONSTRAINT)
    decision = replace(
        decision,
        candidate=replace(decision.candidate, intents=(changed,)),
        speech_reference_resolutions=resolutions[:-1] + (replacement,),
    )
    built = SpeechSemanticContextBuilder(port, owner.publication).build(
        decision, "intent-speech", captured_at=NOW
    )
    assert built.truth_constraints[0].constraint_id == "goal-1"
    assert built.truth_constraints[0].fact_ref == "goal-1"


def test_explicit_directive_commits_and_updated_generation_cannot_commit() -> None:
    from app.domain.speech_semantics.authority import SpeechSemanticAuthority
    from app.domain.speech_semantics.contracts import (
        DeterministicSpeechDirective,
        SpeechProposition,
        SpeechPropositionDisposition,
        SpeechSemanticContextSnapshot,
    )
    from app.domain.speech_semantics.planner import candidate_from_directive
    from app.domain.speech_semantics.production import SpeechDeterministicDirectivePolicy
    from tests.helpers.executive_requirements import fence_clock

    decision, owner, port = inputs()
    decision = replace(
        decision,
        candidate=replace(
            decision.candidate,
            intents=(replace(decision.candidate.intents[0], forbidden_claim_refs=()),),
        ),
        speech_reference_resolutions=tuple(
            r for r in decision.speech_reference_resolutions if r.role is not Role.FORBIDDEN_CLAIM
        ),
    )

    def directive(snapshot: SpeechSemanticContextSnapshot) -> DeterministicSpeechDirective:
        return DeterministicSpeechDirective(
            tuple(
                SpeechProposition(
                    "test-" + f.fact_id,
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
                for f in snapshot.facts
            ),
            snapshot.self_disclosure_policy,
            snapshot.max_question_budget,
            snapshot.max_new_direction_budget,
            tuple(c.constraint_id for c in snapshot.truth_constraints),
            (),
            (),
        )

    value = replace(
        owner.publication().value,
        directive=SpeechDeterministicDirectivePolicy("test-directive", 1, directive),
    )
    owner = SpeechSemanticPolicyOwner(value)
    built = SpeechSemanticContextBuilder(port, owner.publication).build(
        decision, "intent-speech", captured_at=NOW
    )
    assert built.deterministic_directive is not None
    proposed = candidate_from_directive(
        built, built.deterministic_directive, candidate_id="test-semantic", created_at=NOW
    )
    authority = SpeechSemanticAuthority()
    with fence_clock(lambda: NOW):
        plan = authority.commit(
            proposed,
            built,
            current_revisions=built.revisions,
            plan_id="test-plan",
            committed_at=NOW,
        )
    assert plan.plan_id == "test-plan"
    owner.update(replace(value, meaning=None))
    authority = SpeechSemanticAuthority()
    with pytest.raises(SpeechSemanticContextError) as error:
        authority.commit(
            proposed,
            built,
            current_revisions=built.revisions,
            plan_id="test-stale",
            committed_at=NOW,
        )
    assert error.value.code is C.CONTEXT_STALE
    assert authority.snapshot("test-stale") is None


def test_removed_meaning_and_definition_generation_cannot_be_rewritten() -> None:
    owner = SpeechSemanticPolicyOwner(policies())
    value = owner.publication().value
    owner.update(replace(value, meaning=None))
    assert value.meaning is not None
    with pytest.raises(ValueError):
        owner.update(replace(value, meaning=replace(value.meaning, max_question_budget=0)))
    changed_catalog = replace(
        value.meaning.communicative_goal_catalog,
        policy_revision=2,
        definitions=(
            replace(
                definition(),
                semantic_shape=replace(definition().semantic_shape, predicate="changed"),
            ),
        ),
    )
    with pytest.raises(ValueError):
        owner.update(
            replace(
                value,
                meaning=replace(
                    value.meaning, revision=2, communicative_goal_catalog=changed_catalog
                ),
            )
        )

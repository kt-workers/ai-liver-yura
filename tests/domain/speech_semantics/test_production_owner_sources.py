"""採用済みV1 matrix、実Owner captureと改変拒否を検証する。"""

from dataclasses import replace
from typing import Any, cast

import pytest

from app.composition.speech_semantics_policy import bind_speech_semantics_policy_v1
from app.composition.speech_semantics_sources import (
    ProductionSpeechSources,
    SpeechOwnerSourceRegistration,
    build_projection_v1,
    build_truth_v1,
)
from app.domain.activity_execution.authority import ActivityExecutionAuthority
from app.domain.contracts import ExecutionResult, ExecutionStatus
from app.domain.contracts.common import JsonValue
from app.domain.contracts.finalization import AuthorityReadPublication
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity, SemanticSubjectKind
from app.domain.executive.contracts import ExecutiveFactKind, ExecutiveFactRef
from app.domain.executive.speech_references import ExecutiveSpeechReferenceResolution
from app.domain.executive.speech_references import ExecutiveSpeechReferenceRole as Role
from app.domain.executive.speech_references import ExecutiveSpeechResolutionKind as Kind
from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticPolarity,
    GoalCommitmentSemanticSubjectKind,
)
from app.domain.goals import CommitmentStatus, GoalState, GoalStatus
from app.domain.goals.store import GoalCommitmentStore
from app.domain.memory import (
    MemoryAssertionCertainty,
    MemoryAssertionPolarity,
    MemoryAssertionSemantics,
    MemoryAssertionTemporalMeaning,
    MemoryWriteRequest,
)
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from app.domain.memory.semantic_assertions import MemorySemanticAssertionUnavailableReason as R
from app.domain.speech_semantics.production import (
    SpeechSemanticFactProjector,
    SpeechSemanticSourceBinding,
)
from app.domain.speech_semantics_vocabulary import SpeechSemanticContextError
from app.domain.speech_semantics_vocabulary import SpeechSemanticContextFailureCode as C
from app.domain.speech_semantics_vocabulary import SpeechSemanticFactKind as F
from app.domain.speech_semantics_vocabulary import SpeechSourceContractKind as K
from app.domain.speech_semantics_vocabulary import SpeechTruthRule as T
from tests.domain.activity_execution.test_activity_execution import started
from tests.domain.executive.test_executive import NOW, snapshot
from tests.domain.memory.test_memory_store_retrieval import authority, candidate
from tests.helpers.speech_production import (
    IDENTITY,
    InMemorySpeechMemory,
    memory_owner,
    production_sources,
)
from tests.system_integration.test_speech_semantics_policy import binding, committed


async def resolution(
    sources: ProductionSpeechSources, fact: ExecutiveFactRef
) -> ExecutiveSpeechReferenceResolution:
    source = (await sources.capture((fact,)))[0]
    return ExecutiveSpeechReferenceResolution(
        "intent-speech", Role.EVIDENCE, fact.fact_id, Kind.UPSTREAM_FACT, source
    )


@pytest.mark.parametrize(
    "kind,status", [(K.GOAL, s) for s in GoalStatus] + [(K.COMMITMENT, s) for s in CommitmentStatus]
)
@pytest.mark.parametrize(
    "subject", [GoalCommitmentSemanticSubjectKind.SELF, GoalCommitmentSemanticSubjectKind.REFERENCE]
)
@pytest.mark.asyncio
async def test_goal_commitment_exact_envelope(
    kind: K, status: GoalStatus | CommitmentStatus, subject: GoalCommitmentSemanticSubjectKind
) -> None:
    sources = production_sources()
    old = sources._goals.snapshot()
    if kind is K.GOAL:
        state = old.goals[0]
        spec = replace(
            state.semantic_goal_spec,
            subject_kind=subject,
            subject_ref=None if subject is GoalCommitmentSemanticSubjectKind.SELF else "yura",
            polarity=GoalCommitmentSemanticPolarity.NEGATE,
            degree=0.4,
        )
        new = replace(
            old, goals=(replace(state, status=cast(GoalStatus, status), semantic_goal_spec=spec),)
        )
        fact = ExecutiveFactRef("goal-1", ExecutiveFactKind.GOAL, 5, {})
    else:
        c = old.commitments[0]
        spec = replace(
            c.semantic_commitment_spec,
            subject_kind=subject,
            subject_ref=None if subject is GoalCommitmentSemanticSubjectKind.SELF else "yura",
            polarity=GoalCommitmentSemanticPolarity.NEGATE,
            degree=0.4,
        )
        new = replace(
            old,
            commitments=(
                replace(c, status=cast(CommitmentStatus, status), semantic_commitment_spec=spec),
            ),
        )
        fact = ExecutiveFactRef("commitment-1", ExecutiveFactKind.COMMITMENT, 5, {})
    sources._goals = GoalCommitmentStore(new)
    r = await resolution(sources, fact)
    projected = SpeechSemanticFactProjector(build_projection_v1(IDENTITY)).project(
        await sources.acquire(r)
    )
    assert projected.kind is (
        F.SELF if subject is GoalCommitmentSemanticSubjectKind.SELF else F.GENERAL
    )
    assert projected.subject_ref == (
        IDENTITY.self_subject_ref if subject is GoalCommitmentSemanticSubjectKind.SELF else "yura"
    )
    assert projected.value == {
        "modality": "goal" if kind is K.GOAL else "commitment",
        "lifecycle_status": status.value,
        "semantic_predicate": spec.predicate,
        "semantic_value": spec.value,
        "semantic_polarity": spec.polarity.value,
        "semantic_degree": 0.4,
    }
    assert projected.predicate == "goal-commitment-state" and projected.evidence_refs == ()
    assert build_truth_v1().project(projected).rule is T.REQUIRE_MATCH


@pytest.mark.parametrize("temporal", list(MemoryAssertionTemporalMeaning))
@pytest.mark.parametrize("subject_kind", list(SemanticSubjectKind))
@pytest.mark.parametrize("certainty", list(MemoryAssertionCertainty))
@pytest.mark.asyncio
async def test_memory_exact_temporal_and_typed_subject(
    temporal: MemoryAssertionTemporalMeaning,
    subject_kind: SemanticSubjectKind,
    certainty: MemoryAssertionCertainty,
) -> None:
    memory, _ = authority()
    subject = (
        IDENTITY.self_subject()
        if subject_kind is SemanticSubjectKind.SELF
        else IDENTITY.reference_subject("yura")
    )
    source = candidate(subject=subject.subject_ref)
    source = replace(
        source,
        content=replace(
            source.content,
            temporal_scope_ref="scope"
            if temporal is MemoryAssertionTemporalMeaning.TIME_BOUNDED
            else None,
            qualifiers=("second", "first"),
        ),
        subject_identity=subject,
        assertion_semantics=MemoryAssertionSemantics(
            MemoryAssertionPolarity.NEGATE, certainty, temporal
        ),
    )
    record = memory.write(MemoryWriteRequest(source)).record
    assert record is not None
    p = production_sources()
    sources = ProductionSpeechSources(
        goals=p._goals,
        memory=InMemorySpeechMemory(memory),
        execution=ActivityExecutionAuthority(),
    )
    r = await resolution(
        sources,
        ExecutiveFactRef(record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision, {}),
    )
    projected = SpeechSemanticFactProjector(build_projection_v1(IDENTITY)).project(
        await sources.acquire(r)
    )
    assert projected.kind is (F.SELF if subject_kind is SemanticSubjectKind.SELF else F.GENERAL)
    assert projected.value == {
        "semantic_value": source.content.value,
        "temporal_meaning": temporal.value,
        "temporal_scope_ref": source.content.temporal_scope_ref,
        "qualifiers": ("second", "first"),
    }
    assert projected.certainty.value == certainty.value and projected.polarity.value == "negate"
    assert build_truth_v1().project(projected).rule is T.REQUIRE_MATCH


@pytest.mark.parametrize("reason", list(R))
@pytest.mark.asyncio
async def test_all_memory_failure_mapping(reason: R, monkeypatch: pytest.MonkeyPatch) -> None:
    p = production_sources()
    sources = ProductionSpeechSources(
        goals=p._goals,
        memory=p._memory,
        execution=p._execution,
    )
    monkeypatch.setattr(
        memory_owner(p),
        "read_semantic_assertion_publication",
        lambda identity, revision: AuthorityReadPublication(
            MemorySemanticAssertionEntry("m", None, unavailable_reason=reason), ()
        ),
    )
    expected = {
        R.SOURCE_NOT_FOUND: C.SOURCE_NOT_FOUND,
        R.REVISION_STALE: C.SOURCE_REVISION_MISMATCH,
        R.FINALIZATION_UNSUPPORTED: C.UNSUPPORTED_SOURCE_CONTRACT,
        R.REPOSITORY_UNAVAILABLE: C.SOURCE_UNAVAILABLE,
    }.get(reason, C.UNSUPPORTED_PROJECTION)
    with pytest.raises(SpeechSemanticContextError) as exc:
        (await sources.capture((ExecutiveFactRef("m", ExecutiveFactKind.MEMORY_EVIDENCE, 1, {}),)))
    assert exc.value.code is expected


@pytest.mark.parametrize("status", list(ExecutionStatus))
@pytest.mark.asyncio
async def test_execution_all_status_exact(status: ExecutionStatus) -> None:
    owner, record = started()
    result = ExecutionResult(
        record.result.command_id,
        ExecutionStatus.REQUESTED,
        record.result.occurred_at,
        record.result.revisions,
    )
    if status in (
        ExecutionStatus.PLANNED,
        ExecutionStatus.STARTED,
        ExecutionStatus.OBSERVABLE,
        ExecutionStatus.APPLIED,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
    ):
        result = result.transition_to(ExecutionStatus.ACCEPTED, result.occurred_at)
    if status in (ExecutionStatus.OBSERVABLE, ExecutionStatus.APPLIED, ExecutionStatus.COMPLETED):
        result = result.transition_to(ExecutionStatus.STARTED, result.occurred_at)
    if status is not ExecutionStatus.REQUESTED:
        result = result.transition_to(status, result.occurred_at)
    record = replace(record, result=result)
    p = production_sources()
    sources = ProductionSpeechSources(
        goals=p._goals,
        memory=p._memory,
        execution=owner,
    )
    r = await resolution(
        sources,
        ExecutiveFactRef("command-1", ExecutiveFactKind.ACTIVITY, record.record_revision, {}),
    )
    projected = SpeechSemanticFactProjector(build_projection_v1(IDENTITY)).project(
        SpeechSemanticSourceBinding(r, record, r.source.source_tokens if r.source else ())
    )
    assert projected.value == status.value and projected.execution_status is status
    assert projected.subject_ref == "command-1" and projected.evidence_refs == ()
    assert build_truth_v1().project(projected).rule is (
        T.REQUIRE_MATCH if status is ExecutionStatus.COMPLETED else T.FORBID_COMPLETION_CLAIM
    )


@pytest.mark.parametrize(
    "field",
    [
        "subject_ref",
        "predicate",
        "value",
        "kind",
        "polarity",
        "certainty",
        "degree",
        "evidence_refs",
    ],
)
@pytest.mark.asyncio
async def test_whole_fact_tamper_rejected(field: str) -> None:
    from app.domain.speech_semantics_vocabulary import SemanticCertainty, SemanticPolarity

    b = binding()
    d = await committed(b, "yura.communicative.gratitude", ("goal-1",))
    ctx = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    f = ctx.facts[0]
    changes: dict[str, Any] = {
        "subject_ref": "tamper",
        "predicate": "tamper",
        "value": False,
        "kind": F.GENERAL,
        "polarity": SemanticPolarity.NEGATE,
        "certainty": SemanticCertainty.LIKELY,
        "degree": 0.4,
        "evidence_refs": ("goal-1",),
    }
    assert getattr(f, field) != changes[field]
    with pytest.raises(SpeechSemanticContextError):
        replace(ctx, facts=(replace(f, **{field: changes[field]}), *ctx.facts[1:]))


@pytest.mark.asyncio
async def test_act_and_truth_tamper_rejected() -> None:
    b = binding()
    d = await committed(b, "yura.communicative.gratitude", ("goal-1",))
    ctx = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    with pytest.raises(SpeechSemanticContextError):
        replace(ctx, facts=(*ctx.facts[:-1], replace(ctx.facts[-1], value={"kind": "apology"})))
    with pytest.raises(SpeechSemanticContextError):
        replace(
            ctx,
            truth_constraints=(
                replace(ctx.truth_constraints[0], constraint_id="tamper"),
                *ctx.truth_constraints[1:],
            ),
        )


@pytest.mark.asyncio
async def test_actual_capture_rejects_stale_and_dto_self_proof() -> None:
    p = production_sources()
    facts = tuple(f for f in snapshot().facts if f.fact_id in ("goal-1", "commitment-1"))
    first = await p.capture(facts)
    assert first == (await p.capture(facts))
    r = ExecutiveSpeechReferenceResolution(
        "intent-speech", Role.EVIDENCE, first[0].selected_ref, Kind.UPSTREAM_FACT, first[0]
    )
    assert (await p.acquire(r)).tokens == first[0].source_tokens
    with p._goals.finalization_participant.mutation():
        pass
    with pytest.raises(SpeechSemanticContextError):
        (await p.acquire(r))
    with pytest.raises(SpeechSemanticContextError):
        bind_speech_semantics_policy_v1(
            binding().owner, sources=cast(ProductionSpeechSources, object())
        )


@pytest.mark.parametrize("kind", [K.ATTENTION, K.TRUTH_CONSTRAINT])
def test_unsupported_registration(kind: K) -> None:
    p = production_sources()
    with pytest.raises(SpeechSemanticContextError) as e:
        ProductionSpeechSources(
            goals=p._goals,
            memory=p._memory,
            execution=p._execution,
            registrations=(SpeechOwnerSourceRegistration(ExecutiveFactKind.ATTENTION, kind),),
        )
    assert e.value.code is C.UNSUPPORTED_SOURCE_CONTRACT


@pytest.mark.asyncio
async def test_runtime_identity_replacement_invalidates_generation() -> None:
    b = binding()
    d = await committed(b, "yura.communicative.gratitude", ("goal-1",))
    ctx = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    policies = b.owner.publication().value
    other = RuntimeSubjectIdentity("alternate", "alternate", 1, 1)
    b.owner.update(
        replace(
            policies,
            projection=replace(build_projection_v1(other), revision=2),
            truth=replace(build_truth_v1(), revision=2),
        )
    )
    assert ctx.generation is not None
    with pytest.raises(SpeechSemanticContextError) as e:
        ctx.generation.require_current()
    assert e.value.code is C.CONTEXT_STALE


@pytest.mark.parametrize(
    "fault", ["missing_token", "raw_state", "wrong_identity", "wrong_revision"]
)
@pytest.mark.asyncio
async def test_owner_publication_faults(fault: str, monkeypatch: pytest.MonkeyPatch) -> None:
    p = production_sources()
    native = p._goals.goal_semantic_publication("goal-1")
    assert native is not None
    value = native.value
    publication: object = native
    expected = C.SOURCE_KIND_MISMATCH
    if fault == "missing_token":
        publication = AuthorityReadPublication(value, ())
        expected = C.UNSUPPORTED_SOURCE_CONTRACT
    elif fault == "raw_state":
        publication = AuthorityReadPublication(value.state, native.tokens)
    elif fault == "wrong_identity":
        publication = AuthorityReadPublication(
            replace(value, state=replace(cast(GoalState, value.state), goal_id="other")),
            native.tokens,
        )
        expected = C.SOURCE_IDENTITY_MISMATCH
    else:
        publication = AuthorityReadPublication(
            replace(value, state=replace(value.state, revision=4)), native.tokens
        )
        expected = C.SOURCE_REVISION_MISMATCH
    monkeypatch.setattr(p._goals, "goal_semantic_publication", lambda identity: publication)
    with pytest.raises(SpeechSemanticContextError) as e:
        (await p.capture((ExecutiveFactRef("goal-1", ExecutiveFactKind.GOAL, 5, {}),)))
    assert e.value.code is expected


@pytest.mark.parametrize(
    "field",
    ["modality", "lifecycle_status", "semantic_polarity", "semantic_value", "semantic_degree"],
)
@pytest.mark.asyncio
async def test_closed_goal_envelope_cannot_be_dropped_or_changed(field: str) -> None:
    from app.domain.contracts.common import thaw_json
    from app.domain.speech_semantics import SpeechSemanticAuthority
    from tests.system_integration.test_speech_semantics_policy import speech_candidate

    b = binding()
    d = await committed(b, "yura.communicative.gratitude", ("goal-1",))
    ctx = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    proposed = speech_candidate(ctx, 0, 0)
    payload = cast(dict[str, JsonValue], thaw_json(proposed.propositions[0].value))
    payload.pop(field)
    proposed = replace(
        proposed,
        propositions=(replace(proposed.propositions[0], value=payload), *proposed.propositions[1:]),
    )
    with pytest.raises(ValueError):
        SpeechSemanticAuthority().commit(
            proposed,
            ctx,
            current_revisions=ctx.revisions,
            plan_id="invalid-envelope",
            committed_at=NOW,
        )


@pytest.mark.parametrize("ref", ["yura", "alias", "first_person", "Profile", "self:runtime-test"])
@pytest.mark.asyncio
async def test_reference_strings_do_not_become_self(ref: str) -> None:
    p = production_sources()
    old = p._goals.snapshot()
    g = old.goals[0]
    spec = replace(
        g.semantic_goal_spec,
        subject_kind=GoalCommitmentSemanticSubjectKind.REFERENCE,
        subject_ref=ref,
    )
    p._goals = GoalCommitmentStore(replace(old, goals=(replace(g, semantic_goal_spec=spec),)))
    r = await resolution(p, ExecutiveFactRef("goal-1", ExecutiveFactKind.GOAL, 5, {}))
    fact = SpeechSemanticFactProjector(build_projection_v1(IDENTITY)).project(await p.acquire(r))
    assert fact.kind is F.GENERAL and fact.subject_ref == ref


@pytest.mark.asyncio
async def test_reference_to_reserved_self_is_rejected() -> None:
    p = production_sources()
    old = p._goals.snapshot()
    g = old.goals[0]
    spec = replace(
        g.semantic_goal_spec,
        subject_kind=GoalCommitmentSemanticSubjectKind.REFERENCE,
        subject_ref=IDENTITY.self_subject_ref,
    )
    p._goals = GoalCommitmentStore(replace(old, goals=(replace(g, semantic_goal_spec=spec),)))
    r = await resolution(p, ExecutiveFactRef("goal-1", ExecutiveFactKind.GOAL, 5, {}))
    with pytest.raises(SpeechSemanticContextError) as e:
        SpeechSemanticFactProjector(build_projection_v1(IDENTITY)).project(await p.acquire(r))
    assert e.value.code is C.SOURCE_IDENTITY_MISMATCH


@pytest.mark.asyncio
async def test_commitment_filters_other_evidence() -> None:
    b = binding()
    d = await committed(b, "yura.communicative.commitment", ("goal-1", "commitment-1"))
    ctx = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    act = next(f for f in ctx.facts if f.kind is F.DISCOURSE)
    assert act.evidence_refs == ("commitment-1",)
    assert {f.fact_id for f in ctx.facts} == {
        "goal-1",
        "commitment-1",
        "yura.communicative.commitment",
    }


@pytest.mark.parametrize(
    "fault",
    [
        "historical_current",
        "scope_missing",
        "qualifier_missing",
        "value_only",
        "missing_token",
        "other_runtime",
    ],
)
@pytest.mark.asyncio
async def test_memory_material_and_identity_failure_paths(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.composition.speech_semantics_policy import build_speech_semantics_policy_owner_v1
    from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
    from app.domain.contracts.common import thaw_json
    from app.domain.executive.contracts import SpeechIntentPayload
    from app.domain.speech_semantics import SpeechSemanticAuthority
    from tests.system_integration.test_speech_semantics_policy import speech_candidate

    p = production_sources()
    c = candidate(subject=IDENTITY.self_subject_ref)
    c = replace(
        c,
        subject_identity=IDENTITY.self_subject(),
        content=replace(c.content, temporal_scope_ref="known-scope", qualifiers=("q2", "q1")),
        assertion_semantics=MemoryAssertionSemantics(
            MemoryAssertionPolarity.AFFIRM,
            MemoryAssertionCertainty.CERTAIN,
            MemoryAssertionTemporalMeaning.HISTORICAL,
        ),
    )
    record = memory_owner(p).write(MemoryWriteRequest(c)).record
    assert record is not None
    sources = ProductionSpeechSources(
        goals=p._goals,
        memory=p._memory,
        execution=p._execution,
    )
    r = await resolution(
        sources,
        ExecutiveFactRef(record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision, {}),
    )
    if fault == "missing_token":
        pub = memory_owner(p).read_semantic_assertion_publication(record.memory_id, record.revision)
        monkeypatch.setattr(
            memory_owner(p),
            "read_semantic_assertion_publication",
            lambda identity, revision: replace(pub, tokens=()),
        )
        with pytest.raises(SpeechSemanticContextError) as e:
            (await sources.acquire(r))
        assert e.value.code is C.UNSUPPORTED_SOURCE_CONTRACT
        return
    identity = (
        RuntimeSubjectIdentity("other-app", "other-app", 1, 1)
        if fault == "other_runtime"
        else IDENTITY
    )
    b = bind_speech_semantics_policy_v1(
        build_speech_semantics_policy_owner_v1(
            runtime_subject_identity=identity, bounds_policy=BOUNDS
        ),
        sources=sources,
    )
    d = await committed(binding(), "yura.communicative.greeting")
    intent = replace(d.candidate.intents[0], payload=SpeechIntentPayload(record.memory_id))
    d = replace(
        d,
        candidate=replace(d.candidate, intents=(intent,)),
        speech_reference_resolutions=(replace(r, role=Role.SEMANTIC_GOAL),),
    )
    if fault == "other_runtime":
        with pytest.raises(SpeechSemanticContextError) as e:
            (await b.context_builder.build_async(d, "intent-speech", captured_at=NOW))
        assert e.value.code is C.SOURCE_IDENTITY_MISMATCH
        return
    ctx = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    proposed = speech_candidate(ctx, 0, 0)
    value = cast(dict[str, JsonValue], thaw_json(ctx.facts[0].value))
    if fault == "historical_current":
        value["temporal_meaning"] = "current"
    elif fault == "scope_missing":
        value.pop("temporal_scope_ref")
    elif fault == "qualifier_missing":
        value["qualifiers"] = ()
    else:
        value = {"semantic_value": value["semantic_value"]}
    with pytest.raises(SpeechSemanticContextError):
        replace(ctx, facts=(replace(ctx.facts[0], value=value),))
    proposed = replace(proposed, propositions=(replace(proposed.propositions[0], value=value),))
    with pytest.raises(ValueError):
        SpeechSemanticAuthority().commit(
            proposed,
            ctx,
            current_revisions=ctx.revisions,
            plan_id="tamper-memory",
            committed_at=NOW,
        )


@pytest.mark.asyncio
async def test_all_eligible_evidence_preserves_selected_order() -> None:
    p = production_sources()
    old = p._goals.snapshot()
    c2 = replace(old.commitments[0], commitment_id="commitment-2")
    goals = GoalCommitmentStore(replace(old, commitments=(*old.commitments, c2)))
    sources = ProductionSpeechSources(
        goals=goals,
        memory=p._memory,
        execution=p._execution,
    )
    base = binding()
    b = bind_speech_semantics_policy_v1(base.owner, sources=sources)
    d = await committed(base, "yura.communicative.commitment", ("goal-1", "commitment-1"))
    selected = ("commitment-2", "goal-1", "commitment-1")
    intent = replace(d.candidate.intents[0], evidence_refs=selected)
    rs = tuple(
        [
            (
                await resolution(
                    sources,
                    ExecutiveFactRef(
                        ref,
                        ExecutiveFactKind.GOAL if ref == "goal-1" else ExecutiveFactKind.COMMITMENT,
                        5,
                        {},
                    ),
                )
            )
            for ref in selected
        ]
    )
    d = replace(
        d,
        candidate=replace(d.candidate, intents=(intent,)),
        speech_reference_resolutions=(d.speech_reference_resolutions[0], *rs),
    )
    ctx = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    act = next(f for f in ctx.facts if f.kind is F.DISCOURSE)
    assert act.evidence_refs == ("commitment-2", "commitment-1")
    assert len(ctx.facts) == 4

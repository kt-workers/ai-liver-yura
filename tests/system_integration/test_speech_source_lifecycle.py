"""起動後の動的sourceとsnapshot/current/Builderの同一性を検証する。"""

import asyncio
from dataclasses import replace

import pytest

from app.composition.speech_semantics_policy import (
    bind_speech_semantics_policy_v1,
    build_speech_semantics_policy_owner_v1,
)
from app.composition.speech_semantics_sources import ProductionSpeechSources
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.finalization import AuthorityReadPublication
from app.domain.executive import CommitmentTransitionOperation, GoalTransitionOperation
from app.domain.executive.contracts import ExecutiveFactKind as F
from app.domain.executive.contracts import ExecutiveFactRef
from app.domain.executive.speech_references import ExecutiveSpeechReferenceRole
from app.domain.goals import GoalCommitmentStore
from app.domain.memory import MemoryWriteRequest
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from app.domain.speech_semantics_vocabulary import SpeechSemanticContextError
from app.domain.speech_semantics_vocabulary import SpeechSemanticContextFailureCode as C
from app.infrastructure.persistence import PersistenceFailureCode, PersistenceOperationResult
from tests.domain.activity_execution.test_activity_execution import started
from tests.domain.executive.test_executive import NOW
from tests.domain.goals.test_goal_commitment_store import (
    commitment_transition,
    decision,
    goal_transition,
)
from tests.domain.memory.test_memory_store_retrieval import candidate
from tests.domain.memory.test_semantic_assertions import SEMANTICS
from tests.domain.speech_semantics.test_production_owner_sources import resolution
from tests.helpers.speech_production import (
    IDENTITY,
    InMemorySpeechMemory,
    memory_owner,
    production_sources,
)
from tests.system_integration.test_speech_semantics_policy import binding, committed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [F.GOAL, F.COMMITMENT, F.ACTIVITY, F.EXECUTION])
async def test_created_after_routes_is_available_only_when_selected(kind: F) -> None:
    p = production_sources()
    goals = GoalCommitmentStore()
    activity = ActivityExecutionAuthority()
    sources = ProductionSpeechSources(goals=goals, memory=p._memory, execution=activity)
    assert await sources.capture(()) == ()
    if kind in (F.GOAL, F.COMMITMENT):
        changed = goals.apply(
            decision(
                "new-source",
                0,
                goals=(goal_transition(GoalTransitionOperation.CREATE, 0),),
                commitments=(commitment_transition(CommitmentTransitionOperation.CREATE, 0),),
            )
        )
        state = changed.snapshot
        identity, revision = (
            (state.goals[0].goal_id, state.goals[0].revision)
            if kind is F.GOAL
            else (state.commitments[0].commitment_id, state.commitments[0].revision)
        )
    else:
        _, record = started(activity)
        identity, revision = record.result.command_id, record.record_revision
    # 元Ownerに存在しても、選択されるまでは公開しない。
    assert await sources.capture(()) == ()
    fact = ExecutiveFactRef(identity, kind, revision, {"unrelated": "payloadを使わない"})
    captured = await sources.capture((fact,))
    assert len(captured) == 1
    assert captured[0].source_identity == identity
    assert captured[0].source_revision == revision
    assert captured[0].source_tokens
    # routeだけを再構築してもID登録や復元操作なしで利用できる。
    restarted = ProductionSpeechSources(goals=goals, memory=p._memory, execution=activity)
    assert await restarted.capture((fact,)) == captured


@pytest.mark.asyncio
async def test_unsupported_kind_and_unselected_fact_are_not_exposed() -> None:
    p = production_sources()
    assert await p.capture((ExecutiveFactRef("goal-1", F.ATTENTION, 5, {}),)) == ()
    selected = await p.capture((ExecutiveFactRef("goal-1", F.GOAL, 5, {}),))
    assert tuple(x.fact_id for x in selected) == ("goal-1",)
    assert all(x.fact_id != "commitment-1" for x in selected)
    with pytest.raises(SpeechSemanticContextError) as error:
        await p.capture((ExecutiveFactRef("goal:goal-1", F.GOAL, 5, {}),))
    assert error.value.code is C.SOURCE_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "revision", "token", "other_identity"])
async def test_frozen_resolution_never_rescues_changed_owner(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = production_sources()
    r = await resolution(p, ExecutiveFactRef("goal-1", F.GOAL, 5, {}))
    if fault == "missing":
        monkeypatch.setattr(p._goals, "goal_semantic_publication", lambda _: None)
        expected = C.SOURCE_NOT_FOUND
    elif fault == "revision":
        p._goals.apply(
            decision(
                "new-revision", 5, goals=(goal_transition(GoalTransitionOperation.REPRIORITIZE, 5),)
            )
        )
        expected = C.SOURCE_REVISION_MISMATCH
    elif fault == "token":
        with p._goals.finalization_participant.mutation():
            pass
        expected = C.CONTEXT_STALE
    else:
        assert r.source is not None
        r = replace(r, source=replace(r.source, source_identity="commitment-1"))
        expected = C.SOURCE_IDENTITY_MISMATCH
    with pytest.raises(SpeechSemanticContextError) as error:
        await p.acquire(r)
    assert error.value.code is expected


@pytest.mark.asyncio
async def test_builder_rereads_committed_source_and_rejects_token_invalidation() -> None:
    b = binding()
    d = await committed(b, "goal-1")
    first = await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    assert first.facts[0].fact_id == "goal-1"
    with b.executive_evidence.sources._goals.finalization_participant.mutation():
        pass
    with pytest.raises(SpeechSemanticContextError) as error:
        await b.context_builder.build_async(d, "intent-speech", captured_at=NOW)
    assert error.value.code is C.CONTEXT_STALE


class DelayedMemory(InMemorySpeechMemory):
    def __init__(self, source: ProductionSpeechSources) -> None:
        super().__init__(memory_owner(source))
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.reads: list[str] = []

    async def read_semantic_assertion_publication(
        self, memory_id: str, expected_revision: int | None = None
    ) -> PersistenceOperationResult[AuthorityReadPublication[MemorySemanticAssertionEntry]]:
        self.reads.append(memory_id)
        self.entered.set()
        await self.release.wait()
        return await super().read_semantic_assertion_publication(memory_id, expected_revision)


def memory_fact(p: ProductionSpeechSources) -> ExecutiveFactRef:
    item = replace(
        candidate(),
        subject_identity=IDENTITY.reference_subject("user:1"),
        assertion_semantics=SEMANTICS,
    )
    record = memory_owner(p).write(MemoryWriteRequest(item)).record
    assert record is not None
    return ExecutiveFactRef(record.memory_id, F.MEMORY_EVIDENCE, record.revision, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "goal", "policy"])
async def test_memory_wait_allows_other_work_and_checks_earlier_generations(change: str) -> None:
    p = production_sources()
    fact = memory_fact(p)
    memory = DelayedMemory(p)
    sources = ProductionSpeechSources(goals=p._goals, memory=memory, execution=p._execution)
    owner = build_speech_semantics_policy_owner_v1(
        runtime_subject_identity=IDENTITY, bounds_policy=BOUNDS
    )
    b = bind_speech_semantics_policy_v1(owner, sources=sources)
    task = asyncio.create_task(
        b.executive_evidence.capture_speech_sources(
            (ExecutiveFactRef("goal-1", F.GOAL, 5, {}), fact)
        )
    )
    try:
        await asyncio.wait_for(memory.entered.wait(), 1)
        # 無関係な実Activityの公開が同じloop上で完了する。
        _, record = started(p._execution)
        assert record.result.command_id == "command-1" and not task.done()
        if change == "goal":
            with p._goals.finalization_participant.mutation():
                pass
        elif change == "policy":
            owner.update(owner.publication().value)
        memory.release.set()
        if change == "none":
            _, bindings = await task
            assert tuple(x.fact_id for x in bindings) == ("goal-1", fact.fact_id)
        else:
            with pytest.raises(SpeechSemanticContextError) as error:
                await task
            assert error.value.code is C.CONTEXT_STALE
        assert memory.reads == [fact.fact_id]
    finally:
        memory.release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", list(PersistenceFailureCode))
async def test_memory_persistence_failure_is_not_empty_success(
    code: PersistenceFailureCode,
) -> None:
    p = production_sources()

    class FailedMemory(InMemorySpeechMemory):
        async def read_semantic_assertion_publication(
            self, memory_id: str, expected_revision: int | None = None
        ) -> PersistenceOperationResult[AuthorityReadPublication[MemorySemanticAssertionEntry]]:
            return PersistenceOperationResult(None, code)

    sources = ProductionSpeechSources(
        goals=p._goals, memory=FailedMemory(memory_owner(p)), execution=p._execution
    )
    with pytest.raises(SpeechSemanticContextError) as error:
        await sources.capture((ExecutiveFactRef("selected-memory", F.MEMORY_EVIDENCE, 1, {}),))
    assert error.value.code is C.SOURCE_UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "goal", "policy"])
async def test_builder_rechecks_sources_across_memory_await(change: str) -> None:
    b = binding()
    p = b.executive_evidence.sources
    d = await committed(b, "goal-1")
    fact = memory_fact(p)
    selected = await resolution(p, fact)
    intent = replace(d.candidate.intents[0], evidence_refs=(fact.fact_id,))
    d = replace(
        d,
        candidate=replace(d.candidate, intents=(intent,)),
        speech_reference_resolutions=(
            *d.speech_reference_resolutions,
            replace(selected, role=ExecutiveSpeechReferenceRole.EVIDENCE),
        ),
    )
    memory = DelayedMemory(p)
    sources = ProductionSpeechSources(goals=p._goals, memory=memory, execution=p._execution)
    builder = bind_speech_semantics_policy_v1(b.owner, sources=sources).context_builder
    pending = asyncio.create_task(builder.build_async(d, "intent-speech", captured_at=NOW))
    try:
        await asyncio.wait_for(memory.entered.wait(), 1)
        assert not pending.done()
        if change == "goal":
            with p._goals.finalization_participant.mutation():
                pass
        elif change == "policy":
            b.owner.update(b.owner.publication().value)
        memory.release.set()
        if change == "none":
            result = await pending
            assert tuple(f.fact_id for f in result.facts) == ("goal-1", fact.fact_id)
        else:
            with pytest.raises(SpeechSemanticContextError) as error:
                await pending
            assert error.value.code is C.CONTEXT_STALE
        assert memory.reads == [fact.fact_id]
    finally:
        memory.release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidate", [False, True])
async def test_core_evidence_uses_public_capture_on_start_and_current(invalidate: bool) -> None:
    from tests.system_integration.test_core_executive_requirements import deliberate, production

    value = await production()
    p = production_sources()
    sources = ProductionSpeechSources(
        goals=value.core.goals, memory=p._memory, execution=p._execution
    )
    owner = build_speech_semantics_policy_owner_v1(
        runtime_subject_identity=IDENTITY, bounds_policy=BOUNDS
    )
    b = bind_speech_semantics_policy_v1(owner, sources=sources)
    value.reader._speech = b.executive_evidence
    value.port.release.clear()
    pending = asyncio.create_task(deliberate(value))
    await asyncio.wait_for(value.port.started.wait(), 1)
    if invalidate:
        with value.core.goals.finalization_participant.mutation():
            pass
    value.port.release.set()
    if invalidate:
        with pytest.raises(ValueError):
            await pending
        assert value.binding.latest_decision() is None
        assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
        return
    result = await pending
    assert result.speech_reference_resolutions
    built = await b.context_builder.build_async(result, "speak", captured_at=result.committed_at)
    assert any(f.fact_id == "goal-1" for f in built.facts)

"""振り返りの確定候補が記憶保存と検索へそのまま渡ることを確認する。"""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.memory import MemoryKind, MemoryRelationKind, MemoryWriteRequest
from app.domain.memory_reflection import MemoryCandidateProposal, ReflectionContextSnapshot
from app.subsystems.validation.contracts import Gate, LabMode, LabRunSpec, RunStatus
from app.subsystems.validation.reflection import (
    ReflectionLabCase,
    ReflectionMemorySettings,
    ReflectionMemoryWriteBinding,
    reflection_target,
)
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.domain.memory_reflection import test_memory_reflection as source_reflection
from tests.subsystems.validation import test_reflection_target as reflection
from tests.subsystems.validation.json_values import array_at, value_at
from tests.subsystems.validation.test_runtime import POLICY, PROVENANCE, spec


def initial_memory() -> MemoryWriteRequest:
    candidate = memory.candidate("existing", kind=MemoryKind.EPISODIC)
    at = source_reflection.NOW - timedelta(days=1)
    return MemoryWriteRequest(
        replace(
            candidate,
            created_at=at,
            provenance=replace(candidate.provenance, observed_at=at, recorded_at=at),
            temporal=replace(candidate.temporal, observed_at=at),
        )
    )


def setup(
    refs: tuple[str, ...],
    *,
    initial_writes: tuple[MemoryWriteRequest, ...] = (),
    write_bindings: tuple[ReflectionMemoryWriteBinding, ...] = (),
) -> tuple[ReflectionLabCase, ValidationRunner]:
    item = reflection.case()
    item = replace(
        item,
        memory=ReflectionMemorySettings(
            retrieval_policy(),
            (memory.query(memory_kinds=(MemoryKind.EPISODIC,)),),
            initial_writes,
            write_bindings,
        ),
    )
    item = replace(
        item,
        fixture=replace(
            item.fixture,
            typed_inputs=item.typed_inputs(reflection.ACCEPTANCE, reflection.OPERATIONAL),
        ),
    )

    class Proposal:
        async def propose(
            self, snapshot: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            return (source_reflection.proposal(*refs, predicate="executed_activity"),)

    target = reflection_target(
        (item,),
        Proposal(),
        reflection.Support(),
        reflection.ACCEPTANCE,
        reflection.OPERATIONAL,
        PROVENANCE,
        "1",
    )
    return item, ValidationRunner((target,), POLICY)


def run_spec(*, repeat_count: int = 1) -> LabRunSpec:
    return replace(
        spec(), target_module="reflection_memory", mode=LabMode.ADJACENT, repeat_count=repeat_count
    )


@pytest.mark.asyncio
async def test_accepted_reflection_is_written_and_retrievable_with_exact_provenance() -> None:
    item, runner = setup(("execution-1",))
    result = await runner.run(run_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    for stage in result.stage_results:
        output = stage.typed_outputs
        accepted = value_at(output, "reflection_result", "results", 0, "candidate")
        written = value_at(output, "memory", "writes", 0)
        assert value_at(written, "request", "candidate") == accepted
        assert value_at(written, "result", "disposition") == "store_new"
        retrieved = array_at(output, "memory", "retrieval", 0, "items")
        assert len(retrieved) == 1
        assert value_at(retrieved, 0, "content", "predicate") == "executed_activity"
        assert value_at(retrieved, 0, "provenance") == value_at(
            written, "result", "record", "provenance"
        )
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_rejected_reflection_never_becomes_memory() -> None:
    item, runner = setup(("unknown-source",))
    result = await runner.run(run_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "reflection_result", "results", 0, "candidate") is None
    assert value_at(output, "memory", "writes") == ()
    assert value_at(output, "memory", "retrieval", 0, "items") == ()


@pytest.mark.asyncio
async def test_adjacent_memory_evidence_cannot_be_relabelled_integrated() -> None:
    item, runner = setup(("execution-1",))
    result = await runner.run(replace(run_spec(), mode=LabMode.INTEGRATED), item.fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert result.timeline == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [MemoryRelationKind.SUPERSEDES, MemoryRelationKind.CONTRADICTS])
async def test_explicit_relation_uses_owner_revision_and_retains_candidate(
    kind: MemoryRelationKind,
) -> None:
    item, runner = setup(
        ("execution-1",),
        initial_writes=(initial_memory(),),
        write_bindings=(ReflectionMemoryWriteBinding("proposal-1", "existing", 0, kind),),
    )
    result = await runner.run(run_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    for stage in result.stage_results:
        output = stage.typed_outputs
        accepted = value_at(output, "reflection_result", "results", 0, "candidate")
        written = value_at(output, "memory", "writes", 0)
        assert value_at(written, "request", "candidate") == accepted
        assert value_at(written, "request", "expected_revision") == 0
        assert value_at(written, "result", "relation", "kind") == kind.value
        records = array_at(output, "memory", "repository", "records")
        assert len(records) == 2
        original = next(x for x in records if value_at(x, "memory_id") == "existing")
        assert value_at(original, "revision") == (1 if kind is MemoryRelationKind.SUPERSEDES else 0)
        assert len(array_at(output, "memory", "repository", "relations")) == 1
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("expected", [1, 2])
async def test_stale_relation_request_does_not_add_candidate_or_change_existing(
    expected: int,
) -> None:
    item, runner = setup(
        ("execution-1",),
        initial_writes=(initial_memory(),),
        write_bindings=(
            ReflectionMemoryWriteBinding(
                "proposal-1", "existing", expected, MemoryRelationKind.SUPERSEDES
            ),
        ),
    )
    result = await runner.run(run_spec(), item.fixture)
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "memory", "writes", 0, "result", "disposition") == "reject"
    records = array_at(output, "memory", "repository", "records")
    assert len(records) == 1 and value_at(records, 0, "revision") == 0
    assert value_at(output, "memory", "repository", "relations") == ()


@pytest.mark.asyncio
async def test_rejected_reflection_does_not_apply_configured_relation() -> None:
    item, runner = setup(
        ("unknown-source",),
        initial_writes=(initial_memory(),),
        write_bindings=(
            ReflectionMemoryWriteBinding(
                "proposal-1", "existing", 0, MemoryRelationKind.SUPERSEDES
            ),
        ),
    )
    result = await runner.run(run_spec(), item.fixture)
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "memory", "writes") == ()
    assert len(array_at(output, "memory", "repository", "records")) == 1
    assert value_at(output, "memory", "repository", "relations") == ()


def test_duplicate_binding_cannot_choose_one_silently() -> None:
    binding = ReflectionMemoryWriteBinding(
        "proposal-1", "existing", 0, MemoryRelationKind.SUPERSEDES
    )
    with pytest.raises(ValueError, match="重複"):
        setup(("execution-1",), write_bindings=(binding, binding))


@pytest.mark.asyncio
async def test_unmatched_binding_does_not_fall_back_to_unrelated_write() -> None:
    item, runner = setup(
        ("execution-1",),
        initial_writes=(initial_memory(),),
        write_bindings=(
            ReflectionMemoryWriteBinding(
                "other-proposal", "existing", 0, MemoryRelationKind.SUPERSEDES
            ),
        ),
    )
    result = await runner.run(run_spec(), item.fixture)
    assert result.status is RunStatus.HARNESS_FAILED
    assert not any(x.stage.startswith("reflection.memory_") for x in result.timeline)
    assert runner.pending_count == 0

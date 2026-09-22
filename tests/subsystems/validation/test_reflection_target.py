"""既存の振り返り判断、根拠不足による拒否、提供サービス停止と取消を確認する。"""

import asyncio
import json
from dataclasses import replace

import pytest

from app.domain.memory_reflection import (
    MemoryCandidateProposal,
    ReflectionAcceptancePolicy,
    ReflectionContextSnapshot,
    ReflectionSourceKind,
    ReflectionSupportObservation,
)
from app.subsystems.validation.contracts import Gate, RunStatus
from app.subsystems.validation.reflection import ReflectionLabCase, reflection_target
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.memory_reflection import test_memory_reflection as reflection
from tests.domain.memory_reflection.policy_fixtures import reflection_operational_policy
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec

ACCEPTANCE = ReflectionAcceptancePolicy("reflection-v1", 1)
OPERATIONAL = reflection_operational_policy()


def case() -> ReflectionLabCase:
    item = ReflectionLabCase(
        replace(FIXTURE, human_context={"situation": "実行の観測を振り返り記憶候補へ整理する"}),
        reflection.context(reflection.source("execution-1", ReflectionSourceKind.EXECUTION_FACT)),
    )
    return replace(
        item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs(ACCEPTANCE, OPERATIONAL))
    )


class Support:
    async def observe(
        self, snapshot: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
    ) -> ReflectionSupportObservation:
        return reflection.support("execution-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refs,expected",
    [
        (("execution-1",), "accepted_for_store_submission"),
        (("unknown-source",), "rejected_invalid_provenance"),
    ],
)
async def test_actual_authority_determines_candidate_status(
    refs: tuple[str, ...], expected: str
) -> None:
    class Proposal:
        async def propose(
            self, snapshot: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            return (reflection.proposal(*refs, predicate="executed_activity"),)

    item = case()
    target = reflection_target(
        (item,), Proposal(), Support(), ACCEPTANCE, OPERATIONAL, PROVENANCE, "1"
    )
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="reflection", repeat_count=2),
        item.fixture,
    )
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    outputs = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    assert len(outputs) == 2
    for stage in outputs:
        value = stage["typed_outputs"]
        assert value["reflection_result"]["results"][0]["status"] == expected
        assert value["pending_reflection_tasks"] == 0


@pytest.mark.asyncio
async def test_provider_failure_keeps_existing_safe_product_result() -> None:
    class Proposal:
        async def propose(
            self, snapshot: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            raise RuntimeError("公開しない試験用例外")

    item = case()
    target = reflection_target(
        (item,), Proposal(), Support(), ACCEPTANCE, OPERATIONAL, PROVENANCE, "1"
    )
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="reflection"),
        item.fixture,
    )
    assert result.status is RunStatus.PROVIDER_FAILED
    encoded = result.export_json(POLICY.max_export_bytes)
    assert "reflection_provider_unavailable" in encoded and "公開しない" not in encoded


@pytest.mark.asyncio
async def test_cancel_collects_product_owned_reflection_task() -> None:
    started, stopped = asyncio.Event(), asyncio.Event()

    class Proposal:
        async def propose(
            self, snapshot: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            raise AssertionError("待機中の振り返りが通常完了してはなりません")

    item = case()
    target = reflection_target(
        (item,), Proposal(), Support(), ACCEPTANCE, OPERATIONAL, PROVENANCE, "1"
    )
    runner = ValidationRunner((target,), POLICY)
    task = asyncio.create_task(
        runner.run(replace(spec(), target_module="reflection"), item.fixture)
    )
    await asyncio.wait_for(started.wait(), 0.5)
    await runner.cancel(spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED and stopped.is_set()
    assert runner.pending_count == 0
    assert not any(
        t.get_name().startswith("reflection:") and not t.done() for t in asyncio.all_tasks()
    )

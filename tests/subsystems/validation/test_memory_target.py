"""記憶の実際の書込判断・検索と、反復ごとの保存先分離を検証する。"""

import json
from dataclasses import replace

import pytest

from app.domain.memory import MemoryWriteRequest
from app.subsystems.validation.contracts import Gate, LabMode, RunStatus
from app.subsystems.validation.memory import MemoryLabCase, memory_target
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case() -> MemoryLabCase:
    value = {"preference": ("game-a", "game-b")}
    writes = tuple(
        MemoryWriteRequest(item)
        for item in (
            memory.candidate(value=value),
            memory.candidate("duplicate", value=value),
            memory.candidate("new-source", value=value, source="fact:2"),
        )
    )
    item = MemoryLabCase(
        replace(FIXTURE, human_context={"situation": "同じ好みの再取得と別の根拠の追加"}),
        writes,
        (memory.query(),),
    )
    return replace(
        item,
        fixture=replace(item.fixture, typed_inputs=item.typed_inputs(retrieval_policy())),
    )


@pytest.mark.asyncio
async def test_actual_write_decisions_and_provenance_are_retained_per_repeat() -> None:
    item = case()
    target = memory_target((item,), retrieval_policy(), PROVENANCE, "1")
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="memory", repeat_count=2),
        item.fixture,
    )
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    outputs = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    assert len(outputs) == 2
    for stage in outputs:
        actual = stage["typed_outputs"]
        assert [x["disposition"] for x in actual["write_results"]] == [
            "store_new",
            "noop_duplicate",
            "merge_provenance",
        ]
        retrieved = actual["retrieval_results"][0]
        assert len(retrieved["items"]) == 1
        record = retrieved["items"][0]
        assert len(record["provenance"]) == 2
        assert record["content"]["value"] == {"preference": ["game-a", "game-b"]}


@pytest.mark.asyncio
async def test_other_ranking_policy_is_not_silently_substituted() -> None:
    item = case()
    target = memory_target((item,), retrieval_policy(revision=2), PROVENANCE, "1")
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="memory"),
        item.fixture,
    )
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert not any(x.stage.startswith("memory.") for x in result.timeline)


@pytest.mark.asyncio
async def test_local_repository_cannot_be_reported_as_integrated_evidence() -> None:
    item = case()
    target = memory_target((item,), retrieval_policy(), PROVENANCE, "1")
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="memory", mode=LabMode.INTEGRATED),
        item.fixture,
    )
    assert result.status is RunStatus.BLOCKED_UPSTREAM and not result.timeline

"""生成候補を本番の待ち行列から取り出した後に最新状態を取得する。"""

import asyncio
from dataclasses import replace

import pytest

from app.domain.speech_performance import SpeechPerformancePlanner
from app.domain.speech_performance.policy import yura_revision_1_policy
from app.domain.speech_runtime.contracts import (
    PreparedSpeechCandidate,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
)
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.speech_adjacent import (
    SpeechAdjacentBindings,
    SpeechAdjacentCase,
    speech_adjacent_target,
)
from app.subsystems.validation.speech_preparation import SpeechRevalidationStatePort
from tests.domain.speech_runtime import test_presentation as product
from tests.subsystems.validation import test_speech_adjacent as adjacent
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import POLICY, PROVENANCE
from tests.subsystems.validation.test_speech_preparation import settings


def setup(
    port: SpeechRevalidationStatePort | None, *, validate: bool = False
) -> tuple[SpeechAdjacentCase, ValidationRunner]:
    item, connections = adjacent.case(), adjacent.Connections()
    item = replace(
        item,
        preparation=replace(
            settings(),
            queue_for_revalidation=True,
            validate_for_presentation=validate,
            presentation_modes=(SpeechPresentationMode.TEXT_ONLY,),
        ),
    )
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    bindings = SpeechAdjacentBindings(
        connections.realizer,
        connections.verifier,
        SpeechPerformancePlanner(yura_revision_1_policy()),
        revalidation=port,
    )
    target = speech_adjacent_target((item,), bindings, PROVENANCE, "1", ())
    return item, ValidationRunner((target,), POLICY)


@pytest.mark.asyncio
async def test_current_state_is_requested_after_queue_pop_without_claiming_revalidation_pass() -> (
    None
):
    seen = []

    class Live:
        async def current_state(
            self, candidate: PreparedSpeechCandidate
        ) -> SpeechPresentationCommitState:
            seen.append(candidate)
            assert candidate.lifecycle.value == "revalidating"
            return product._state()

    item, runner = setup(Live())
    result = await runner.run(adjacent.spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED and len(seen) == 1
    output = value_at(result.stage_results[0].typed_outputs, "prepared_candidate")
    assert value_at(output, "candidate", "lifecycle") == "revalidating"
    assert value_at(output, "revalidation_state", "turn_id") == "turn"
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_cancel_while_getting_current_state_reaps_queue_work() -> None:
    started, stopped = asyncio.Event(), asyncio.Event()

    class Live:
        async def current_state(
            self, candidate: PreparedSpeechCandidate
        ) -> SpeechPresentationCommitState:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            raise AssertionError("待機中の現在状態取得が通常完了してはなりません")

    item, runner = setup(Live())
    task = asyncio.create_task(runner.run(adjacent.spec(), item.fixture))
    await asyncio.wait_for(started.wait(), 0.5)
    await runner.cancel(adjacent.spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert stopped.is_set() and runner.pending_count == 0


def test_missing_live_state_connection_is_rejected_before_run() -> None:
    with pytest.raises(ValueError, match="最新状態"):
        setup(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_current_production_validation_controls_ready_state(stale: bool) -> None:
    class Live:
        async def current_state(
            self, candidate: PreparedSpeechCandidate
        ) -> SpeechPresentationCommitState:
            return replace(
                product._state(),
                source_context_revision=candidate.source_context_revision + int(stale),
                goal_revision=candidate.goal_revision,
                attention_revision=candidate.attention_revision,
                semantic_acceptance_id=candidate.semantic_acceptance_id,
                performance_plan_id=candidate.performance_plan_id,
            )

    item, runner = setup(Live(), validate=True)
    result = await runner.run(adjacent.spec(), item.fixture)
    assert result.status is (RunStatus.PRODUCT_FAILED if stale else RunStatus.COMPLETED)
    if not stale:
        output = value_at(result.stage_results[0].typed_outputs, "prepared_candidate")
        assert value_at(output, "candidate", "lifecycle") == "ready_to_present"
    assert runner.pending_count == 0

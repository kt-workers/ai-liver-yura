"""実際の意味検証結果が候補の準備完了・採用拒否へ反映されることを確認する。"""

from dataclasses import replace

import pytest

from app.domain.speech_runtime.contracts import SpeechPresentationMode
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.subsystems.validation.contracts import Gate, RunStatus
from app.subsystems.validation.speech_preparation import SpeechPreparationSettings
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.subsystems.validation import test_speech_adjacent as adjacent
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_speech_generation import setup
from tests.subsystems.validation.test_speech_generation_chain import Verification, chain_spec


def settings() -> SpeechPreparationSettings:
    return SpeechPreparationSettings(
        runtime_policy(),
        SpeechCandidatePriority.FOREGROUND,
        "expiry",
        (),
        (SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )


@pytest.mark.asyncio
async def test_actual_acceptance_prepares_candidate_without_marking_it_presentable() -> None:
    item, connections = adjacent.case(), adjacent.Connections()
    item = replace(item, preparation=settings())
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    result = await connections.runner(item).run(adjacent.spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    output = result.stage_results[0].typed_outputs
    candidate = value_at(output, "prepared_candidate")
    assert value_at(candidate, "lifecycle") == "prepared"
    assert value_at(candidate, "semantic_acceptance_id") == value_at(
        output, "verification", "acceptance", "acceptance_id"
    )
    assert value_at(candidate, "utterance_id") == value_at(output, "utterance", "utterance_id")
    assert value_at(candidate, "performance_plan_id") == value_at(
        output, "performance_plan", "performance_plan_id"
    )
    assert value_at(candidate, "prepared_audio_ref") is None


@pytest.mark.asyncio
async def test_generation_chain_rejection_is_not_replaced_with_fake_acceptance() -> None:
    verification = Verification()
    item, runner, _, _ = setup(verifier=verification.build, preparation=settings())
    result = await runner.run(chain_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED
    output = value_at(result.stage_results[0].typed_outputs, "evaluation")
    candidate = value_at(output, "prepared_candidate")
    assert value_at(candidate, "lifecycle") == "rejected"
    assert value_at(candidate, "readiness", "verifier") == "rejected"
    assert value_at(candidate, "semantic_acceptance_id") == value_at(
        output, "verification", "acceptance", "acceptance_id"
    )
    assert runner.pending_count == 0


def test_preparation_cannot_skip_real_verification_connection() -> None:
    with pytest.raises(ValueError, match="意味検証"):
        setup(preparation=settings())

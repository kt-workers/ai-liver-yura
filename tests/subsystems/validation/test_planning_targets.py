"""既存計画器の定型経路とLLM経路を置き換えずに呼ぶことを確認する。"""

import json
from dataclasses import replace

import pytest

from app.domain.contracts import RevisionVector
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.domain.speech_semantics import SpeechSemanticContextSnapshot
from app.subsystems.validation.contracts import (
    FailureInjection,
    InjectedFailure,
    RunStatus,
    ValidationFixture,
)
from app.subsystems.validation.planning import (
    PlanningLabCase,
    goal_planning_target,
    speech_semantics_target,
)
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.goal_planning import test_goal_planning as goals
from tests.domain.speech_semantics import test_speech_semantics as speech
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def setup(
    kind: str, deterministic: bool
) -> tuple[ValidationFixture, ValidationRunner, list[LLMRoleRequest]]:
    module = goals if kind == "goal_planning" else speech
    item = PlanningLabCase(FIXTURE, module.context(deterministic=deterministic), module.NOW)
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    requests: list[LLMRoleRequest] = []

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            assert not deterministic
            requests.append(request)
            return (
                goals.result_for(request, goals.candidate_json())
                if kind == "goal_planning"
                else speech.result_for(request, speech.candidate_json())
            )

    class SpeechLive:
        async def current_revisions(
            self, snapshot: SpeechSemanticContextSnapshot
        ) -> RevisionVector:
            return snapshot.revisions

    target = (
        goal_planning_target(
            (item,), Port(), goals.FakeLiveState(), goals.policy(), PROVENANCE, "1", ()
        )
        if kind == "goal_planning"
        else speech_semantics_target(
            (item,), Port(), SpeechLive(), speech.policy(), PROVENANCE, "1", ()
        )
    )
    return item.fixture, ValidationRunner((target,), POLICY), requests


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["goal_planning", "speech_semantics"])
@pytest.mark.parametrize("deterministic", [False, True])
async def test_production_selects_deterministic_or_llm_path(kind: str, deterministic: bool) -> None:
    fixture, runner, requests = setup(kind, deterministic)
    result = await runner.run(replace(spec(), target_module=kind, repeat_count=2), fixture)
    assert result.status is RunStatus.COMPLETED
    assert len(requests) == (0 if deterministic else 2)
    outputs = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    assert len(outputs) == 2
    assert len({stage["typed_outputs"]["plan_id"] for stage in outputs}) == 2
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["goal_planning", "speech_semantics"])
async def test_injected_unavailability_keeps_product_failure_behavior(kind: str) -> None:
    fixture, runner, requests = setup(kind, False)
    result = await runner.run(
        replace(
            spec(),
            target_module=kind,
            failure_injections=(
                FailureInjection(f"{kind}.llm", InjectedFailure.PROVIDER_UNAVAILABLE, 1),
            ),
        ),
        fixture,
    )
    assert result.status is RunStatus.PRODUCT_FAILED
    assert not requests and not result.stage_results

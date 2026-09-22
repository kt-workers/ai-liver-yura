"""身体運動計画の実際の採用境界と、未実行の計画としての記録を確認する。"""

import json
from dataclasses import replace

import pytest

from app.domain.body_motion_planning import (
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    DeterministicBodyPlanningDirective,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.subsystems.validation.body import BodyPlanningLabCase, _project, body_planning_target
from app.subsystems.validation.contracts import FailureInjection, InjectedFailure, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.body_motion_planning import test_contracts as body
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def setup(
    deterministic: bool = False,
) -> tuple[BodyPlanningLabCase, ValidationRunner, list[LLMRoleRequest]]:
    snapshot = body._snapshot()
    if deterministic:
        value = body._candidate()
        snapshot = replace(
            snapshot,
            deterministic_directive=DeterministicBodyPlanningDirective(
                value.goals,
                value.phases,
                value.coordination_constraints,
                value.expression_bindings,
            ),
        )
    item = BodyPlanningLabCase(FIXTURE, snapshot, body.NOW)
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    calls: list[LLMRoleRequest] = []

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            assert not deterministic
            calls.append(request)
            value = body._candidate_value()
            value["request_id"] = request.request_id
            return replace(
                body._success(request),
                output=StructuredPayload(
                    "body.motion-planning.candidate.v1",
                    _project(value),
                ),
            )

    class Live:
        async def current_commit_state(
            self, snapshot: BodyMotionPlanningContextSnapshot
        ) -> BodyMotionPlanningCommitState:
            return body._current()

    target = body_planning_target((item,), Port(), Live(), body._policy(), PROVENANCE, "1", ())
    return item, ValidationRunner((target,), POLICY), calls


@pytest.mark.asyncio
@pytest.mark.parametrize("deterministic", [False, True])
async def test_body_planner_uses_actual_plan_authority_and_keeps_repeat_identity(
    deterministic: bool,
) -> None:
    item, runner, calls = setup(deterministic)
    result = await runner.run(
        replace(spec(), target_module="body_planning", repeat_count=2), item.fixture
    )
    assert result.status is RunStatus.COMPLETED
    assert len(calls) == (0 if deterministic else 2)
    outputs = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    assert len({x["typed_outputs"]["plan_id"] for x in outputs}) == 2
    for output in outputs:
        candidate = output["typed_outputs"]["candidate"]
        assert candidate["body_model_id"] == item.snapshot.body_model.body_model_id
        assert len(candidate["goals"]) == 1
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_body_provider_unavailability_does_not_create_a_plan() -> None:
    item, runner, calls = setup()
    result = await runner.run(
        replace(
            spec(),
            target_module="body_planning",
            failure_injections=(
                FailureInjection("body.planning.llm", InjectedFailure.PROVIDER_UNAVAILABLE, 1),
            ),
        ),
        item.fixture,
    )
    assert result.status is RunStatus.PRODUCT_FAILED
    assert not result.stage_results and not calls

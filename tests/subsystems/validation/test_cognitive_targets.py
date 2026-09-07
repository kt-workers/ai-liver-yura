"""状況評価と実行判断の製品入口、世代照合、接続注入を検証する。"""

import json
from dataclasses import replace

import pytest

from app.domain.appraisal import DeepAppraisalContext, DeepAppraisalFreshnessStamp
from app.domain.executive import (
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.subsystems.validation.appraisal import AppraisalLabCase, appraisal_target
from app.subsystems.validation.contracts import (
    FailureInjection,
    Gate,
    InjectedFailure,
    RunStatus,
    ValidationFixture,
)
from app.subsystems.validation.executive import ExecutiveLabCase, executive_target
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.appraisal import test_appraisal_paths as appraisal
from tests.domain.executive import test_executive as executive
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def setup(
    kind: str, *, stale: bool = False
) -> tuple[ValidationFixture, ValidationRunner, list[str]]:
    calls: list[str] = []
    if kind == "appraisal":
        item = AppraisalLabCase(
            FIXTURE,
            appraisal.event(),
            appraisal.meaning(),
            appraisal.state(),
            DeepAppraisalContext(),
            appraisal.NOW,
        )
        item = replace(
            item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs(appraisal.policy()))
        )

        class Port:
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                calls.append(request.request_id)
                return appraisal.result(request)

        class Live:
            async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
                return DeepAppraisalFreshnessStamp(7, 4 if stale else 3)

        target = appraisal_target((item,), Port(), Live(), appraisal.policy(), PROVENANCE, "1", ())
    else:
        executive_item = ExecutiveLabCase(FIXTURE, executive.snapshot(), executive.NOW)
        executive_item = replace(
            executive_item,
            fixture=replace(FIXTURE, typed_inputs=executive_item.typed_inputs(executive.policy())),
        )

        class ExecutivePort:
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                calls.append(request.request_id)
                return executive.success(request)

        class ExecutiveLive:
            async def current_for_commit(
                self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
            ) -> ExecutiveCommitState:
                return executive.live_state(internal_state_revision=3 if stale else 2)

        target = executive_target(
            (executive_item,),
            ExecutivePort(),
            ExecutiveLive(),
            executive.policy(),
            PROVENANCE,
            "1",
            (),
        )
        return executive_item.fixture, ValidationRunner((target,), POLICY), calls
    return item.fixture, ValidationRunner((target,), POLICY), calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["appraisal", "executive"])
async def test_actual_product_result_and_distinct_repeat_requests(kind: str) -> None:
    fixture, runner, calls = setup(kind)
    result = await runner.run(replace(spec(), target_module=kind, repeat_count=2), fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    assert len(calls) == len(set(calls)) == 2
    outputs = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    if kind == "appraisal":
        assert outputs[0]["typed_outputs"]["proposals"][0]["delta"] == 0.2
    else:
        assert outputs[0]["typed_outputs"]["candidate"]["outcome"] == "respond"
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["appraisal", "executive"])
async def test_changed_live_state_is_rejected_by_product(kind: str) -> None:
    fixture, runner, calls = setup(kind, stale=True)
    result = await runner.run(replace(spec(), target_module=kind), fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert len(calls) == 1 and not result.stage_results


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["appraisal", "executive"])
async def test_injected_unavailability_stops_owner_without_calling_provider(kind: str) -> None:
    fixture, runner, calls = setup(kind)
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
    assert not calls and not result.stage_results

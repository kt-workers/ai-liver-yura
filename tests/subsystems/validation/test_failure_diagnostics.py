"""失敗注入と既存運用診断を製品の意味判断から分離する検証。"""

import json
from dataclasses import replace

import pytest

from app.adapters.llm.openai_responses import OpenAIResponsesAdapter
from app.domain.input_meaning import InputMeaningFreshnessStamp, build_request
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.subsystems.validation.contracts import (
    FailureInjection,
    Gate,
    InjectedFailure,
    RunStatus,
    TargetObservation,
)
from app.subsystems.validation.input_meaning import InputMeaningLabCase, input_meaning_target
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from tests.adapters.llm.test_openai_responses import (
    FakeClient,
    make_config,
    make_request,
    status_error,
)
from tests.domain.input_meaning import test_input_meaning as meaning
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec, target


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,status",
    [
        (InjectedFailure.PROVIDER_UNAVAILABLE, RunStatus.PROVIDER_FAILED),
        (InjectedFailure.TIMEOUT, RunStatus.TIMED_OUT),
        (InjectedFailure.CANCELLED, RunStatus.CANCELLED),
    ],
)
async def test_injected_role_failure_uses_real_owner_without_calling_provider(
    kind: InjectedFailure,
    status: RunStatus,
) -> None:
    event, refs, policy = meaning.event(), meaning.context(), meaning.policy()
    request = build_request(
        event,
        refs,
        request_id="r",
        trace_id=event.envelope.trace_id,
        created_at=meaning.NOW,
        policy=policy,
    )
    fixture = replace(FIXTURE, typed_inputs=request.input.value)

    class ForbiddenPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            pytest.fail("注入対象で実提供サービスを呼んではなりません")

    class ForbiddenLive:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            pytest.fail("非成功結果で現在世代を読んではなりません")

    binding = input_meaning_target(
        (InputMeaningLabCase(fixture, event, refs, meaning.NOW),),
        ForbiddenPort(),
        ForbiddenLive(),
        policy,
        PROVENANCE,
        "1",
        (),
    )
    runner = ValidationRunner((binding,), POLICY)
    result = await runner.run(
        replace(
            spec(),
            target_module="input_meaning",
            failure_injections=(FailureInjection("input_meaning.llm", kind, 1),),
        ),
        fixture,
    )
    assert result.status is status
    encoded = json.loads(result.export_json(POLICY.max_export_bytes))
    assert encoded["run_spec"]["failure_injections"][0]["closed_failure_kind"] == kind.value
    assert encoded["stage_results"][0]["typed_outputs"]["meaning"] is None
    assert encoded["human_evaluation"]["status"] == "UNRATED"


@pytest.mark.asyncio
async def test_unknown_failure_stage_is_blocked_without_running_target() -> None:
    runner = ValidationRunner((target(),), POLICY)
    result = await runner.run(
        replace(
            spec(),
            failure_injections=(FailureInjection("unknown", InjectedFailure.TIMEOUT, 1),),
        ),
        FIXTURE,
    )
    assert result.status is RunStatus.BLOCKED_UPSTREAM and not result.timeline


@pytest.mark.asyncio
async def test_actual_provider_diagnostic_route_is_exported_without_raw_exception() -> None:
    async def invoke(context: RunContext, fixture: object) -> TargetObservation:
        client = FakeClient(status_error(401, "試験用の非公開例外本文"))
        port = OpenAIResponsesAdapter(
            client, (make_config(),), now=lambda: meaning.NOW, diagnostic_sink=context.diagnostics
        )
        await port.invoke(replace(make_request(), created_at=meaning.NOW))
        return TargetObservation(RunStatus.PROVIDER_FAILED, Gate.NOT_RUN, None)

    runner = ValidationRunner((replace(target(), run=invoke),), POLICY)
    result = await runner.run(spec(), FIXTURE)
    encoded = result.export_json(POLICY.max_export_bytes)
    diagnostics = json.loads(encoded)["provider_diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["http_status"] == 401
    assert "試験用の非公開例外本文" not in encoded
    assert result.status is RunStatus.PROVIDER_FAILED

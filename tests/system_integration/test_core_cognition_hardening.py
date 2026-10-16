"""通常認知の複数入力・登録欠落・正規受付の拒否を検証する。"""

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from app import application as bootstrap
from app.composition.cognition_configuration import CoreCognitionConfiguration
from app.config.core import load_core_config
from app.domain.appraisal import InternalStateReducer
from app.domain.attention import AttentionSchedulingPolicy, AttentionTurnStore
from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.preconditions import PreconditionSourceRouter
from app.domain.executive import ExecutiveIntentRequirementsPolicy, ExecutiveRequirementsOwner
from app.domain.input_meaning import InputMeaningInterpretationResult
from app.domain.plugin_registry import PluginRegistryAuthority
from tests.domain.appraisal.test_appraisal_paths import policy, state
from tests.domain.executive.test_executive import policy as executive_policy
from tests.helpers.brain_outcomes import next_outcome_matching
from tests.system_integration.test_core_cognition import admission, application


def configuration() -> CoreCognitionConfiguration:
    owner = ExecutiveRequirementsOwner(BOUNDS)
    owner.publish(ExecutiveIntentRequirementsPolicy("registered", 1, ()))
    return CoreCognitionConfiguration(
        policy(),
        executive_policy(),
        InternalStateReducer(replace(state(), source_context_revision=0)),
        AttentionTurnStore(AttentionSchedulingPolicy.production()),
        owner,
        PluginRegistryAuthority(),
        PreconditionSourceRouter(()),
        (),
        (),
    )


@pytest.mark.parametrize(
    "field",
    [
        "state",
        "attention",
        "requirements",
        "registry",
        "precondition_router",
        "appraisal_policy",
        "executive_policy",
    ],
)
def test_missing_registration_is_a_configuration_failure(field: str) -> None:
    with pytest.raises(ValueError):
        missing: dict[str, Any] = {field: None}
        replace(configuration(), **missing)


@pytest.mark.asyncio
@pytest.mark.parametrize("supersede", [False, True])
async def test_cancelled_source_cannot_be_selected_by_unrelated_input(
    monkeypatch: pytest.MonkeyPatch, supersede: bool
) -> None:
    app, port = application(monkeypatch)
    port.release.clear()
    await bootstrap.start_core(app)
    try:
        app.cognition.submit_input(admission(app))
        await asyncio.wait_for(port.entered.wait(), 2)
        first = await next_outcome_matching(
            app.brain, trace_id="trace-1", module=BrainIntegrationModule.INPUT_MEANING
        )
        second = app.cognition.submit_input(admission(app, event_id="event-2", trace_id="trace-2"))
        assert second.accepted
        # 遅い評価が待機中でも別のforeground入力の意味採用は完了する。
        foreground = await next_outcome_matching(
            app.brain, trace_id="trace-2", module=BrainIntegrationModule.INPUT_MEANING
        )
        assert (
            foreground.trace_id == "trace-2"
            and foreground.module is BrainIntegrationModule.INPUT_MEANING
        )
        assert app.cognition.cancel_trace("trace-1", "取消", supersede=supersede) == 1
        cancelled = await next_outcome_matching(
            app.brain,
            trace_id="trace-1",
            status=BrainWorkStatus.SUPERSEDED if supersede else BrainWorkStatus.CANCELLED,
        )
        assert cancelled.trace_id == "trace-1"
        assert cancelled.status is (
            BrainWorkStatus.SUPERSEDED if supersede else BrainWorkStatus.CANCELLED
        )
        port.release.set()
        remaining = [
            await next_outcome_matching(app.brain, trace_id="trace-2", module=module)
            for module in (BrainIntegrationModule.APPRAISAL, BrainIntegrationModule.EXECUTIVE)
        ]
        decision = remaining[-1]
        assert decision.status is BrainWorkStatus.COMPLETED, remaining
        assert decision.module is BrainIntegrationModule.EXECUTIVE
        assert decision.trace_id == "trace-2"
        assert decision.result.candidate.source_event_ids == ("event-2",)
        assert app.brain.trace("trace-2").root_trigger_id == "event-2"
    finally:
        await bootstrap.stop_core(app)
        await bootstrap.stop_core(app)


@pytest.mark.asyncio
async def test_runtime_queue_rejects_without_executive_for_rejected_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = load_core_config

    def small_queue(data: bytes) -> Any:
        config = load(data)
        return replace(
            config,
            integration_policy=replace(
                config.integration_policy,
                lane_policies=tuple(
                    replace(lane, queue_capacity=1, max_in_flight=1)
                    for lane in config.integration_policy.lane_policies
                ),
            ),
        )

    monkeypatch.setattr(bootstrap, "load_core_config", small_queue)
    app, port = application(monkeypatch)
    await bootstrap.start_core(app)
    try:
        assert app.cognition.submit_input(admission(app, internal=True)).accepted
        rejected = app.cognition.submit_input(
            admission(app, internal=True, event_id="rejected", trace_id="rejected")
        )
        assert not rejected.accepted
        rejected_outcome = await next_outcome_matching(
            app.brain, trace_id="rejected", status=BrainWorkStatus.REJECTED
        )
        assert rejected_outcome.status is BrainWorkStatus.REJECTED
        assert all(r.trace_id != "rejected" for r in port.requests)
        assert all(
            i.status is BrainWorkStatus.REJECTED for i in app.brain.trace("rejected").intervals
        )
    finally:
        await bootstrap.stop_core(app)


@pytest.mark.asyncio
async def test_attention_capacity_rejection_does_not_start_appraisal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    from app.usecases.attention import UserInteractionAttentionProjector

    app, port = application(monkeypatch)
    owner = app.cognition._attention_owner
    owner.update_policy(
        replace(owner.policy, policy_revision=2, attention_budget=1), datetime.now(timezone.utc)
    )
    occupied = admission(app, event_id="occupied", trace_id="occupied")
    owner.offer(UserInteractionAttentionProjector().project(occupied))
    await bootstrap.start_core(app)
    try:
        with pytest.raises(ValueError, match="注意所有者"):
            app.cognition.submit_input(admission(app))
        assert not port.requests
        assert [s.source_ref for s in owner.snapshot().sources] == ["occupied"]
    finally:
        await bootstrap.stop_core(app)


@pytest.mark.asyncio
async def test_selected_old_source_keeps_provenance_with_new_current_appraisal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, port = application(monkeypatch)
    await bootstrap.start_core(app)
    try:
        app.cognition.submit_input(admission(app))
        for module in (
            BrainIntegrationModule.INPUT_MEANING,
            BrainIntegrationModule.APPRAISAL,
            BrainIntegrationModule.EXECUTIVE,
        ):
            outcome = await next_outcome_matching(app.brain, trace_id="trace-1", module=module)
            assert outcome.status is BrainWorkStatus.COMPLETED, outcome
        app.cognition.submit_input(admission(app, event_id="event-2", trace_id="trace-2"))
        for module in (
            BrainIntegrationModule.INPUT_MEANING,
            BrainIntegrationModule.APPRAISAL,
        ):
            outcome = await next_outcome_matching(app.brain, trace_id="trace-2", module=module)
            assert outcome.status is BrainWorkStatus.COMPLETED, outcome
        decision = await next_outcome_matching(
            app.brain, trace_id="trace-1", module=BrainIntegrationModule.EXECUTIVE
        )
        assert decision.status is BrainWorkStatus.COMPLETED, outcomes
        assert decision.trace_id == "trace-1"
        assert decision.result.candidate.source_event_ids == ("event-1",)
        assert app.cognition.appraisal.current_commit().candidate.source_event_ids == ("event-2",)
        assert port.requests[-1].trace_id == "trace-1"
        assert app.brain.trace("trace-1").root_trigger_id == "event-1"
        assert app.brain.trace("trace-2").root_trigger_id == "event-2"
    finally:
        await bootstrap.stop_core(app)


@pytest.mark.asyncio
async def test_unavailable_provider_preserves_input_failure_without_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.llm.production import UnavailableLLMRolePort
    from app.domain.llm import LLMFailureCode

    application(monkeypatch)
    monkeypatch.setattr(
        bootstrap,
        "create_openai_port_from_environment",
        lambda roles: UnavailableLLMRolePort(roles),
    )
    unavailable = bootstrap.build_core_runtime(cognition=configuration())
    assert unavailable.cognition is not None
    await bootstrap.start_core(unavailable)
    try:
        unavailable.cognition.submit_input(admission(unavailable))
        outcome = await next_outcome_matching(
            unavailable.brain, trace_id="trace-1", module=BrainIntegrationModule.INPUT_MEANING
        )
        assert isinstance(outcome.result, InputMeaningInterpretationResult)
        assert outcome.result.meaning is None
        assert outcome.result.role_failure is not None
        assert outcome.result.role_failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
        assert len(unavailable.brain.trace("trace-1").intervals) == 1
        assert unavailable.cognition.appraisal.current_commit() is None
    finally:
        await bootstrap.stop_core(unavailable)


@pytest.mark.asyncio
@pytest.mark.parametrize("supersede", [False, True])
async def test_cancel_before_execution_and_repeated_stop_leave_no_owned_work(
    monkeypatch: pytest.MonkeyPatch, supersede: bool
) -> None:
    app, port = application(monkeypatch)
    await bootstrap.start_core(app)
    accepted = app.cognition.submit_input(admission(app, internal=True))
    assert app.cognition.cancel_trace("trace-1", "開始前取消", supersede=supersede) == 1
    outcome = await next_outcome_matching(
        app.brain, work_id=accepted.work_id,
        status=BrainWorkStatus.SUPERSEDED if supersede else BrainWorkStatus.CANCELLED,
    )
    assert outcome.status is (
        BrainWorkStatus.SUPERSEDED if supersede else BrainWorkStatus.CANCELLED
    )
    await bootstrap.stop_core(app)
    await bootstrap.stop_core(app)
    assert not port.requests
    assert not app.brain.cancel(accepted.work_id, "回収済み")
    diagnostics = app.brain._runtime.diagnostics()
    assert diagnostics.owned_task_count == 0
    assert all(lane.in_flight == lane.queue_depth == 0 for lane in diagnostics.lanes)


@pytest.mark.asyncio
async def test_missing_measured_publication_cannot_commit_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.contracts.preconditions import PreconditionSourceBinding, PreconditionSourceRef

    _, port = application(monkeypatch)
    config = replace(
        configuration(),
        precondition_bindings=(
            PreconditionSourceBinding(
                "test-condition",
                "test-subject",
                "test-predicate",
                PreconditionSourceRef("unregistered", "test-current"),
            ),
        ),
    )
    app = bootstrap.build_core_runtime(cognition=config)
    assert app.cognition is not None
    await bootstrap.start_core(app)
    try:
        app.cognition.submit_input(admission(app, internal=True))
        appraisal = await next_outcome_matching(
            app.brain, trace_id="trace-1", module=BrainIntegrationModule.APPRAISAL
        )
        assert appraisal.status is BrainWorkStatus.COMPLETED
        decision = await next_outcome_matching(
            app.brain, trace_id="trace-1", module=BrainIntegrationModule.EXECUTIVE
        )
        assert decision.module is BrainIntegrationModule.EXECUTIVE
        assert decision.status is BrainWorkStatus.FAILED
        assert decision.result is None
        assert [r.role_id for r in port.requests] == ["subjective_appraisal"]
    finally:
        await bootstrap.stop_core(app)


@pytest.mark.asyncio
async def test_concurrent_appraisals_do_not_share_a_stale_state_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, port = application(monkeypatch)
    port.release.clear()
    await bootstrap.start_core(app)
    try:
        app.cognition.submit_input(admission(app))
        await asyncio.wait_for(port.entered.wait(), 2)
        first = await next_outcome_matching(
            app.brain, trace_id="trace-1", module=BrainIntegrationModule.INPUT_MEANING
        )
        assert first.status is BrainWorkStatus.COMPLETED
        app.cognition.submit_input(admission(app, event_id="event-2", trace_id="trace-2"))
        second = await next_outcome_matching(
            app.brain, trace_id="trace-2", module=BrainIntegrationModule.INPUT_MEANING
        )
        assert second.trace_id == "trace-2"
        # 両方の深い評価が同じ採用前リビジョンを読んだ状態で再開する。
        for _ in range(100):
            if sum(r.role_id == "subjective_appraisal" for r in port.requests) == 2:
                break
            await asyncio.sleep(0)
        assert sum(r.role_id == "subjective_appraisal" for r in port.requests) == 2
        port.release.set()
        appraisals = [
            await next_outcome_matching(
                app.brain, trace_id=trace_id, module=BrainIntegrationModule.APPRAISAL
            )
            for trace_id in ("trace-1", "trace-2")
        ]
        assert sorted(o.status.value for o in appraisals) == ["completed", "failed"]
        committed = app.cognition.appraisal.current_commit()
        assert committed is not None
        successful = next(o for o in appraisals if o.status is BrainWorkStatus.COMPLETED)
        assert (
            committed.candidate.source_event_ids
            == app.brain.trace(successful.trace_id).source_event_ids
        )
        assert all(o.trace_id in ("trace-1", "trace-2") for o in appraisals)
    finally:
        await bootstrap.stop_core(app)


@pytest.mark.asyncio
async def test_appraisal_attention_rejection_cannot_start_executive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    from app.usecases.attention import UserInteractionAttentionProjector

    app, port = application(monkeypatch)
    owner = app.cognition._attention_owner
    owner.update_policy(
        replace(owner.policy, policy_revision=2, attention_budget=1), datetime.now(timezone.utc)
    )
    owner.offer(
        UserInteractionAttentionProjector().project(
            admission(app, event_id="occupied", trace_id="occupied")
        )
    )
    await bootstrap.start_core(app)
    try:
        assert app.cognition.submit_input(admission(app, internal=True)).accepted
        outcome = await next_outcome_matching(
            app.brain, trace_id="trace-1", module=BrainIntegrationModule.APPRAISAL
        )
        assert outcome.module is BrainIntegrationModule.APPRAISAL
        assert outcome.status is BrainWorkStatus.FAILED
        assert outcome.result is None
        assert [r.role_id for r in port.requests] == ["subjective_appraisal"]
    finally:
        await bootstrap.stop_core(app)
    assert app.brain._runtime.diagnostics().owned_task_count == 0

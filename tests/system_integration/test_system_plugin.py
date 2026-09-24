"""本番構成と模擬提供先で、Pluginの有無と実行事実の還流を検証する。"""

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from app import bootstrap
from app.composition.execution import CoreExecutionDelivery, ExecutionFeedbackRetentionPolicy
from app.composition.execution_configuration import CoreExecutionConfiguration
from app.domain.activity_execution import (
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectEvidence,
    ExecutionEffectKind,
    ExecutionEffectUncertainty,
    ExecutionPreflightSnapshot,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityAvailability, ExecutionStatus
from app.domain.contracts.finalization import FinalizationError
from app.domain.goal_planning import GoalPlanningAuthority
from app.domain.input_gateway import InputPermission, InputSourceState
from app.domain.input_gateway.normalizer import InputAdmissionLedger, InputNormalizer
from app.domain.plan_execution.contracts import PlanExecutionPolicy
from app.domain.plan_execution.owner import PlanExecutionCurrentState
from app.domain.plugin_integration import (
    PluginActivityExecutionPort,
    PluginCapabilityAdapterBinding,
    PluginCapabilityPreflightPort,
    PluginIntegrationOperationalPolicy,
)
from app.domain.plugin_registry import PluginRegistryAuthority
from app.runtime.kernel.clock import SystemRuntimeClock
from tests.domain.activity_binding import test_binding
from tests.domain.executive.test_executive import NOW
from tests.domain.plugin_registry.test_plugin_registry_adjacent import (
    available_registry,
    grant_snapshot,
)
from tests.helpers.executive_requirements import fence_clock, make_authority
from tests.system_integration.test_core_cognition import admission, application
from tests.system_integration.test_early_boot import work


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["completed", "revoked", "unknown", "applied_revoked", "cancelled"]
)
async def test_plugin_fact_crosses_production_composition_and_returns_to_cognition(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    registry = available_registry()
    monkeypatch.setattr(test_binding, "available_registry", lambda: registry)
    binding, _, _, captured, proposed, current = test_binding.direct_fixture()
    with fence_clock(lambda: NOW):
        decision = make_authority(captured).commit(
            proposed,
            captured,
            current=current,
            decision_id="system-plugin-decision",
        )
    clock = SystemRuntimeClock()
    requests: list[ExecutionDispatchRequest] = []
    entered, reaped = asyncio.Event(), asyncio.Event()

    class BasePreflight:
        async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return ExecutionPreflightSnapshot(invocation.command.revisions, (), (), clock.now())

    class Native:
        async def execute(
            self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
        ) -> tuple[ExecutionAdapterReport, ...]:
            raise AssertionError("Plugin要求を本体固有操作へ移してはいけません")

    class Provider:
        async def execute(
            self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
        ) -> tuple[ExecutionAdapterReport, ...]:
            requests.append(request)
            entered.set()
            if mode == "cancelled":
                try:
                    await asyncio.Event().wait()
                finally:
                    reaped.set()
            evidence: tuple[ExecutionEffectEvidence, ...] = ()
            if mode == "applied_revoked":
                selected = request.bindings[0]
                evidence = (
                    ExecutionEffectEvidence(
                        "effect-1",
                        selected.capability_id,
                        selected.descriptor_revision,
                        request.invocation.operation_ref,
                        ExecutionEffectKind.APPLIED,
                        {"source": "模擬提供先"},
                    ),
                )
                registry.adopt_permission_grants(grant_snapshot(1, ()))
            return (
                ExecutionAdapterReport(
                    request.invocation.command.command_id,
                    request.invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.TIMED_OUT if mode == "unknown" else ExecutionStatus.COMPLETED,
                    clock.now(),
                    {},
                    evidence,
                    ExecutionEffectUncertainty.POSSIBLY_APPLIED
                    if mode == "unknown"
                    else ExecutionEffectUncertainty.NONE,
                ),
            )

    class PlanContext:
        async def current_for(self, scope_id: str) -> PlanExecutionCurrentState:
            raise AssertionError("直接実行の検証から計画を開始してはいけません")

    plugin = PluginActivityExecutionPort(
        Native(),
        registry,
        (PluginCapabilityAdapterBinding("plugin-a", 0, "capability-a", Provider()),),
        PluginIntegrationOperationalPolicy(),
        clock,
    )
    config = CoreExecutionConfiguration(
        GoalPlanningAuthority(),
        PlanExecutionPolicy("system-plugin", 1, 2, 2, 4, 256),
        PlanContext(),
        PluginCapabilityPreflightPort(BasePreflight(), registry),
        plugin,
        InputNormalizer(InputAdmissionLedger(), bounds_policy=BOUNDS),
        InputSourceState(
            "activity_execution",
            "activity_execution",
            CapabilityAvailability.AVAILABLE,
            InputPermission.NOT_REQUIRED,
        ),
        (binding,),
        ExecutionFeedbackRetentionPolicy("system-plugin", 1, 4),
    )
    build = bootstrap.build_minimum_core

    def composed(*args: Any, **kwargs: Any) -> bootstrap.MinimumCoreApplication:
        kwargs["cognition"] = replace(kwargs["cognition"], registry=registry, execution=config)
        return build(*args, **kwargs)

    monkeypatch.setattr(bootstrap, "build_minimum_core", composed)
    app, llm = application(monkeypatch)
    delivery = app.cognition.execution
    assert isinstance(delivery, CoreExecutionDelivery)
    assert len(registry.snapshot().plugins) == 1
    if mode == "revoked":
        registry.adopt_permission_grants(grant_snapshot(1, ()))
    await app.start()
    parent = work()
    parent = replace(
        parent, envelope=replace(parent.envelope, root_trigger_id="system-plugin-root")
    )
    try:
        if mode == "revoked":
            with pytest.raises(FinalizationError):
                delivery.accept_decision(parent, decision)
            assert requests == []
            return
        delivery.accept_decision(parent, decision)
        if mode == "cancelled":
            await asyncio.wait_for(entered.wait(), 2)
            assert app.cognition.submit_input(
                admission(app, internal=True, event_id="independent", trace_id="independent")
            ).accepted
            for _ in range(2):
                independent = await asyncio.wait_for(app.brain.next_outcome(), 2)
                assert independent.trace_id == "independent"
                assert independent.status.value == "completed"
            trace = app.brain.trace(parent.envelope.trace_id)
            assert trace is not None
            activity_id = next(
                item.work_id
                for item in trace.intervals
                if item.module.value == "activity_execution"
            )
            app.brain.cancel(activity_id, "検証取消")
            app.brain.cancel(activity_id, "検証再取消")
        outcomes = []
        for _ in range(3):
            outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
            if mode == "applied_revoked" and outcome.module.value == "executive":
                assert outcome.status.value == "failed"
                assert outcome.error == "FinalizationError"
            else:
                assert outcome.status.value in {"completed", "cancelled", "stale"}, (
                    outcome.module,
                    outcome.error,
                )
            outcomes.append(outcome)
        activity = outcomes[0]
        record = app.activities.snapshot(activity.work_id)
        assert record is not None
        expected = {
            "completed": ExecutionStatus.COMPLETED,
            "revoked": ExecutionStatus.UNSUPPORTED,
            "unknown": ExecutionStatus.TIMED_OUT,
            "applied_revoked": ExecutionStatus.COMPLETED,
            "cancelled": ExecutionStatus.CANCELLED,
        }[mode]
        assert record.result.status is expected
        assert len(requests) == (0 if mode == "revoked" else 1)
        assert outcomes[-1].module.value == "executive"
        assert outcomes[-1].status.value == ("failed" if mode == "applied_revoked" else "completed")
        assert record in app.input_context.snapshot().activities
        assert any(request.role_id == "subjective_appraisal" for request in llm.requests)
        assert any(request.role_id == "executive_deliberation" for request in llm.requests) == (
            mode != "applied_revoked"
        )
        assert record.bindings[0].capability_id == "capability-a"
        if mode == "unknown":
            assert record.effect_uncertainty is ExecutionEffectUncertainty.POSSIBLY_APPLIED
        if mode == "applied_revoked":
            assert record.result.effect_refs
        if mode == "cancelled":
            assert reaped.is_set()
        trace = app.brain.trace(parent.envelope.trace_id)
        assert trace is not None and trace.root_trigger_id == parent.envelope.root_trigger_id
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_zero_plugin_keeps_production_cognition_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistryAuthority()
    build = bootstrap.build_minimum_core

    def composed(*args: Any, **kwargs: Any) -> bootstrap.MinimumCoreApplication:
        kwargs["cognition"] = replace(kwargs["cognition"], registry=registry)
        return build(*args, **kwargs)

    monkeypatch.setattr(bootstrap, "build_minimum_core", composed)
    app, _ = application(monkeypatch)
    await app.start()
    try:
        assert registry.snapshot().foundation_capabilities == ()
        assert app.cognition.submit_input(admission(app, internal=True)).accepted
        outcomes = [await asyncio.wait_for(app.brain.next_outcome(), 2) for _ in range(2)]
        assert all(item.status.value == "completed" for item in outcomes)
        assert outcomes[-1].module.value == "executive"
        assert registry.snapshot().plugins == ()
    finally:
        await app.stop()

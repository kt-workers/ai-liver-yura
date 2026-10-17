"""本番S2構成を配送へ接続し、取消・現在性・独立した前景進行を検証する。"""

import asyncio
from typing import Any

import pytest

from app.bootstrap import build_s2_production_core
from app.composition.s2_provider import S2ProviderLease
from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.domain.executive import GoalTransitionOperation
from tests.composition.test_system_cognition_configuration import parameters
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.system_integration.test_core_cognition import Port, admission


async def application() -> tuple[Any, Port]:
    port = Port()

    async def provider(roles: Any, configs: Any, bindings: Any, mode: str) -> S2ProviderLease:
        async def close() -> None:
            pass

        return S2ProviderLease(port, bindings, mode, close)

    params = parameters()
    params["provider_factory"] = provider
    return await build_s2_production_core(**params), port


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [False, True])
async def test_production_policies_reach_delivery(internal: bool) -> None:
    app, port = await application()
    await app.start()
    try:
        app.core.cognition.submit_input(admission(app.core, internal=internal))
        outcomes = [
            await asyncio.wait_for(app.core.brain.next_outcome(), 2)
            for _ in range(2 if internal else 3)
        ]
        assert all(outcome.status is BrainWorkStatus.COMPLETED for outcome in outcomes), outcomes
        policies = {request.execution_policy.policy_id for request in port.requests}
        assert "yura.appraisal.execution" in policies
        assert "yura.executive.execution" in policies
        assert "test.llm.execution" not in policies
        assert outcomes[-1].module is BrainIntegrationModule.EXECUTIVE
    finally:
        await app.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "supersede", "stale"])
async def test_invalidated_appraisal_never_reaches_executive(operation: str) -> None:
    app, port = await application()
    port.release.clear()
    await app.start()
    try:
        app.core.cognition.submit_input(admission(app.core, internal=True))
        await asyncio.wait_for(port.entered.wait(), 2)
        if operation == "stale":
            apply_goal(app.core.goals, GoalTransitionOperation.CREATE, 0)
            port.release.set()
        else:
            app.core.cognition.cancel_trace(
                "trace-1", "試験取消", supersede=operation == "supersede"
            )
        outcome = await asyncio.wait_for(app.core.brain.next_outcome(), 2)
        expected = {
            "cancel": BrainWorkStatus.CANCELLED,
            "supersede": BrainWorkStatus.SUPERSEDED,
            "stale": BrainWorkStatus.FAILED,
        }
        assert outcome.status is expected[operation]
        assert [r.role_id for r in port.requests] == ["subjective_appraisal"]
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_foreground_progress_while_slow_appraisal_is_pending() -> None:
    app, port = await application()
    port.release.clear()
    await app.start()
    try:
        app.core.cognition.submit_input(admission(app.core, internal=True))
        await asyncio.wait_for(port.entered.wait(), 2)
        app.core.cognition.submit_input(admission(app.core, event_id="event-2", trace_id="trace-2"))
        outcome = await asyncio.wait_for(app.core.brain.next_outcome(), 2)
        assert outcome.module is BrainIntegrationModule.INPUT_MEANING
        assert outcome.status is BrainWorkStatus.COMPLETED
        app.core.cognition.cancel_trace("trace-1", "前景とは独立した取消")
        cancelled = await asyncio.wait_for(app.core.brain.next_outcome(), 2)
        assert cancelled.status is BrainWorkStatus.CANCELLED
    finally:
        await app.stop()

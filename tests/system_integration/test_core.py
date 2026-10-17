"""本番core構成を配送へ接続し、取消・現在性・独立した前景進行を検証する。"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.application import build_core
from app.config.llm_connections import LLMConnectionConfig
from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.domain.executive import GoalTransitionOperation
from app.domain.llm import LLMRoleDescriptor
from app.usecases.ports.llm import LLMRolePort
from tests.composition.test_system_cognition_configuration import parameters
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.helpers.brain_outcomes import next_outcome_matching
from tests.system_integration.test_core_cognition import Port, admission


class _PortLLMAdapter:
    """本番のLLM接続境界へ試験用Role Portを接続する。"""

    adapter_id = "openai_responses"

    def __init__(self, port: Port) -> None:
        self._port = port

    async def connect(
        self,
        connection: object,
        descriptors: tuple[LLMRoleDescriptor, ...],
    ) -> tuple[LLMRolePort, Callable[[], Awaitable[None]]]:
        if not isinstance(connection, LLMConnectionConfig):
            raise ValueError("接続設定の型が不正です")

        async def close() -> None:
            return None

        return self._port, close


async def application() -> tuple[Any, Port]:
    port = Port()
    params = parameters()
    params["llm_adapters"] = (_PortLLMAdapter(port),)
    return await build_core(**params), port


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [False, True])
async def test_production_policies_reach_delivery(internal: bool) -> None:
    app, port = await application()
    await app.start()
    try:
        app.core.cognition.submit_input(admission(app.core, internal=internal))
        modules = (
            (BrainIntegrationModule.APPRAISAL, BrainIntegrationModule.EXECUTIVE)
            if internal
            else (
                BrainIntegrationModule.INPUT_MEANING,
                BrainIntegrationModule.APPRAISAL,
                BrainIntegrationModule.EXECUTIVE,
            )
        )
        outcomes = [
            await next_outcome_matching(app.core.brain, trace_id="trace-1", module=module)
            for module in modules
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
        accepted = app.core.cognition.submit_input(admission(app.core, internal=True))
        await asyncio.wait_for(port.entered.wait(), 2)
        if operation == "stale":
            apply_goal(app.core.goals, GoalTransitionOperation.CREATE, 0)
            port.release.set()
        else:
            app.core.cognition.cancel_trace(
                "trace-1", "試験取消", supersede=operation == "supersede"
            )
        expected = {
            "cancel": BrainWorkStatus.CANCELLED,
            "supersede": BrainWorkStatus.SUPERSEDED,
            "stale": BrainWorkStatus.FAILED,
        }
        outcome = await next_outcome_matching(
            app.core.brain, work_id=accepted.work_id, status=expected[operation]
        )
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
        accepted = app.core.cognition.submit_input(admission(app.core, internal=True))
        await asyncio.wait_for(port.entered.wait(), 2)
        app.core.cognition.submit_input(admission(app.core, event_id="event-2", trace_id="trace-2"))
        outcome = await next_outcome_matching(
            app.core.brain,
            trace_id="trace-2",
            module=BrainIntegrationModule.INPUT_MEANING,
        )
        assert outcome.status is BrainWorkStatus.COMPLETED
        app.core.cognition.cancel_trace("trace-1", "前景とは独立した取消")
        cancelled = await next_outcome_matching(
            app.core.brain, work_id=accepted.work_id, status=BrainWorkStatus.CANCELLED
        )
        assert cancelled.status is BrainWorkStatus.CANCELLED
    finally:
        await app.stop()

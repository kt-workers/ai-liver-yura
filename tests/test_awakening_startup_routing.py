from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.domain.activities import ActivityResult
from app.domain.behavior import ActivityPlanEvaluation, BehaviorPlanningContext
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.runtime.behavior_planning_context_builder import BehaviorPlanningPreparation
from app.runtime.behavior_routing_coordinator import BehaviorRoutingCoordinator


class _ContextBuilder:
    def build(self, event: AgentEvent) -> BehaviorPlanningPreparation:
        return BehaviorPlanningPreparation(
            event=event,
            context=BehaviorPlanningContext(
                user_text="",
                source_event_id=event.event_id,
                available_capabilities=frozenset(),
                event_type=event.event_type.value,
                authority_role=event.authority.role,
                instruction_trusted=event.authority.instruction_trusted,
            ),
            ongoing_activity=None,
        )


class _Validator:
    def validate(self, plan: Any) -> ActivityPlanEvaluation:
        return ActivityPlanEvaluation(
            plan=plan,
            accepted=True,
            result=ActivityResult(
                result_type="activity_plan_accepted",
                summary="accepted",
            ),
        )


class _Fallback:
    def with_plugin_availability(self, event: AgentEvent) -> AgentEvent:
        return event

    def with_execution_fallback(self, *args: object, **kwargs: object) -> AgentEvent:
        raise AssertionError("startup plan must not be rejected")


@pytest.mark.asyncio
async def test_app_started_preserves_awakening_context_in_situation_analysis() -> None:
    awakening = {
        "startup_kind": "resume",
        "downtime_seconds": 420.0,
        "previous_inner_state": {"drive": {"energy": 0.72}},
        "capabilities": {
            "body_available": True,
            "tts_available": False,
            "conversation_output_available": True,
        },
    }
    coordinator = BehaviorRoutingCoordinator(
        planner=cast(Any, MagicMock()),
        validator=cast(Any, _Validator()),
        plugin_manager=cast(Any, object()),
        context_builder=cast(Any, _ContextBuilder()),
        confirmation_coordinator=None,
        plugin_activity_coordinator=cast(Any, object()),
        activity_switch_coordinator=cast(Any, object()),
        fallback_router=cast(Any, _Fallback()),
        trace_logger=cast(Any, MagicMock()),
    )
    event = AgentEvent(
        AgentEventType.APP_STARTED,
        payload={"source": "test", "awakening_context": awakening},
        authority=InputAuthority.SYSTEM,
    )

    routed = await coordinator.route(event)

    assert routed is not None
    situation = routed.payload["situation_analysis"]
    assert situation["lifecycle_phase"] == "awakening"
    assert situation["awakening_context"] == awakening
    assert routed.payload["behavior_plan"]["activity_type"] == "awakening"

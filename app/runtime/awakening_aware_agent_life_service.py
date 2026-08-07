from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.events import AgentEvent
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.awakening_aware_autonomous_event_planner import (
    AwakeningAwareAutonomousEventPlanner,
)
from app.runtime.awakening_lifecycle_policy import AwakeningLifecyclePolicy


class AwakeningAwareAgentLifeService(AgentLifeService):
    """既存Life Serviceへ覚醒Lifecycle進行だけを合成する。"""

    def __init__(
        self,
        *args: Any,
        awakening_lifecycle_policy: AwakeningLifecyclePolicy | None = None,
        **kwargs: Any,
    ) -> None:
        injected_autonomous_planner = kwargs.get("autonomous_event_planner")
        super().__init__(*args, **kwargs)
        self._awakening_lifecycle_policy = (
            awakening_lifecycle_policy or AwakeningLifecyclePolicy()
        )
        if injected_autonomous_planner is None:
            self._autonomous_event_planner = AwakeningAwareAutonomousEventPlanner(
                self._activity_manager,
                autonomous_activity_policy=self._autonomous_activity_policy,
                autonomous_plan_state=self._autonomous_plan_state,
                conversation_resume_state=self._conversation_resume_state,
                pending_confirmation_provider=self._pending_confirmation_provider,
                conversation_idle_timeout_seconds=self._conversation_idle_timeout_seconds,
            )

    def plan_next_event(self, now: datetime | None = None) -> AgentEvent | None:
        current_time = now or datetime.now(timezone.utc)
        self._advance_awakening(current_time)
        return super().plan_next_event(current_time)

    def _advance_awakening(self, now: datetime) -> None:
        current = self._agent_state.awakening_state
        if current is None or current.ready:
            return
        advanced = self._awakening_lifecycle_policy.advance(current, now=now)
        if advanced == current:
            return
        self._agent_state = self._agent_state.with_awakening_state(advanced)
        self._trace_logger.info(
            "awakening_lifecycle:transition",
            previous_phase=current.phase.value,
            next_phase=advanced.phase.value,
            readiness=advanced.appraisal.readiness,
            sleepiness=advanced.appraisal.sleepiness,
            activation_urge=advanced.appraisal.activation_urge,
            orientation_need=advanced.appraisal.orientation_need,
            security_need=advanced.appraisal.security_need,
        )
        if advanced.ready:
            self._awakening_completed_at = advanced.completed_at


__all__ = ["AwakeningAwareAgentLifeService"]

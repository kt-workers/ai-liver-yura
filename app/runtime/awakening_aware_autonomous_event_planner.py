from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.domain.awakening_state import AwakeningLifecyclePhase
from app.domain.topic import InterruptedTopic, TopicContinuationResult
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_event_planner import (
    AutonomousEventPlanResult,
    AutonomousEventPlanner,
)


class AwakeningAwareAutonomousEventPlanner(AutonomousEventPlanner):
    """新Awakening Lifecycleがある場合、一律settleではなくreadyを自律開始境界にする。"""

    def plan(
        self,
        state: AgentState,
        *,
        now: datetime,
        awakening_completed_at: datetime | None,
        continuation_provider: Callable[[], TopicContinuationResult | None],
        autonomous_topic_provider: Callable[[], InterruptedTopic | None],
    ) -> AutonomousEventPlanResult:
        awakening = state.awakening_state
        if (
            awakening is not None
            and awakening.phase is not AwakeningLifecyclePhase.READY
        ):
            return self._skip(
                "awakening_not_ready",
                log_level="debug",
                awakening_phase=awakening.phase.value,
                awakening_readiness=awakening.appraisal.readiness,
                awakening_sleepiness=awakening.appraisal.sleepiness,
                awakening_activation_urge=awakening.appraisal.activation_urge,
                awakening_orientation_need=awakening.appraisal.orientation_need,
                awakening_security_need=awakening.appraisal.security_need,
            )
        return super().plan(
            state,
            now=now,
            awakening_completed_at=(
                None if awakening is not None else awakening_completed_at
            ),
            continuation_provider=continuation_provider,
            autonomous_topic_provider=autonomous_topic_provider,
        )


__all__ = ["AwakeningAwareAutonomousEventPlanner"]

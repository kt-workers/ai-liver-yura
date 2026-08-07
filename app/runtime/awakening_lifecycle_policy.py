from __future__ import annotations

from datetime import datetime

from app.domain.awakening_state import (
    AwakeningLifecyclePhase,
    AwakeningState,
)


class AwakeningLifecyclePolicy:
    """覚醒Appraisalの強さから、Lifecycleの進行速度だけを決める。"""

    def advance(self, state: AwakeningState, *, now: datetime) -> AwakeningState:
        if state.ready:
            return state
        elapsed = max(0.0, (now - state.phase_started_at).total_seconds())
        appraisal = state.appraisal

        if state.phase is AwakeningLifecyclePhase.INITIALIZING:
            return state.transition(AwakeningLifecyclePhase.WAKING, at=now)

        if state.phase is AwakeningLifecyclePhase.WAKING:
            waking_seconds = (
                0.55
                + appraisal.sleepiness * 2.8
                + appraisal.orientation_need * 0.65
                + appraisal.security_need * 0.45
                - appraisal.activation_urge * 0.35
            )
            if elapsed >= max(0.35, waking_seconds):
                return state.transition(AwakeningLifecyclePhase.ORIENTING, at=now)
            return state

        if state.phase is AwakeningLifecyclePhase.ORIENTING:
            orienting_seconds = (
                0.45
                + appraisal.orientation_need * 2.1
                + appraisal.security_need * 1.2
                + appraisal.sleepiness * 0.55
                - appraisal.readiness * 0.45
            )
            if elapsed >= max(0.30, orienting_seconds):
                return state.transition(AwakeningLifecyclePhase.READY, at=now)
        return state


__all__ = ["AwakeningLifecyclePolicy"]

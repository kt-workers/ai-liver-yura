from __future__ import annotations

from dataclasses import dataclass

from app.domain.awakening import AwakeningContext
from app.domain.awakening_state import (
    AwakeningAppraisal,
    AwakeningLifecyclePhase,
    AwakeningState,
)
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_state import AgentState
from app.runtime.awakening_appraiser import AwakeningAppraiser, AwakeningContextParser
from app.runtime.awakening_state_projector import (
    AwakeningStateProjection,
    AwakeningStateProjector,
)


@dataclass(frozen=True, slots=True)
class AwakeningStateTransition:
    context: AwakeningContext
    appraisal: AwakeningAppraisal
    projection: AwakeningStateProjection
    awakening_state: AwakeningState


class AwakeningStateTransitionService:
    """APP_STARTEDの有限Contextを覚醒評価と内的状態変化へ変換する。"""

    def __init__(
        self,
        *,
        parser: AwakeningContextParser | None = None,
        appraiser: AwakeningAppraiser | None = None,
        projector: AwakeningStateProjector | None = None,
    ) -> None:
        self._parser = parser or AwakeningContextParser()
        self._appraiser = appraiser or AwakeningAppraiser()
        self._projector = projector or AwakeningStateProjector()

    def transition(
        self,
        state: AgentState,
        event: AgentEvent,
    ) -> AwakeningStateTransition | None:
        if event.event_type is not AgentEventType.APP_STARTED:
            return None
        context = self._parser.parse(event.payload.get("awakening_context"))
        if context is None:
            return None
        appraisal = self._appraiser.appraise(context)
        projection = self._projector.project(
            context=context,
            appraisal=appraisal,
            emotion=state.current_emotion,
            desire=state.current_desire,
            drive=state.current_drive,
        )
        awakening_state = AwakeningState(
            phase=AwakeningLifecyclePhase.INITIALIZING,
            appraisal=appraisal,
            started_at=event.occurred_at,
            phase_started_at=event.occurred_at,
        )
        return AwakeningStateTransition(
            context=context,
            appraisal=appraisal,
            projection=projection,
            awakening_state=awakening_state,
        )


__all__ = ["AwakeningStateTransition", "AwakeningStateTransitionService"]

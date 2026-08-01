from __future__ import annotations

from app.domain.emotions import EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.domain.morals import MoralProfile, MoralState
from app.domain.relationships import RelationshipState


class MoralStateUpdater:
    """Profile・感情・Eventから観測専用のMoral Stateを更新する。"""

    def update_by_event(
        self,
        current: MoralState,
        event: AgentEvent,
        *,
        profile: MoralProfile,
        emotion: EmotionState,
        relationship: RelationshipState | None = None,
    ) -> MoralState:
        target = self._target_state(profile, emotion, relationship)
        updated = self._blend(current, target, factor=0.20)

        if event.event_type in {
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        }:
            return updated.adjusted(
                empathy_activation=0.03,
                selfish_impulse=-0.01,
            )
        if event.event_type == AgentEventType.USER_INTERACTION:
            return updated.adjusted(empathy_activation=0.02)
        if event.event_type == AgentEventType.ACTION_FAILED:
            return updated.adjusted(
                restraint=0.02,
                aggressive_impulse=0.02,
                guilt=0.08,
            )
        if event.event_type == AgentEventType.ACTIVITY_RESULT_RECORDED:
            return self._apply_activity_outcome(updated, event.payload.get("outcome"))
        if event.event_type == AgentEventType.SPEECH_FINISHED:
            return updated.adjusted(
                selfish_impulse=-0.01,
                aggressive_impulse=-0.02,
            )
        return updated

    def update_by_elapsed_time(
        self,
        current: MoralState,
        *,
        profile: MoralProfile,
        emotion: EmotionState,
        elapsed_seconds: float,
        relationship: RelationshipState | None = None,
    ) -> MoralState:
        if elapsed_seconds <= 0.0:
            return current
        target = self._target_state(profile, emotion, relationship)
        factor = min(1.0, elapsed_seconds / 900.0)
        return self._blend(current, target, factor=factor)

    @classmethod
    def _target_state(
        cls,
        profile: MoralProfile,
        emotion: EmotionState,
        relationship: RelationshipState | None,
    ) -> MoralState:
        baseline = MoralState.from_profile(profile)
        reactive = emotion.reactive
        empathy_relationship_delta = 0.0
        if relationship is not None:
            normalized_affinity = (relationship.affinity + 1.0) / 2.0
            empathy_relationship_delta = (
                relationship.trust * 0.06
                + relationship.familiarity * 0.03
                + normalized_affinity * 0.03
            )

        return baseline.adjusted(
            restraint=(
                reactive.fear * 0.08
                + reactive.discomfort * 0.08
                - reactive.anger * 0.12
                - reactive.emotional_pressure * 0.05
            ),
            empathy_activation=(
                reactive.joy * 0.03
                + reactive.sadness * 0.05
                - reactive.anger * 0.04
                + empathy_relationship_delta
            ),
            selfish_impulse=(
                reactive.emotional_pressure * 0.08
                + reactive.anger * 0.05
            ),
            aggressive_impulse=(
                reactive.anger * 0.35
                + reactive.discomfort * 0.12
                + reactive.emotional_pressure * 0.10
            ),
            guilt=(
                reactive.sadness * 0.12
                + reactive.discomfort * 0.05
            ),
        )

    @staticmethod
    def _apply_activity_outcome(current: MoralState, outcome: object) -> MoralState:
        if outcome == "failed":
            return current.adjusted(restraint=0.02, guilt=0.08)
        if outcome == "partial":
            return current.adjusted(guilt=0.03)
        if outcome == "canceled":
            return current.adjusted(guilt=0.02)
        if outcome == "completed":
            return current.adjusted(guilt=-0.03, aggressive_impulse=-0.02)
        return current

    @staticmethod
    def _blend(current: MoralState, target: MoralState, *, factor: float) -> MoralState:
        normalized_factor = max(0.0, min(1.0, float(factor)))
        return MoralState(
            restraint=current.restraint
            + (target.restraint - current.restraint) * normalized_factor,
            empathy_activation=current.empathy_activation
            + (
                target.empathy_activation - current.empathy_activation
            )
            * normalized_factor,
            selfish_impulse=current.selfish_impulse
            + (target.selfish_impulse - current.selfish_impulse) * normalized_factor,
            aggressive_impulse=current.aggressive_impulse
            + (
                target.aggressive_impulse - current.aggressive_impulse
            )
            * normalized_factor,
            guilt=current.guilt + (target.guilt - current.guilt) * normalized_factor,
        )

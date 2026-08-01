from __future__ import annotations

from dataclasses import asdict, dataclass

from app.domain.desires import DesireState
from app.domain.drives import DriveState
from app.domain.emotions import EmotionAppraisal, EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.domain.memory import EmotionHistoryEntry, EpisodicMemory
from app.domain.morals import MoralState
from app.domain.relationships import RelationshipMemory, RelationshipState
from app.runtime.agent_state import AgentState
from app.runtime.desire_state_updater import DesireStateUpdater
from app.runtime.drive_state_updater import DriveStateUpdater
from app.runtime.emotion_appraiser import EmotionAppraiser
from app.runtime.emotion_state_updater import EmotionStateUpdater
from app.runtime.moral_state_updater import MoralStateUpdater
from app.runtime.relationship_state_updater import RelationshipStateUpdater


@dataclass(frozen=True, slots=True)
class AgentEventStateUpdateResult:
    state: AgentState
    appraisal: EmotionAppraisal
    before_drive: DriveState
    after_drive: DriveState
    before_desire: DesireState
    after_desire: DesireState
    before_emotion: EmotionState
    after_emotion: EmotionState
    before_moral: MoralState
    after_moral: MoralState
    relationship_memory: RelationshipMemory
    before_relationship: RelationshipState | None
    after_relationship: RelationshipState | None
    relationship_changed: bool
    input_source: str | None


class AgentEventStateUpdater:
    """EventからAgentStateの確定状態を構築する。"""

    def __init__(
        self,
        *,
        drive_state_updater: DriveStateUpdater | None = None,
        desire_state_updater: DesireStateUpdater | None = None,
        emotion_appraiser: EmotionAppraiser | None = None,
        emotion_state_updater: EmotionStateUpdater | None = None,
        moral_state_updater: MoralStateUpdater | None = None,
        relationship_state_updater: RelationshipStateUpdater | None = None,
    ) -> None:
        self._drive_state_updater = drive_state_updater or DriveStateUpdater()
        self._desire_state_updater = desire_state_updater or DesireStateUpdater()
        self._emotion_appraiser = emotion_appraiser or EmotionAppraiser()
        self._emotion_state_updater = emotion_state_updater or EmotionStateUpdater()
        self._moral_state_updater = moral_state_updater or MoralStateUpdater()
        self._relationship_state_updater = (
            relationship_state_updater or RelationshipStateUpdater()
        )

    def update(self, state: AgentState, event: AgentEvent) -> AgentEventStateUpdateResult:
        before_drive = state.current_drive
        before_desire = state.current_desire
        before_emotion = state.current_emotion
        before_moral = state.current_moral
        before_relationship = state.relationship_memory.current

        after_drive = self._drive_state_updater.update_by_event(before_drive, event)
        after_desire = self._desire_state_updater.update_by_event(before_desire, event)
        appraisal = self._emotion_appraiser.appraise(
            event,
            current_emotion=before_emotion,
            relationship=before_relationship,
            recent_history=state.memory.emotion_history,
        )
        after_emotion = self._emotion_state_updater.apply(before_emotion, appraisal)
        relationship_memory = self._relationship_state_updater.update(
            state.relationship_memory,
            event,
        )
        after_relationship = relationship_memory.current
        after_moral = self._moral_state_updater.update_by_event(
            before_moral,
            event,
            profile=state.moral_profile,
            emotion=after_emotion,
            relationship=after_relationship,
        )
        relationship_changed = (
            after_relationship is not None and after_relationship != before_relationship
        )
        attention_target = (
            after_relationship.counterpart_id
            if relationship_changed and after_relationship is not None
            else state.attention_target
        )
        source = event.payload.get("source")
        input_source = source if isinstance(source, str) and source.strip() else None

        updated = (
            state.with_drive(after_drive)
            .with_desire(after_desire)
            .with_emotion(after_emotion)
            .with_moral(after_moral)
            .with_relationship_memory(relationship_memory)
            .with_attention_target(attention_target)
            .with_memory(
                state.memory.remember_episode(
                    EpisodicMemory(
                        event_id=event.event_id,
                        event_type=event.event_type.value,
                        occurred_at=event.occurred_at,
                        activity_id=(
                            state.active_activity.activity_id
                            if state.active_activity is not None
                            else None
                        ),
                        counterpart_id=attention_target,
                    )
                ).record_emotion(
                    EmotionHistoryEntry(
                        source_event_id=event.event_id,
                        before=asdict(before_emotion),
                        after=asdict(after_emotion),
                        reason=appraisal.reason,
                        cause_category=(
                            appraisal.cause.category
                            if appraisal.cause is not None
                            else appraisal.reason
                        ),
                        cause_summary=(
                            appraisal.cause.summary
                            if appraisal.cause is not None
                            else ""
                        ),
                        target_id=(
                            appraisal.cause.target
                            if appraisal.cause is not None
                            else None
                        ),
                        confidence=appraisal.confidence,
                        relational_meaning=appraisal.relational_meaning.value,
                        recorded_at=event.occurred_at,
                    )
                )
            )
            .with_situation(
                state.current_situation.observe_event(
                    event_id=event.event_id,
                    event_type=event.event_type.value,
                    occurred_at=event.occurred_at,
                    input_source=input_source,
                    input_authority_role=event.authority.role,
                    attention_target=attention_target,
                )
            )
        )

        if event.event_type in {
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        }:
            updated = updated.mark_user_input_received(event.occurred_at)
        if event.event_type == AgentEventType.SPEECH_STARTED:
            updated = updated.mark_speech_started(event.occurred_at)
        if event.event_type == AgentEventType.SPEECH_FINISHED:
            updated = updated.mark_speech_finished(event.occurred_at)

        return AgentEventStateUpdateResult(
            state=updated,
            appraisal=appraisal,
            before_drive=before_drive,
            after_drive=after_drive,
            before_desire=before_desire,
            after_desire=after_desire,
            before_emotion=before_emotion,
            after_emotion=after_emotion,
            before_moral=before_moral,
            after_moral=after_moral,
            relationship_memory=relationship_memory,
            before_relationship=before_relationship,
            after_relationship=after_relationship,
            relationship_changed=relationship_changed,
            input_source=input_source,
        )

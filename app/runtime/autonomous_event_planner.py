from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.activities import ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.domain.topic import (
    InterruptedTopic,
    TopicContinuationDecision,
    TopicContinuationResult,
)
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
from app.runtime.autonomous_interaction_decider import AutonomousInteractionDecider
from app.runtime.autonomous_motivation_context import AutonomousMotivationContextBuilder
from app.runtime.autonomous_plan_state import AutonomousPlanState
from app.runtime.conversation_resume_state import ConversationResumeState
from app.runtime.interaction_expression_projector import InteractionExpressionProjector
from app.runtime.response_content_planner import ResponseContentPlanner


@dataclass(frozen=True, slots=True)
class AutonomousEventPlanResult:
    """自律イベント計画の成否と診断情報を返す。"""

    event: AgentEvent | None = None
    skip_reason: str | None = None
    log_event: str = "agent_life_service:plan_next_event:skipped"
    log_level: str = "write"
    details: dict[str, object] = field(default_factory=dict)

    @property
    def planned(self) -> bool:
        return self.event is not None


class AutonomousEventPlanner:
    """現在状態から次の自律発話Eventを計画する。"""

    def __init__(
        self,
        activity_manager: ActivityManager,
        *,
        autonomous_activity_policy: AutonomousActivityPolicy,
        autonomous_plan_state: AutonomousPlanState,
        conversation_resume_state: ConversationResumeState,
        pending_confirmation_provider: Callable[[], bool],
        conversation_idle_timeout_seconds: float,
        motivation_context_builder: AutonomousMotivationContextBuilder | None = None,
        response_content_planner: ResponseContentPlanner | None = None,
        autonomous_interaction_decider: AutonomousInteractionDecider | None = None,
        interaction_expression_projector: InteractionExpressionProjector | None = None,
    ) -> None:
        self._activity_manager = activity_manager
        self._autonomous_activity_policy = autonomous_activity_policy
        self._autonomous_plan_state = autonomous_plan_state
        self._conversation_resume_state = conversation_resume_state
        self._pending_confirmation_provider = pending_confirmation_provider
        self._conversation_idle_timeout_seconds = max(
            0.0, float(conversation_idle_timeout_seconds)
        )
        self._motivation_context_builder = (
            motivation_context_builder or AutonomousMotivationContextBuilder()
        )
        self._response_content_planner = (
            response_content_planner or ResponseContentPlanner()
        )
        self._autonomous_interaction_decider = (
            autonomous_interaction_decider or AutonomousInteractionDecider()
        )
        self._interaction_expression_projector = (
            interaction_expression_projector or InteractionExpressionProjector()
        )

    def plan(
        self,
        state: AgentState,
        *,
        now: datetime,
        awakening_completed_at: datetime | None,
        continuation_provider: Callable[[], TopicContinuationResult | None],
        autonomous_topic_provider: Callable[[], InterruptedTopic | None],
    ) -> AutonomousEventPlanResult:
        if self._pending_confirmation_provider():
            return self._skip("pending_confirmation_exists", log_level="debug")

        active_activity = state.active_activity
        is_autonomous_lookahead = (
            active_activity is not None
            and active_activity.activity_type == ActivityType.AUTONOMOUS_TALK
            and active_activity.context.get("action_plan_prepared") is True
            and self._activity_manager.pending_turn_count(active_activity.activity_id) < 2
            and not self._activity_manager.activity_completion_requested(
                active_activity.activity_id
            )
            and not state.pending_activities
            and not state.suspended_activities
        )

        if active_activity is not None and not is_autonomous_lookahead:
            return self._skip(
                "active_activity_exists",
                active_activity_type=active_activity.activity_type.value,
            )

        if state.pending_activities:
            return self._skip(
                "pending_activity_exists",
                pending_activity_count=len(state.pending_activities),
            )

        ongoing_activity = self._activity_manager.ongoing_activity
        if ongoing_activity is not None:
            self._conversation_resume_state.observe_ongoing_activity(
                ongoing_activity.ongoing_activity_id
            )
            return self._skip(
                "ongoing_activity_active",
                log_level="debug",
                ongoing_activity_id=ongoing_activity.ongoing_activity_id,
                ongoing_activity_type=ongoing_activity.activity_type,
            )

        awakening_settle_seconds = (
            self._autonomous_activity_policy.awakening_settle_seconds(
                state.current_emotion
            )
        )
        if self._is_within_pause(
            since=awakening_completed_at,
            now=now,
            pause_seconds=awakening_settle_seconds,
        ):
            return self._skip(
                "awakening_settle",
                log_level="debug",
                awakening_completed_at=awakening_completed_at,
                settle_seconds=awakening_settle_seconds,
                emotion_arousal=state.current_emotion.arousal,
                emotion_talkativeness=state.current_emotion.talkativeness,
            )

        resume_reason = self._conversation_resume_state.resolve_reason(
            last_user_input_at=state.last_user_input_at,
            now=now,
            idle_timeout_seconds=self._conversation_idle_timeout_seconds,
        )
        if resume_reason is None and self._is_within_pause(
            since=state.last_user_input_at,
            now=now,
            pause_seconds=self._conversation_idle_timeout_seconds,
        ):
            return self._skip(
                "conversation_idle_timeout_not_reached",
                log_level="debug",
                last_user_input_at=state.last_user_input_at,
                conversation_idle_timeout_seconds=(
                    self._conversation_idle_timeout_seconds
                ),
            )

        continuation_result = continuation_provider()
        autonomous_topic = autonomous_topic_provider()
        if continuation_result is not None and continuation_result.decision in {
            TopicContinuationDecision.WAIT,
            TopicContinuationDecision.SUSPEND_ORIGINAL,
            TopicContinuationDecision.ABANDON_ORIGINAL,
        }:
            return self._skip(
                "topic_continuation_no_event",
                log_event="agent_life_service:topic_continuation:no_event",
                log_level="debug",
                topic_id=autonomous_topic.topic_id if autonomous_topic else None,
                decision=continuation_result.decision.value,
                reasons=list(continuation_result.reasons),
            )

        if self._autonomous_activity_policy.should_defer_talking(
            state.current_emotion
        ):
            return self._skip(
                "emotion_reduces_speech",
                emotion_mood=state.current_emotion.mood.value,
                emotion_talkativeness=state.current_emotion.talkativeness,
            )

        motivation = self._motivation_context_builder.build(state)
        moral_value = motivation.get("moral")
        moral = moral_value if isinstance(moral_value, dict) else {}
        response_content_plan = self._response_content_planner.build(
            motivation=motivation,
            moral=moral,
        )
        start_decision, start_comparison = (
            self._autonomous_interaction_decider.decide(
                state,
                motivation=motivation,
                continuation_result=continuation_result,
                autonomous_topic=autonomous_topic,
                resume_reason=resume_reason,
                is_autonomous_lookahead=is_autonomous_lookahead,
            )
        )
        decision_details = {
            "interaction_action": start_decision.action.value,
            "interaction_intention": (
                start_decision.interaction_intention.intention.value
            ),
            "interaction_intention_reason": (
                start_decision.interaction_intention.reason
            ),
            "interaction_intention_confidence": start_decision.confidence,
            "interaction_primary_desire": (
                start_decision.interaction_intention.primary_desire
            ),
            **start_comparison.as_context(),
        }

        if not start_comparison.legacy_drive_ready:
            return self._skip(
                "drive_too_weak",
                drive_curiosity=state.current_drive.curiosity,
                drive_engagement=state.current_drive.engagement,
                drive_boredom=state.current_drive.boredom,
                drive_energy=state.current_drive.energy,
                **decision_details,
            )

        if not start_comparison.conservative_start_allowed:
            return self._skip(
                "interaction_intention_wait",
                emotion_mood=state.current_emotion.mood.value,
                emotion_arousal=state.current_emotion.arousal,
                emotion_talkativeness=state.current_emotion.talkativeness,
                drive_curiosity=state.current_drive.curiosity,
                drive_engagement=state.current_drive.engagement,
                drive_boredom=state.current_drive.boredom,
                drive_energy=state.current_drive.energy,
                **decision_details,
            )

        minimum_pause_seconds = (
            self._autonomous_activity_policy.minimum_talk_interval_seconds(
                state.current_emotion
            )
        )
        if not is_autonomous_lookahead and self._is_within_pause(
            since=state.last_speech_finished_at,
            now=now,
            pause_seconds=minimum_pause_seconds,
        ):
            return self._skip(
                "after_speech_pause",
                pause_seconds=minimum_pause_seconds,
                last_speech_finished_at=state.last_speech_finished_at,
                **decision_details,
            )

        if (
            not is_autonomous_lookahead
            and resume_reason is None
            and self._is_within_pause(
                since=state.last_user_input_at,
                now=now,
                pause_seconds=minimum_pause_seconds,
            )
        ):
            return self._skip(
                "after_user_input_pause",
                pause_seconds=minimum_pause_seconds,
                last_user_input_at=state.last_user_input_at,
                **decision_details,
            )

        autonomous_talk_interval_seconds = self._autonomous_talk_interval_seconds(
            state
        )
        if self._autonomous_plan_state.is_retry_backoff_active(now):
            return self._skip(
                "autonomous_plan_retry_backoff",
                backoff_seconds=self._autonomous_plan_state.reconsider_after_seconds,
                last_rejected_at=self._autonomous_plan_state.last_rejected_at,
                **decision_details,
            )

        if (
            not is_autonomous_lookahead
            and self._autonomous_plan_state.is_talk_interval_active(
                now, autonomous_talk_interval_seconds
            )
        ):
            return self._skip(
                "autonomous_talk_interval",
                interval_seconds=autonomous_talk_interval_seconds,
                last_autonomous_talk_planned_at=(
                    self._autonomous_plan_state.last_accepted_at
                ),
                emotion_arousal=state.current_emotion.arousal,
                emotion_talkativeness=state.current_emotion.talkativeness,
                drive_energy=state.current_drive.energy,
                **decision_details,
            )

        intention_context = start_decision.interaction_intention.as_context()
        expression_context = self._interaction_expression_projector.project(
            start_decision.interaction_intention
        ).as_context()
        payload: dict[str, Any] = {
            "reason": "internal_drive",
            "drive": state.current_drive.strongest_drive_name(),
            "motivation": motivation,
            "interaction_intention": intention_context,
            "interaction_expression": expression_context,
            "autonomous_start_decision": start_decision.as_context(),
            "autonomous_start_comparison": start_comparison.as_context(),
            "memory": {
                "response_content_plan": response_content_plan.as_context(),
                "interaction_intention": intention_context,
                "interaction_expression": expression_context,
            },
            "autonomous_planned_for": now.isoformat(),
            "interaction_environment": {
                "observation_source": "internal_state",
                "input_authority_role": "system",
                "direct_user_addressed": False,
                "ambient_activity_observed": False,
                "foreground_activity_kind": None,
                "interruption_cost": "unknown",
            },
        }
        if is_autonomous_lookahead:
            payload["lookahead"] = True
        if resume_reason is not None and resume_reason != "no_conversation":
            payload["resume_reason"] = resume_reason
        if continuation_result is not None:
            payload.update(
                {
                    "continuation_decision": continuation_result.decision.value,
                    "continuation_reasons": list(continuation_result.reasons),
                    "reintroduction_required": (
                        continuation_result.reintroduction_required
                    ),
                    "selected_topic": continuation_result.selected_topic,
                    "interrupted_topic": (
                        autonomous_topic.original_text
                        if autonomous_topic is not None
                        else None
                    ),
                }
            )

        event = AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload=payload,
            priority=10,
            discardable=True,
            replace_key="agent_life_service:curiosity_peak",
        )
        return AutonomousEventPlanResult(
            event=event,
            log_event="agent_life_service:plan_next_event:planned",
            details={
                "event_type": event.event_type.value,
                "reason": "internal_drive",
                "drive": state.current_drive.strongest_drive_name(),
                "motivation_top_desires": [
                    item.get("desire_type")
                    for item in motivation.get("ranked_desires", [])
                    if isinstance(item, dict)
                ],
                "drive_curiosity": state.current_drive.curiosity,
                "drive_engagement": state.current_drive.engagement,
                "drive_boredom": state.current_drive.boredom,
                "drive_energy": state.current_drive.energy,
                "autonomous_talk_interval_seconds": (
                    autonomous_talk_interval_seconds
                ),
                "emotion_arousal": state.current_emotion.arousal,
                "emotion_talkativeness": state.current_emotion.talkativeness,
                "resume_reason": resume_reason,
                **decision_details,
            },
        )

    @staticmethod
    def _skip(
        reason: str,
        *,
        log_event: str = "agent_life_service:plan_next_event:skipped",
        log_level: str = "write",
        **details: object,
    ) -> AutonomousEventPlanResult:
        return AutonomousEventPlanResult(
            skip_reason=reason,
            log_event=log_event,
            log_level=log_level,
            details={"reason": reason, **details},
        )

    @staticmethod
    def _is_within_pause(
        *,
        since: datetime | None,
        now: datetime,
        pause_seconds: float,
    ) -> bool:
        if since is None:
            return False
        return (now - since).total_seconds() < pause_seconds

    @staticmethod
    def _autonomous_talk_interval_seconds(state: AgentState) -> float:
        emotion = state.current_emotion
        drive = state.current_drive
        tension = (
            emotion.arousal * 0.45
            + emotion.talkativeness * 0.45
            + drive.energy * 0.10
        )
        tension = max(0.0, min(1.0, tension))
        minimum_interval_seconds = 8.0
        maximum_interval_seconds = 60.0
        return maximum_interval_seconds - (
            (maximum_interval_seconds - minimum_interval_seconds) * tension
        )

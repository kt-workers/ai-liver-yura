from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.domain.autonomous_interaction import (
    AutonomousInteractionAction,
    AutonomousInteractionComparison,
    AutonomousInteractionDecision,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.domain.topic import (
    InterruptedTopic,
    TopicContinuationDecision,
    TopicContinuationResult,
)
from app.runtime.agent_state import AgentState
from app.utils.trace import TraceLogger


class AutonomousInteractionDecider:
    """現在の心理状態から、自律的に関わり始めるかを決定する。"""

    _CONTINUATION_START_DECISIONS = {
        TopicContinuationDecision.RESUME_ORIGINAL,
        TopicContinuationDecision.RESUME_WITH_REFRAMING,
        TopicContinuationDecision.BRANCH_FROM_ORIGINAL,
        TopicContinuationDecision.BRANCH_FROM_INTERRUPTION,
        TopicContinuationDecision.START_NEW_TOPIC,
    }

    def __init__(self, trace_logger: TraceLogger | None = None) -> None:
        self._trace_logger = trace_logger or TraceLogger()

    def decide(
        self,
        state: AgentState,
        *,
        motivation: Mapping[str, object],
        continuation_result: TopicContinuationResult | None,
        autonomous_topic: InterruptedTopic | None,
        resume_reason: str | None,
        is_autonomous_lookahead: bool,
    ) -> tuple[AutonomousInteractionDecision, AutonomousInteractionComparison]:
        legacy_ready = state.current_drive.should_start_autonomous_talk()
        primary_desire = self._optional_text(motivation.get("primary_desire"))
        decision = self._decide(
            state,
            motivation=motivation,
            primary_desire=primary_desire,
            continuation_result=continuation_result,
            autonomous_topic=autonomous_topic,
            resume_reason=resume_reason,
            is_autonomous_lookahead=is_autonomous_lookahead,
            legacy_ready=legacy_ready,
        )
        comparison = AutonomousInteractionComparison.compare(
            legacy_drive_ready=legacy_ready,
            causal_should_start=decision.should_start,
        )
        self._trace_logger.info(
            "autonomous_interaction:decision_compared",
            action=decision.action.value,
            interaction_intention=(
                decision.interaction_intention.intention.value
            ),
            intention_reason=decision.interaction_intention.reason,
            decision_reason=decision.reason,
            confidence=decision.confidence,
            primary_desire=primary_desire,
            legacy_drive_ready=legacy_ready,
            causal_should_start=decision.should_start,
            matched=comparison.matched,
            conservative_start_allowed=(
                comparison.conservative_start_allowed
            ),
            expansion_blocked=comparison.expansion_blocked,
            causal_vetoed_legacy_start=(
                comparison.causal_vetoed_legacy_start
            ),
            resume_reason=resume_reason,
            continuation_decision=(
                continuation_result.decision.value
                if continuation_result is not None
                else None
            ),
            autonomous_topic_available=autonomous_topic is not None,
            is_autonomous_lookahead=is_autonomous_lookahead,
            emotion_mood=state.current_emotion.mood.value,
            emotion_arousal=state.current_emotion.arousal,
            emotion_talkativeness=state.current_emotion.talkativeness,
            drive_curiosity=state.current_drive.curiosity,
            drive_engagement=state.current_drive.engagement,
            drive_boredom=state.current_drive.boredom,
            drive_energy=state.current_drive.energy,
        )
        return decision, comparison

    def _decide(
        self,
        state: AgentState,
        *,
        motivation: Mapping[str, object],
        primary_desire: str | None,
        continuation_result: TopicContinuationResult | None,
        autonomous_topic: InterruptedTopic | None,
        resume_reason: str | None,
        is_autonomous_lookahead: bool,
        legacy_ready: bool,
    ) -> AutonomousInteractionDecision:
        if is_autonomous_lookahead:
            return self._decision(
                AutonomousInteractionAction.START,
                InteractionIntentionType.SHARE,
                0.98,
                "prepared_autonomous_activity_needs_lookahead",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
            )

        if (
            continuation_result is not None
            and continuation_result.decision in self._CONTINUATION_START_DECISIONS
            and autonomous_topic is not None
        ):
            return self._decision(
                AutonomousInteractionAction.START,
                InteractionIntentionType.SHARE,
                0.94,
                "topic_continuation_authorizes_reintroduction",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
                target_type="topic",
                target_id=autonomous_topic.topic_id,
            )

        emotion = state.current_emotion
        drive = state.current_drive
        tension = max(
            emotion.reactive.fear,
            emotion.reactive.discomfort,
            emotion.reactive.emotional_pressure,
            emotion.reactive.anger,
        )
        security_conflict = self._has_security_conflict(motivation)
        if (
            primary_desire == "security"
            or security_conflict
            or tension >= 0.48
        ):
            return self._decision(
                AutonomousInteractionAction.WAIT,
                InteractionIntentionType.PAUSE,
                0.90,
                "security_or_tension_prefers_waiting",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
                requires_response=False,
            )

        if drive.energy < 0.30 or emotion.talkativeness < 0.30:
            return self._decision(
                AutonomousInteractionAction.WAIT,
                InteractionIntentionType.PAUSE,
                0.92,
                "insufficient_energy_or_talkativeness",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
                requires_response=False,
            )

        expression_strength = self._number(
            motivation.get("expression_strength"),
            default=0.5,
        )
        if primary_desire in {"expression", "autonomy"}:
            if expression_strength >= 0.35:
                return self._decision(
                    AutonomousInteractionAction.START,
                    InteractionIntentionType.SHARE,
                    0.82,
                    "expression_motivation_prefers_self_initiated_share",
                    primary_desire,
                    legacy_ready,
                    resume_reason,
                    continuation_result,
                )
            return self._decision(
                AutonomousInteractionAction.OBSERVE,
                InteractionIntentionType.OBSERVE,
                0.75,
                "expression_motivation_is_not_ready_to_surface",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
                requires_response=False,
            )

        if primary_desire == "connection":
            relationship = state.relationship_memory.current
            if (
                relationship is not None
                and drive.engagement >= 0.62
                and expression_strength >= 0.42
            ):
                return self._decision(
                    AutonomousInteractionAction.START,
                    InteractionIntentionType.INVITE,
                    0.78,
                    "connection_motivation_and_relationship_allow_invitation",
                    primary_desire,
                    legacy_ready,
                    resume_reason,
                    continuation_result,
                    target_type="counterpart",
                    target_id=relationship.counterpart_id,
                )
            return self._decision(
                AutonomousInteractionAction.OBSERVE,
                InteractionIntentionType.LISTEN,
                0.74,
                "connection_motivation_without_open_interaction_window",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
                requires_response=False,
            )

        if primary_desire == "curiosity":
            strategies = self._strings(
                motivation.get("recommended_conversation_strategies")
            )
            if (
                drive.curiosity >= 0.70
                and expression_strength >= 0.35
                and "explore_related_topic" in strategies
            ):
                return self._decision(
                    AutonomousInteractionAction.START,
                    InteractionIntentionType.SHARE,
                    0.76,
                    "curiosity_prefers_sharing_without_unsolicited_question",
                    primary_desire,
                    legacy_ready,
                    resume_reason,
                    continuation_result,
                )
            return self._decision(
                AutonomousInteractionAction.OBSERVE,
                InteractionIntentionType.OBSERVE,
                0.76,
                "curiosity_not_yet_grounded_for_speech",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
                requires_response=False,
            )

        if primary_desire in {"achievement", "recognition"}:
            activity_type = self._first_string(
                motivation.get("recommended_activity_types")
            )
            return self._decision(
                AutonomousInteractionAction.OBSERVE,
                InteractionIntentionType.ACT,
                0.72,
                "non_speech_activity_motivation_does_not_start_talk",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
                activity_type=activity_type,
                requires_response=False,
            )

        if drive.engagement >= 0.75 and expression_strength >= 0.45:
            return self._decision(
                AutonomousInteractionAction.START,
                InteractionIntentionType.SHARE,
                0.66,
                "general_engagement_supports_brief_self_initiated_share",
                primary_desire,
                legacy_ready,
                resume_reason,
                continuation_result,
            )

        return self._decision(
            AutonomousInteractionAction.OBSERVE,
            InteractionIntentionType.OBSERVE,
            0.62,
            "no_causal_reason_to_claim_the_turn",
            primary_desire,
            legacy_ready,
            resume_reason,
            continuation_result,
            requires_response=False,
        )

    @staticmethod
    def _decision(
        action: AutonomousInteractionAction,
        intention: InteractionIntentionType,
        confidence: float,
        reason: str,
        primary_desire: str | None,
        legacy_ready: bool,
        resume_reason: str | None,
        continuation_result: TopicContinuationResult | None,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        activity_type: str | None = None,
        requires_response: bool = True,
    ) -> AutonomousInteractionDecision:
        interaction_intention = InteractionIntention(
            intention=intention,
            confidence=confidence,
            source="autonomous_motivation_appraisal",
            reason=reason,
            primary_desire=primary_desire,
            target_type=target_type,
            target_id=target_id,
            activity_type=activity_type,
            requires_response=requires_response,
        )
        return AutonomousInteractionDecision(
            action=action,
            interaction_intention=interaction_intention,
            confidence=confidence,
            reason=reason,
            legacy_drive_ready=legacy_ready,
            conversation_resume_reason=resume_reason,
            topic_continuation=(
                continuation_result.decision.value
                if continuation_result is not None
                else None
            ),
        )

    @classmethod
    def _has_security_conflict(cls, motivation: Mapping[str, object]) -> bool:
        conflicts = motivation.get("conflicts")
        if not isinstance(conflicts, Sequence) or isinstance(conflicts, (str, bytes)):
            return False
        for item in conflicts:
            if not isinstance(item, Mapping):
                continue
            reason = cls._optional_text(item.get("reason"))
            if reason is not None and "security" in reason:
                return True
        return False

    @staticmethod
    def _strings(value: object) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return ()
        return tuple(
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )

    @classmethod
    def _first_string(cls, value: object) -> str | None:
        values = cls._strings(value)
        return values[0] if values else None

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
        return None

    @staticmethod
    def _number(value: object, *, default: float) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
        return default

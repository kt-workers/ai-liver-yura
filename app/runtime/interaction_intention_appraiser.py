from __future__ import annotations

from collections.abc import Mapping

from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    StructuredInputMeaning,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)


class InteractionIntentionAppraiser:
    """意味上の応答義務とMotivationを有限の対人的意図へ変換する。"""

    def appraise(
        self,
        meaning: StructuredInputMeaning,
        planning_input: Mapping[str, object],
    ) -> InteractionIntention:
        motivation = self._mapping(planning_input.get("motivation"))
        emotion = self._mapping(planning_input.get("emotion"))
        relationship = self._mapping(planning_input.get("relationship"))
        primary_desire = self._text(motivation.get("primary_desire"))
        target_type = meaning.target.target_type if meaning.target is not None else None
        target_id = meaning.target.target_id if meaning.target is not None else None

        explicit = self._explicit_meaning_intention(
            meaning,
            primary_desire=primary_desire,
            emotion=emotion,
            target_type=target_type,
            target_id=target_id,
        )
        if explicit is not None:
            return explicit

        negative_affect = max(
            self._number(emotion, "anger"),
            self._number(emotion, "fear"),
            self._number(emotion, "discomfort"),
            self._number(emotion, "emotional_pressure"),
        )
        if primary_desire == "security":
            intention = (
                InteractionIntentionType.SET_BOUNDARY
                if negative_affect >= 0.40
                else InteractionIntentionType.PAUSE
            )
            return self._build(
                intention,
                0.78,
                "motivation_appraisal",
                "security_desire_shapes_interaction",
                primary_desire,
                target_type,
                target_id,
            )

        if primary_desire == "connection":
            if max(
                self._number(emotion, "sadness"),
                self._number(emotion, "fear"),
            ) >= 0.35:
                intention = InteractionIntentionType.COMFORT
                reason = "connection_desire_with_distress"
            elif self._relationship_openness(relationship) >= 0.62:
                intention = InteractionIntentionType.INVITE
                reason = "connection_desire_with_relationship_openness"
            else:
                intention = InteractionIntentionType.LISTEN
                reason = "connection_desire_prefers_receptive_contact"
            return self._build(
                intention,
                0.72,
                "motivation_appraisal",
                reason,
                primary_desire,
                target_type,
                target_id,
            )

        if primary_desire == "curiosity":
            if self._target_has_knowledge_gap(meaning, planning_input):
                intention = InteractionIntentionType.ASK
                reason = "target_specific_gap_authorizes_question"
            else:
                intention = InteractionIntentionType.OBSERVE
                reason = "global_curiosity_does_not_authorize_question"
            return self._build(
                intention,
                0.74,
                "motivation_appraisal",
                reason,
                primary_desire,
                target_type,
                target_id,
            )

        if primary_desire in {"expression", "autonomy"}:
            return self._build(
                InteractionIntentionType.SHARE,
                0.70,
                "motivation_appraisal",
                "expression_or_autonomy_prefers_self_expression",
                primary_desire,
                target_type,
                target_id,
            )

        if primary_desire in {"achievement", "recognition"} and self._has_activity(
            motivation
        ):
            return self._build(
                InteractionIntentionType.ACT,
                0.68,
                "motivation_appraisal",
                "goal_or_contribution_motivation_prefers_activity",
                primary_desire,
                target_type,
                target_id,
                activity_type=self._first_activity(motivation),
            )

        return self._build(
            InteractionIntentionType.OBSERVE,
            0.55,
            "motivation_appraisal",
            "no_strong_interaction_direction",
            primary_desire,
            target_type,
            target_id,
            requires_response=False,
        )

    def _explicit_meaning_intention(
        self,
        meaning: StructuredInputMeaning,
        *,
        primary_desire: str | None,
        emotion: Mapping[str, object],
        target_type: str | None,
        target_id: str | None,
    ) -> InteractionIntention | None:
        common = {
            "primary_desire": primary_desire,
            "target_type": target_type,
            "target_id": target_id,
        }
        if meaning.expected_response is ExpectedResponse.ACTION:
            return self._build(
                InteractionIntentionType.ACT,
                0.98,
                "structured_input_meaning",
                "input_requires_action_intention",
                **common,
                activity_type=(target_id if target_type == "activity" else None),
                operation=self._operation_from_intent(meaning.primary_intent),
            )
        if (
            meaning.expected_response is ExpectedResponse.DIRECT_ANSWER
            or meaning.input_speech_act is InputSpeechAct.QUESTION
        ):
            return self._build(
                InteractionIntentionType.ANSWER,
                0.98,
                "structured_input_meaning",
                "input_requires_direct_answer",
                **common,
            )
        if meaning.expected_response is ExpectedResponse.NO_RESPONSE:
            return self._build(
                InteractionIntentionType.PAUSE,
                0.97,
                "structured_input_meaning",
                "input_requests_no_response",
                **common,
                requires_response=False,
            )
        if meaning.input_speech_act is InputSpeechAct.CLOSING:
            return self._build(
                InteractionIntentionType.ACKNOWLEDGE,
                0.96,
                "structured_input_meaning",
                "closing_requires_brief_acknowledgement",
                **common,
            )
        if meaning.input_speech_act is InputSpeechAct.ACKNOWLEDGEMENT:
            return self._build(
                InteractionIntentionType.LISTEN,
                0.94,
                "structured_input_meaning",
                "acknowledgement_prefers_listening",
                **common,
            )
        if meaning.expected_response is ExpectedResponse.CONTINUE_LISTENING:
            return self._build(
                InteractionIntentionType.LISTEN,
                0.94,
                "structured_input_meaning",
                "input_requests_continued_listening",
                **common,
            )
        if meaning.expected_response is ExpectedResponse.ACKNOWLEDGEMENT:
            intent = meaning.primary_intent.casefold()
            distress_tokens = (
                "negative",
                "sad",
                "fear",
                "loss",
                "problem",
                "つら",
                "辛",
                "悲",
                "困",
            )
            if any(token in intent for token in distress_tokens) or max(
                self._number(emotion, "sadness"),
                self._number(emotion, "fear"),
            ) >= 0.40:
                intention = InteractionIntentionType.COMFORT
                reason = "acknowledgement_of_distress_prefers_comfort"
            else:
                intention = InteractionIntentionType.ACKNOWLEDGE
                reason = "input_requires_acknowledgement"
            return self._build(
                intention,
                0.93,
                "structured_input_meaning",
                reason,
                **common,
            )
        return None

    @staticmethod
    def _build(
        intention: InteractionIntentionType,
        confidence: float,
        source: str,
        reason: str,
        primary_desire: str | None,
        target_type: str | None,
        target_id: str | None,
        *,
        activity_type: str | None = None,
        operation: str | None = None,
        requires_response: bool = True,
    ) -> InteractionIntention:
        return InteractionIntention(
            intention=intention,
            confidence=confidence,
            source=source,
            reason=reason,
            primary_desire=primary_desire,
            target_type=target_type,
            target_id=target_id,
            activity_type=activity_type,
            operation=operation,
            requires_response=requires_response,
        )

    @classmethod
    def _target_has_knowledge_gap(
        cls,
        meaning: StructuredInputMeaning,
        planning_input: Mapping[str, object],
    ) -> bool:
        target = meaning.target
        if target is None:
            return False
        related = planning_input.get("related_knowledge")
        if not isinstance(related, list):
            return False
        for item in related:
            if not isinstance(item, Mapping):
                continue
            item_type = str(item.get("target_type") or item.get("type") or "")
            item_id = str(item.get("target_id") or item.get("id") or "")
            if item_type.casefold() != target.target_type.casefold():
                continue
            if item_id.casefold() != target.target_id.casefold():
                continue
            for key in (
                "knowledge_gaps",
                "unresolved_knowledge_gaps",
                "unresolved_questions",
                "gaps",
            ):
                value = item.get(key)
                if isinstance(value, list) and any(str(entry).strip() for entry in value):
                    return True
                if isinstance(value, str) and value.strip():
                    return True
        return False

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @classmethod
    def _number(cls, context: Mapping[str, object], key: str) -> float:
        candidates = (
            context.get(key),
            cls._mapping(context.get("reactive")).get(key),
            cls._mapping(context.get("current")).get(key),
            cls._mapping(cls._mapping(context.get("current")).get("reactive")).get(key),
        )
        for value in candidates:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return 0.0

    @staticmethod
    def _text(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
        return None

    @classmethod
    def _relationship_openness(cls, relationship: Mapping[str, object]) -> float:
        trust = cls._number(relationship, "trust")
        familiarity = cls._number(relationship, "familiarity")
        affinity = cls._number(relationship, "affinity")
        normalized_affinity = (max(-1.0, min(1.0, affinity)) + 1.0) / 2.0
        return max(
            0.0,
            min(1.0, trust * 0.4 + familiarity * 0.3 + normalized_affinity * 0.3),
        )

    @staticmethod
    def _has_activity(motivation: Mapping[str, object]) -> bool:
        activities = motivation.get("recommended_activity_types")
        return isinstance(activities, list) and bool(activities)

    @staticmethod
    def _first_activity(motivation: Mapping[str, object]) -> str | None:
        activities = motivation.get("recommended_activity_types")
        if not isinstance(activities, list) or not activities:
            return None
        value = activities[0]
        return str(value).strip() or None

    @staticmethod
    def _operation_from_intent(primary_intent: str) -> str | None:
        normalized = primary_intent.casefold()
        for token, operation in (
            ("continue", "continue"),
            ("resume", "continue"),
            ("stop", "stop"),
            ("explain", "explain"),
            ("discuss", "discuss"),
            ("start", "start"),
            ("再開", "continue"),
            ("続", "continue"),
            ("停止", "stop"),
            ("説明", "explain"),
            ("開始", "start"),
        ):
            if token in normalized:
                return operation
        return None

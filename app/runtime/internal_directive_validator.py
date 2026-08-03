from __future__ import annotations

import json
from dataclasses import replace

from app.domain.cognitive_direction import (
    ActivityIntent,
    ExpectedResponse,
    InputSpeechAct,
    InterestChange,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
    TargetInterestUpdate,
    ValidatedActionPlan,
)


class InternalDirectiveValidator:
    """LLM候補をCore側の上限・存在境界・Activity Registryで確定する。"""

    def validate(
        self,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> ValidatedActionPlan:
        notes: list[str] = []
        response_mode = directive.response_mode
        question_budget = min(directive.question_budget, 1)
        new_direction_budget = min(directive.new_direction_budget, 1)
        initiative_level = directive.initiative_level
        self_disclosure_level = directive.self_disclosure_level
        target_interest_updates = directive.target_interest_updates
        activity_intent = self._validated_activity_intent(
            directive.activity_intent,
            planning_input,
        )
        if directive.activity_intent is not None and activity_intent is None:
            notes.append("activity_intent_rejected_by_registry")

        if meaning.expected_response is ExpectedResponse.DIRECT_ANSWER or (
            meaning.input_speech_act is InputSpeechAct.QUESTION
        ):
            if activity_intent is not None:
                activity_intent = None
                notes.append("direct_question_rejects_activity_intent")
            response_mode = ResponseMode.ANSWER
            question_budget = 0
            new_direction_budget = 0
            initiative_level = min(initiative_level, 0.35)
            if self._is_internal_state_target(meaning):
                self_disclosure_level = max(self_disclosure_level, 0.35)
                notes.append("internal_state_question_allows_direct_disclosure")
            notes.append("direct_question_forces_answer")
        elif meaning.input_speech_act is InputSpeechAct.ACKNOWLEDGEMENT:
            if activity_intent is not None:
                activity_intent = None
                notes.append("acknowledgement_rejects_activity_intent")
            if response_mode not in {ResponseMode.LISTEN, ResponseMode.REACT}:
                response_mode = ResponseMode.LISTEN
                notes.append("acknowledgement_prevents_topic_expansion")
            question_budget = 0
            new_direction_budget = 0
            initiative_level = min(initiative_level, 0.25)
        elif meaning.input_speech_act is InputSpeechAct.CLOSING:
            if activity_intent is not None:
                activity_intent = None
                notes.append("closing_rejects_activity_intent")
            response_mode = ResponseMode.REACT
            question_budget = 0
            new_direction_budget = 0
            initiative_level = min(initiative_level, 0.15)
            notes.append("closing_forces_brief_farewell")

        if response_mode is ResponseMode.ASK and not self._has_target_question_signal(
            target_interest_updates
        ):
            response_mode = ResponseMode.LISTEN
            question_budget = 0
            new_direction_budget = 0
            notes.append("global_curiosity_does_not_authorize_question")

        requirements = list(directive.content_requirements)
        forbidden_claims = list(directive.forbidden_claims)
        if meaning.input_speech_act is InputSpeechAct.CLOSING:
            requirements.append(
                "短い別れの挨拶を1文で返し、speechを空にしない"
            )
            forbidden_claims.append(
                "会話を再開する質問、新しい話題、長い説明を追加する"
            )
        existence_boundaries = self._existence_boundaries(character_profile)
        impossible_embodied_experience = self._is_impossible_embodied_experience(
            meaning,
            existence_boundaries,
        )
        if impossible_embodied_experience and target_interest_updates:
            target_interest_updates = ()
            notes.append("impossible_embodied_experience_rejects_knowledge_gaps")
        self._add_internal_state_requirements(
            meaning,
            planning_input,
            requirements,
            forbidden_claims,
        )
        self._add_existence_constraints(
            meaning,
            existence_boundaries,
            requirements,
            forbidden_claims,
        )
        validated = replace(
            directive,
            response_mode=response_mode,
            activity_intent=activity_intent,
            initiative_level=initiative_level,
            question_budget=question_budget,
            new_direction_budget=new_direction_budget,
            self_disclosure_level=self_disclosure_level,
            content_requirements=tuple(dict.fromkeys(requirements)),
            forbidden_claims=tuple(dict.fromkeys(forbidden_claims)),
            target_interest_updates=target_interest_updates,
        )
        return ValidatedActionPlan(
            meaning=meaning,
            directive=validated,
            validation_notes=tuple(notes),
            character_profile=character_profile,
            existence_boundaries=existence_boundaries,
        )

    @staticmethod
    def _validated_activity_intent(
        intent: ActivityIntent | None,
        planning_input: dict[str, object],
    ) -> ActivityIntent | None:
        if intent is None:
            return None
        activities = planning_input.get("available_activities")
        if not isinstance(activities, list):
            return None
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            if str(activity.get("activity_type")) != intent.activity_type:
                continue
            operations = activity.get("supported_operations")
            if not isinstance(operations, list) or intent.operation not in {
                str(value) for value in operations
            }:
                return None
            return intent
        return None

    @staticmethod
    def _has_target_question_signal(
        updates: tuple[TargetInterestUpdate, ...],
    ) -> bool:
        return any(
            update.new_knowledge_gaps
            and update.interest_change
            in {InterestChange.INCREASE, InterestChange.SLIGHTLY_INCREASE}
            for update in updates
        )

    @staticmethod
    def _is_internal_state_target(meaning: StructuredInputMeaning) -> bool:
        target = meaning.target
        return target is not None and target.target_type.casefold() in {
            "internal_state",
            "agent_internal_state",
        }

    @staticmethod
    def _existence_boundaries(
        character_profile: dict[str, object],
    ) -> tuple[str, ...]:
        existence = character_profile.get("existence")
        if not isinstance(existence, dict):
            return (
                "物理的な身体を持たない",
                "実体験は根拠がある場合だけ語る",
            )
        boundaries: list[str] = []
        for key in (
            "physical_capabilities",
            "sensory_capabilities",
            "experience_boundaries",
        ):
            values = existence.get(key)
            if isinstance(values, (list, tuple)):
                boundaries.extend(str(value) for value in values)
        relationship = existence.get("world_relationship")
        if relationship:
            boundaries.append(str(relationship))
        return tuple(dict.fromkeys(boundaries))

    @staticmethod
    def _is_impossible_embodied_experience(
        meaning: StructuredInputMeaning,
        boundaries: tuple[str, ...],
    ) -> bool:
        no_physical_body = any(
            "物理的な身体を持たない" in item for item in boundaries
        )
        if not no_physical_body:
            return False

        intent = meaning.primary_intent.casefold()
        if intent in {
            "ask_physical_experience",
            "ask_agent_physical_experience",
            "ask_agent_bodily_state",
            "ask_agent_physical_hunger",
        }:
            return True

        target = meaning.target
        if target is None:
            return False
        target_type = target.target_type.casefold()
        target_id = target.target_id.casefold()
        bodily_target_ids = {
            "physical_hunger",
            "hunger",
            "sleepiness",
            "physical_sensation",
            "yesterday_outing",
            "outing",
            "travel",
            "walk",
            "お腹",
            "空腹",
            "眠気",
            "外出",
            "旅行",
            "散歩",
        }
        if target_id in bodily_target_ids:
            return True
        return target_type == "character_experience" and any(
            token in target_id
            for token in ("outing", "travel", "walk", "外出", "旅行", "散歩")
        )

    @staticmethod
    def _add_internal_state_requirements(
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        requirements: list[str],
        forbidden_claims: list[str],
    ) -> None:
        target = meaning.target
        if target is None or target.target_type.casefold() not in {
            "internal_state",
            "agent_internal_state",
        }:
            return
        emotion = planning_input.get("emotion")
        emotion_state = emotion if isinstance(emotion, dict) else {}
        target_id = target.target_id.casefold()
        if target_id in {
            "current_feeling",
            "current_mood",
            "current_emotion",
            "mood",
            "feeling",
        }:
            emotion_values = _numeric_state_values(emotion_state)
            dominant_summary = _dominant_state_summary(emotion_values)
            requirements.append(
                "現在の気分全体はEmotionの値が高い1〜2項目を中心に、強度を誇張せず直接回答する"
            )
            if dominant_summary:
                requirements.append(
                    f"現在の気分の中心候補: {dominant_summary}"
                )
            requirements.append(
                "Emotion evidence: "
                + json.dumps(
                    emotion_values,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            drive = planning_input.get("drive")
            drive_state = drive if isinstance(drive, dict) else {}
            drive_values = _numeric_state_values(drive_state)
            if "curiosity" in drive_values:
                requirements.append(
                    "Drive evidence（感情ではなく補助的な好奇心・関心）: "
                    f"curiosity={drive_values['curiosity']}"
                )
            forbidden_claims.extend(
                (
                    "低いEmotion値を主感情として強く誇張する",
                    "curiosityやengagementだけを根拠に楽しい・うれしいと断定する",
                    "現在値にない悲しみ、怒り、強い興奮を創作する",
                )
            )
        elif target_id in {"joy", "amusement", "fun", "楽しさ"}:
            joy = _nested_number(emotion_state, "joy")
            amusement = _nested_number(emotion_state, "amusement")
            motivation = planning_input.get("motivation")
            motivation_state = motivation if isinstance(motivation, dict) else {}
            engagement_value = _find_nested_number(motivation_state, "engagement")
            if engagement_value is None:
                engagement_value = _nested_number(emotion_state, "engagement")
            requirements.append(
                "joy/amusementの値を根拠に直接回答し、engagementとは区別する"
            )
            requirements.append(
                "現在値: "
                f"joy={joy}, amusement={amusement}, engagement={engagement_value}"
            )
            forbidden_claims.append(
                "joyとamusementが低いのにengagementだけを根拠として楽しいと断定する"
            )
        elif target_id in {"anger", "怒り", "angry"}:
            anger = _nested_number(emotion_state, "anger")
            requirements.append(f"現在のanger={anger}を根拠に率直に回答する")
        elif target_id in {"current_desire", "desire", "want"}:
            drive = planning_input.get("drive")
            requirements.append(
                "現在の欲求・Driveから最も近い希望を説明し、存在しない身体欲求を創作しない"
            )
            requirements.append(
                "Drive evidence: " + json.dumps(drive, ensure_ascii=False, default=str)
            )

    @classmethod
    def _add_existence_constraints(
        cls,
        meaning: StructuredInputMeaning,
        boundaries: tuple[str, ...],
        requirements: list[str],
        forbidden_claims: list[str],
    ) -> None:
        target_id = meaning.target.target_id.casefold() if meaning.target else ""
        bodily_intents = {
            "physical_hunger",
            "hunger",
            "sleepiness",
            "physical_sensation",
            "お腹",
            "空腹",
        }
        no_physical_body = any("物理的な身体を持たない" in item for item in boundaries)
        if no_physical_body and (
            target_id in bodily_intents
            or meaning.primary_intent in {
                "ask_agent_physical_hunger",
                "ask_agent_bodily_state",
            }
        ):
            requirements.append(
                "AI VTuberとして人間と同じ物理的身体感覚は持たないことを明示する"
            )
            forbidden_claims.extend(
                (
                    "人間と同じ物理的な空腹を感じている、または今は空腹でないだけだと主張する",
                    "現実空間の空気・温度・匂いを身体で直接感じたと主張する",
                )
            )

        if cls._is_impossible_embodied_experience(meaning, boundaries):
            requirements.extend(
                (
                    "物理的な身体を持たないため、対象の現実世界での身体経験や行動は起こらないことを明示する",
                    "未確認・不明という曖昧な説明ではなく、存在境界に基づいて簡潔かつ誠実に答える",
                )
            )
            forbidden_claims.extend(
                (
                    "現実世界で対象の身体経験や行動をした可能性があるかのように述べる",
                    "存在境界上不可能な経験を、単に未確認または情報不足であるだけと説明する",
                    "存在境界上不可能な経験の内容を創作する",
                )
            )


def _find_nested_number(data: dict[str, object], name: str) -> float | None:
    direct = data.get(name)
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return float(direct)
    for container_name in ("current", "reactive", "mood", "state"):
        container = data.get(container_name)
        if isinstance(container, dict):
            nested = container.get(name)
            if isinstance(nested, (int, float)) and not isinstance(nested, bool):
                return float(nested)
            for nested_container in ("reactive", "mood"):
                sub = container.get(nested_container)
                if isinstance(sub, dict):
                    value = sub.get(name)
                    if isinstance(value, (int, float)) and not isinstance(
                        value,
                        bool,
                    ):
                        return float(value)
    return None


def _nested_number(data: dict[str, object], name: str) -> float:
    value = _find_nested_number(data, name)
    return value if value is not None else 0.0


def _numeric_state_values(data: dict[str, object]) -> dict[str, float]:
    values: dict[str, float] = {}

    def collect(container: dict[str, object]) -> None:
        for key, value in container.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.setdefault(str(key), float(value))

    collect(data)
    for container_name in ("current", "reactive", "mood", "state"):
        nested = data.get(container_name)
        if not isinstance(nested, dict):
            continue
        collect(nested)
        for nested_container_name in ("reactive", "mood"):
            sub = nested.get(nested_container_name)
            if isinstance(sub, dict):
                collect(sub)
    return values


def _dominant_state_summary(values: dict[str, float]) -> str:
    strongest = sorted(
        values.items(),
        key=lambda item: (-item[1], item[0]),
    )[:2]
    return ", ".join(
        f"{name}={value} ({_intensity_label(value)})"
        for name, value in strongest
    )


def _intensity_label(value: float) -> str:
    if value >= 0.70:
        return "強め"
    if value >= 0.45:
        return "中程度"
    if value >= 0.25:
        return "少し"
    return "低め"

from __future__ import annotations

from dataclasses import replace

from app.domain.cognitive_direction import (
    ConversationPhaseSignal,
    ExpectedResponse,
    InputSpeechAct,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)


class InternalDirectiveCandidateNormalizer:
    """Planner候補を、入力対象に応じた最小限の司令へ正規化する。"""

    def normalize(
        self,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
        planning_input: dict[str, object] | None = None,
    ) -> InternalDirective:
        normalized = self._normalize_gap_answer_acknowledgement(
            meaning,
            directive,
        )
        normalized = self._normalize_existence_constraints(meaning, normalized)
        return self._restore_target_gap_question(
            meaning,
            normalized,
            planning_input or {},
        )

    @classmethod
    def _normalize_gap_answer_acknowledgement(
        cls,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
    ) -> InternalDirective:
        if not _is_gap_answer_input(meaning):
            return directive
        if not cls._resolved_target_gaps(meaning, directive):
            return directive

        forbidden_claims = tuple(
            dict.fromkeys(
                (
                    *directive.forbidden_claims,
                    "ユーザーが提供した説明を、自分の新しい説明として繰り返す",
                    "追加質問や新しい話題を持ち出す",
                )
            )
        )
        return replace(
            directive,
            response_mode=ResponseMode.REACT,
            response_goal=(
                "提供された情報を受け止め、既存Knowledge Gapが解消されたことを"
                "示す短い反応を返す"
            ),
            initiative_level=min(directive.initiative_level, 0.2),
            question_budget=0,
            new_direction_budget=0,
            content_requirements=(
                "提供された情報を理解したことが伝わる短い反応を返す",
                "既存Knowledge Gapが解消されたことを自然に受け止める",
                "提供された内容を必要以上に説明し直さない",
            ),
            forbidden_claims=forbidden_claims,
            reason=(
                "Core補正: ユーザーの回答により既存Knowledge Gapが解消されたため、"
                "内容を再説明せず短い受領・理解反応を返す"
            ),
        )

    @staticmethod
    def _normalize_existence_constraints(
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
    ) -> InternalDirective:
        if _is_existence_sensitive_input(meaning):
            return directive

        requirements = tuple(
            value
            for value in directive.content_requirements
            if not _is_generic_existence_constraint(value)
        )
        forbidden_claims = tuple(
            value
            for value in directive.forbidden_claims
            if not _is_generic_existence_constraint(value)
        )
        if (
            requirements == directive.content_requirements
            and forbidden_claims == directive.forbidden_claims
        ):
            return directive
        return replace(
            directive,
            content_requirements=requirements,
            forbidden_claims=forbidden_claims,
        )

    @classmethod
    def _restore_target_gap_question(
        cls,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
        planning_input: dict[str, object],
    ) -> InternalDirective:
        gap = cls._eligible_target_gap(meaning, directive, planning_input)
        if gap is None or not cls._question_expansion_is_allowed(meaning):
            return directive
        if not cls._has_high_question_motivation(planning_input):
            return directive

        requirements = tuple(
            value
            for value in directive.content_requirements
            if not _is_question_prohibition(value)
        )
        forbidden_claims = tuple(
            value
            for value in directive.forbidden_claims
            if not _is_question_prohibition(value)
        )
        requirements = tuple(
            dict.fromkeys(
                (
                    *requirements,
                    f"現在対象の未解決Knowledge Gap『{gap}』に沿った質問を1件だけ行う",
                    "現在の対象を掘り下げ、無関係な新しい話題へ展開しない",
                )
            )
        )
        forbidden_claims = tuple(
            dict.fromkeys(
                (
                    *forbidden_claims,
                    "対象と無関係な質問、複数の質問、別方向の話題を追加する",
                )
            )
        )
        return replace(
            directive,
            response_mode=ResponseMode.ASK,
            response_goal=(
                "現在対象の未解決Knowledge Gapに沿った関連質問を1件だけ行う"
            ),
            initiative_level=max(directive.initiative_level, 0.35),
            question_budget=1,
            new_direction_budget=0,
            content_requirements=requirements,
            forbidden_claims=forbidden_claims,
            reason=(
                "Core補正: 現在対象と一致する未解決Knowledge Gap"
                f"『{gap}』があり、対象別関心とCuriosityまたはEngagementが"
                "閾値を満たすため、関連質問を1件だけ許可した"
            ),
        )

    @classmethod
    def _eligible_target_gap(
        cls,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
        planning_input: dict[str, object],
    ) -> str | None:
        target = meaning.target
        if target is None:
            return None
        resolved_gaps = cls._resolved_target_gaps(meaning, directive)
        related = planning_input.get("related_knowledge")
        if not isinstance(related, list):
            return None
        for item in related:
            if not isinstance(item, dict):
                continue
            target_type = str(
                item.get("target_type") or item.get("type") or ""
            ).casefold()
            target_id = str(item.get("target_id") or item.get("id") or "").casefold()
            if target_type != target.target_type.casefold():
                continue
            if target_id != target.target_id.casefold():
                continue
            interest = _number_from_keys(
                item,
                "interest",
                "interest_level",
                "target_interest",
            )
            if interest is None or interest < 0.75:
                continue
            for key in (
                "knowledge_gaps",
                "unresolved_knowledge_gaps",
                "unresolved_questions",
                "gaps",
            ):
                value = item.get(key)
                if isinstance(value, list):
                    for entry in value:
                        text = str(entry).strip()
                        if text and text.casefold() not in resolved_gaps:
                            return text
                elif isinstance(value, str):
                    text = value.strip()
                    if text and text.casefold() not in resolved_gaps:
                        return text
        return None

    @staticmethod
    def _resolved_target_gaps(
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
    ) -> set[str]:
        target = meaning.target
        if target is None:
            return set()
        target_type = target.target_type.casefold()
        target_id = target.target_id.casefold()
        resolved: set[str] = set()
        for update in directive.target_interest_updates:
            if update.target_type.casefold() != target_type:
                continue
            if update.target_id.casefold() != target_id:
                continue
            resolved.update(
                gap.casefold()
                for gap in update.resolved_knowledge_gaps
                if gap.strip()
            )
        return resolved

    @staticmethod
    def _question_expansion_is_allowed(
        meaning: StructuredInputMeaning,
    ) -> bool:
        if meaning.conversation_phase_signal is not ConversationPhaseSignal.CONTINUE:
            return False
        if meaning.input_speech_act in {
            InputSpeechAct.QUESTION,
            InputSpeechAct.ANSWER,
            InputSpeechAct.CLOSING,
            InputSpeechAct.COMMAND,
            InputSpeechAct.REQUEST,
        }:
            return False
        if meaning.expected_response in {
            ExpectedResponse.DIRECT_ANSWER,
            ExpectedResponse.ACTION,
            ExpectedResponse.NO_RESPONSE,
            ExpectedResponse.CLARIFICATION,
        }:
            return False
        intent = meaning.primary_intent.casefold()
        return not any(
            token in intent
            for token in (
                "positive_experience",
                "share_happy",
                "share_joy",
                "provide_answer",
                "answer_existing_gap",
                "resolve_existing_gap",
                "resolve_knowledge_gap",
                "knowledge_gap_answer",
                "closing",
                "end_conversation",
                "continue_previous",
                "stop_activity",
                "嬉",
                "喜びを共有",
                "既存gapへの回答",
                "gapを解消",
                "解消する回答",
            )
        )

    @staticmethod
    def _has_high_question_motivation(
        planning_input: dict[str, object],
    ) -> bool:
        drive = planning_input.get("drive")
        drive_state = drive if isinstance(drive, dict) else {}
        motivation = planning_input.get("motivation")
        motivation_state = motivation if isinstance(motivation, dict) else {}
        curiosity = _number_from_keys(drive_state, "curiosity") or 0.0
        engagement = _number_from_keys(motivation_state, "engagement") or 0.0
        return curiosity >= 0.75 or engagement >= 0.75


def _is_gap_answer_input(meaning: StructuredInputMeaning) -> bool:
    if meaning.expected_response is not ExpectedResponse.ACKNOWLEDGEMENT:
        return False
    if meaning.input_speech_act is InputSpeechAct.ANSWER:
        return True
    intent = meaning.primary_intent.casefold()
    return any(
        token in intent
        for token in (
            "provide_answer",
            "answer_existing_gap",
            "resolve_existing_gap",
            "resolve_knowledge_gap",
            "knowledge_gap_answer",
            "既存gapへの回答",
            "gapを解消",
            "解消する回答",
        )
    )


def _number_from_keys(
    data: dict[str, object],
    *keys: str,
) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _is_question_prohibition(value: str) -> bool:
    normalized = value.casefold()
    has_question = any(token in normalized for token in ("質問", "問いかけ", "ask"))
    has_prohibition = any(
        token in normalized
        for token in (
            "しない",
            "禁止",
            "追加しない",
            "行わない",
            "広げない",
            "拡張はしない",
            "do not",
        )
    )
    return has_question and has_prohibition


def _is_existence_sensitive_input(meaning: StructuredInputMeaning) -> bool:
    intent = meaning.primary_intent.casefold()
    if any(
        token in intent
        for token in (
            "physical",
            "bodily",
            "body_state",
            "hunger",
            "sleepiness",
            "sensory_experience",
            "outing",
            "travel",
            "walk",
            "身体",
            "空腹",
            "眠気",
            "外出",
            "旅行",
            "散歩",
        )
    ):
        return True

    target = meaning.target
    if target is None:
        return False
    target_type = target.target_type.casefold()
    target_id = target.target_id.casefold()
    if target_type in {
        "character_experience",
        "physical_state",
        "bodily_state",
        "sensory_experience",
    }:
        return True
    return any(
        token in target_id
        for token in (
            "physical",
            "bodily",
            "hunger",
            "sleepiness",
            "outing",
            "travel",
            "walk",
            "身体",
            "空腹",
            "眠気",
            "外出",
            "旅行",
            "散歩",
        )
    )


def _is_generic_existence_constraint(value: str) -> bool:
    normalized = value.casefold()
    return any(
        token in normalized
        for token in (
            "物理的な身体",
            "現実の身体",
            "身体経験",
            "身体的",
            "物理的感覚",
            "現実空間",
            "現実世界",
            "現実体験",
            "実体験",
            "観測経験",
            "存在境界",
            "physical body",
            "physical experience",
            "real-world experience",
        )
    )

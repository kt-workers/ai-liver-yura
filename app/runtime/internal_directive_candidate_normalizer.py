from __future__ import annotations

from dataclasses import replace

from app.domain.cognitive_direction import InternalDirective, StructuredInputMeaning


class InternalDirectiveCandidateNormalizer:
    """Planner候補を、入力対象に応じた最小限の司令へ正規化する。"""

    def normalize(
        self,
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

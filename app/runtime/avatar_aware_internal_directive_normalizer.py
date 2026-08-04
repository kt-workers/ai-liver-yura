from __future__ import annotations

from dataclasses import replace

from app.domain.cognitive_direction import (
    ExpectedResponse,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.runtime.internal_directive_candidate_normalizer import (
    InternalDirectiveCandidateNormalizer,
)

_AVATAR_TARGET_TYPES = {
    "avatar_body_action",
    "gaze_direction",
    "orientation_direction",
}


class AvatarAwareInternalDirectiveCandidateNormalizer(
    InternalDirectiveCandidateNormalizer
):
    """アバター身体命令を現実の身体経験禁止と分離する。"""

    def normalize(
        self,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
        planning_input: dict[str, object] | None = None,
    ) -> InternalDirective:
        normalized = super().normalize(meaning, directive, planning_input)
        target = meaning.target
        if (
            meaning.expected_response is not ExpectedResponse.ACTION
            or target is None
            or target.target_type.casefold() not in _AVATAR_TARGET_TYPES
        ):
            return normalized

        requirements = tuple(
            value
            for value in normalized.content_requirements
            if not _generic_physical_boundary(value)
        )
        forbidden = tuple(
            value
            for value in normalized.forbidden_claims
            if not _generic_physical_boundary(value)
        )
        requirements = tuple(
            dict.fromkeys(
                (
                    *requirements,
                    "ユーザーの指示は現実の生身の肉体ではなく、接続済みアバター身体への操作命令として扱う",
                    "Body Subsystemが対象の方向または身体Actionを実行する前提で、短く自然に受領する",
                    "発話内容と実行するアバター動作を一致させる",
                )
            )
        )
        forbidden = tuple(
            dict.fromkeys(
                (
                    *forbidden,
                    "物理的な身体がないことを理由に、アバターの顔・目・口・首・胴体・腕を動かせないと主張する",
                    "Body Subsystemへ渡される操作命令を、気持ちだけ向ける等の比喩で置き換える",
                )
            )
        )
        return replace(
            normalized,
            response_mode=ResponseMode.REACT,
            response_goal=(
                "指定されたアバター身体の動作をBody Subsystemで実行し、"
                "その動作と矛盾しない短い反応を返す"
            ),
            activity_intent=None,
            initiative_level=min(normalized.initiative_level, 0.3),
            question_budget=0,
            new_direction_budget=0,
            content_requirements=requirements,
            forbidden_claims=forbidden,
            reason=(
                "Core補正: 明示的なアバター身体操作であり、現実世界の身体経験ではないため、"
                "Body Subsystemで実行可能な命令として扱う"
            ),
        )


def _generic_physical_boundary(value: str) -> bool:
    normalized = value.casefold()
    return any(
        token in normalized
        for token in (
            "物理的な身体を持たないため",
            "物理的動作はできない",
            "物理的にはできない",
            "現実世界での身体経験",
            "存在境界上できない",
            "physical body",
            "physical action is impossible",
        )
    )

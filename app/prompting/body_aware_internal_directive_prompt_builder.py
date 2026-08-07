from __future__ import annotations

import json

from app.domain.body_instruction import (
    BODY_ACTION_INTENT_CONSTRAINT,
    BODY_EXPRESSION_ACTIVITY_TYPE,
)
from app.domain.cognitive_direction import StructuredInputMeaning
from app.prompting.cognitive_direction_prompt_builders import (
    InternalDirectivePromptBuilder,
)


class BodyAwareInternalDirectivePromptBuilder(InternalDirectivePromptBuilder):
    """明示Body要求を「入力要求」から「ゆら自身の行動決定」へ分離する。

    Input Meaningのbody_instructionはユーザーが望んだことを表すだけで、Body Runtimeを
    直接駆動しない。Internal Directive Plannerが実行を選んだ場合だけ、Core所有の
    body_expression_loop Activity Intentへ高レベルbody_action_intentを載せる。
    """

    def build(
        self,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> str:
        prompt = super().build(
            meaning,
            planning_input,
            character_profile=character_profile,
        )
        instruction = meaning.body_instruction
        if instruction is None:
            return prompt

        core_activity = {
            "activity_type": BODY_EXPRESSION_ACTIVITY_TYPE,
            "description": (
                "ゆらが意識的に選んだアバター身体行動をBody Realizerへ渡すCore Activity"
            ),
            "supported_operations": ["start"],
            "constraints": {
                BODY_ACTION_INTENT_CONSTRAINT: {
                    "effector": "string",
                    "direction": "string",
                    "side": "string|null",
                    "magnitude": "number 0.0..1.0",
                }
            },
        }
        requested_action = instruction.as_context()
        return "\n".join(
            [
                prompt,
                "# Core Conscious Body Action Contract",
                json.dumps(core_activity, ensure_ascii=False),
                "structured_input_meaning.body_instructionはユーザーが要求した身体行動の意味であり、"
                "ゆら自身が実行すると決めた事実ではない。入力要求からBodyを直接駆動しない。",
                "この要求に応じてゆら自身が身体を動かすと判断した場合だけ、activity_intentを"
                f"activity_type={BODY_EXPRESSION_ACTIVITY_TYPE}, operation=start とし、constraints.{BODY_ACTION_INTENT_CONSTRAINT}へ"
                "ゆらが実際に行うと決めた高レベル身体意図を入れる。",
                "body_action_intentにはPose軸、関節角、固定Motion名、Preset名を書かない。"
                "対象部位・方向・左右・強度の意味だけを保持し、実現方法はBody Realizerに任せる。",
                "このCore Activityは明示Body要求があるTurnではInternal Directiveが選択できる。"
                "DirectiveInput.available_activitiesにPlugin Activityとして列挙されていなくても、"
                "この契約で示したCore Activityは利用可能な意識的行動候補として扱う。",
                "『物理的な身体を持たない』という存在境界は、人間と同じ生物学的肉体や現実空間の"
                "身体経験を創作しないための境界である。アバターBodyを動かす能力そのものを否定する"
                "根拠にはしない。",
                "身体行動を選んだ場合もCharacterへ『手を挙げた』等の実況・完了報告を必須にしない。"
                "response_goalは同じ意思と矛盾しなければよく、短い相づちや無言方針も許容する。",
                "逆に、身体行動を選んだのに『体は動かせない』『その動作はできない』など、"
                "選択した意思とアバター能力を自己否定する方針をresponse_goalや"
                "content_requirementsへ入れてはいけない。実行失敗は後段Runtimeの事実であり、"
                "Internal Directiveが先回りして失敗したことにしない。",
                "# Requested Body Action Meaning",
                json.dumps(requested_action, ensure_ascii=False),
            ]
        )


__all__ = ["BodyAwareInternalDirectivePromptBuilder"]

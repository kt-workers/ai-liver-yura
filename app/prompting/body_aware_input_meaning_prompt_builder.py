from __future__ import annotations

from app.prompting.cognitive_direction_prompt_builders import (
    InputMeaningPromptBuilder as BaseInputMeaningPromptBuilder,
)


class BodyAwareInputMeaningPromptBuilder(BaseInputMeaningPromptBuilder):
    """Input Meaningへ、Raw text非依存の身体意味指示を追加する。"""

    def build(self, planning_input: dict[str, object]) -> str:
        prompt = super().build(planning_input)
        return "\n".join(
            (
                prompt,
                "# Optional Body Instruction",
                "入力がゆら自身の身体・視線を明示的に動かすcommand/requestで、"
                "expected_response=actionの場合だけbody_instructionを追加する。",
                "body_instructionはnullまたは"
                '{"effector":"head|gaze|arm|hand|torso|body等の意味上の対象",'
                '"direction":"right|left|up|down|raise|lower|inward|outward|forward|backward等",'
                '"side":"left|right|null","magnitude":0.0}の形にする。',
                "magnitudeは意味上の強さ0.0..1.0であり、角度、速度、回数、時刻、"
                "Live2D Parameter、モーション名ではない。通常会話ではbody_instruction=null。",
                "『右見て』はhead/right、『右手挙げて』はarm/up/rightのように、"
                "表面語ではなく意味上の身体対象・方向・左右へ正規化する。",
                "Body Runtimeが実行できるか、実行に成功したかは判断しない。",
                "既存の出力JSONにbody_instructionフィールドを追加して返す。",
            )
        )


__all__ = ["BodyAwareInputMeaningPromptBuilder"]

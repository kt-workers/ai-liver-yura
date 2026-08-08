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
                "単一動作のbody_instructionは"
                '{"effector":"head|gaze|arm|hand|torso|body等の意味上の対象",'
                '"direction":"right|left|up|down|raise|lower|inward|outward|forward|backward等",'
                '"side":"left|right|null","magnitude":0.0}の形にする。',
                "一つの入力が複数部位を同時に動かす意味を含む場合、一方を捨ててはいけない。"
                "body_instructionをeffector=body,direction=compose,side=null,magnitude=1.0とし、"
                '"components"配列へ同時に満たす単一動作の意味をすべて入れる。',
                "たとえば『左を見ながら右手を挙げて』は、head/leftとarm/raise/rightの"
                "2 componentを持つ一つの複合body_instructionとして表す。",
                "componentsは実行順、Preset、Motion名ではなく、同時に成立させる意味要素である。"
                "入れ子のcomponentsは作らない。",
                "left/rightは常に行為主体であるゆら自身を基準に解釈する。"
                "side=left/rightはゆら自身の解剖学的左/右、direction=left/rightは"
                "ゆら自身から見て左/右であり、視聴者・カメラ・画面の左右へ読み替えない。",
                "magnitudeは意味上の強さ0.0..1.0であり、角度、速度、回数、時刻、"
                "Live2D Parameter、モーション名ではない。通常会話ではbody_instruction=null。",
                "『右見て』はhead/right、『右手挙げて』はarm/raise/rightのように、"
                "表面語ではなく意味上の身体対象・方向・左右へ正規化する。",
                "Body Runtimeが実行できるか、実行に成功したかは判断しない。",
                "既存の出力JSONにbody_instructionフィールドを追加して返す。",
            )
        )


__all__ = ["BodyAwareInputMeaningPromptBuilder"]

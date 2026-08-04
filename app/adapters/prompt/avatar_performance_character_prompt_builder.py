from __future__ import annotations

from app.adapters.prompt.directive_aware_prompt_builders import (
    CharacterPromptBuilder as DirectiveAwareCharacterPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import ResponseContext


class AvatarPerformanceCharacterPromptBuilder(DirectiveAwareCharacterPromptBuilder):
    """Character表現へBody Subsystem向けの意味的な演技Intentを追加する。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: str | None,
    ) -> str:
        prompt = super().build(
            context,
            character_profile=character_profile,
            correction=correction,
        )
        return "\n".join(
            [
                prompt,
                "# Embodied Expression Intent",
                "身体はCharacter LLMとは独立して常時動作する。呼吸、瞬き、微細な姿勢変化、"
                "周辺への一瞬の視線などを毎回指定しない。",
                "structured_input_meaning.target.typeがavatar_body_action、gaze_direction、"
                "orientation_directionのいずれかでexpected_response=actionの場合、その命令は"
                "Body Subsystemが接続済みアバター身体で実行する。",
                "現実世界の生身の肉体を持たないことと、アバターの顔・目・口・首・胴体・腕を"
                "動かせることを混同しない。アバター身体への命令に対して『動かせない』"
                "『物理的にはできない』『気持ちだけ向ける』と返してはいけない。",
                "身体ActionそのものはCoreからBodyへ別経路で送られるため、speechは動作と"
                "矛盾しない短い受領または自然な反応にする。実際の身体部位やMotion名を"
                "Character LLMのgestureとして再指定する必要はない。",
                "reaction_segmentsの各要素では、発話に密接な人格的表現が必要な場合だけ"
                "embodied_expression、attention_intent、speech_emphasisを追加する。",
                "expression_intensityは0.0〜1.0で、表情の見せ方の強さだけに使用できる。",
                "embodied_expressionは{attitude, intensity, valence, arousal, tension, openness,"
                " approach, agreement, surprise, assertiveness, warmth}。",
                "intensity、arousal、tension、openness、surprise、assertiveness、warmthは0.0〜1.0。"
                "valence、approach、agreementは-1.0〜1.0。",
                "agreementは肯定方向を正、否定方向を負、approachは近付く態度を正、"
                "距離を取る態度を負として表す。",
                "attention_intentはnullまたは{target, behavior, engagement, avoidance, eye_follow,"
                " head_follow, body_follow}。behaviorはmaintain、glance、avoid、search、wander。",
                "targetはconversation_partner、viewer、speaker、cursor、object、stimulusなど"
                "意味上の対象を指定し、画面座標や角度を指定しない。",
                "speech_emphasisは必要な場合だけ[{text, intent, strength}]として、発話中の"
                "意味的な強調位置を示す。時刻は指定しない。",
                "首、腕、胴体などの身体部位、head_shake、nod、wave等のモーション名、"
                "回数、振幅、速度、開始時刻、ポーズを直接指定しない。gesture、"
                "gesture_intensity、gazeは旧Runtime互換項目であり、新しい応答では原則nullにする。",
                "身体表現を埋めるためだけに値を追加しない。Characterとして意図的に表したい"
                "態度がない場合は、Body Subsystemの自律制御へ任せる。",
                "performance_id、priority、duration_ms、fade、interrupt_policy、Live2D Parameter、"
                "VTube Studio Hotkeyは出力しない。これらはBody SubsystemとAvatar Runtimeが"
                "決定する。",
            ]
        )

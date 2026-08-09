from __future__ import annotations

import json
from dataclasses import replace

from app.adapters.prompt.character_prompt_builder import (
    CharacterPromptBuilder as LegacyCharacterPromptBuilder,
)
from app.adapters.prompt.response_validator_prompt_builder import (
    ResponseValidatorPromptBuilder as LegacyResponseValidatorPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import CharacterResponse, Claim, ResponseContext


_MODE_STRATEGIES: dict[str, tuple[str, ...]] = {
    "answer": ("explain_clearly",),
    "listen": ("acknowledge_other",),
    "react": ("share_reaction",),
    "ask": ("acknowledge_other", "ask_follow_up"),
    "speak": ("state_preference",),
    "observe": ("observe_before_speaking",),
}


class CharacterPromptBuilder(LegacyCharacterPromptBuilder):
    """Validated Internal Directiveを決定論的にCharacter Promptへ射影する。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: str | None,
    ) -> str:
        directive = _validated_directive(context)
        effective_context = _effective_context(context, directive)
        prompt = super().build(
            effective_context,
            character_profile=character_profile,
            correction=correction,
        )
        if directive is None:
            return prompt
        sections = [
            prompt,
            "# Validated Internal Directive",
            json.dumps(directive, ensure_ascii=False, default=str),
            "この司令はCoreで検証済みの最終方針である。Raw User Textから別の意味や"
            "方針を再推定しない。",
            "Conversation Response DecisionとResponse Content Planは、この司令を"
            "表現層へ投影した補助情報であり、矛盾する場合はValidated Internal Directiveを"
            "必ず優先する。",
            "response_modeとresponse_goalに従い、question_budgetと"
            "new_direction_budgetを上限として厳守する。content_requirementsを満たし、"
            "forbidden_claimsとexistence_boundariesに反する主張を生成しない。",
            "conversation_phaseがwinding_downの場合はspeechを空にせず、質問や新しい話題を"
            "含まない短い別れの挨拶を返す。",
            "character_profileは存在設定を含む確定済みProfileであり、物理的な身体や"
            "現実空間での実体験を根拠なく創作しない。",
        ]
        direct_state_contract = _direct_internal_state_contract(
            effective_context,
            directive,
        )
        if direct_state_contract is not None:
            sections.extend(
                [
                    "# Direct Internal State Answer Contract",
                    json.dumps(
                        direct_state_contract,
                        ensure_ascii=False,
                        default=str,
                    ),
                    "targetは今回ユーザーが直接尋ねた内部状態のtyped identityである。"
                    "Raw User Textから別targetへ読み替えず、このtargetへ直接答える。",
                    "current_emotionとcurrent_driveは現在状態のstructured source of truthである。"
                    "recent_speech_summary、recent_conversation_summary、memory、related knowledgeは"
                    "会話継続の参考にできるが、現在状態の事実を上書きしない。",
                    "質問targetとは異なる内部状態が高くても、その高さをtarget自身の存在や強さの"
                    "根拠へ代用しない。curiosityやengagementはjoy/amusementではなく、"
                    "関心や関与の補助状態として区別する。",
                    "内部キー名、数値、強度分類を説明せず、targetとcurrent structured stateに"
                    "意味的に整合する人物としての自然な自己表現へ変換する。",
                ]
            )
            if _correction_reason(correction) == "recent_speech_too_similar":
                sections.extend(
                    [
                        "# Internal State Repetition Correction",
                        "前回応答との類似が理由で再生成している。一般的な『別の主題または内容を"
                        "選ぶ』という修正指示は、この場合は別話題へ移る意味ではない。",
                        "同じtyped internal-state targetへ直接答え続け、直前回答の文面をコピーせず、"
                        "current structured stateから改めて自然に表現する。無関係な新話題へ"
                        "逃げない。",
                    ]
                )
        return "\n".join(sections)


class ResponseValidatorPromptBuilder(LegacyResponseValidatorPromptBuilder):
    """存在境界を含むValidated DirectiveでCharacter Responseを検証する。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        extracted_claims: tuple[Claim, ...] = (),
    ) -> str:
        directive = _validated_directive(context)
        effective_context = _effective_context(context, directive)
        prompt = super().build(
            effective_context,
            response,
            extracted_claims=extracted_claims,
        )
        if directive is None:
            return prompt
        sections = [
            prompt,
            "# Validated Internal Directive / Character Profile / Existence Boundaries",
            json.dumps(directive, ensure_ascii=False, default=str),
            "Validated Internal Directiveは最終上限であり、Conversation Response Decisionや"
            "Response Content Planが矛盾して見える場合も、こちらを優先して検証する。",
            "Character Responseがresponse_mode、response_goal、question_budget、"
            "new_direction_budget、content_requirementsに一致するか検証する。",
            "question_budget=0で質問を含む場合、new_direction_budget=0で明示的に別話題へ"
            "移る場合、またはwinding_downで会話を再開する場合はaccepted=falseにする。",
            "forbidden_claims、character_profile、existence_boundariesのいずれかに"
            "反する身体感覚・実体験・感情断定があればaccepted=falseにする。",
            "物理的な身体を持たないProfileで『今はお腹が空いていない』だけを"
            "回答し、人間同様の空腹能力を暗示する表現は拒否する。",
        ]
        direct_state_contract = _direct_internal_state_contract(
            effective_context,
            directive,
        )
        if direct_state_contract is not None:
            sections.extend(
                [
                    "# Direct Internal State Semantic Validation",
                    json.dumps(
                        direct_state_contract,
                        ensure_ascii=False,
                        default=str,
                    ),
                    "Character Responseがtyped targetへ直接答えているか、targetとcurrent_emotion / "
                    "current_driveの意味関係に照らして検証する。",
                    "別の内部状態の高さをtarget自身の高さ・存在へ代用した場合は、文章が自然でも"
                    "事実不整合としてaccepted=falseにする。特にcuriosity/engagementを"
                    "joy/amusementとして扱わない。これは文字列照合ではなく意味関係の検証である。",
                    "current structured stateと矛盾する自己状態の断定、または過去発話・関連記憶を"
                    "現在状態の正本として採用した回答はaccepted=falseにする。",
                    "内部キーや数値をそのまま読み上げた診断的回答もaccepted=falseにする。",
                ]
            )
        return "\n".join(sections)


def _validated_directive(context: ResponseContext) -> dict[str, object] | None:
    value = context.constraints.get("_internal_directive")
    return dict(value) if isinstance(value, dict) else None


def _direct_internal_state_contract(
    context: ResponseContext,
    envelope: dict[str, object] | None,
) -> dict[str, object] | None:
    if envelope is None:
        return None
    meaning_value = envelope.get("structured_input_meaning")
    if not isinstance(meaning_value, dict):
        return None
    meaning = dict(meaning_value)
    target_value = meaning.get("target")
    if not isinstance(target_value, dict):
        return None
    target = dict(target_value)
    target_type = str(target.get("type") or "").strip().casefold()
    if target_type not in {"internal_state", "agent_internal_state"}:
        return None
    speech_act = str(meaning.get("input_speech_act") or "").strip().casefold()
    expected_response = str(meaning.get("expected_response") or "").strip().casefold()
    if speech_act != "question" and expected_response != "direct_answer":
        return None
    return {
        "target": {
            "type": str(target.get("type") or ""),
            "id": str(target.get("id") or ""),
        },
        "current_emotion": context.emotion,
        "current_drive": context.drive,
        "source_of_truth": "current_structured_internal_state",
    }


def _correction_reason(correction: str | None) -> str | None:
    if not correction:
        return None
    try:
        value = json.loads(correction)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    reason = value.get("reason")
    return str(reason) if reason is not None else None


def _effective_context(
    context: ResponseContext,
    envelope: dict[str, object] | None,
) -> ResponseContext:
    """旧会話方針をValidated Internal Directiveの範囲内へ保守的に投影する。"""

    if envelope is None:
        return context
    internal_value = envelope.get("internal_directive")
    meaning_value = envelope.get("structured_input_meaning")
    if not isinstance(internal_value, dict):
        return context
    internal = dict(internal_value)
    meaning = dict(meaning_value) if isinstance(meaning_value, dict) else {}
    mode = str(internal.get("response_mode") or "").strip().lower()
    strategies = _MODE_STRATEGIES.get(mode)
    if strategies is None:
        return context

    memory = dict(context.memory)
    raw_plan = memory.get("response_content_plan")
    content_plan = dict(raw_plan) if isinstance(raw_plan, dict) else {}
    content_plan["primary_desire"] = None
    content_plan["conversation_strategies"] = list(strategies)
    content_plan["question_budget"] = (
        1 if internal.get("question_budget") == 1 and mode == "ask" else 0
    )
    content_plan["new_direction_budget"] = (
        1
        if internal.get("new_direction_budget") == 1 and mode in {"ask", "speak"}
        else 0
    )
    disclosure = internal.get("self_disclosure_level")
    content_plan["self_disclosure_level"] = (
        "brief"
        if isinstance(disclosure, (int, float))
        and not isinstance(disclosure, bool)
        and float(disclosure) >= 0.35
        and mode in {"answer", "speak"}
        else "none"
    )
    reasons_value = content_plan.get("reasons")
    reasons = (
        [str(item) for item in reasons_value if isinstance(item, str) and item.strip()]
        if isinstance(reasons_value, (list, tuple))
        else []
    )
    if "validated_internal_directive_projected" not in reasons:
        reasons.append("validated_internal_directive_projected")
    content_plan["reasons"] = reasons
    content_plan["observation_only"] = True
    memory["response_content_plan"] = content_plan

    initiative = internal.get("initiative_level")
    initiative_level = (
        float(initiative)
        if isinstance(initiative, (int, float))
        and not isinstance(initiative, bool)
        and 0.0 <= float(initiative) <= 1.0
        else context.initiative_level
    )
    if mode in {"listen", "react", "observe"}:
        initiative_level = min(initiative_level, 0.25)
    elif mode == "answer":
        initiative_level = min(initiative_level, 0.35)
    elif mode in {"ask", "speak"}:
        initiative_level = max(initiative_level, 0.65)

    speech_act = str(meaning.get("input_speech_act") or context.speech_act)
    phase_signal = str(meaning.get("conversation_phase_signal") or "")
    conversation_phase = context.conversation_phase
    if speech_act == "closing" or phase_signal == "winding_down":
        conversation_phase = "winding_down"
    elif speech_act == "greeting" or phase_signal == "greeting":
        conversation_phase = "greeting"
    elif phase_signal in {"opening", "continue"}:
        conversation_phase = "active"

    return replace(
        context,
        memory=memory,
        speech_act=speech_act,
        conversation_phase=conversation_phase,
        initiative_level=initiative_level,
    )

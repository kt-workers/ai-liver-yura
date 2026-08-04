from __future__ import annotations

import json
from dataclasses import asdict

from app.domain.character_response import CharacterResponse, Claim, ResponseContext
from app.domain.conversation_utterance_policy import (
    apply_conversation_response_policy,
)
from app.domain.response_content_plan import ResponseContentPlan


class ResponseValidatorPromptBuilder:
    """実行事実とCharacter Responseの整合だけを評価するrole専用PromptBuilder。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        extracted_claims: tuple[Claim, ...] = (),
    ) -> str:
        raw_content_plan = ResponseContentPlan.from_context(
            context.memory.get("response_content_plan")
        )
        content_plan, response_decision = apply_conversation_response_policy(
            raw_content_plan,
            speech_act=context.speech_act,
            conversation_phase=context.conversation_phase,
            initiative_level=context.initiative_level,
            user_input=context.user_input,
            drive=context.drive,
        )
        return "\n".join(
            [
                "あなたはResponse Validatorです。表現の事実整合性と確定済み対話方針への"
                "整合性を評価する。",
                "Response Context: "
                + json.dumps(asdict(context), ensure_ascii=False, default=str),
                "Conversation Response Decision: "
                + json.dumps(
                    response_decision.as_context(),
                    ensure_ascii=False,
                    default=str,
                ),
                "Effective Response Content Plan: "
                + json.dumps(
                    content_plan.as_context(),
                    ensure_ascii=False,
                    default=str,
                ),
                "Character Response: "
                + json.dumps(asdict(response), ensure_ascii=False, default=str),
                "Speechから独立抽出済みのClaims: "
                + json.dumps(
                    [asdict(claim) for claim in extracted_claims],
                    ensure_ascii=False,
                    default=str,
                ),
                "決定論的検証済みの事実を変更せず、曖昧・婉曲・比喩表現から"
                "追加の事実Claimを独立抽出する。",
                "ActivityDefinitionにないActivityや、実行Resultにない成功事実を追加しない。",
                "発話がConversation Response DecisionのmodeとEffective Response Content Planの"
                "question_budget、new_direction_budget、self_disclosure_levelに一致しているか評価する。",
                "入力が挨拶・相槌であることだけを理由に質問や発話を拒否しない。"
                "状態と状況から確定したConversation Response Decisionを優先する。",
                "JSONのみ返す: "
                '{"accepted":true,"reason":"facts_consistent","extracted_claims":['
                '{"claim_type":"conversation_only","activity_type":null,'
                '"operation":null,"status":null,"target":null,"confidence":0.9,'
                '"evidence":"発話中の根拠"}]}',
            ]
        )

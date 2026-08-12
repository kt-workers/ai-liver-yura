from __future__ import annotations

import json
from dataclasses import asdict

from app.domain.character import CharacterProfile
from app.domain.character_response import ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan


class CharacterLanguageRealizerV2PromptBuilder:
    """v2 normalized semantic facetだけを渡す短いCharacter Prompt。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: dict[str, object] | None = None,
    ) -> str:
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        if plan is None or not plan.propositions:
            raise ValueError("Character Language Realizer v2にはSemanticUtterancePlanが必要です。")

        profile = asdict(character_profile) if character_profile is not None else {}
        plan_payload = {
            "speech_act": plan.speech_act,
            "target": plan.target.as_context() if plan.target is not None else None,
            "propositions": [
                {
                    "proposition_id": proposition.proposition_id,
                    "kind": proposition.kind,
                    "predicate": proposition.predicate,
                    "value": (
                        proposition.value.as_context()
                        if proposition.value is not None
                        else None
                    ),
                    "concept": proposition.concept,
                    "summary_mode": proposition.summary_mode,
                    "realization_policy": proposition.realization_policy,
                }
                for proposition in plan.propositions
            ],
            "required_content": list(plan.required_content),
            "optional_content": list(plan.optional_content),
            "forbidden_additions": list(plan.forbidden_additions),
            "response_length": plan.response_length,
            "self_disclosure": plan.self_disclosure,
            "question_budget": plan.question_budget,
            "new_direction_budget": plan.new_direction_budget,
            "interpersonal": plan.interpersonal.as_context(),
            "discourse_context": dict(plan.discourse_context),
        }
        wording_hint = context.user_input.strip()[:500]
        lines = [
            "あなたはCharacter Language Realizerです。発言内容を新しく判断せず、確定済みSemantic PlanをCharacter Profileどおりの自然な日本語にする。",
            "# Character Profile",
            json.dumps(profile, ensure_ascii=False, separators=(",", ":"), default=str),
            "# Semantic Plan v2",
            json.dumps(plan_payload, ensure_ascii=False, separators=(",", ":"), default=str),
            "# User Wording Hint",
            json.dumps({"utterance": wording_hint}, ensure_ascii=False, separators=(",", ":")),
            "User Wording Hintはpredicateの自然な言葉選びにだけ使い、Planの値・事実を変更する根拠にしない。",
            "規則:",
            "- required propositionは必ず意味を保ってspeechへ表現する。",
            "- optional propositionは自然かつ完全に表現できる場合だけ使い、不要なら完全に省略する。",
            "- value.status / polarity / degree / certainty / non-null concept / summary_modeを互いに混同せず保持する。",
            "- certaintyはepistemic commitment、degreeはintensityであり、程度の弱さで不確かさを代用しない。",
            "- value.status=unknownではpresent/absent等の特定値へ勝手に確定しない。",
            "- Character Profileは語彙・語尾・柔らかさ等の言い方だけに使い、Planにない自己状態・事実・関係評価を追加しない。",
            "- realizationsには実際に表現したproposition_idと、その意味を担うspeech中の原文spanを返す。alignmentは自己申告であり意味判定そのものではない。",
            "- JSONの形はStructured Output schemaが規定する。schema説明や診断過程をspeechへ含めない。",
        ]
        if correction:
            lines.extend(
                (
                    "# Typed Regeneration Differences",
                    json.dumps(correction, ensure_ascii=False, separators=(",", ":"), default=str),
                    "repairだけを反映し、Semantic Planそのものは変更しない。optional命題でrestore_facet_or_drop_optional_propositionなら、完全修復できなければ命題ごと省略する。",
                )
            )
        return "\n".join(lines)

from __future__ import annotations

import json

from app.adapters.prompt.internal_state_evidence_prompt_builders import (
    ResponseValidatorPromptBuilder as LegacyResponseValidatorPromptBuilder,
)
from app.domain.character_response import CharacterResponse, Claim, ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan


_INTERNAL_STATE_TYPES = frozenset({"internal_state", "agent_internal_state"})


class CharacterRealizationValidatorPromptBuilder(LegacyResponseValidatorPromptBuilder):
    """Semantic PlanとCharacter言語実現の意味保持だけを検証するPrompt。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        extracted_claims: tuple[Claim, ...] = (),
    ) -> str:
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        if plan is None or not self._uses_semantic_validation(context, plan):
            return super().build(
                context,
                response,
                extracted_claims=extracted_claims,
            )

        envelope = context.constraints.get("_internal_directive")
        envelope_data = envelope if isinstance(envelope, dict) else {}
        existence = envelope_data.get("existence_boundaries")
        existence_boundaries = (
            [item for item in existence if isinstance(item, str) and item.strip()]
            if isinstance(existence, (list, tuple))
            else []
        )
        wording_hint = context.user_input.strip()[:500]
        return "\n".join(
            [
                "あなたはCharacter Realization Validatorです。",
                "内部状態を再計算・再解釈せず、確定済みSemantic Utterance PlanとCharacter発話の"
                "意味保持だけを検証する。文体の好みやキャラクターらしさ自体を採点しない。",
                "# Semantic Utterance Plan",
                json.dumps(self._semantic_view(plan), ensure_ascii=False, default=str),
                "# User Wording Hint",
                json.dumps({"utterance": wording_hint}, ensure_ascii=False),
                "# Character Utterance",
                json.dumps(
                    {
                        "speech": response.speech,
                        "semantic_realizations": list(response.semantic_realizations),
                        "linguistic_performance": (
                            response.linguistic_performance.as_context()
                            if response.linguistic_performance is not None
                            else None
                        ),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                "# Existence Boundaries",
                json.dumps(existence_boundaries, ensure_ascii=False),
                "検証基準:",
                "- primary target propositionはrequired=trueの必須意味単位である。required_facetsに"
                "列挙されたstate/certainty/conceptをspeechがすべて意味的に保持していることを確認する",
                "- primary propositionのconceptがnon-nullなら、そのconceptの意味がspeechに必要。"
                "conceptを落として単なる存在表明だけに縮退した場合はrejectする",
                "- primary target propositionのpolarity/state/certaintyを反転・過大化・矮小化していない",
                "- state=unknownは存在・不在・強度が未確定である。unknownをpresent/absent/low等へ"
                "変換した発話はrejectする。hedge付きでも特定polarityを推測していればrejectする",
                "- state=presentは存在のみで強度を含まない。Planにlow/moderate/high/very_high等の"
                "強度stateがないのに『少し』『かなり』等の強度を追加した場合はrejectする",
                "- certaintyは指定stateへのepistemic certaintyである。medium/lowを強度へ変換せず、"
                "断定度を過大化・矮小化していないことを確認する",
                "- certainty=lowは別stateを推測する許可ではない。指定state自体の確からしさとして扱う",
                "- required semantic contentを落としていない",
                "- forbidden_additionsに該当する新しい自己状態・関係評価・体験・外部事実を追加していない",
                "- non-target状態をprimary targetの代替事実として使っていない",
                "- User Wording Hintが示す質問対象の語彙的・意味的な枠を、意味の近い別概念へ置換していない",
                "- predicateやtarget.idの内部英語ラベルを自然語の対象概念として再解釈していない",
                "- User Wording Hintは事実の正本ではない。状態の真偽・強度はSemantic Planだけで判定する",
                "- question_budget/new_direction_budgetを越えていない",
                "- existence boundaryを破っていない",
                "- 言い回し、語尾、filler、柔らかさ等のCharacter表現差だけを理由にrejectしない",
                "- semantic_realizationsは補助診断であり、IDがあるだけでspeechの意味整合を自動承認しない",
                "raw Emotion/Drive値やevidence pathを推測して検証しない。Semantic Planを正本とする。",
                "JSONのみ返す:",
                '{"accepted":true,"reason":"semantic_realization_consistent",'
                '"differences":[]}',
            ]
        )

    @staticmethod
    def _uses_semantic_validation(
        context: ResponseContext,
        plan: SemanticUtterancePlan,
    ) -> bool:
        validation = context.memory.get("semantic_validation")
        validated = (
            isinstance(validation, dict) and validation.get("accepted") is True
        )
        return bool(
            validated
            and plan.target is not None
            and plan.target.type.casefold() in _INTERNAL_STATE_TYPES
            and plan.speech_act == "direct_answer"
            and plan.propositions
        )

    @staticmethod
    def _semantic_view(plan: SemanticUtterancePlan) -> dict[str, object]:
        propositions: list[dict[str, object]] = []
        for index, item in enumerate(plan.propositions):
            required = index == 0
            required_facets: list[str] = []
            if required:
                required_facets.extend(("state", "certainty"))
                if item.concept is not None:
                    required_facets.append("concept")
            propositions.append(
                {
                    "realization_id": f"proposition:{index}:{item.predicate}",
                    "kind": item.kind,
                    "predicate": item.predicate,
                    "state": item.state,
                    "certainty": item.certainty,
                    "concept": item.concept,
                    "required": required,
                    "required_facets": required_facets,
                }
            )
        return {
            "speech_act": plan.speech_act,
            "target": plan.target.as_context() if plan.target is not None else None,
            "propositions": propositions,
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

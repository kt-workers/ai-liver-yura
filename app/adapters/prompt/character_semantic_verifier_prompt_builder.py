from __future__ import annotations

import json

from app.domain.character_response import ResponseContext
from app.domain.character_utterance import CharacterUtterance
from app.domain.semantic_utterance import SemanticUtterancePlan


class CharacterSemanticVerifierPromptBuilder:
    """Planとspeechのrelative semantic relationだけを判定させるv2 Prompt。"""

    def build(
        self,
        context: ResponseContext,
        utterance: CharacterUtterance,
        plan: SemanticUtterancePlan,
        *,
        existence_boundaries: tuple[str, ...] = (),
    ) -> str:
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
            "forbidden_additions": list(plan.forbidden_additions),
            "question_budget": plan.question_budget,
            "new_direction_budget": plan.new_direction_budget,
        }
        utterance_payload = {
            "speech": utterance.speech,
            "alignment_hints": [item.as_context() for item in utterance.realizations],
        }
        user_hint = context.user_input.strip()[:500]
        return "\n".join(
            (
                "あなたはIndependent Character Semantic Verifierです。",
                "確定済みSemantic PlanとCharacter speechを直接比較し、Planに対してspeechがどの意味関係にあるかを判定する。",
                "speechから旧state enumや期待値を独立再構成する仕事ではない。Planを比較基準として使用してよい。",
                "# Semantic Plan",
                json.dumps(plan_payload, ensure_ascii=False, separators=(",", ":")),
                "# Character Speech",
                json.dumps(utterance_payload, ensure_ascii=False, separators=(",", ":")),
                "# User Wording Hint",
                json.dumps({"utterance": user_hint}, ensure_ascii=False, separators=(",", ":")),
                "User Wording Hintはpredicateの自然語意味枠を確認する補助であり、Planの値を上書きする根拠ではない。",
                "# Existence Boundaries",
                json.dumps(list(existence_boundaries), ensure_ascii=False, separators=(",", ":")),
                "判定規則:",
                "- 各planned propositionについて1件のresultを返す。alignment_hintsはspan候補であり意味authorityではない。",
                "- predicate_relation: 対象関係が同じならpreserved。省略はomitted、別意味ならchanged/unrelated、不明瞭ならambiguous。",
                "- value_status_relation: known/unknownの保持を比較する。unknownを特定状態へ確定したらcommitted_when_unknown。knownをunknownへ弱めたらunknown_when_known。",
                "- polarity_relation: present/absentを比較し、反転はcontradicted。Planでpolarityがnullならnot_applicable。",
                "- degree_relation: Planのdegreeに対し同等ならpreserved、弱めたらweaker、強めたらstronger。degreeがnullならnot_applicable。",
                "- certainty_relation: Planに対するepistemic commitmentが同等ならpreserved、強断定ならstronger、慎重すぎればweaker。不明瞭ならambiguous。",
                "- concept_relation: non-null conceptの意味をpredicate関係の中で保持すればpreserved。Planがnullならnot_applicable。",
                "- summary_relation: summary_mode=overviewを総合状態として保持すればpreserved。単一dimensionへ縮退したらcollapsed。detailならnot_applicable。",
                "- optional propositionがspeechに存在しない場合はrealized=false、predicate_relation=omitted、その他のfacet relationはnot_applicable、evidence_spans=[]とする。",
                "- required propositionの意味がspeechから明確でない場合はambiguous/omittedを正直に返し、推測でpreservedにしない。",
                "- evidence_spansはCharacter speechに実在する原文部分だけを返す。",
                "- required/forbidden content、未根拠の新規事実、existence boundary、question/new-direction budgetもPlanに対して比較する。",
                "- Character Profile由来の自然な言い換え、語尾、filler、文体差だけでchangedにしない。",
                "- open-ended自然言語の意味判定を有限単語・phrase・regex・substring対応表へ置き換えない。",
                "出力JSONの形・enumはStructured Output schemaが規定する。accepted/reasonを自分で決めない。",
            )
        )

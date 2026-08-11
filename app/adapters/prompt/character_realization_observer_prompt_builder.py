from __future__ import annotations

import json

from app.domain.character_response import CharacterResponse, ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan


class CharacterRealizationObserverPromptBuilder:
    """Planの期待state/certainty/conceptを見せずspeechの実現意味を観測する。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        plan: SemanticUtterancePlan,
    ) -> str:
        candidates = []
        planned_by_id = {
            f"proposition:{index}:{item.predicate}": item
            for index, item in enumerate(plan.propositions)
        }
        for realization_id in dict.fromkeys(response.semantic_realizations):
            proposition = planned_by_id.get(realization_id)
            if proposition is None:
                continue
            candidates.append(
                {
                    "realization_id": realization_id,
                    "kind": proposition.kind,
                    "predicate": proposition.predicate,
                }
            )

        return "\n".join(
            [
                "あなたはCharacter発話の意味観測器です。",
                "この工程ではSemantic Planとの一致・不一致を判定しない。期待state、期待certainty、"
                "期待conceptは与えられていない。Character speechが実際に何を表現しているかだけを観測する。",
                "# Candidate Predicate IDs",
                json.dumps(candidates, ensure_ascii=False),
                "Candidateは観測対象を対応付けるcanonical IDであり、期待するstateや強度を示さない。",
                "# User Wording Hint",
                json.dumps({"utterance": context.user_input.strip()[:500]}, ensure_ascii=False),
                "User Wording Hintはprimary predicateの自然語意味枠を特定する補助にだけ使う。"
                "そこからstate、certainty、conceptを推測してはいけない。",
                "# Character Speech",
                json.dumps({"speech": response.speech}, ensure_ascii=False),
                "観測規則:",
                "- 各Candidateについて、speechがそのpredicateを実際に表現しているかpredicate_realizedで答える。",
                "- observed_stateはspeechが実際に表すstateを absent/low/moderate/high/very_high/"
                "present/overview/unknown/omitted から選ぶ。期待値を想像して合わせない。",
                "- low/moderate/high/very_highはpresenceとは異なる。speechが存在だけを表し強度を"
                "意味的に区別できない場合はpresentとする。",
                "- 強度の表現手段は副詞に限らず、構文、対比、反復、婉曲、強調など自由。"
                "有限個の語彙リストへ置き換えて判定しない。",
                "- unknownは対象の存在・不在・強度を確定していない意味。肯定/否定へcommitしたspeechを"
                "unknownにしない。",
                "- observed_certaintyはそのobserved_stateへの断定度を high/medium/low/unknown から選ぶ。"
                "強度とcertaintyを混同しない。",
                "- predicate_evidence_spans/state_evidence_spans/certainty_evidence_spansにはspeechに実在する"
                "原文部分だけを列挙する。該当する明示spanが不要または存在しないfacetは空配列でよい。",
                "- Candidateのcanonical英語IDをspeech中に存在する語だと仮定しない。",
                "- Characterのsemantic_realizations等の自己申告metadataは観測根拠にしない。",
                "JSONのみ返す。各observationはrealization_id、predicate_realized、observed_state、"
                "observed_certainty、predicate_evidence_spans、state_evidence_spans、"
                "certainty_evidence_spansを含める。",
            ]
        )

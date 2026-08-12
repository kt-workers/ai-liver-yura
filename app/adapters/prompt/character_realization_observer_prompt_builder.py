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
                "あなたはCharacter発話の独立意味観測器です。",
                "この工程ではSemantic Planとの一致・不一致を判定しない。期待state、期待certainty、"
                "期待conceptは与えられていない。Character speechが実際に表現している意味だけを観測する。",
                "# Candidate Predicate IDs",
                json.dumps(candidates, ensure_ascii=False),
                "Candidateは観測対象を対応付けるcanonical IDであり、期待するstate・polarity・強度・certaintyを示さない。",
                "# User Wording Hint",
                json.dumps({"utterance": context.user_input.strip()[:500]}, ensure_ascii=False),
                "User Wording Hintはprimary predicateの自然語意味枠を特定する補助にだけ使う。"
                "そこからstate、polarity、強度、certainty、conceptを推測してはいけない。",
                "User Wording Hintはevidenceではない。evidence_spansへUser Wording Hintの文字列を入れてはいけない。",
                "# Character Speech",
                json.dumps({"speech": response.speech}, ensure_ascii=False),
                "観測規則:",
                "- 各Candidateについて、speechがそのpredicateを実際に表現しているかpredicate_realizedで答える。",
                "- observed_stateはspeechが実際に表すstateを absent/low/moderate/high/very_high/"
                "present/overview/unknown/omitted から選ぶ。期待値を想像して合わせない。",
                "- absentは対象の存在・成立を否定している状態。lowは対象が存在・成立した上で弱い強度を"
                "表している状態であり、否定や非存在をlowへ読み替えない。",
                "- presentは対象の存在・成立を表すが、順序づけられた強度差までは表していない状態。",
                "- low/moderate/high/very_highはpresentとは異なり、speechから順序づけられた強度差が"
                "意味的に識別できる場合だけ選ぶ。強度の表現手段を特定の単語・副詞・語尾へ固定しない。",
                "- overviewは対象そのものを単にpresentと述べる状態ではない。全体状態・総合状態を、"
                "一つ以上の状態次元や性質をまとめて特徴づけている場合に使う。",
                "- unknownは対象の存在・不在・強度・値を現時点で確定していない状態。"
                "特定polarityへcommitしたspeechをunknownにしない。",
                "- omittedはspeechがそのpredicateを意味として表現していない場合に使う。",
                "- observed_certaintyは、観測器自身の判定自信度でもpredicateの強度でもない。"
                "speechが『このpredicateはobserved_stateである』という命題へどの程度epistemically commitしているかを"
                "high/medium/low/unknownで表す。Semantic Plan側のcertaintyも同じ命題certaintyとして扱う。",
                "- highはobserved_state自体を明確に確定して述べる場合、mediumはそのstateを暫定的・蓋然的に述べる場合、"
                "lowはそのstate判定そのものへ強い留保・判断困難を残す場合に使う。certaintyを強度へ読み替えない。",
                "- observed_state=unknownでも同じ定義を使う。『対象状態が現在unknownである』ことを明確に述べるspeechは"
                "observed_certainty=highになり得る。一方、unknownという判定自体にも留保を残すspeechはmedium/lowになり得る。"
                "unknownだから自動的にcertainty=lowへ固定しない。",
                "- predicate_evidence_spans/state_evidence_spans/certainty_evidence_spansにはCharacter Speechに"
                "実在する原文部分だけを列挙する。User Wording Hint、Candidate ID、説明文をspanへ混ぜない。",
                "- certainty_evidence_spansはmedium/lowのepistemic留保をspeech中で支える原文部分を優先する。"
                "highで無標の直接表現なら空配列でもよい。",
                "- 該当する明示spanが不要または存在しないfacetは空配列でよい。",
                "- Candidateのcanonical英語IDをspeech中に存在する語だと仮定しない。",
                "- Characterのsemantic_realizations等の自己申告metadataは観測根拠にしない。",
                "- 自然言語の意味判定を有限個の単語・phrase・regex・substring対応表へ置き換えない。",
                "top-levelは必ずobjectとし、observations配列を1つ含める。",
                "JSONのみ返す。各observationはrealization_id、predicate_realized、observed_state、"
                "observed_certainty、predicate_evidence_spans、state_evidence_spans、"
                "certainty_evidence_spansを含める。",
            ]
        )

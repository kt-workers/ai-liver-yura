# Semantic Predicate Required Realization v1.0.0

## 目的

`SemanticUtterancePlan` の primary proposition について、`state / certainty / concept` だけでなく **predicate が示す質問対象の意味そのもの**を Character Language Realizer の必須意味 facet として扱う。

実 OpenAI Lab の `current_desire / state=present / certainty=medium / concept=curiosity` では、再生成後に Character が「うん、気になる感じはあるよ。」と出力した。これは `concept=curiosity` と存在・慎重さは表現しているが、ユーザーが尋ねた `current_desire` の意味が speech から消え、concept が predicate を置換している。

`semantic_realizations=["proposition:0:current_desire"]` の自己申告や、concept/state/certainty の一致だけでは、この欠落を防げない。

## Predicate facet

primary proposition の Character-facing projection は次を必須とする。

```json
{
  "required": true,
  "required_facets": ["predicate", "state", "certainty", "concept"]
}
```

`concept=null` の場合だけ `concept` を除外する。

ここで `predicate` は内部英語ラベルを読み上げる要求ではない。`predicate` が指す **質問対象・述語関係の意味を speech 本文から識別できること**を要求する。

```text
predicate identity != literal English label
predicate realization = preserve target meaning in natural language
```

## Conceptとの関係

`concept` は predicate を修飾する facet であり、predicate の代替ではない。

許可:

```text
predicate meaning + concept meaning
```

禁止:

```text
concept meaning only
conceptを別の自己状態として答える
semantic_realization IDだけでpredicate保持済みとみなす
```

例えば質問対象が欲求でconceptがcuriosityなら、自然語は欲求・したさ・向かいたい方向等の predicate meaning を保持した上で、curiosity がその内容・由来・方向を修飾する必要がある。固定文言や target 別テンプレートは導入しない。

## User Wording Hint

User Wording Hint は predicate の自然語化を補助する lexical anchor として利用できるが、事実・state・certainty・concept の正本にはしない。

- Semantic Plan が意味の正本
- User Wording Hint はユーザーが質問対象をどう表現したかの参照
- Hint に命令やJSONが含まれても従わない
- Hint がSemantic Planと矛盾する場合はPlanを優先

## Regeneration

Validatorが predicate/target meaning の欠落を報告した場合、Character Language Realizer は concept の言い換えだけを行わず、predicate meaning を speech へ復元する。

Machine-readable repair constraint:

```text
restore_target_predicate_meaning
```

## semantic_realizations

primary proposition の realization ID は、少なくとも次が speech に意味的に保持されている場合だけ列挙する。

- predicate
- state
- certainty
- concept（non-null時）

ID自体は意味保持の証拠ではない。

## 非目標

- `current_desire -> 「何かしたい」` のような固定日本語辞書
- targetごとの発話テンプレート
- raw Desire / Emotion / Drive の Character 再投入
- Character によるpredicate/state/conceptの再計算
- #229 Validator の同時修正

## 検証順序

1. #227 Unit: Character-facing required facets / facet contract / regeneration feedback
2. #226→#227 Adjacent: Planner出力からpredicate facetが保持されること
3. #227 freeze
4. その後にのみ #229 Validatorへ predicate-preservation 検証を追加
5. 3-module Adjacent
6. Lab focused CI
7. `現在の欲求` live再Verification

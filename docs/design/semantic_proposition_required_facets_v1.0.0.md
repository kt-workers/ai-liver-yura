# Semantic Proposition Required Facets v1.0.1

## 目的

`SemanticUtterancePlan`のprimary propositionを、単なるrealization IDではなく複数の意味facetを持つ必須意味単位としてCharacter Language Realizerへ渡す。

実OpenAI Labでは、`current_desire / state=present / certainty=medium / concept=curiosity` に対して、最初はCharacterが「うん、少しあるよ。」と出力してconceptを落とし未根拠の強度を追加した。さらにcertainty/intensity修復後には「うん、気になる感じはあるよ。」と出力し、conceptは保持した一方で質問対象である`current_desire`のpredicate meaningをspeechから落とした。

これは固定語彙の問題ではなく、primary propositionのfacet完全性を`state / certainty / concept`だけで定義していた問題として扱う。

## Required Facets

primary proposition（先頭proposition）は必須とし、Character-facing projectionへ次を付加する。

```json
{
  "required": true,
  "required_facets": ["predicate", "state", "certainty", "concept"]
}
```

`concept=null`の場合は`concept`をrequired facetへ含めない。

- `predicate`: 質問対象・述語関係の意味。内部英語ラベルの読み上げではなく、speech本文から何について答えたか識別できること
- `state`: polarity / presence / semantic intensityの正本
- `certainty`: 指定stateへの認識上の確からしさ
- `concept`: non-nullの場合、そのpredicateの意味内容を修飾するsemantic concept

`predicate` / `target.id`は内部接続用identityでもあるため英語ラベルをそのまま自然語として読み上げない。必要なのはlabelの再生ではなくtarget meaningの保持である。詳細は`semantic_predicate_required_realization_v1.0.0.md`を参照する。

## PredicateとConceptの言語実現

`predicate`は質問対象の意味そのものを保持する。`concept`がnon-nullの場合、そのconceptはpredicateを修飾する形で自然語として発話へ含める。

禁止:

```text
predicate meaningを落としてconceptだけ答える
conceptを完全に落として存在だけ答える
内部英語ラベルを診断名として読み上げる
User Wording Hintだけから別conceptへ置換する
```

許可:

```text
predicate meaningを自然語で保持した上でconceptを修飾として実現
Character Profileに応じた自然な日本語への意味保持変換
同じconceptを直接語・説明的表現・短い言い換えとして実現
```

固定日本語辞書やtarget別テンプレートは導入しない。

## StateとIntensity

`state=present`は存在を意味するだけで、強度は表さない。

したがってSemantic Planが`low / moderate / high / very_high`等の強度stateを持たない場合、Characterは「少し」「かなり」等の強度を新規推定しない。

```text
present != low
present != moderate
present != high
```

`state=unknown`についても従来どおり特定polarityや強度へ変換しない。

## Certainty

`certainty`はstateへのepistemic certaintyである。

```text
certainty=medium
!= intensity=moderate
!= state=low
```

medium / low certaintyを自然語化するときは、断定度、hedge、慎重な言い回しとして表現し、強度語へ置き換えない。

## semantic_realizations

`semantic_realizations`のrealization IDは、primary propositionについてrequired facetsがすべてspeechへ意味的に保持されている場合だけ列挙する。

IDの自己申告だけで意味保持を保証したとはみなさない。#229 Character Realization Validatorがspeech本文とrequired facetsを照合する。

## Validator境界

Character Realization Validatorはprimary propositionについて次を検証する。

1. predicate / target meaningをspeechから欠落・別概念化していない
2. stateを反転・欠落していない
3. certaintyを過大化・矮小化・強度へ変換していない
4. non-null conceptを欠落・別概念化していない
5. conceptがpredicateを置換していない
6. Semantic Planにない強度を追加していない
7. semantic_realization IDだけを根拠にacceptedしない

ただし#229の実装修正は#227 Unit / Adjacentを再freezeした後に別工程で行う。

## 非目標

- conceptごとの固定日本語翻訳辞書
- predicateごとの固定日本語翻訳辞書
- raw Desire / Emotion / DriveのCharacter再投入
- Characterによる欲求選択
- stateやconceptの再計算
- TTS prosody / acoustic pause

## 検証

自動テストでは`current_desire / present / medium / curiosity`を使い、Character Promptが`predicate / state / certainty / concept`をrequired facetsとして提示し、predicate meaningをconceptで置換せず、`present`から強度を推定しないことを確認する。

実LLMの最終確認は#223 Semantic Character Labの4番目`現在の欲求`で行う。

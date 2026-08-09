# Semantic Proposition Required Facets v1.0.0

## 目的

`SemanticUtterancePlan`のprimary propositionを、単なるrealization IDではなく複数の意味facetを持つ必須意味単位としてCharacter Language Realizerへ渡す。

今回の実OpenAI Labでは、`current_desire / state=present / certainty=medium / concept=curiosity` に対してCharacterが「うん、少しあるよ。」と出力し、`concept`を落としたうえSemantic Planにない強度「少し」を追加した。

これは固定語彙の問題ではなく、primary propositionのfacet完全性が契約化されていなかった問題として扱う。

## Required Facets

primary proposition（先頭proposition）は必須とし、Character-facing projectionへ次を付加する。

```json
{
  "required": true,
  "required_facets": ["state", "certainty", "concept"]
}
```

`concept=null`の場合は`concept`をrequired facetへ含めない。

- `state`: polarity / presence / semantic intensityの正本
- `certainty`: 指定stateへの認識上の確からしさ
- `concept`: non-nullの場合、そのpropositionが何についての意味状態かを表すsemantic concept

`predicate` / `target.id`は内部接続用identityであり、自然語ラベルとして読み上げることを要求しない。

## Conceptの言語実現

`concept`がnon-nullの場合、Characterはその概念の意味を自然語として発話へ含める。

禁止:

```text
conceptを完全に落として存在だけ答える
内部英語ラベルを診断名として読み上げる
User Wording Hintだけから別conceptへ置換する
```

許可:

```text
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

1. stateを反転・欠落していない
2. certaintyを過大化・矮小化・強度へ変換していない
3. non-null conceptを欠落・別概念化していない
4. Semantic Planにない強度を追加していない
5. semantic_realization IDだけを根拠にacceptedしない

## 非目標

- conceptごとの固定日本語翻訳辞書
- raw Desire / Emotion / DriveのCharacter再投入
- Characterによる欲求選択
- stateやconceptの再計算
- TTS prosody / acoustic pause

## 検証

自動テストでは`current_desire / present / medium / curiosity`を使い、Character Promptが`state / certainty / concept`をrequired facetsとして提示し、`present`から強度を推定しないことを確認する。

実LLMの最終確認は#223 Semantic Character Labの4番目`現在の欲求`で行う。

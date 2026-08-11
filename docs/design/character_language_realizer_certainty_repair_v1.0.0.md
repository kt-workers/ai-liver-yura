# Character Language Realizer Certainty Repair v1.0.0

## 目的

#223 Semantic Labのlive Verification `current_desire` で、Semantic Planが

```text
state = present
certainty = medium
concept = curiosity
```

を正しく保持している一方、Character Language Realizerが`medium certainty`を程度・強度へ誤変換し、`少し`→`ちょっと`のような同種置換を再生成でも繰り返した。

本修正は#227 Character Language Realizerの言語実現責務だけを補強する。#226 Semantic Planの意味、#229 Validatorの判定基準、retry回数は変更しない。

## 意味境界

- `state` は対象状態の存在/不在/強度を表す。
- `certainty` は指定されたstateへのepistemic certaintyであり、stateの強度ではない。
- `concept` はpredicateの意味内容を修飾するfacetであり、concept単独の別stateへ置換しない。

したがって `state=present + certainty=medium` は「弱く存在する」ではない。

## Character-facing facet realization contract

primary propositionについてPromptへmachine-readableな補助契約を追加する。

- `state_semantics`
- `certainty_semantics = epistemic_not_intensity`
- `certainty_realization`
- `intensity_allowed`
- `degree_marker_substitution`
- `concept_role`

強度state (`low/moderate/high/very_high`) がない場合は `intensity_allowed=false` とする。

`certainty=medium/low` は `certainty_realization=epistemic_modality` とし、程度副詞へ写像しない。

`concept` がある場合は `concept_role=modify_predicate_not_replace_it` とし、predicateの意味を保ったまま自然語化する。

## Regeneration

Validatorがunsupported intensityを返した場合、次の再生成を禁止する。

```text
程度語Aを削除せず、意味の近い程度語Bへ置換するだけ
```

Regeneration Feedbackには、元の差分に加えてmachine-readableなrepair constraintを追加する。

- unsupported intensityを除去する
- 別の程度語へ置換しない
- primary propositionのrequired facetsを再点検する

このconstraintは新しいstateや事実を生成する命令ではなく、Semantic Planを保持したまま前回の言語実現差分だけを修復するためのもの。

## 非対象

- #226 `current_desire` の `certainty=medium` をhighへ変更すること
- #229 Validatorを緩めること
- fixed Japanese response template
- curiosity専用の固定文言
- retry回数の増加
- Body/TTS/Voice制御

## Unit gate

1. `state=present / certainty=medium` が `epistemic_not_intensity` としてPromptへ投影される。
2. 強度stateがなければ `intensity_allowed=false` になる。
3. `concept` はpredicateを置換しないfacetとして明示される。
4. unsupported intensityのregeneration feedbackに「別の程度語へ置換しない」repair constraintが付く。
5. raw execution status / claim payload / Emotion等は引き続きCharacterへ逆流しない。
6. Legacy pathとSemantic raw output schemaは変更しない。

Unit PASS後、#226↔#227 Adjacentを再実行し、その後#229とのAdjacentとLab focused CIを再実行する。
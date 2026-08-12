# Semantic Unknown State Realization v1.0.0

## 目的

`SemanticUtterancePlan`の`state=unknown`を、Character Language Realizerが勝手に`present` / `absent` / 強度付き状態へ変換しないための意味境界を定義する。

## 背景

Character Semantic Labの`current_desire` live検証で、上流情報が不足して次のSemantic Planになった。

```text
predicate = current_desire
state = unknown
certainty = low
```

しかしCharacterは「うん、少しあるかも。」と発話し、未確定状態を弱い肯定へ変換した。Character Realization Validatorもこれを受理した。

`unknown`は「弱く存在する」「存在する可能性が高い」を意味しない。

## 契約

```text
state = unknown
```

は次だけを意味する。

- 対象状態の存在・不在・強度をSemantic Planが確定していない
- Characterは`present` / `absent` / `low` / `moderate`等を推測しない
- `certainty=low`は別stateを推測する許可ではない
- 必要なら「現在は判断できていない」という不確定性だけを自然言語化する

次の変換は禁止する。

```text
unknown -> present
unknown -> absent
unknown -> low
unknown -> high
unknown + low certainty -> maybe present
```

## Character Language Realizer

Characterは確定済みstateを言語実現するだけであり、`unknown`からpolarityを作らない。

固定日本語フレーズは定義しない。Character Profileに沿った自然な不確定表現を生成してよいが、新しい自己状態を追加してはならない。

## Character Realization Validator

Validatorは`state=unknown`に対して、存在・不在・強度を断定または推測する発話をrejectする。

特に、hedgeを付けただけの特定polarityも許可しない。

```text
「あるかも」
「ないかも」
「少しある」
```

上記は例示であり、文字列一致による実装規則ではない。意味としてunknownから特定stateへ変換しているかを検証する。

## current_desireの上流契約

通常Runtimeでは、

```text
Desire State
-> Motivation Appraisal
-> ResponseContentPlanner
-> ResponseContentPlan.primary_desire
-> event.payload.memory.response_content_plan
-> ResponseContext.memory
-> ResponseSemanticsPlanner
```

の順で現在欲求を供給する。

Labがこの上流を省略する場合は、productionと同じ`ResponseContentPlan`契約をfixtureとして入力する。Drive値をDesireの代用品にはしない。

## 非目標

- DriveからDesireを推測すること
- `unknown`用固定回答テンプレートを作ること
- Characterへraw Desire数値を渡すこと
- Validatorへraw Desire Stateを戻すこと
- `primary_desire`をActivity実行許可として扱うこと

## Verification

- `state=unknown`のCharacter Promptに推測禁止契約がある
- Validator Promptもunknownから特定polarityへの変換をrejectする
- current_desire Lab presetはproductionと同じResponseContentPlan契約を供給する
- known primary_desireではSemantic Planが`present + concept`になる
- raw Desire/Drive数値はCharacter/Validator model boundaryへ出さない

# Character Regeneration Feedback v1.0.0

## 目的

Parent #225 / Work #227 / #229。

Character Language RealizerがRealization Validatorのreject後に再生成するとき、raw Validator payloadやResponseContextへ戻らず、前回発話の**意味差分だけ**を受け取って同じ`SemanticUtterancePlan`を再言語化する。

```text
Validated SemanticUtterancePlan
        ↓
Character Language Realizer
        ↓
CharacterUtterance candidate
        ↓
Character Realization Validator
        ↓ reject
ResponseValidationResult
  - reason
  - claim_differences
        ↓ projection
Regeneration Feedback
  - reason
  - differences[]
        ↓
Character Language Realizer retry
```

## 背景

live Labの`current_desire`ケースで、Planは`state=present / certainty=medium / concept=curiosity`だったが、Characterが`少し`という未計画の強度を付加した。

Validatorは1回目を`unsupported_intensity_added`としてrejectしたが、2回目のCharacter生成でも同じ`少し`が残った。

Pipelineのcorrection JSONには`claim_differences`が存在していた一方、Character-facing Prompt Builderは`reason`だけを`correction_kind`へ縮退していたため、Characterは「何が差分だったか」を受け取れていなかった。

## Character-facing Feedback契約

Characterへ渡すのは次だけ。

```json
{
  "reason": "unsupported_intensity_added",
  "differences": [
    "unsupported_intensity_markers:少し"
  ]
}
```

`differences`はValidatorがSemantic Planとspeechを比較した結果であり、最大8件・各300文字に制限する。

Characterへ渡さないもの:

- full `ResponseValidationResult`
- `execution_status`
- raw extracted claims
- invalid speech claim payload
- ResponseContext
- raw Emotion / Desire / Drive
- evidence path / value
- Activity execution payload

## 優先順位

```text
SemanticUtterancePlan
    > Regeneration Feedback
    > Character Profile / wording variation
```

Regeneration Feedbackは**新しい事実・状態・指示の正本ではない**。

Characterはfeedbackを使って前回発話との差分だけを修正し、Semantic Planのstate / certainty / concept / required / forbiddenを変更しない。

feedback文字列自体をユーザー向け発話として読み上げない。

## 例

```text
Plan:
  current_desire
  state=present
  certainty=medium
  concept=curiosity

candidate 1:
  「うん、少し気になるかな。」

Validator:
  reason=unsupported_intensity_added
  difference=unsupported_intensity_markers:少し

retry:
  「うん、気になってることはあるかな。」
```

retry例は固定文ではない。必要なのは、同じSemantic Planを保持しながら指摘された未計画強度を除去することである。

## Validatorとの境界

#229 Realization Validatorは`semantic_checks`と`surface_evidence`を用いてfacet単位のreject理由を構造化する。

Character側はValidatorのraw内部診断全体を受け取らず、Pipelineが`ResponseValidationResult.claim_differences`へ正規化したSemantic差分だけを受け取る。

これによりValidatorの実装詳細やraw stateをCharacter責務へ逆流させない。

## 検証

自動テストでは次を確認する。

1. `reason`と`claim_differences`だけがCharacter Promptへ投影される。
2. `execution_status`、raw claims、Emotion等は投影されない。
3. feedbackはSemantic Planより下位の診断情報であることをPromptに明示する。
4. live Labではreject後の2回目生成が同一差分を繰り返さず、Validator acceptedへ到達できるか確認する。

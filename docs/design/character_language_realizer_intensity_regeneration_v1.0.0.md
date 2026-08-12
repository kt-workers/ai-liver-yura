# Character Language Realizer Intensity Regeneration v1.0.0

## 位置付け

Parent #225 / Work #227 / Draft PR #232。

Extended Verification E1 `joy=high` の実LLM再検証で、初回Character発話 `かなり楽しい` がValidatorに `strengthened` としてrejectされた後、再生成が `楽しい` まで弱まり、Planの `high` が単なるpresenceへ縮退した。

本設計はCharacter Language Realizerの再生成時state fidelityだけを対象とする。特定の日本語程度語をstateへ固定対応させず、台詞品質やCharacterらしさは採点しない。

## 原因

既存のRegeneration Feedbackは `state_preserved` というdiagnostic文字列を検出した場合だけ `restore_state_fidelity` を追加する。

E1の実ログではValidatorが:

- reason: `state_intensity_overstated`
- state_fidelity: `strengthened`
- difference: planのhighより強い / state fidelityがexactではない

を返したが、Pipelineのcorrectionへはreasonとdifference文字列だけが投影されるため、#227はこれをstate fidelity修復として認識できなかった。

結果として2回目は「過剰強度を消す」ことだけに寄り、`high`そのものを失った。

## 修復契約

再生成feedbackが次のいずれかを示す場合、#227は `restore_state_fidelity` を必須repair constraintとして扱う。

- `state_preserved` failure
- `state_fidelity` / `state fidelity` mismatch
- `strengthened`
- `weakened`
- `unknown_committed`
- `polarity_changed`
- `state_intensity_overstated`
- `state_intensity_understated`

特にexplicit intensity stateでは、修復を次のように解釈する。

- strengthened: 過剰な強度を下げるが、Planのexplicit intensity state自体は消さない
- weakened: 強度意味をPlanのstateまで戻す
- unknown/polarity系: present/absentへ確定せずPlan stateを復元する

修復の基準は常に現在のSemantic Planであり、Validatorの自然文differenceを新しい状態の正本として使用しない。

## E1で必要な挙動

Plan:

```text
predicate=joy
state=high
certainty=high
```

初回が`strengthened`としてrejectされた場合、再生成は:

- `very_high`相当へ強めない
- 単なる`present`相当へ弱めない
- `high`という意味を自然文として保持する

必要がある。

「かなり」「とても」「すごく」等の固定語辞書はCharacter側に導入しない。

## Unit Gate

#227 Unitでは最低限次を確認する。

1. E1実ログ型のreason=`state_intensity_overstated`から`restore_state_fidelity`を生成する
2. `state fidelity` / `state_fidelity` diagnosticから同repair constraintを生成する
3. strengthened/weakened系diagnosticでも同repair constraintを生成する
4. regeneration promptが「過剰を除去してもexplicit intensity stateをpresenceへ落とさない」と明示する
5. Semantic Plan / evidence / raw Emotion・Drive境界は変更しない

## 非目標

- Validator #229のfalse accept修正
- 特定の日本語程度語とhigh/moderate/lowの固定対応
- SpeechPerformancePlan / TTS / Body
- Characterらしさ・自然さの採点

#227 Unit PASS後に#226↔#227 Adjacentを再実行し、その後にのみ#229へ戻る。

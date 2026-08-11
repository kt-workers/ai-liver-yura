# Semantic → Character Intensity Regeneration Adjacent v1.0.0

## 対象

#226 SemanticUtterancePlan → #227 Character Language Realizer。

Extended Verification E1で発生した `joy=high` 再生成弱化を、手作りPlanではなくproduction Planner出力から隣接契約として固定する。

## Production path

```text
InternalStateAwareResponseContextBuilder
→ ResponseSemanticsPlanner
→ SemanticUtterancePlan: joy/high/high
→ CharacterLanguageRealizerService correction normalization
→ CharacterLanguageRealizerPromptBuilder
```

Validator #229そのものはこのAdjacentでは起動しない。E1実ログ型correctionだけを#227入力として与える。

## 入力

- typed target: `internal_state/joy`
- user text: `楽しい？`
- emotion.current.reactive.joy: `0.78`

production Plannerの期待:

- predicate: `joy`
- state: `high`
- certainty: `high`

## Correction

E1 liveで観測した形:

- reason: `state_intensity_overstated`
- difference: Planのhighを超える / state fidelity exactではない

#227はこれをstate fidelity repairへ正規化する。

## Acceptance

再生成Promptで:

1. production Planの `joy/high/high` が変わらない
2. Required Facet Contractは `state_fidelity=preserve_exact_semantic_state`
3. `intensity_fidelity=must_preserve_intensity_if_realized`
4. Regeneration Feedbackに `restore_state_fidelity` がある
5. Promptがhighをpresenceへ弱めないことを要求する
6. raw evidence path / numeric emotion値をCharacter境界へ出さない

## 非目標

- #229 Validatorの正誤判定
- 日本語の特定程度語をhighへ固定すること
- live OpenAIの出力文を固定すること

このAdjacent PASS後に#227を再freezeし、その後にのみ#229のfalse accept修正へ進む。

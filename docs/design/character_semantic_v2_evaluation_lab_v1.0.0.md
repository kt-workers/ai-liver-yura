# Character Semantic v2 Evaluation Lab v1.0.0

## Scope

Issue #223 / #303 / Parent #225。

Semantic Realization v2を、全Runtime・Body・TTSから切り離して評価するarchitecture evaluation harness。

## 正規Pipeline

```text
SemanticUtterancePlan v2
→ Structured Character Language Realizer v2
→ CharacterUtterance + alignment hints
→ CharacterSemanticVerifier
→ Runtime relative semantic decision
```

production gateとして以下を使用しない。

- `character_realization_observer`
- old absolute `observed_state / observed_certainty`
- Post-Observation Validator
- finite natural-language dictionary / regex / substring matcher

## Baseline

```text
Character model: gpt-5.4-mini
Character reasoning: none
Verifier model: gpt-5.4-mini
Verifier reasoning: low
```

上位`gpt-5.4`はdiagnostic upper boundであり、上位だけ成功しても完了扱いにしない。

## Model matrix

同一caseについてCharacter生成とVerifier検証を分離して再利用する。

```text
mini Character speech  → mini Verifier
large Character speech → mini Verifier
mini Character speech  → large Verifier
large Character speech → large Verifier
```

Character speechをVerifierごとに再生成しない。

## Fixed cases

既存LabのBasic4 + E1-E8 = 12ケースを維持する。

目的は正解文固定ではなく、意味保持原因クラスの比較。

## Failure classes

- structured_output_failure
- predicate_changed
- value_status_changed
- polarity_contradicted
- degree_weakened
- degree_strengthened
- certainty_stronger
- certainty_weaker
- concept_changed
- required_omitted
- summary_collapsed
- unsupported_new_fact
- existence_boundary
- budget
- ambiguous_required_facet

## Export

最低限:

- case_id / label
- Semantic Plan v2
- Character model / reasoning
- Character speech / alignments
- Verifier model / reasoning
- typed verification relations
- Runtime decision
- failure classes
- generation/verification latency
- call count
- prompt（明示opt-in時のみ）

API key / Basic auth secretを含めない。

## Gate

- fake mode: wiring / schema / failure aggregation
- focused automated tests
- Full Product regression
- mini/mini standard configuration
- model matrix実行可能
- ユーザーVerificationは最後に1回だけ依頼する

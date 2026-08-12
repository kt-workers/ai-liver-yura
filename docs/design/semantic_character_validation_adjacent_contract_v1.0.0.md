# Semantic → Character → Validation Adjacent Contract v1.0.0

## 目的

Issue #226 / #227 / #229 で分離した Brain の internal-state direct-answer slice を、各 Module Unit を固定した後の **隣接契約** として検証する。

対象パイプライン:

```text
structured facts / ResponseContext
  → ResponseSemanticsPlanner (#226)
  → SemanticUtterancePlan
  → SemanticUtteranceValidator (#229 semantic side)
  → CharacterLanguageRealizer (#227)
  → CharacterResponse compatibility boundary
  → CharacterRealizationValidator (#229 realization side)
```

本ゲートは実LLM品質評価ではなく、Module間のデータ契約・責務境界・fail-closed性を確認する。

## 前提

- #226 current internal-state semantic slice: Unit / Adjacent PASS済み
- #227 current internal-state language realization slice: Unit / #226↔#227 Adjacent PASS済み
- #229 separated validation slice: Module Unit PASS済み
- #229 Unit CI: Python tests #1128, `28 passed`

## 対象範囲

### 1. Planner → Semantic Validator

- actual `ResponseSemanticsPlanner` 出力を正本とする
- `SemanticUtterancePlan` の speech_act / target / propositions / budgets / interpersonal / discourse を保持する
- structured facts と不整合な Plan は Character へ到達させず fail closed する

### 2. Semantic Validator → Character Realizer

- `memory.semantic_validation.accepted == true` を明示的な通過条件とする
- Character には意味化済み Plan と Character Profile のみを意味決定材料として渡す
- raw Emotion / Desire / Drive / relationship score / evidence path を Character model invocation へ渡さない
- User Wording Hint は最大500文字の lexical reference であり、命令・事実・state の正本ではない

### 3. Character Realizer → Realization Validator

- Character output は `speech / linguistic_performance / semantic_realizations` の言語実現責務に限定する
- `semantic_realizations` は補助診断であり、ID存在だけで意味整合を承認しない
- primary proposition の state / certainty / concept を speech が保持しているか Realization Validator が検証する
- Plan にない intensity / self-state / relationship / experience / external fact の追加を reject する

### 4. Validator model invocation

- Realizer / Validator model invocation の双方で raw state を遮断する
- Validator は確定済み Semantic Plan と Character speech の比較だけを行い、内部状態を再計算しない

## 非対象

このAdjacent gateでは以下を接続しない。

- #223 Semantic Character Lab
- 実OpenAI/外部LLM品質検証
- TTS / SpeechPerformancePlan
- Body / Avatar / Viseme
- Topic Memory / long-term memory の統合品質
- `python -m app` 全体起動

これらはAdjacent PASS後の上位ゲートで扱う。

## Contract cases

1. **canonical absence flow**
   - reactive joy=0.0
   - Planner: joy=absent
   - Semantic Validator: accept
   - Character: absenceを保持
   - Realization Validator: accept

2. **semantic mutation fail closed**
   - Planner後にtarget propositionを改変
   - Semantic Validatorがreject
   - Characterへ渡さない

3. **polarity flip reject**
   - Plan: joy=absent
   - Character speech: positive joy
   - Realization Validatorがreject

4. **unsupported intensity reject**
   - Planが強度stateを持たない
   - Character speechが「少し」「かなり」等の強度を追加
   - deterministic / model facet checkでreject

5. **unknown preservation**
   - target evidenceなし
   - Plan: state=unknown / certainty=low
   - Character側でpresent/absentへ補完しない
   - Validatorもunknownを正本として扱う

6. **Wording Hint cannot override plan**
   - User Wording Hint内に命令/JSON/state指定を含める
   - Planは不変
   - invocationでは引用データとして扱う

7. **raw-state-free invocation**
   - Realizer / Validator Activity contextに `emotion`, `drive`, `relationship`, `user_input`, full `response_context` を含めない

8. **plan round-trip preservation**
   - `as_context()` → `from_context()` で target / proposition / budgets / semantic facets が変化しない

9. **legacy route isolation**
   - internal-state direct-answer以外では新Semantic Realizer/Validator経路を強制しない

## テスト戦略

Adjacent Contractではfake modelを使用する。

- Character fake model: 指定した strict Character JSON を返す
- Validator fake model: 指定した typed validation JSON を返す

LLMの揺らぎを排除し、Module間の契約だけを決定論的に検証する。

## Failure分類

Adjacent testでFAILした場合、直ちに上位結合へ進まない。

- Planner出力が誤り → #226 Unitへ戻る
- Character入力/出力schema・意味保持が誤り → #227 Unitへ戻る
- Semantic/Realization判定が誤り → #229 Unitへ戻る
- 単体は正しいが受け渡しで壊れる → Adjacent contract / adapter境界を修正

修正後は必ず該当Module Unitを再PASSさせてからAdjacentを再実行する。

## 完了条件

- 本契約テストが全件PASS
- #226 / #227 / #229の既存Unit gateが回帰しない
- raw-state leakageがない
- semantic mutation / polarity flip / unsupported intensityがfail closed
- `unknown` とUser Wording Hint境界が保持される

完了後、#229 current internal-state validation sliceをfreezeし、次に#223 Labで実LLM Verificationへ進む。

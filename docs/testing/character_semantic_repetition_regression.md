# Character Semantic Repetition Regression

## 対象

Character / Response Validator Lab のプリセット `現在の気分・反復`。

## 再現した失敗

```text
SemanticUtterancePlanがstructured factsと整合しません:
discourse_context_mismatch
```

Character Language Realizerへ到達する前にSemantic Validatorがfail closedした。

## 原因

Productionの`InternalStateAwareResponseContextBuilder`は`ResponseSemanticsPlanner.plan()`の後で、`avoid_repetition=true`かつ`recent_speech_summary`ありの場合に反復回避用`discourse_context`を後付けしていた。

一方、`SemanticUtteranceValidator`は`ResponseSemanticsPlanner.plan()`だけでcanonical Planを再構成して比較していたため、同じResponseContextから次の2種類のPlanが生じた。

```text
Production Plan
  discourse_context.recent_speech_summary = present

Validator canonical Plan
  discourse_context.recent_speech_summary = absent
```

## 修正

`app/runtime/semantic_discourse_context.py`の`project_semantic_discourse_context()`へ談話Context投影規則を一本化した。

```text
ResponseSemanticsPlanner
        ↓
project_semantic_discourse_context
        ↓
SemanticUtterancePlan
```

Production ResponseContext生成側とSemantic Validatorのcanonical再構成側が同じProjectorを利用する。

Validatorで`discourse_context_mismatch`を無視する修正にはしていない。改ざんされた談話Contextは引き続き不整合として検出する。

## 回帰テスト

`tests/test_semantic_repetition_context.py`で以下を確認する。

- `avoid_repetition=true`かつrecent speechあり → finite discourse contextを投影
- `avoid_repetition=false` → recent speechをCharacter-facing Semantic Planへ露出しない
- 投影済みPlanをSemantic Validatorへ渡す → `semantic_plan_consistent`

## 再Verification

Renderへ最新branchが反映された後、`現在の気分・反復`をlive modeで再実行する。

期待:

1. `discourse_context_mismatch`で停止しない
2. Semantic Validation accepted
3. Character Language Realizerへ到達
4. recent speechと同一・近似表現を避ける
5. target=`current_feeling`を維持
6. 無関係な新話題・未根拠自己状態を追加しない
7. Character Realization Validator accepted

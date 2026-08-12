# Character Realization Observer Schema Retry v1.0.0

## 位置づけ

Parent #225 / Work #229 / Draft PR #233。

2026-08-12の#223 Live Verificationで、`extended_current_desire_unknown`が意味不一致ではなくObserverの出力型不正によりfallbackした。

実例では`predicate_realized`がJSON booleanではなく`"no"` / `"omitted"`文字列として返り、`RealizedSemanticObservation.from_mapping()`が正しくfail closedした。

本設計はsemantic authorityを緩めず、**schema不正だけを1回再取得するbounded contract retry**を追加する。

## 原則

正規フロー:

```text
Character speech
→ Independent Observer call #1
→ typed schema valid? ─ yes → Runtime typed comparison
                 └ no
                   ↓
          Observer contract retry #2
                   ↓
          typed schema valid? ─ yes → Runtime typed comparison
                         └ no → fail closed
```

## Retryで変えないもの

2回目も同じIndependent Observerであり、次を渡さない。

- expected state
- expected certainty
- expected concept
- expected intensity
- raw Emotion / Desire / Drive
- Planとの一致/不一致結果

`llm_role`も`character_realization_observer`を維持する。

## Retryで追加する情報

追加するのは出力型契約だけ。

- `predicate_realized`はJSON boolean `true / false`
- `observed_state` / `observed_certainty`は既存closed enum
- evidence spansは`array[string]`
- top-levelは`{"observations":[...]}`または同じtyped observation配列

前回の不正raw output自体は2回目Promptへ渡さない。したがって`"no"`を`false`へ変換する等のcorrection taskにはしない。

## Runtimeで行わないこと

- string `"no"` → boolean `false`
- string `"yes"` → boolean `true`
- string `"omitted"` → `predicate_realized=false`
- state / certainty / polarityをspeechの有限語彙から補完
- 不足fieldへPlan期待値を注入

これらは型修復に見えてsemantic valueを推定するため禁止する。

## Fail closed

以下ではsemantic validation済みと扱わない。

- Observer model invocation failure
- 2回ともJSON parse失敗
- 2回ともtyped schema不正
- enum不正
- evidence schema不正

schema retryは最大1回とし、無制限再試行しない。

## Envelope normalizationとの関係

既存どおり、同じtyped observation配列の

- `{ "observations": [...] }`
- top-level `[...]`

の差だけは構文上正規化してよい。

これは意味値の補完ではない。

## Gate

1. 1回目の`predicate_realized="no"`をRuntimeでcoerceしない。
2. 2回目を同じspeechから独立再観測し、valid boolなら受理できる。
3. retry Promptへexpected semantic facetsを追加しない。
4. 前回のinvalid raw valueをretry Promptへ渡さない。
5. 2回目もschema不正ならfail closed。
6. top-level list normalizationは維持する。
7. finite natural-language semantic matcherを追加しない。

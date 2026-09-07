# #323 D10 LLM実行Policy 実装対応

Owner: #323
Canonical: `llm_execution_numeric_contracts.md`
Status: Implementation mapping

## 1. 目的

D10で追加されたLLM実行数値契約を、既存の可変Role契約を作り直さずprovider-neutralなDomain契約へ反映する。

本工程はProvider固有model名・temperature range・retryable分類を決めない。それらは#357の責務とする。

## 2. LLMExecutionPolicy generation

`LLMExecutionPolicy` は次を必須にする。

- `policy_id`
- `policy_revision`
- `model_class`
- `reasoning_effort`
- `timeout_seconds`
- `max_attempts`
- `max_output_tokens`
- `retry_policy`
- optional `temperature_normalized`

`policy_id` / `policy_revision` はrequestの `execution_policy` に含まれることでrequest generationへbindされる。

`temperature_normalized` はProvider値ではなく `[0, 1]` のprovider-neutral controlである。旧 `[0, 2]` temperature意味はDomain正本から除去する。

## 3. Retry policy

`LLMRequestRetryPolicy` を追加する。

- `initial_backoff_seconds > 0`
- `backoff_multiplier >= 1`
- `max_backoff_seconds >= initial_backoff_seconds`
- bool / NaN / Infinityを拒否

retry番号 `n >= 1` に対して次を決定的に返す。

```text
min(max_backoff_seconds,
    initial_backoff_seconds * backoff_multiplier ** (n - 1))
```

jitterは持たない。

## 4. #357との境界

#323ではdelay算出までをDomain Authorityとする。

#357は後続工程で次を実装する。

- Provider mapping identity/revision
- normalized temperatureからconcrete Provider値への明示mapping
- unsupported temperatureのfail-closed
- Provider max output token上限
- typed retryable classificationに基づくsleep/backoff
- retry sleep後のdeadline再確認
- policy/mapping provenance

現行OpenAI Adapterが参照する `.temperature` は#357移行までの読み取り互換だけ残す。この値はnormalized controlであり、Provider parameterとしてのcanonical mappingではない。#357でAdapterを正本mappingへ移行し、この互換参照への依存を解消する。

## 5. Verification

- identity/revision strict validation
- timeout / attempts / output tokens strict validation
- normalized temperatureの0/1境界と範囲外拒否
- retry policy strict validation
- retry n=1、指数増加、上限cap
- bool拒否
- request serializationへpolicy identity/revision/retry policyを保持
- 既存Role / Request / Result / schema交換契約の回帰なし

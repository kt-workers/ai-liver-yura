# V2 LLM Execution / Numerical Contracts

Owners: #323 / #357
Related: `llm_role_contracts.md`, `llm_provider_adapter_contracts.md`, `runtime_kernel_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

`LLMExecutionPolicy`のtimeout、attempt、output token、temperature、request retry backoffを、Provider Adapterや実装者のhidden defaultに委ねずprovider-neutral contractとして固定する。

Logical Roleとconcrete Provider/modelの分離は維持する。

## 2. Canonical execution policy

D10以降の`LLMExecutionPolicy`は次を正本とする。

```text
LLMExecutionPolicy
- policy_id: non-empty stable identity
- policy_revision: non-negative int
- model_class
- reasoning_effort: minimal | low | medium | high
- timeout_seconds: finite float > 0
- max_attempts: int >= 1
- max_output_tokens: int >= 1
- temperature_normalized: optional finite float in [0, 1]
- retry_policy: LLMRequestRetryPolicy

LLMRequestRetryPolicy
- initial_backoff_seconds: finite float > 0
- backoff_multiplier: finite float >= 1
- max_backoff_seconds: finite float >= initial_backoff_seconds
```

- boolをinteger/numberとして受理しない。
- `max_attempts`は**initial Provider attemptを含む総attempt数**。`1`はretryなし。
- `temperature_normalized`はProvider固有temperature値ではなく、0=deterministic寄り、1=Role policyで許す最大variationというprovider-neutral controlである。
- Roleがtemperature制御を必要としない場合はnull。AdapterはnullをProvider defaultへ暗黙変換するのではなく、そのRole mappingで「parameterを送らない」ことを明示する。
- policy missing/invalid時はProvider callを行わず`POLICY_VIOLATION`でfail-closedする。

## 3. Provider mapping

Provider registryは`model_class / reasoning_effort / temperature_normalized`をconcrete設定へ明示mappingする。

```text
LLMProviderExecutionMapping
- mapping_id
- mapping_revision
- provider_id
- model_class
- reasoning_effort
- concrete_model_ref
- concrete_reasoning_value?
- temperature_mapping?
- provider_max_output_tokens?
```

`temperature_mapping`が存在する場合:

```text
ProviderTemperatureMapping
- provider_min
- provider_max
```

linear mappingを正本とする。

```text
provider_temperature =
  provider_min
  + temperature_normalized * (provider_max - provider_min)
```

Rules:

- provider_min/maxはfiniteかつ`provider_min <= provider_max`。
- ProviderがtemperatureをsupportしないRole/mappingでは`temperature_normalized != null`をsilent ignoreせず`POLICY_VIOLATION`または明示degradation policyへ閉じる。
- Provider固有range/clampをCore codeに埋め込まない。
- concrete modelのoutput limitがknownなら`max_output_tokens <= provider_max_output_tokens`をcall前に検証する。超過値をsilent clampしない。

## 4. Timeout / deadline

requestに`deadline_at`がある場合、Provider invocationへ使えるeffective timeoutは次とする。

```text
remaining_deadline_seconds = deadline_at_absolute - now_absolute

effective_timeout_seconds =
  min(policy.timeout_seconds, remaining_deadline_seconds)
```

- remainingが`<= 0`ならProvider callを開始せず`TIMED_OUT`。
- retry開始前にもremainingを再計算する。
- `asyncio.wait_for`等へ渡すtimeoutはfiniteかつ`>0`でなければならない。
- timeout発生をProvider successへ変換しない。

## 5. Per-request retry backoff

attempt番号を1始まりとする。attempt 1がinitial call。

attempt `k` がretryable failureで終わり、次のattempt `k+1`を開始する前のretry番号を`n=k`とする。

```text
retry_delay_seconds(n) =
  min(max_backoff_seconds,
      initial_backoff_seconds * backoff_multiplier ** (n - 1))
```

- `attempt_count >= max_attempts`ならretryしない。
- deadline内にdelay+次attemptを行える保証がない場合でもdelay開始自体は許可できるが、sleep後にremaining deadlineを再検証し、失効していればProvider callを開始しない。
- cancellation/shutdown/supersedeはretry sleepを中断する。
- hidden random jitterを入れない。必要ならversioned mapping/policyへ追加してから実装する。
- retryable分類は#357 typed failure classificationをAuthorityとし、exception message substringで推測しない。

## 6. Policy generation freshness

Role requestは`policy_id / policy_revision`をexecution provenanceとしてbindする。

- Provider resultは使用したpolicy identity/revisionとmapping identity/revisionをmetrics/provenanceとして保持する。
- request実行中にRole execution policyまたはProvider mapping revisionが変わっても、in-flight attemptをnew revisionへ付け替えない。
- old generation resultのDomain commit可否はowning Moduleのrevision/precondition gateで決める。Adapterはpolicy revision変更だけを理由にDomain意味を再解釈しない。
- new requestはcurrent policy/mapping generationを取得する。

## 7. Required tests

- timeout/max attempts/token/temperatureのstrict numeric validation
- bool拒否
- max_attempts=1でretryなし
- retry delay n=1がinitial_backoff、指数増加、max cap
- deadline既失効でProvider call 0回
- policy timeoutよりdeadline remainingが短い場合のeffective timeout
- retry sleep後deadline失効で次Provider callなし
- normalized temperature 0/1/中間のlinear mapping
- unsupported temperatureをsilent ignoreしない
- provider max token超過をsilent clampしない
- policy/mapping missingでcall前fail-closed
- cancellation/shutdownでretry sleep中断
- provider SDK型/model名をDomain DTOへ露出しない

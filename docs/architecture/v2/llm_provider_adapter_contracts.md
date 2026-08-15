# V2 LLM Provider Adapter Contract

Status: Implementation Contract / Issue #357

Parent: `docs/architecture/v2/llm_role_contracts.md`

## 1. 目的

`LLMRolePort`をOpenAI Responses API等の実Providerへ接続する。ただしProviderは論理Role、Domain State、Goal、Attention、Execution Factを所有しない。

## 2. 境界

- 入力は`LLMRoleRequest`のみ、出力は必ず`LLMRoleResult`のみとする。
- SDK response、HTTP例外、API key、Prompt本文をDomain DTO・failure message・traceへ出さない。
- `LLMModelClass`と`LLMReasoningEffort`をProvider固有model/reasoning設定へ解決する責務はAdapterにある。
- Roleごとのmodel mapping、system instruction、strict JSON schemaは不変のregistryから取得し、Role間で混ぜない。
- schema validation、revision/preconditionのcommit再検証はそれぞれAdapter後段のschema registry、Owning Moduleが所有する。

## 3. 実行

1. role descriptorとrequest schemaが一致しない場合、Provider呼出前に`POLICY_VIOLATION`で失敗する。
2. Adapterはrequestごとに独立したattemptを実行し、共有Provider clientは許可するがrequest/result/metricsは共有しない。
3. timeoutは`asyncio.timeout`でrequest policyに従う。取消は`CancelledError`を握り潰さず、呼出済みrequestには`CANCELLED`結果を返す。
4. retryは`RETRY_BOUNDED`かつretryable provider failureだけに限定し、最大attempt数を超えない。deadline超過時はretryしない。
5. `foreground`、`normal`、`background`の優先・queue・max-in-flightはRuntime Kernel #322の責務であり、Adapterは再実装しない。

## 4. Provider response

- strict JSON objectだけを`StructuredPayload`へ変換する。
- response schema IDはdescriptorのoutput schema IDと完全一致しなければならない。
- malformed JSON、object以外、schema mismatchは`SCHEMA_INVALID`へ正規化する。
- provider unavailable、rate limit、transport errorは`PROVIDER_UNAVAILABLE`または`PROVIDER_ERROR`へ正規化する。
- resultはstarted/completed UTC時刻、attempt count、token usage（未取得時は0）を持つ。到着だけでDomain commitしてはならない。

## 5. 設定と安全性

- API keyは環境変数からComposition Rootで渡し、Adapterのconstructorは文字列を保持しても公開・ログ出力しない。
- credentialなし、対応しないmodel mapping、schema registry不在はfail-closedである。
- 実Provider smokeはsecretをCIへ渡さず、ローカルHuman/Provider Verificationでのみ行う。

## 6. 検証

- fake injected clientで成功、malformed response、timeout、cancel、retry上限、provider failure、Role/schema隔離を検証する。
- slow background requestとforeground requestの独立性はRuntime #322とのAdjacent testで検証する。
- real Providerはstrict output、timeout、credential非露出をVerificationで確認する。

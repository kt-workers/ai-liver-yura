# V2 LLM Provider Adapter Contract

状態: #357の実装契約 / #567の未構成時接続設計（実装前レビュー対象）

Parent: `docs/architecture/v2/llm_role_contracts.md`

## 1. 目的

`LLMRolePort`をOpenAI Responses API等の実Providerへ接続する。ただしProviderは論理Role、Domain State、Goal、Attention、Execution Factを所有しない。

## 2. 境界

- 入力は`LLMRoleRequest`のみ、出力は必ず`LLMRoleResult`のみとする。
- SDK response、HTTP例外、API key、Prompt本文をDomain DTO・failure message・traceへ出さない。
- `LLMModelClass`と`LLMReasoningEffort`をProvider固有model/reasoning設定へ解決する責務はAdapterにある。
- Roleごとのmodel mapping、system instruction、strict JSON schemaは不変のregistryから取得し、Role間で混ぜない。
- Provider policyはRoleごとに許可した`LLMModelClass`と`LLMReasoningEffort`の組だけを、具体model名とreasoning parameterへ解決する。不明な組はProvider呼出前に`POLICY_VIOLATION`でfail-closedにする。
- D10の`LLMProviderExecutionMapping`は`mapping_id / mapping_revision`、temperature線形mapping、既知のProvider output token上限を明示して不変registryへ保持する。Adapterはrequestの`policy_id / policy_revision`と使用mapping世代を安全なexecution provenanceへ保持するが、concrete Provider値やSDK詳細をDomainへ露出しない。
- Domainの`output_schema_id`はcanonicalなschema identityであり、Providerのstructured-output format nameではない。AdapterはRole設定に明示したProvider固有のformat nameを用いて、両者を分離する。
- OpenAI Responses APIのformat nameは`^[A-Za-z0-9_-]{1,64}$`を満たさなければならない。不正値またはRole間で重複するProvider format nameはconstructorで拒否し、Provider呼出前にfail-closedにする。Domain schema IDを文字置換してProvider名へ暗黙変換してはならない。
- schema validation、revision/preconditionのcommit再検証はそれぞれAdapter後段のschema registry、Owning Moduleが所有する。

## 3. 構成済み提供サービスの実行

1. role descriptorとrequest schemaが一致しない場合、Provider呼出前に`POLICY_VIOLATION`で失敗する。
2. Adapterはrequestごとに独立したattemptを実行し、共有Provider clientは許可するがrequest/result/metricsは共有しない。
3. timeoutはPython 3.10互換の`asyncio.wait_for`でrequest policyに従う。request policyに起因する`asyncio.TimeoutError`は、retryが許される間だけ上限付き再試行の候補とし、retryしない又はattemptを使い切った終端は`TIMED_OUT` / `TIMEOUT`とする。OpenAI SDKの`APITimeoutError`及びHTTP `408`等のProvider側timeout分類とは区別する。取消は`CancelledError`を通常の成功として扱わず、呼出済みrequestには`CANCELLED`結果を返す。
4. retryはprovider例外を先にtyped分類した上で、`RETRY_BOUNDED`かつretryable provider failureだけに限定し、最大attempt数を超えない。delayはrequestの`LLMRequestRetryPolicy`による決定的backoffを使い、sleep後にdeadlineとshutdownを再確認する。deadline超過時はretryしない。OpenAI SDKのconnection/timeout、HTTP `408`、`429`、`5xx`はretryable候補とし、認証・権限・不正request・unsupported parameter等の恒久failureはretryしない。`LLMRoleFailure.retryable`はRole policyではなく実際の分類結果と一致させる。
5. `foreground`、`normal`、`background`の優先・queue・max-in-flightはRuntime Kernel #322の責務であり、Adapterは再実装しない。

## 4. Provider response

- strict JSON objectだけを`StructuredPayload`へ変換する。Provider response成功後も`StructuredPayload.schema_id`はProvider format nameではなく、元のDomain `output_schema_id`を保持する。
- response schema IDはdescriptorのoutput schema IDと完全一致しなければならない。
- malformed JSON、object以外、schema mismatchは`SCHEMA_INVALID`へ正規化する。
- provider unavailable、rate limit、transport errorは`PROVIDER_UNAVAILABLE`または`PROVIDER_ERROR`へ正規化する。
- resultはstarted/completed UTC時刻、attempt count、token usage（未取得時は0）を持つ。到着だけでDomain commitしてはならない。

## 5. 設定と安全性

- 資格情報は環境からInfrastructureの接続生成境界へ渡し、構成処理には`LLMRolePort`を返す。資格情報を公開・ログ出力しない。
- 実サービス必須の`OpenAIResponsesAdapter.from_environment()`は、資格情報なしで構築に失敗する既存契約を維持する。
- 本番の任意接続では、資格情報なしを第7節の有効な利用不可接続として表現し、最小Coreの構成失敗にしない。対応しないモデル対応付け・構造登録不在等の契約違反は引き続き拒否する。
- 実Provider smokeはsecretをCIへ渡さず、ローカルHuman/Provider Verificationでのみ行う。

## 6. 検証

- fake injected clientで成功、malformed response、timeout、cancel、deadline開始前/再試行中の失効、retry上限、transient/permanent provider failure、Role/schema隔離、model/reasoning mapping、credential・Prompt・SDK例外の非露出を検証する。dotを含むDomain schema ID、妥当な明示Provider format name、format nameのdot・65文字超過・空文字のconstructor拒否、Role間のProvider format name重複拒否も検証する。
- slow background requestとforeground requestの独立性はRuntime #322とのAdjacent testで検証する。
- real Providerはstrict output、timeout、credential非露出をVerificationで確認する。


## 7. 提供サービス未構成時の本番接続 — #567

### 7.1 目的と接続の選択

任意のLLM提供サービスが未構成であることは、最小Coreの構成失敗ではなく、有効な縮退接続である。
Infrastructure側に、OpenAI環境から本番用の`LLMRolePort`を選択する専用生成関数を設ける。
これは既存の`OpenAIResponsesAdapter.from_environment()`とは別の公開入口とする。

```text
本番用LLM接続の生成関数
  ├─ 提供サービスを構成可能 → OpenAIResponsesAdapter
  └─ 提供サービス未構成   → UnavailableLLMRolePort
```

`UnavailableLLMRolePort`は本番用の`LLMRolePort`実装であり、試験用の偽実装ではない。
有効な構成契約の下では、構成処理は資格情報がなくても利用可能なPortを取得できる。
構成処理や入力意味解析等の利用側に、資格情報の有無の判定や提供サービス固有の失敗生成を複製しない。
資格情報が存在するふり、架空の意味・確認要求・成功結果の生成は禁止する。

既存の`from_environment()`を資格情報なしでも成功するAPIへ暗黙変更しない。
実サービス必須の検証・Lab等は既存入口を継続利用できる。任意接続を必要とする本番の構成処理だけが新しい生成関数を明示的に選ぶ。
資格情報がある場合のSDK初期化・構成エラーを一律に未構成へ置き換えない。

### 7.2 構成契約の検証と失敗の優先順

両接続は同じ役割登録・入力構造・実行方針の契約を用いる。
生成関数と未構成接続にも、検証に必要な不変の役割登録と許可済みモデル・推論方針等の対応付けを渡す。
未構成だからといって空の登録や暗黙の方針で全要求を受理しない。登録自体の重複・不正は既存構成契約に従って拒否する。

要求ごとの正規順序は次のとおり。

```text
要求・役割・入力構造・実行方針を検証
  ├─ 不正 → POLICY_VIOLATION または SCHEMA_INVALID
  └─ 正当
       ├─ 提供サービス構成済み → 既存の提供サービス接続へ実行を委譲
       └─ 提供サービス未構成 → FAILED / PROVIDER_UNAVAILABLE
```

- 未登録の役割は`POLICY_VIOLATION`とする。
- 入力構造の識別不一致は既存の検証契約に従う`SCHEMA_INVALID`または`POLICY_VIOLATION`とする。
- 未対応のモデル・推論方針・実行方針の対応付けは`POLICY_VIOLATION`とする。温度や出力上限等の既存対応付け制約も省略しない。
- 検証は提供サービスの呼出を必要としない。未構成を理由にプログラム誤用・構成違反を隠さない。
- 不正なドメインオブジェクトを無理にサービス不在の結果へ変換しない。

### 7.3 正当な要求に対する利用不可結果

`UnavailableLLMRolePort.invoke()`は実サービスを呼び出さず、既存の`LLMRoleResult`を返す。

| 項目 | 値 |
| --- | --- |
| status | FAILED |
| failure.code | PROVIDER_UNAVAILABLE |
| failure.retryable | false |
| failure.message | 資格情報や生の例外を含まない、未構成を示す固定説明文 |
| output | None |
| attempt_count | 0 |
| token_usage.input_tokens / output_tokens | 0 / 0 |
| request_id / role_id / trace_id / revisions | 要求から正確に保持 |
| model_class | 要求の実行方針から正確に保持 |
| execution_provenance | None |

実サービスを呼び出していないため、提供サービスの実行来歴や使用量を捏造しない。
完了時刻等は既存のLLM結果・交換契約を満たすローカル観測として扱い、実サービスの実行事実と混同しない。
出力を持たない結果から`StructuredPayload`や成功した意味を生成してはならない。

### 7.4 復旧・再試行・診断の責務

資格情報未構成は要求単位の再試行対象ではなく、`retryable=false`とする。
要求の再試行方針を理由に、環境読取・資格情報探索・再接続を各LLM要求から繰り返さない。
将来の資格情報追加・提供サービス復旧・接続差替えは#350の依存先の利用可否と世代管理で扱う。
古い接続世代の実行結果を新しい世代へ適用しないという既存規約を維持する。

- #357: 構成済み提供サービスの呼出・既存方針の検証。
- #567: 未構成時の本番接続と明示的な接続選択。
- #350: 利用可否、ライフサイクル、将来の復旧・接続世代。
- #561: これらの本番接続を利用する構成処理。

新たな`LLMFailureCode`は追加しない。SDKオブジェクト・生の例外・資格情報・Prompt本文をドメインの結果や診断へ出さない。
ローカルの未構成状態をHTTP/SDKの呼出失敗へ偽装せず、#437の運用診断分類を本Workの都合で拡張しない。

### 7.5 後続実装の検証契約

以下はCode Phaseで追加する試験の受入条件であり、今回の設計commitでは実装・試験コードを変更しない。

1. 資格情報なしでも専用生成関数は例外終了せず、有効な`LLMRolePort`を返す。
2. 正当な要求は第7.3節の利用不可結果となり、再試行不可・出力なし・試行0・使用量0を確認できる。
3. 要求の識別情報・世代・追跡情報・モデル区分を完全に保持する。
4. 未登録の役割を利用不可で隠さず、方針違反として拒否する。
5. 入力構造の識別不一致を構造または方針違反として拒否する。
6. 未対応の提供サービス方針を方針違反として拒否する。
7. 資格情報ありでは構成済み`OpenAIResponsesAdapter`経路を維持し、既存`from_environment()`の意味も維持する。
8. 資格情報・Prompt・生の例外を公開しない。
9. 未構成接続は実サービス呼出・SDK通信を行わず、架空の実行来歴を作らない。
10. 本Workの実装後に#561で、提供サービスなしの最小Core起動と、LLM必須処理だけが型付き利用不可となる隣接・System検証を行う。これは本Work内で起動実装を追加する要求ではない。

ChatGPTによるDraft PRの読み取り専用設計レビューと、別途のCode Phase指示を受けるまで、本番コードへ進まない。

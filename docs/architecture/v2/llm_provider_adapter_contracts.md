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

### 7.2 検証責務の二層分離と失敗の優先順

提供サービスに依存しない検証と、具体的な提供サービスの対応付け検証を分離する。

| 検証層 | 検証する契約 |
| --- | --- |
| 提供サービス非依存 | 論理的な役割の登録、役割識別、入力構造識別、要求DTOの不変条件、`LLMExecutionPolicy`自体の型・値域・既存ドメイン不変条件 |
| 提供サービス固有 | 具体的なモデル対応付け、固有の推論設定、温度対応付け、出力トークン上限、提供サービス用の形式名・構造対応付け、その他`OpenAIResponsesRoleConfig`固有の方針 |

`UnavailableLLMRolePort`へ渡す登録は、既存の`LLMRoleDescriptor`を用いた不変の論理役割登録とする。
役割IDを一意に登録し、要求の役割IDから対応する記述子を引いて入力構造の識別を検証する。
新しい共通登録型や#323のドメイン契約変更は必要としない。
`default_execution_policy`を役割ごとの許可モデル一覧や要求方針との完全一致条件として読み替えない。
実行方針の検証は、既存`LLMExecutionPolicy`自体の型・値域・不変条件に限定する。

未構成接続は提供サービス非依存の本番Portであり、`OpenAIResponsesRoleConfig`を必須の構築依存にしない。
具体的なOpenAIモデル名・出力形式名・指示文・モデル方針登録を要求せず、登録済みモデルや推論対応付けの有無を仮想的に判定しない。
生成関数も、未構成接続を選択するためにこれらの固有設定を必須としない。

要求ごとの正規順序は次のとおり。

```text
LLMRoleRequest
→ 提供サービス非依存の要求・論理役割検証
  ├─ 不正 → 既存のPOLICY_VIOLATION / SCHEMA_INVALID
  └─ 正当 → 本番の提供サービス接続を選択
       ├─ 未構成 → FAILED / PROVIDER_UNAVAILABLE
       └─ 構成済み → 提供サービス固有の対応付けを検証
            ├─ 不正 → POLICY_VIOLATION等の既存失敗
            └─ 正当 → 提供サービスを呼び出す
```

この順序は要求の判定順序であり、各要求から資格情報探索・接続生成を繰り返すという意味ではない。

- 未登録の論理役割や役割識別の不整合は`POLICY_VIOLATION`とする。
- 入力構造の識別不一致は既存の検証契約に従う`SCHEMA_INVALID`または`POLICY_VIOLATION`とする。
- 要求DTO・実行方針の既存不変条件違反を、提供サービス不在で隠さない。構築時等のプログラム誤用を無理に運用上の失敗結果へ変換することも求めない。
- OpenAI固有のモデル・推論設定・温度・出力上限等は、構成済み接続を選択した後にだけ既存Adapterの契約で検証する。未構成接続へ検証を複製しない。
- 資格情報があり提供サービス接続を選択済みなのに、設定・モデル対応付け・構造等が不正な場合は、構成済み接続の既存の拒否契約に従う。`UnavailableLLMRolePort`へ切り替えて構成不良を隠してはならない。

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
古い接続世代の実行結果を新しい世代へ適用しないという既存規約を維持する。接続復旧後も、過去の利用不可結果を成功へ書き換えない。

- #357: 構成済み提供サービスの呼出・既存方針の検証。
- #567: 未構成時の本番接続と明示的な接続選択。
- #350: 利用可否、ライフサイクル、将来の復旧・接続世代。
- #561: これらの本番接続を利用する構成処理。

新たな`LLMFailureCode`は追加しない。SDKオブジェクト・生の例外・資格情報・Prompt本文をドメインの結果や診断へ出さない。
ローカルの未構成状態をHTTP/SDKの呼出失敗へ偽装せず、#437の運用診断分類を本Workの都合で拡張しない。

#567は本番接続の選択と未構成時のPortだけを所有する。
入力意味解析・Executive・Character・Planner等、各役割固有の本番要求・登録設定・構造を新規定義するWorkではない。
#561再開時に必要な役割の本番登録・設定自体が不足していると判明した場合は、#567や#561で補作せず、該当する所有者を特定して停止する。
特にCharacter Language用のOpenAI設定を入力意味解析等へコピーしてはならない。

### 7.5 後続実装の検証契約

以下はCode Phaseで追加する試験の受入条件であり、今回の設計commitでは実装・試験コードを変更しない。

1. 資格情報・提供サービス接続なしでも、正当な論理役割登録を渡した専用生成関数は成功し、`UnavailableLLMRolePort`を返す。
2. 正当な論理要求は第7.3節の利用不可結果となる。`FAILED / PROVIDER_UNAVAILABLE`、再試行不可、出力なし、試行0、使用量0と、要求の識別情報・世代・追跡情報・モデル区分の完全保持を確認する。
3. 論理役割・入力構造・識別の違反、要求DTO・実行方針の既存不変条件違反を、利用不可で隠さない。
4. 未構成接続の生成・要求処理に、具体的なOpenAIモデル対応付け・形式名・指示文・モデル方針登録が不要であることを確認する。
5. 提供サービス接続がある場合だけ、OpenAI固有のモデル・推論・温度・出力上限等の対応付け検証を行う。
6. 構成済みOpenAI対応付けの不正は既存の方針失敗等として拒否し、未構成Portへの代替で隠さない。
7. 資格情報ありでは構成済み`OpenAIResponsesAdapter`経路を維持し、既存`from_environment()`の意味も維持する。
8. 未構成PortのSDK・提供サービス呼出は0である。
9. 資格情報・Prompt・生の例外を公開せず、架空の提供サービス実行来歴を作らない。
10. 本Workの実装後に#561で、提供サービスなしの最小Core起動と、LLM必須処理だけが型付き利用不可となる隣接・System検証を行う。本Workでは役割固有設定や起動実装を追加しない。

ChatGPTによるDraft PRの読み取り専用設計レビューと、別途のCode Phase指示を受けるまで、本番コードへ進まない。

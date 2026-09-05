# V2 外部・検証面の運用数値契約

Owners: #344 / #351 / #352 / #353 / #359 / #360
Related: #343 / #350 / #445
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

Plugin Integration、GUI/Admin、Validation Lab、Development Tooling、Persistence、System Integrationで使う`bounded`、`timeout`、`queue`、`payload size`、`verification SLO`を、実装者の隠れ定数へ委ねず、版管理されたPolicyとして固定する。

本書は各Domain/Subsystemの意味Authorityを変更しない。数値は初期V2の運用基準であり、Human Verificationや実環境計測で変更する場合はPolicy revisionを進める。

## 2. 共通数値規則

- count/revision/byte/codepointはconcrete `int`。`bool`を数値として受理しない。
- seconds/rate/ratioはfinite number。NaN / ±Infinityを拒否する。
- durationの単位は秒。
- sizeの単位は明記がない限りUTF-8 byte。
- 上限超過をsilent truncate/clampして成功扱いしない。
- Policy missing/invalid時はhidden defaultを使わず、そのsurfaceだけをtyped degraded/unavailableへ閉じる。
- Policy identity/revisionはasync request、queue generation、Export/evidenceへ必要に応じてbindする。

## 3. Plugin Integration運用Policy — #344

```text
PluginIntegrationOperationalPolicy
- policy_id
- policy_revision: non-negative int
- max_in_flight_per_plugin: int >= 1
- max_in_flight_per_capability: int >= 1
- event_projection_capacity: int >= 1
- lifecycle_operation_timeout_seconds: finite float > 0
- diagnostic_min_interval_seconds: finite float >= 0
```

初期V2値:

```text
policy_id = v2.plugin-integration.default
policy_revision = 1
max_in_flight_per_plugin = 8
max_in_flight_per_capability = 4
event_projection_capacity = 128
lifecycle_operation_timeout_seconds = 30.0
diagnostic_min_interval_seconds = 5.0
```

Rules:

- effective capability concurrencyはplugin上限、capability上限、#322 lane上限の最小値。
- `max_in_flight_per_capability > max_in_flight_per_plugin`でも構文上は許可するが、effective値はplugin上限を超えない。
- event projection overflowはsilent drop禁止。state-like signalはexplicit latest/coalesce policy、effect/history signalはreject/backpressure evidenceを残す。
- lifecycle timeoutで外部effect発生可能性が残る場合、`not applied`を捏造しない。
- retry/backoffは`runtime_operational_numeric_contracts.md`を共有し、Plugin固有の無期限retryを持たない。

## 4. GUI/Adminの運用方針 — #351（第2版）

```text
GuiAdminOperationalPolicy
- policy_id
- policy_revision
- max_read_model_payload_bytes: int >= 1
- max_command_payload_bytes: int >= 1
- per_client_update_capacity: int >= 1
- max_history_page_items: int >= 1
- max_active_subscriptions_per_client: int >= 1
- max_in_flight_commands: int >= 1
- command_timeout_seconds: finite float > 0
```

現在のV2値:

```text
policy_id = v2.gui-admin.default
policy_revision = 2
max_read_model_payload_bytes = 262144
max_command_payload_bytes = 65536
per_client_update_capacity = 32
max_history_page_items = 200
max_active_subscriptions_per_client = 64
max_in_flight_commands = 16
command_timeout_seconds = 30.0
```

第1版には`max_in_flight_commands`がなく、他の数値は上記と同じだった。第1版を再定義せず、全所有者を合計した管理コマンドの受付上限、重複適用防止の判断責任、暗黙の方針補完の禁止を実装上明確にするため、第2版へ進める。

第2版の規則:

- 方針は構成・接続処理が不変のスナップショットとして必須注入する。構成要素内部で未指定を既定値へ置き換えない。欠落・不正時は構成失敗または型付きの利用不能状態とする。
- `max_in_flight_commands`は汎用配送処理が担当する全所有者合計の上限。要求の基本検証後、実行中の同一IDを先に判定し、次に容量を確認してから所有者の解決・版照合・実行へ進む。
- 実行中の同一IDは`DUPLICATE / COMMAND_ALREADY_IN_FLIGHT`、容量超過は`REJECTED / ADMIN_COMMAND_CONCURRENCY_LIMIT_REACHED`を返す。どちらも所有者呼出しは0回。容量超過の`applied_at`は`None`とし、隠れた待機キュー、黙示的な破棄、適用成功の捏造を禁止する。
- 汎用層は実行中IDだけを保持し、終了時に除去する。識別子保持数は`max_in_flight_commands`以下。終了結果のキャッシュや永久の処理済みID集合を設けない。
- 終了後の同一IDは現在の検証と受付制限を通して所有者へ再委譲する。意味上の重複適用防止、保持期間・件数・削除、永続化・再起動、要求の同一性判定、再送・再取得は所有者固有の契約と版管理された方針が所有する。本方針に一律の終了ID保持設定を追加しない。
- 各インスタンスは構築時の`policy_id / policy_revision`に固定する。実行途中で版を変えず、新インスタンス・新世代から新方針を使う。購読・更新・結果の検証証拠でも同一の方針由来情報を維持する。
- 意味と必須試験の詳細は`gui_admin_contracts.md`第5.1〜5.4節および第17.1節を正本とする。

- state snapshot更新は同一`model_kind + source_owner`でlatest-state coalescing可能。
- event/historyはsnapshot coalescingで失わない。別bounded history/query surfaceを使う。
- Read Model/Commandがbyte上限を超える場合、途中JSONやtextを切って成功扱いしない。
- command timeout後もownerがeffectを適用した可能性がある場合、refresh/readbackで事実を確認する。
- slow/disconnected clientはowner publicationをawaitさせない。

### 4.1 Stage AのHTTP通信方針 — #351（第1版）

`GuiAdminHttpTransportPolicy`は管理コマンドや表示量の方針と分離し、HTTP要求の受付・解析・停止の上限を所有する。第4節の`GuiAdminOperationalPolicy`第2版は維持する。

```text
GuiAdminHttpTransportPolicy
- policy_id
- policy_revision
- max_concurrent_requests: int >= 1
- request_timeout_seconds: finite number > 0
- shutdown_grace_seconds: finite number > 0
- max_request_line_bytes: int >= 1
- max_header_field_bytes: int >= 1
```

初期値:

```text
policy_id = v2.gui-admin-http.local-readonly
policy_revision = 1
max_concurrent_requests = 16
request_timeout_seconds = 5.0
shutdown_grace_seconds = 2.0
max_request_line_bytes = 4096
max_header_field_bytes = 8192
```

- 個数・版・バイト数には具体的な整数を要求し、boolを数値として受理しない。秒数は正の有限数とし、NaNと無限大を拒否する。
- 方針は必須注入とし、欠落・不正を内部の暗黙の既定値で補わない。構築時の識別子・版へ固定し、実行途中で別世代へ付け替えない。
- 同時要求数はGUI HTTP全体で16件まで。超過は503と安全な`GUI_REQUEST_LIMIT_REACHED`で拒否し、隠れた待機キューを作らない。終了・失敗・取消時に枠を解放する。
- HTTP要求処理は5.0秒以内に収束させ、時間切れは安全な`GUI_REQUEST_TIMED_OUT`とする。HTTP失敗をドメイン上の事実へ変換しない。
- 応答本文として直列化する表示モデルは、ラッパーを含めて`GuiAdminOperationalPolicy.max_read_model_payload_bytes`以下とし、途中切断・切詰めを成功扱いしない。
- Stage A APIは要求本文を受理しない。要求行4096バイト、単一ヘッダー項目8192バイトの上限を適用する。これらの上限を接続全体やヘッダー総量の上限と混同しない。
- 接続を応答後に長期維持しない。WebSocket/SSE/自動ポーリングは使用せず、初回と明示再取得のHTTP/JSONだけとする。
- 停止時は新規受付を止め、実行中要求を収束または取り消し、待受・接続・所有タスクを2.0秒以内に回収する。所有未完了タスク0を確認し、上限超過を停止成功として扱わない。
- 公開範囲、認証を設けない理由、待受失敗時の型付き状態、#351/#360の責務と必須試験は`gui_admin_contracts.md`第19節を正本とする。待受は127.0.0.1、初期ポート8765、アクセス区分はPUBLIC_VISUALIZATIONのみ。

## 5. Validation Lab運用Policy — #352

```text
ValidationLabOperationalPolicy
- policy_id
- policy_revision
- max_repeat_count: int >= 1
- max_delay_injections: int >= 0
- max_failure_injections: int >= 0
- max_single_injected_delay_seconds: finite float >= 0
- max_timeline_events: int >= 1
- max_work_intervals: int >= 1
- max_export_bytes: int >= 1
- max_concurrent_runs: int >= 1
```

初期V2値:

```text
policy_id = v2.validation-lab.default
policy_revision = 1
max_repeat_count = 100
max_delay_injections = 64
max_failure_injections = 64
max_single_injected_delay_seconds = 60.0
max_timeline_events = 20000
max_work_intervals = 5000
max_export_bytes = 16777216
max_concurrent_runs = 4
```

Rules:

- `repeat_count`やinjection数超過はrun admission時にrejectする。
- timeline上限到達後、machine gateに必要なeventを先頭N件だけ残してPASSさせない。runを`HARNESS_FAILED/EVIDENCE_LIMIT_EXCEEDED`へ閉じる。
- Export上限超過時は証拠を意味不明な途中sliceにせず、Export失敗と安全なsize metadataを返す。
- delay injectionはfake/wrapper境界だけに適用し、本番Domain clockを改変しない。
- concurrent run上限でforeground production runtimeをblockしない。

## 6. Development Tooling運用Policy — #353

```text
DevelopmentToolingOperationalPolicy
- policy_id
- policy_revision
- max_source_refs_per_artifact: int >= 1
- max_findings_per_artifact: int >= 1
- max_artifact_json_bytes: int >= 1
- max_input_file_bytes: int >= 1
- max_concurrent_analyses: int >= 1
- analysis_timeout_seconds: finite float > 0
```

初期V2値:

```text
policy_id = v2.development-tooling.default
policy_revision = 1
max_source_refs_per_artifact = 1000
max_findings_per_artifact = 2000
max_artifact_json_bytes = 16777216
max_input_file_bytes = 536870912
max_concurrent_analyses = 4
analysis_timeout_seconds = 300.0
```

Rules:

- input file上限超過は解析拒否。先頭だけ解析して全体結論として提示しない。
- finding/source上限超過時はcomplete auditを名乗らず`truncated/incomplete`ではなくtyped incomplete artifactとして扱う。
- timeoutで生成途中artifactをcanonical evidenceへ昇格しない。
- GitHub/Repository mutationは本Policyの解析上限とは別のexplicit mutation workflowを要求する。

## 7. Persistence運用Policy — #359

```text
PersistenceOperationalPolicy
- policy_id
- policy_revision
- snapshot_payload_max_bytes: int >= 1
- persistence_backlog_capacity: int >= 1
- max_in_flight_operations: int >= 1
- max_list_items: int >= 1
- transaction_timeout_seconds: finite float > 0
- retry_policy_ref
```

初期V2値:

```text
policy_id = v2.persistence.default
policy_revision = 1
snapshot_payload_max_bytes = 1048576
persistence_backlog_capacity = 256
max_in_flight_operations = 4
max_list_items = 100
transaction_timeout_seconds = 30.0
retry_policy_ref = v2 runtime dependency retry policy
```

Rules:

- snapshot payloadはcanonical serialized envelope全体でsizeを測る。
- 1MiB超過snapshotを分割して同一atomic snapshotと偽らない。ownerが明示chunk schemaを設計するまでreject。
- backlog overflow時、latest-state coalescing可能なsnapshotだけowner契約どおり置換できる。event/historyはsilent drop禁止。
- `list_compatible(..., limit)`のlimitは`1..max_list_items`。
- transaction timeout後、commit outcome不明ならreadback/reconciliationなしにretryして二重mutationを起こさない。
- retry/backoff/cancellation/shutdown graceは#350共通Policyを使う。

## 8. System Verification運用Policy — #360

System Integrationのhard SLOはProvider応答時間そのものではなく、**process-local scheduling / boundedness / non-starvation**を正本とする。Provider latencyは別metricsとして記録する。

```text
SystemVerificationOperationalPolicy
- policy_id
- policy_revision
- max_scenario_seconds: finite float > 0
- max_concurrent_scenarios: int >= 1
- foreground_eligible_to_start_bound_seconds: finite float > 0
- max_trace_events: int >= 1
- max_work_intervals: int >= 1
- max_revision_conflicts: int >= 1
- max_availability_transitions: int >= 1
```

初期決定論的統合試験値:

```text
policy_id = v2.system-verification.deterministic.v1
policy_revision = 1
max_scenario_seconds = 300.0
max_concurrent_scenarios = 2
foreground_eligible_to_start_bound_seconds = 0.250
max_trace_events = 50000
max_work_intervals = 10000
max_revision_conflicts = 10000
max_availability_transitions = 10000
```

### 8.1 Foreground non-starvation判定

`eligible_at`は#333/#322の必要preconditionが満たされ、foreground workがscheduler admission可能になったmonotonic instant。

`started_at`はhandler/workerが実際に開始したmonotonic instant。

```text
scheduler_delay = started_at - eligible_at
PASS if scheduler_delay <= foreground_eligible_to_start_bound_seconds
```

- Provider network/LLM execution timeをscheduler_delayへ含めない。
- deliberate delay injectionでそのforeground自身を遅延対象にした場合はSLO適用外とし、対象外理由をtraceへ明示する。
- background負荷、Streaming burst、Reflection、prepared speechが存在しても、直接ユーザーforegroundのeligible→startをこのbound内に保つ。

### 8.2 Scenario timeout

`max_scenario_seconds`は検証Harness全体の上限であり、production runtimeの通常timeoutではない。

- timeout時に途中結果をPASSへしない。
- pending task / resource ownerを回収しterminal evidenceを残す。
- Human Verification待ち時間はこのmachine scenario timeoutへ含めない。

### 8.3 Trace bound

trace各配列が上限へ達し必要証拠を完全記録できない場合、古いeventを捨ててPASSさせず`EVIDENCE_LIMIT_EXCEEDED`でmachine gate FAIL。

## 9. Live environment SLO profile

実LLM/TTS/Streaming/Game/GUI等のlive Verificationでは、環境差のあるProvider latency値を本書の初期決定論的値から推測しない。

各live runは開始前に版管理された`LiveVerificationSLOProfile`を必須とする。

```text
LiveVerificationSLOProfile
- profile_id
- profile_revision
- environment_class
- metric_bounds[]
- excluded_external_waits[]
- rationale
```

metric boundが未定義の指標を「速そうだからPASS」にしない。初回Human Verificationで計測のみを行う指標は`MEASURE_ONLY`と明示し、PASS条件と混同しない。

## 10. Policy freshness / generation

- GUI client session、Lab run、Tooling analysis、Persistence worker、Plugin integration generation、System Verification runは開始時Policy identity/revisionをbindする。
- Policy revision変更中のin-flight operationをnew revisionへ付け替えない。
- new operation/runからcurrent Policyを使う。GUI/Adminでは第4節に従い、新インスタンス・新世代から新方針を使用する。
- old generation resultはowner-specific freshness gateへ従う。

## 11. D10 required tests

### Plugin
- per-plugin/per-capability effective concurrency
- event projection overflow no silent loss
- lifecycle timeout ambiguity

### GUI
- read/command byte boundary
- slow client coalescing
- history non-loss
- timeout後readback

### Lab
- repeat/injection/timeline/export/concurrent run上限
- evidence overflowでPASS禁止

### Tooling
- input size/artifact/finding/source limit
- timeout partial artifactをcomplete扱いしない

### Persistence
- 1MiB snapshot境界
- backlog/coalescing/history non-loss
- list limit
- ambiguous transaction timeout reconciliation

### System
- foreground scheduler 250ms bound under background load
- scenario timeout
- trace bound overflow fail
- provider latencyとscheduler delayの分離
- live profile missing時にsubjective latency PASSを捏造しない

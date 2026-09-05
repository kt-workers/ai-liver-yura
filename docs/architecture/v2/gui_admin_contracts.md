# V2 GUI / Administration Contracts

Owner Issue: #351
Parent: #345
Upstream: #334 / #341 / #344
Related: #350 / #352 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#351は、Core / Body / Plugin / Subsystemの状態・設定・診断を、**typed Read Modelと明示されたAdmin Command APIだけ**を通して可視化・操作するGUI/Admin Subsystemを定義する。

```text
Core / Subsystem owners
→ typed Read Model publication
→ GUI/Admin

GUI/Admin
→ typed Admin Command
→ owning command boundary
→ owner validation / mutation
→ new Read Model
```

GUIはDomain Authorityではない。

---

## 2. Authority boundary

GUI may:
- display current read models
- request allowed configuration changes
- request lifecycle/admin operations
- display sanitized diagnostics/health
- export safe diagnostic/validation data where explicitly supported

GUI may not:
- directly mutate Internal State
- directly set Emotion/Desire/Drive
- decide Executive Goal/Action
- directly mutate Goal/Commitment
- directly set Attention/Focus
- directly create Activity execution fact
- directly write BodyState/joint pose
- alter Character Definition by editing Runtime Profile
- infer provider success from button press

Button click is a request, not a successful state transition.

---

## 3. Read Model boundary

Every screen reads purpose-specific immutable DTOs, not live Domain object references.

Common envelope:

```text
AdminReadModelEnvelope
- model_kind
- schema_version
- source_owner
- source_revision
- generated_at
- payload
- availability
- degraded_reasons[]
```

Rules:
- payload is bounded for screen purpose.
- no writable alias to owner state.
- source revision visible for stale detection.
- raw provider SDK objects excluded.
- secrets excluded.
- prompts/raw private payload included only if a dedicated safe debugging contract explicitly permits it; default is exclude.

---

## 4. Read Model categories

Initial categories may include:

```text
SYSTEM_HEALTH
RUNTIME_LIFECYCLE
INTERNAL_STATE_SUMMARY
GOAL_COMMITMENT_SUMMARY
ATTENTION_FOCUS_SUMMARY
ACTIVITY_SUMMARY
SPEECH_RUNTIME_SUMMARY
BODY_SUMMARY
PLUGIN_CAPABILITY_SUMMARY
SUBSYSTEM_HEALTH_SUMMARY
PROVIDER_DIAGNOSTIC_SUMMARY
CONFIGURATION_SUMMARY
```

The Read Model schema must reflect owner semantics; GUI must not flatten all state into arbitrary generic key/value JSON and then infer meaning client-side.

---

## 5. Admin command boundary

GUI writes only through typed commands.

```text
AdminCommandRequest
- command_id
- command_kind
- target_owner
- target_ref?
- expected_revision?
- payload
- requested_at
- actor_context
```

```text
AdminCommandResult
- command_id
- status
- owner_revision_before?
- owner_revision_after?
- applied_at?
- failure_code?
- sanitized_message?
```

The concrete command schemas are owned by the target module, not by the GUI.

GUI may not invent a generic `set_state(path, value)` API across Core.

---

### 5.1 運用方針の必須注入と世代

`GuiAdminReadModelBroker`、`GuiAdminCommandDispatcher`等の本番GUI/Admin構成要素は、`GuiAdminOperationalPolicy`を必須の依存として受け取る。構成を組み立てる処理またはサブシステムの接続処理が、現在の運用方針を不変のスナップショットとして明示的に渡す。

`policy=None`から`GuiAdminOperationalPolicy()`を生成するような暗黙の代替は禁止する。コンストラクタは方針の省略を通常経路として許容せず、試験用補助処理でも「引数省略時の本番既定値」を仕様化しない。方針が欠落・不正な場合は、そのGUI/Admin提供面の構成を失敗させるか、型付きの利用不能状態へ閉じる。構成要素内部で正本の数値を暗黙に補完しない。

数値の正本は`external_surface_operational_numeric_contracts.md`の第4節とし、現在の版は`policy_id = v2.gui-admin.default`、`policy_revision = 2`とする。各インスタンスは構築時の識別子と版へ固定する。実行中のコマンドを将来の版へ付け替えず、新しいインスタンス・世代から新方針を使用する。購読、更新バッチ、結果の検証証拠にも同じ方針の識別子と版を一貫して記録する。これを理由に`AdminCommandResult`の結果分類を変更しない。

### 5.2 全所有者を合計した管理コマンド受付上限

汎用の`GuiAdminCommandDispatcher`は、担当する全所有者を合計した実行中コマンド数を`max_in_flight_commands`以下に保つ。現在値は16とする。ブラウザや所有者ごとに上限を掛け算して、この全体上限を回避してはならない。

受付順序は次のとおりとする。

1. 要求の基本形式とペイロードを検証する。
2. 同じ`command_id`が現在実行中なら、`DUPLICATE / COMMAND_ALREADY_IN_FLIGHT`を返す。
3. 全体の実行枠が満杯なら、`REJECTED / ADMIN_COMMAND_CONCURRENCY_LIMIT_REACHED`を返す。
4. 実行枠と識別子を確保し、対象所有者の解決、版の照合、実行へ進む。

重複確認・空き容量確認・枠の確保は、並行要求が同じ枠を重複取得できない受付単位とする。所有者の呼出し前から枠を数え、終了時には枠と実行中の識別子を必ず解放する。拒否された要求のために待機キューを隠れて作らない。

| 受付結果 | status | failure_code | 所有者の呼出し |
| --- | --- | --- | --- |
| 同一IDが現在実行中 | `DUPLICATE` | `COMMAND_ALREADY_IN_FLIGHT` | 0回 |
| 全体の同時実行上限に到達 | `REJECTED` | `ADMIN_COMMAND_CONCURRENCY_LIMIT_REACHED` | 0回 |

上限超過時の`applied_at`は`None`とする。安全に加工した型付き結果を返し、黙って要求を捨てたり、`APPLIED`を捏造したりしない。同一IDの実行中判定は、容量超過の判定より先に行う。各所有者が独自により厳しい同時実行制限を設けることは妨げない。

### 5.3 汎用層が保持するコマンド識別子

汎用配送処理が所有する識別子状態は、現在実行中の`command_id`だけとする。`_terminal_command_ids`、終了結果のキャッシュ、上限のない完了履歴を持たず、終了済み識別子・結果の長期的な正本にならない。

コマンド終了時に実行中集合から識別子を除去するため、汎用層の識別子保持数は`max_in_flight_commands`以下となる。所有者が利用不能だった要求も、識別子を永久に処理済みとして保持しない。

終了後に同一IDが再到着した場合、汎用層は過去の処理済み判定を行わない。現在の基本検証、受付上限、所有者の解決と版の照合を通過した要求を、改めて対象所有者へ渡す。所有者が返す`APPLIED / DUPLICATE / STALE_ADMIN_VIEW / REJECTED`等を型付きの事実として扱い、過去の成功事実を汎用GUI層で合成しない。

### 5.4 所有者側の重複適用防止と再試行

意味上の重複適用防止（idempotency）の判断責任は、実際の状態変更またはライフサイクル状態を所有する側にある。GUI/Admin配送処理は、変更の適用、再起動前の処理、時間切れ後の作用、所有者のトランザクション確定を判断する正本ではない。終了IDを永久保持して、一度だけの適用を保証する責任を代行してはならない。

所有者が重複適用を防ぐと保証して公開するコマンド種別では、所有者境界が`command_id`を利用し、同一IDかつ同じ正規のコマンド識別情報・ペイロードによる要求を再適用しない。同一IDで意味的に異なる要求は、所有者契約違反として拒否し、安全側に閉じる。

所有者が終了した識別子や結果を保持する必要がある場合、次は所有者固有の契約と版管理された方針で定義する。

- 保持期間と保持可能な識別子・結果の最大件数。
- 保持対象を削除する条件と順序。
- 永続化と再起動時の扱い。
- 要求の同一性を判定する情報（request fingerprint）。
- 再送時の結果返却と、現在の事実を再取得する方法。

これらを`GuiAdminOperationalPolicy`で一律に決めない。GUI/Adminは各所有者から状態変更の事実を確定する責任を奪わない。

重複適用防止を保証しないコマンドでは、GUIや通信処理が同一IDの再送だけから一度だけの適用を推測してはならない。再試行可否は所有者の結果と契約に従う。時間切れや接続断後に「未適用」を捏造せず、必要なら所有者が持つ正しい現在状態を再取得する。既存D10の時間切れ後の確認規則を維持する。

---

## 6. Allowed command classes

Examples of admin-level requests:
- runtime start/stop/reconnect where owner exposes it
- configuration update through versioned config owner
- validation trigger in Lab subsystem
- safe plugin enable/disable request through Plugin lifecycle boundary
- diagnostic refresh

Not allowed as generic GUI commands:
- `set_emotion(joy=1)`
- `set_goal(...)` bypassing Executive/#366
- `move_joint(...)` bypassing Body authority
- `mark_activity_completed` without execution evidence
- `set_stream_live=true`

Development-only simulators may inject fixtures through separate Validation/Test contracts, clearly not production Admin authority.

---

## 7. Optimistic concurrency / stale UI

State-changing Admin commands use owner revision where applicable.

```text
screen reads revision R
→ user requests change expected_revision=R
→ owner currently R+1
→ STALE_ADMIN_VIEW
→ GUI refreshes
```

Do not silently overwrite a newer canonical state from an old browser tab.

Idempotent lifecycle/admin commands should carry command identity for duplicate delivery handling.

---

## 8. Configuration ownership

Configuration UI edits configuration through typed/versioned schemas.

```text
ConfigReadModel
- config_owner
- schema_version
- config_revision
- editable_fields[]
- effective_values
- provenance
```

Rules:
- Character Bible content is not a generic Runtime config form unless the Character authoring workflow explicitly exposes it.
- provider credentials are never returned as current plaintext values.
- secret fields expose configured/not-configured status and replacement action only.
- changes requiring restart/reload report that requirement explicitly.
- invalid field/value fails before owner mutation.

---

## 9. Secret handling

Browser never receives:
- OpenAI API key
- YouTube OAuth token
- GitHub token
- DB password
- Authorization headers
- raw credential files

Secret write flow:

```text
browser secret replacement input
→ TLS/authenticated Admin endpoint
→ secret backend/composition storage
→ sanitized result
```

The secret value is not echoed into Read Model, logs, Export or client state longer than needed.

---

## 10. Authentication / authorization

Production Admin surfaces require explicit access policy.

Initial contract distinguishes:
- public/read-only visualization if intentionally exposed
- operator read access
- operator mutation access
- development/validation-only access

Mutation endpoints are never enabled merely because a UI element exists.

Render/local deployments may use Basic Auth or future auth adapter, but authentication mechanism stays outside Core Domain.

---

## 11. Subscription / realtime updates

GUI can subscribe to Read Model updates via WebSocket/SSE/polling adapters.

Requirements:
- slow/disconnected client does not block owner publication.
- per-client bounded queue/latest-state coalescing for state snapshots.
- event history that must not be lost uses separate bounded history/query contract.
- reconnect fetches latest authoritative snapshot; client cache is not authority.
- schema version mismatch is explicit.

---

## 12. Diagnostics boundary

Safe diagnostics may expose:
- IDs/revisions/status
- timestamps/latencies
- closed failure categories
- provider safe request IDs where allowed
- queue depth/counts
- degradation states

Default exclude:
- raw prompts
- API credentials
- raw provider response bodies
- unbounded conversation text
- unnecessary Memory content
- arbitrary stack traces containing sensitive paths/data

Detailed development diagnostics belong to explicit development tooling contracts, not every production GUI.

---

## 13. GUI screen inventory lifecycle

Existing `gui/*` screens are classified:

```text
PRODUCTION_ADMIN
PRODUCTION_VISUALIZER
VALIDATION_LAB
DEVELOPMENT_TOOL
DEPRECATED
```

Each screen must declare:
- owner Issue
- purpose
- input Read Models
- allowed commands
- deployment mode
- auth requirement
- V2 replacement/supersession if any

Do not update every old screen merely to preserve it. Screens without V2 purpose may be deprecated.

---

## 14. Render / local deployment

UI deployment is a Subsystem concern.

- Core does not know Render URLs/ports.
- environment-specific server configuration stays outside Domain.
- frontend does not embed server credentials/tokens.
- health endpoint may be intentionally unauthenticated only if it reveals no sensitive state.
- admin/data endpoints follow access policy.

---

## 15. Failure / degradation

GUI unavailable:
- Core and other Subsystems continue.

Core/subsystem read model unavailable:
- screen shows typed unavailable/degraded state.
- do not substitute stale cached value without age/provenance indicator.

Command failure:
- display owner failure result.
- button state does not pretend command applied.

---

## 16. Observability

GUI/Admin metrics:
- active connections
- read model publication lag
- dropped/coalesced client updates
- command request/result latency
- stale command rejects
- auth failures (rate-limited/sanitized)
- schema mismatch

Do not log secret payload or full sensitive command body.

---

## 17. Required tests

- immutable Read Model projection
- GUI cannot mutate owner object by alias
- typed command owner validation
- stale revision rejection
- duplicate idempotent command handling
- secret not returned/logged/exported
- disconnected/slow client nonblocking
- reconnect latest snapshot
- schema mismatch handling
- unavailable Core/subsystem screen degradation
- no generic `set_state` authority bypass
- screen classification inventory completeness
- GUI absent Core normal operation

Browser usability/visual correctness remains Human Verification after contract tests.

---

### 17.1 運用方針第2版と管理コマンドの必須試験

後続のコード修正では、既存試験に加えて次を検証する。

1. `GuiAdminReadModelBroker`は方針引数を省略できない。
2. `GuiAdminCommandDispatcher`は方針引数を省略できない。
3. 第2版の識別子・版・全数値が数値正本の現在値と完全一致する。
4. `max_in_flight_commands = 16`である。
5. 16件実行中の17件目は`REJECTED / ADMIN_COMMAND_CONCURRENCY_LIMIT_REACHED`、所有者呼出し0回、`applied_at = None`となり、隠れた待機キューを作らない。
6. 実行中の同一IDは`DUPLICATE / COMMAND_ALREADY_IN_FLIGHT`となり、所有者の2回目の呼出しは0回となる。容量上限到達時もこの重複判定が優先する。
7. 終了後に汎用配送処理がIDを永久保持せず、識別子保持数が同時実行上限以下となる。
8. 重複を判定する模擬所有者へ同一IDを再委譲できる。所有者が`DUPLICATE`を返し、状態変更を再適用しない。
9. 所有者が利用不能だった要求のIDを、汎用配送処理が永久に終了済みとして扱わない。
10. 時間切れ後に未適用を捏造せず、既存の所有者状態の再取得契約を維持する。
11. 実行枠解放後は新しいコマンドを受け付けられる。
12. 方針の識別子と版が購読・更新バッチ・結果の検証証拠で一致し、実行途中で別の版へ付け替わらない。

---

## 18. #445 Gate

GUI/Admin production implementation remains frozen until #445 D1-D9 and final user confirmation PASS.

---

## 19. Stage A：ローカル読取専用の本番GUI

### 19.1 目的と技術選択

#351の最初の段階を`Stage A — Local Read-only Production GUI`とする。実際の本番用通信処理を1本成立させ、不変の型付き表示モデルをブラウザへ表示する。秘密・私的状態・状態変更権限は公開しない。GUIの失敗でCoreを停止させず、後続の所有者結合の足場を作る。この段階の完了を#351全体の完了としない。

Stage Aはブラウザ画面とし、サーバは**aiohttpによるHTTP/JSONスナップショット通信**、画面は**素のHTML / CSS / JavaScript**を採用する。現在の本番実行基盤であるasyncioに接続し、同じ実行基盤内でサーバの起動停止を所有するための選択である。別のASGIサーバプロセスを要求しない。将来の通信拡張の可能性は、Stage Aでその機能を実装する許可を意味しない。

- Stage AではWebSocket、SSE、長期購読通信、自動ポーリングを使用しない。
- 初回表示とユーザーの明示的な「再取得」操作だけで、同一オリジンのAPIをGETする。
- 外部CDNを使用しない。Node/npm/Vite/Vue/React等のビルド工程を導入しない。
- **PyQt / QtのデスクトップGUIはStage A以降の本番GUI構成から除外する。** 代替候補として残さず、互換層やデスクトップへの代替経路を作らない。

現在の`Pipfile`にある`pyqt6`は、本方針の本番GUIでは使用しない。今回の設計改訂では`Pipfile`と`Pipfile.lock`を変更しない。ChatGPTの設計レビューPASS後のコード実装工程で、未使用の本番依存としてPyQt6を削除し、aiohttpを本番依存へ追加し、`Pipfile.lock`を正規の依存解決手順で更新する。互換用の補助コードやダミーimportを追加しない。`pyinstaller`等の別依存は、この決定だけで削除せず、個別に未使用かを確認して判断する。

### 19.2 必須の表示対象と情報源

Stage Aで必須の種類は`CONFIGURATION_SUMMARY`の1種類だけとする。情報源は、実際の本番構成へ読み込まれ、#360の構成処理から注入された**同一の不変な`MinimumBrainProductionConfig`インスタンス**である。

GUIはYAMLのパス探索・再読込、環境からの再構築、Brain内部の探索を行わない。別プロセスで読み直した値を、現在稼働中の設定と表示してはならない。

ブラウザへ出せる最小Brain設定情報は次の4項目だけとする。

```text
schema_id
config_id
config_revision
brain_module_registrations
```

`character_definition_path`、資格情報、`OPENAI_API_KEY`、提供サービス固有設定、生の指示文、再試行処理の内部設定、ファイルシステムのパス、私的文脈、ドメインの生オブジェクトを含めない。項目追加は別途、安全な投影のレビューを必要とする。

### 19.3 設定の純粋な投影

#351が所有する`MinimumBrainConfigurationReadModelProjector`は、注入された設定から`GuiAdminConfigurationReadModel`と必要な`AdminReadModelEnvelope`を構築する純粋な投影アダプタとする。

```text
GuiAdminConfigurationReadModel
  config_owner = yura.minimum-brain.production
  schema_version = 1
  config_revision = 注入された設定のconfig_revision
  editable_fields = ()
  secret_fields = ()
  effective_values = 上記4項目だけ
  provenance = 設定のconfig_idとconfig_revisionだけ

AdminReadModelEnvelope
  model_kind = CONFIGURATION_SUMMARY
  schema_version = 1
  source_owner = yura.minimum-brain.production
  source_revision = 注入された設定のconfig_revision
  availability = AVAILABLE
  degraded_reasons = ()
```

登録モジュールは既存の識別値として投影し、内部の実装参照を出さない。ラッパーに含む構造識別子・版・生成時刻・利用状態も型付きのメタデータに限定し、追加の秘密情報を由来情報へ混入させない。設定変更要求を生成しない。

`generated_at`には構成処理から注入された`SystemRuntimeClock`相当の安全な時計を使用する。同じ不変設定世代について作成済みの表示モデルと生成時刻を再利用し、GETのたびに同一`source_revision`の内容を変えて公開しない。偽の状態版を生成しない。`AVAILABLE`はこの設定投影を利用できる意味であり、全体Coreや全モジュールの稼働正常を表さない。

### 19.4 HTTP経路と画面

公開経路は次だけとする。HEADを許可する場合は、GETと同じ公開境界を適用する。

```text
GET /
GET /assets/app.js
GET /assets/app.css
GET /api/v1/configuration/minimum-brain
GET /healthz
```

既知経路の未対応メソッドは405、不明経路は404とする。POST / PUT / PATCH / DELETE、汎用コマンド、汎用状態変更、任意所有者の問合せ経路を設けない。Stage A APIは要求本文を受理しない。

`/healthz`はGUI通信処理自身の生存確認だけであり、Core全体の正常性を宣言しない。既存`GuiAdminCommandDispatcher`は保持するが、このHTTP通信処理から到達不能にする。状態変更APIは0経路とする。

画面は「ゆら GUI/Admin」「最小Brainの設定」と、構造識別子、設定ID、版、登録済みBrainモジュール、「再取得」操作で構成する。状態変更ボタンと秘密入力欄を設けない。

### 19.5 公開範囲とアクセス分類

公開方式は`LOCAL_READ_ONLY`とし、設定値は`deployment_mode = local_read_only`とする。待受ホストは**`127.0.0.1`だけ**を許可する。`0.0.0.0`、公開IP、LAN IP、Renderの公開インターフェースを含む、それ以外のホストで起動しない。Stage Aを遠隔・公開配置へ使用しない。

使用できるアクセス分類は`PUBLIC_VISUALIZATION`だけであり、設定値は`public_visualization`とする。表示内容そのものを未認証でも公開可能な部分集合に限定するための区分である。要求の`actor_context`、ヘッダー、クエリ、Cookieから`OPERATOR_READ`、`OPERATOR_MUTATION`、`DEVELOPMENT_VALIDATION`を生成しない。

ループバック制限は本人認証ではない。Stage Aでは特権APIを公開しないため認証アダプタを実装しない。Basic Auth、Bearer token、セッション/Cookie認証、遠隔リバースプロキシ認証はいずれも未採用とする。

管理者向け読取・変更を追加する前に別の設計改訂を必須とする。その際に本人性の証明、資格情報の供給・更新・失効、TLS境界、信頼済みアクセス区分への変換、CSRFと再送の意味を正本化する。

### 19.6 通信方針と配置設定

HTTP固有の上限は、既存の`GuiAdminOperationalPolicy`と分離した`GuiAdminHttpTransportPolicy`へ置く。数値・検証規則は`external_surface_operational_numeric_contracts.md`第4.1節を正本とする。両方の方針を必須注入し、欠落や不正を暗黙の既定値で補わない。

#351の構成・設定層は、次の版管理された静的設定を所有する。環境固有の待受設定をDomain DTOへ入れない。

```text
将来のファイル: resources/config/v2/gui_admin.yaml
schema_id = yura.gui-admin.production-config.v1
config_id = yura.gui-admin.production
config_revision = 1

deployment_mode = local_read_only
bind_host = 127.0.0.1
port = 8765
access_level = public_visualization

gui_operational_policy = 第4節のGuiAdminOperationalPolicy第2版
gui_http_transport_policy = 第4.1節のGuiAdminHttpTransportPolicy第1版
```

秘密項目は0件とする。この設計工程では設定ファイル実体を作らない。不正なホスト・特権アクセス分類・方針が入っている場合はGUIの構成を安全側へ失敗させるが、Coreの起動は継続可能とする。

### 19.7 GUI自身の起動停止と失敗

#351の`GuiAdminSubsystem`は少なくとも`start()`、`stop()`、型付きの`availability`を所有する。

起動は設定・方針の検証、安全な投影の構築、ローカルHTTP待受開始の順とし、成功後に`AVAILABLE`を公開する。構成・待受に失敗した場合は待受を稼働状態に残さず、途中で確保した資源を閉じて型付き`UNAVAILABLE`とする。GUI起動失敗をCore失敗へ変換しない。

停止は新規HTTP受付停止、有界な実行中要求の収束または取消、待受と接続のclose、所有タスクの回収の順とする。停止後のGUI所有未完了タスクは0件、繰り返し停止は安全とし、停止上限は2.0秒とする。上限超過や回収失敗を正常停止として報告しない。HTTP失敗からドメイン上の事実を生成しない。

Stage Aで用いる安全な失敗コードは次を基本とする。

```text
GUI_CONFIG_INVALID
GUI_UNSAFE_BIND_CONFIGURATION
GUI_BIND_FAILED
GUI_REQUEST_LIMIT_REACHED
GUI_REQUEST_TIMED_OUT
GUI_INTERNAL_TRANSPORT_FAILURE
```

例外の生文字列、パス、ソケット詳細、資格情報をブラウザへ返さない。提供サービス診断の分類を新設しない。`PROVIDER_DIAGNOSTIC_SUMMARY`はStage Aへ載せず、後続で#437の安全な診断DTOを再利用する。

### 19.8 #351と#360の構成責務

| 所有者 | 責務 |
| --- | --- |
| #351 | 投影アダプタ、表示モデル契約、HTTP通信アダプタ、静的画面、GUI設定schema/loader、GUI自身の起動停止、安全な型付き利用状態 |
| #360 | 本番構成の起動点への登録、稼働中の同一設定インスタンスと時計の注入、GUIを任意で配置する判断、SystemCompositionSnapshotのsubsystem binding、起動・縮退の伝播、全体停止順の検証 |

#351は`app/bootstrap.py`の構成権限を持たず、Stage Aのコード工程で同ファイルを変更しない。本番へのGUI接続は既存#360のS7で行う。GUI独自のCoordinatorや、既存の起動点を置き換える別系統の起動処理を作らない。

#360へ引き渡す全体停止順は次のとおりとする。

1. GUIの外部要求の新規受付を停止する。
2. 実行中GUI要求を上限内で収束または取り消す。
3. GUIの待受・接続・タスクを閉じる。
4. Brain/Coreの作業を停止する。
5. RuntimeLifecycleと資源を閉じる。

GUI停止に失敗しても、Brain/CoreとLifecycleの停止・資源解放を必ず試みる。この順序の実際の制御と検証は#360が所有する。

### 19.9 後続の表示と所有者契約

`SYSTEM_HEALTH`、`RUNTIME_LIFECYCLE`、`INTERNAL_STATE_SUMMARY`、`GOAL_COMMITMENT_SUMMARY`、`ATTENTION_FOCUS_SUMMARY`、`ACTIVITY_SUMMARY`、`SPEECH_RUNTIME_SUMMARY`、`BODY_SUMMARY`、`PLUGIN_CAPABILITY_SUMMARY`、`SUBSYSTEM_HEALTH_SUMMARY`、`PROVIDER_DIAGNOSTIC_SUMMARY`はStage A必須ではない。不要と決定したのではなく、所有者の公開面・版・利用状態・構成接続が整ったものをStage B以降へ追加する。

管理操作を公開しないため、次の既存の契約不足はStage Aを妨げない。GUIで所有者の意味や内部状態を補作せず、必要な段階で担当を確認する。

| 後続契約 | 所有者 |
| --- | --- |
| System/Runtimeの公開更新世代 | #322 / #334 / #350 / #360 |
| 全体状態の集約 | #360 |
| Runtimeの管理操作 | #350と#360の構成処理 |
| Plugin管理操作 | #343 / #344 |
| 検証開始 | #352 |
| 提供サービス診断の集約 | #437 / #356 / #360 |
| 設定変更 | 各設定所有者 |

Stage Aのための新たな所有者コード変更は不要とする。別所有者の作業が必要になった時点で、open/closedの既存Issueを重複検索してから分離する。今回は所有者Issueを作らない。通信設計は#351を継続し、本番統合は#360が所有するため重複Issueを作成しない。

### 19.10 後続コード工程の機械検証

- 投影は注入された同一設定・版に基づき、許可された4項目だけを含む。不変性、パス・秘密・提供サービス設定の非公開、ファイル再読込なしを確認する。
- GETで画面と安全な型付き設定を取得でき、初回と明示再取得だけが通信する。`/healthz`はCoreの正常性を宣言しない。
- POST/PUT/PATCH/DELETEを拒否し、不明経路は404、管理コマンド経路は存在しない。
- `127.0.0.1`と`PUBLIC_VISUALIZATION`だけを受理し、それ以外の待受・権限を拒否する。要求由来の権限昇格がない。
- 16件の同時要求を受け付け、17件目は503で有界に失敗する。隠れた待機キューなし、時間切れ上限、終了後の枠解放、要求本文拒否、要求行・ヘッダー上限を確認する。
- 停止後の新規受付なし、GUI所有未完了タスク0、繰り返し停止、2秒の停止上限を確認する。
- JSONと失敗応答に秘密・生例外・パスを含めない。外部CDNなし、同一オリジン通信、適切なCSP・no-store・nosniffを確認する。
- 待受ポートの確保失敗でGUIは型付き`UNAVAILABLE`となる。Coreに依存しない試験で、GUI失敗が注入元の状態を変更しないことを確認する。
- PyQtの互換層・ダミーimport・デスクトップ代替経路を作らず、承認済みの依存変更を正規のlock更新とCIで確認する。

### 19.11 人間による確認の境界

#351のローカルブラウザ確認では、実際のGUI通信処理を通した表示、ラベルの読みやすさ、明示再取得、許可項目、操作ボタンの不在、ローカル限定動作、配置・操作性を検証する。確認用構成である場合は明示し、別途読み込んだ設定を稼働中Coreの設定だと表示しない。

この確認は、稼働中Coreとの本番接続、SystemCompositionSnapshotの由来情報、Runtime healthの事実、所有者の管理操作、遠隔認証、#360 S7の成功を証明しない。それらは後続のシステム結合検証が所有する。静的な模擬画面だけを本番通信の確認証拠へ昇格させない。

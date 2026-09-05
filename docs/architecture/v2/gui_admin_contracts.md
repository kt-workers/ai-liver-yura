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

# V2 Persistence / Repository Contracts

Owner Issue: #359
Parent: #356
Upstream owners: #332, #350, #366 and any future owner with an explicit restart-safe snapshot contract
Related:
- `docs/architecture/v2/memory_store_retrieval_contracts.md`
- `docs/architecture/v2/goal_commitment_state_contracts.md`
- `docs/architecture/v2/runtime_lifecycle_contracts.md`
- `docs/architecture/v2/concurrency_architecture.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#359は、Memory canonical recordsと、**owner側でrestart-safeと明示された最小Snapshot**を、PostgreSQL等の具体Storageから分離して保存・取得・復元候補化するInfrastructure responsibilityである。

```text
Domain owner
  ├─ #332 Memory Repository Port
  └─ restart-safe Snapshot Port
            ↓
#359 Persistence Adapter
            ↓
PostgreSQL / future storage
            ↓
raw durable data
            ↓
#359 decode/version/integrity gate
            ↓
rehydration candidate
            ↓
owning Domain validates/applies
```

Persistenceは保存したpayloadの意味Authorityを持たない。

---

## 2. Authority boundary

### #359 owns

- storage connection / pool / transaction
- schema/table/index representation
- serialization format implementation
- optimistic expected-revision persistence
- durable transaction boundary
- storage schema migration/version compatibility
- integrity checksum/digest validation
- provider failure normalization
- restart-safe snapshot storage/retrieval mechanism
- persistence availability/degradation diagnostics
- background persistence worker/retry mechanics where used

### #359 does not own

- Memory semantic identity/reconciliation/ranking (#332)
- Reflection candidate generation (#364)
- Goal/Commitment lifecycle semantics (#366)
- current Internal State semantics (#327)
- Attention/Focus semantics (#333)
- Activity execution truth (#329)
- Runtime shutdown decision (#350)
- which arbitrary Domain object is safe to restore

DB schema is not Domain Authority.

---

## 3. Two persistence surfaces

#359 exposes two conceptually separate persistence surfaces.

### 3.1 MemoryRepositoryPort implementation

Implements the #332 canonical repository contract:
- Memory record create/read/update with expected revision
- relation persistence
- bounded filtering/listing required by #332
- lifecycle/history preservation
- transactionality required by #332 dispositions

The persisted data must preserve the complete #332 canonical semantics; DB shortcuts must not collapse:
- ACTIVE vs SUPERSEDED vs ARCHIVED
- provenance history
- contradiction/support/refine/supersede relations
- temporal/confidence metadata

### 3.2 LifecycleSnapshotRepositoryPort

Generic mechanism for owner-authored restart-safe snapshots.

```text
LifecycleSnapshotRepositoryPort
- put_snapshot(envelope, expected_revision?)
- get_latest(owner_id, snapshot_kind)
- list_compatible(owner_id, snapshot_kind, limit)
- mark_rejected_or_obsolete(snapshot_ref, reason)?
```

It stores owner payloads but never applies them directly to Domain state.

---

## 4. PersistenceSnapshotEnvelope

```text
PersistenceSnapshotEnvelope
- snapshot_id
- owner_id
- snapshot_kind
- snapshot_schema_id
- snapshot_schema_version
- owner_state_revision
- runtime_epoch
- captured_at
- payload
- payload_digest
- source_refs[]
```

Requirements:
- immutable DTO
- timezone-aware timestamps
- strict integer revisions; bool-as-int rejected
- payload is bounded JSON-compatible structured data or another explicitly versioned safe encoding
- arbitrary Python pickle/object serialization is not a canonical interchange format
- digest covers canonical serialized payload + relevant identity metadata

---

## 5. Restart-safe ownership rule

**No module is restorable merely because it has data.**

A Domain owner must explicitly define:
- snapshot kind
- schema/version
- capture boundary
- rehydration DTO
- validation rules
- stale/obsolete handling
- whether restoration is canonical, historical-only, or forbidden

Without that owner-side contract, #359 may not invent restoration semantics.

### Initial known restart-safe consumer

#366 explicitly defines `GoalCommitmentSnapshot` rehydration boundary and is eligible for persistence via #359 after exact schema alignment.

#332 canonical Memory is durable through its repository surface rather than an opaque lifecycle snapshot.

### Not restart-safe by default

Unless a future owner-specific canonical explicitly says otherwise, do not restore as current runtime truth:
- current Emotion/Desire/Arousal snapshot
- current Attention/Focus/Turn ownership
- queued/prepared Speech candidates
- in-flight verifier/TTS requests
- current Body pose/velocity as canonical startup truth
- in-flight Activity execution state
- provider connection/session objects

Historical evidence may be remembered through #332, but that is not equivalent to current-state restoration.

---

## 6. RehydrationCandidate

Storage retrieval returns an infrastructure-validated candidate, not applied Domain state.

```text
RehydrationCandidate
- snapshot_ref
- owner_id
- snapshot_kind
- schema_id/version
- owner_state_revision
- runtime_epoch
- captured_at
- decoded_payload
- integrity_status
- storage_version
```

Flow:

```text
#359 integrity/version decode PASS
→ RehydrationCandidate
→ owning Domain parser/validator
→ owner either accepts into its explicit initial-state boundary or rejects
```

#359 must not call a generic `set_state(payload)` on Domain objects.

---

## 7. Runtime epoch

Each Core process start has a `runtime_epoch` identity.

Purpose:
- distinguish state produced in a prior process instance
- prevent accidental resumption of in-flight operational work as if still live
- support diagnostics / clean-shutdown markers

A new runtime epoch does not invalidate historical Memory.

Owner-specific rehydration decides whether cross-epoch data is valid.

---

## 8. Memory transaction semantics

The PostgreSQL adapter for #332 must provide atomicity matching the Domain operation.

Examples:
- create Memory record + initial provenance
- update expected record revision
- create relation with referenced-record existence validation at the repository boundary
- disposition that requires record lifecycle update + replacement record/relation set where #332 defines one atomic semantic operation

Use DB transaction/isolation or equivalent to ensure a failed partial write is not reported as successful canonical Memory persistence.

Expected-revision conflict returns typed `PERSISTENCE_CONFLICT`, never last-write-wins silently.

---

## 9. Goal/Commitment persistence sequencing

#366 current state mutation remains an in-memory Domain atomic operation with no DB I/O inside its lock.

After successful #366 commit:

```text
GoalCommitmentSnapshot
→ persistence work item outside Domain lock
→ #359 durable snapshot write
→ DurabilityReceipt
```

Persistence failure:
- does not retroactively mutate/rollback the valid current runtime Goal State
- marks durability degraded/pending
- is observable
- may be retried by bounded policy
- does not claim restart durability until receipt exists

This preserves runtime non-blocking while making durability truth explicit.

---

## 10. DurabilityReceipt

```text
DurabilityReceipt
- persistence_request_id
- owner_id
- owner_state_revision
- snapshot_or_record_ref
- status
- durable_at?
- storage_revision?
- failure_code?
```

Status:
- DURABLE
- PENDING_RETRY
- FAILED
- CANCELLED
- SUPERSEDED_BY_NEWER_SNAPSHOT

A current in-memory state can be valid while its restart durability is degraded. These facts must not be conflated.

---

## 11. Snapshot coalescing

For snapshot-style owners such as #366, persistence may coalesce obsolete pending snapshots.

Example:
- revision 10 pending
- revision 11 committed before 10 is written
- policy may persist only 11 if owner contract allows latest-state snapshots

Requirements:
- never reorder into an older durable revision after a newer one
- observable supersession
- no unbounded write backlog
- cancellation/shutdown semantics explicit

Event/history records that require every transition must use an event/journal contract instead; snapshot coalescing cannot silently delete required history.

coalescibleでないrequestは、同じowner/kindで先行writeが実行中でも個別queue entryとして保持し、各callerへterminal `DurabilityReceipt`を返す。latest-state coalescingは明示的に許可されたpending snapshotだけを置換でき、event/history requestを置換してはならない。

Storage adapterはexpected revision検査とdurable mutationを同一lock / transaction内で実行する。複数tableから構成されるMemory repository snapshotは、一つのread transactionでrecordsとrelationsを読み、異なるcommit世代を混在させない。

---

## 12. Storage schema versions

Distinguish:

```text
Domain schema/version
Storage schema/version
Snapshot payload schema/version
```

They are not one integer.

- Domain schema is owned by Domain canonical contracts.
- Storage schema is owned by #359 migration layer.
- Snapshot payload schema is owned by the snapshot producer/consumer contract.

Changing a DB index/column layout need not change Domain schema.

---

## 13. Migration policy

Migrations are explicit, ordered, versioned and testable.

Rules:
- no destructive automatic reset on version mismatch
- no dropping unknown newer data to “make startup work”
- migration runs before adapter declares fully available
- migration failure yields typed unavailable/degraded state
- backup/rollback operational procedure is provider responsibility where applicable
- downgrade support is not assumed unless explicitly designed

If DB storage schema is newer than this runtime understands:
- fail closed for incompatible durable operations
- Core may continue without persistence when policy allows
- do not reinterpret unknown fields

---

## 14. Payload migration / owner migration

#359 can migrate storage representation but must not invent semantic transformation of owner payload.

If `snapshot_schema_version` changes:
- owner supplies an explicit migration/decoder contract, or
- old snapshot is incompatible and owner starts from safe default/degraded state

For Memory, #332 Domain migration requirements must be explicit before #359 rewrites semantic content.

---

## 15. Startup sequence

Persistence is optional for Core boot unless a higher-level deployment policy says otherwise.

Initial lifecycle:

```text
start persistence adapter
→ connect
→ inspect storage schema
→ migrate if compatible/required
→ availability = AVAILABLE or DEGRADED/UNAVAILABLE
→ load canonical Memory/restart candidates as requested
→ owner validates rehydration
→ Core admits normal work independently of unavailable optional persistence
```

Do not block unrelated Core startup forever waiting for DB reconnect.

Retry follows #350 bounded backoff policy.

---

## 16. Clean shutdown

#350 owns shutdown sequencing.

At shutdown:
- stop accepting new persistence work after cutoff
- coalesce/persist latest eligible snapshot within bounded grace
- settle/abort transactions
- stop retries
- close pool/connection idempotently

Snapshot persistence is best effort under bounded shutdown time.

Failure does not prevent remaining resources from closing.

Do not leave retry/snapshot worker pending when event loop closes.

---

## 17. Crash consistency

A process can terminate without clean shutdown.

Therefore:
- durable records rely on committed transactions, not shutdown-only flush
- owner snapshots should be written during runtime at meaningful commit boundaries, not only at Ctrl+C
- startup uses only fully committed/integrity-valid entries
- half-written/corrupt entries are rejected and diagnosed

A clean-shutdown marker may aid diagnostics but is not proof that all semantic state is current.

---

## 18. Corruption / integrity

Validate:
- payload digest
- schema/version
- required identity fields
- revision monotonicity where applicable
- referenced records where transaction semantics require

Corrupt data handling:
- do not deserialize unsafely
- return typed `CORRUPT_RECORD` / `INTEGRITY_FAILED`
- isolate affected record/snapshot where possible
- do not rewrite it silently to guessed defaults

Owner decides whether degraded continuation is safe.

---

## 19. Failure model

Closed failure categories at minimum:
- UNAVAILABLE
- CONNECTION_FAILED
- TIMEOUT
- PERSISTENCE_CONFLICT
- CONSTRAINT_VIOLATION
- INCOMPATIBLE_STORAGE_VERSION
- INCOMPATIBLE_PAYLOAD_VERSION
- MIGRATION_FAILED
- CORRUPT_RECORD
- INTEGRITY_FAILED
- CANCELLED
- CLOSED

Provider-specific SQLSTATE/driver exceptions can be sanitized diagnostics but do not become Domain semantic errors.

---

## 20. Retry policy

Retry only transient operational failures.

- bounded exponential/backoff policy from lifecycle configuration
- cancellation/shutdown interrupts retry wait
- schema incompatibility, integrity failure and permanent constraint errors are not blind-retried
- repeated error diagnostics rate-limited

No unbounded hidden persistence queue.

---

## 21. Semantic index boundary

#332 `MemorySemanticIndexPort` is a derived index, not canonical Memory.

A vector/embedding persistence implementation may be supplied alongside PostgreSQL, but:
- vector provider/schema is Infrastructure
- index update failure after Memory commit does not erase canonical Memory
- index has repair/rebuild state
- index freshness/revision is observable
- search results are candidates/signals to #332 ranking/reconciliation, not duplicate Authority

---

## 22. Security / secret boundary

- credentials/DSN/password remain Infrastructure configuration
- never embed credentials in Domain DTO/snapshot
- no raw SQL/provider response in normal Domain diagnostics
- parameterized queries / safe driver binding required
- arbitrary pickled executable objects forbidden for persisted Domain snapshots
- migration tooling must not expose secrets to browser/client
- backup/diagnostic output respects retention/privacy policy

---

## 23. Concurrency / backpressure

- DB await occurs outside Domain mutation locks
- independent reads/writes can use bounded pool/concurrency
- persistence backlog is bounded
- snapshot latest-wins coalescing only where owner semantics permit
- foreground critical read may outrank background Reflection/index repair according to scheduler policy
- slow DB does not block Body realtime, current Speech playback, Input reception
- cancellation is request-scoped

---

## 24. Observability

Events/metrics:

```text
persistence_connect_started/succeeded/failed
storage_migration_started/succeeded/failed
memory_write_started/completed/conflict/failed
snapshot_queued/coalesced/written/failed
rehydration_loaded/accepted/rejected
index_update_started/completed/failed/rebuild_required
persistence_retry_scheduled/cancelled
persistence_closed
```

Measure:
- queue wait
- transaction latency
- pool saturation
- retry counts
- pending durability age
- latest durable owner revision vs current owner revision
- index lag

Do not log secrets/raw full Memory payload by default.

---

## 25. Required tests

### Memory repository
- create/read/update expected revision
- stale revision conflict
- relation persistence
- transaction rollback on partial failure
- lifecycle/provenance/contradiction metadata preserved

### Snapshot
- valid put/get
- digest mismatch
- incompatible payload schema
- owner rejects invalid rehydration
- cross-epoch handling
- newer snapshot cannot be overwritten by older snapshot
- allowed latest-state coalescing

### Goal durability
- #366 commit contains no DB await
- successful follow-up snapshot gives DurabilityReceipt
- DB failure leaves current runtime state valid but durability degraded
- restart rehydrates only via `GoalCommitmentSnapshot` owner validation

### Startup/migration
- DB unavailable Core degraded boot
- compatible migration
- migration failure
- newer incompatible storage
- corrupt record isolation

### Shutdown/crash
- bounded best-effort final snapshot
- retry stops on shutdown
- no pending DB worker after close
- committed runtime snapshot survives unclean process termination in integration fixture

### Boundary
- no current Emotion/Attention/Body/in-flight Speech restoration without owner contract
- DB schema does not become Memory/Goal semantic authority
- no provider credential/raw object leakage

### Index
- index failure after canonical Memory commit preserves Memory
- degraded exact/filter retrieval continues where safe
- index rebuild catches up without changing canonical content

---

## 26. Non-goals

- Memory importance/reconciliation/ranking
- Reflection LLM
- Goal lifecycle decisions
- automatic resurrection of in-flight work
- persistence of every Runtime object
- database-specific schema as Domain canonical
- unbounded event sourcing without an owner contract

---

## 27. Design Gate

#359 implementation starts only after:
- #332 Memory repository semantics canonicalized
- #366 rehydration snapshot exact schema mapped without semantic changes
- #350 lifecycle retry/shutdown semantics aligned
- any additional snapshot owner explicitly defines restart-safe contract before use
- #445 Design Completion Gate PASS

#359 detailed design completion alone does not lift the global Implementation Freeze.

## 28. PostgreSQL の本番実装への対応

本番の保存先は PostgreSQL とする。SQLite の既存実装は単体試験またはローカル検証用であり、本番 PostgreSQL の完成証拠を代替しない。PR #458 のレビュー comment 5419242845 の要件を維持する。

接続生成は構成側が所有し、認証情報は既存の秘密情報所有者から渡す。認証情報を状態保存内容・例外説明・ログへ含めない。Domain の記憶保存契約へ PostgreSQL やドライバーの型を持ち込まない。接続先や資格情報を検証基盤の入力文字列から自動解決しない。

`PostgresConnectionPolicy` で接続数・取得待ち件数・取得期限・接続期限・文実行期限・取引全体の期限・接続群の終了期限を明示する。共有接続群を借りる保存先と、その群を終了する構成側を区別する。同期の保存契約を呼ぶ処理はイベントループの外で実行し、実行中のDB処理を残したまま終了成功を報告しない。稼働中の所有者が状態を確定するロックへDB待機を持ち込まない。

記憶記録と関係は同じ読み取り取引で取得する。同一記録の更新は期待版と次版を検査し、複数接続から競合しても一方だけが成功する。関係には参照先存在のDB制約を設け、新しい記録・既存記録の版変更・関係追加の途中で失敗した場合は全変更を取り消す。保存先の構造版が未対応なら、自動削除・初期化による復旧を行わない。

保存待ち処理は受理済み要求を容量超過で消失させない。統合可能な待ち要求が存在しない場合も上限を適用する。新しい版の待ち要求を古い版で置き換えない。実行中の同期保存へ終了要求が届いた場合は、その処理結果を回収する。保存が確定した結果は DURABLE として実際の要求識別子へ返し、未開始の要求の取消と区別する。保存先自身の期限と合わせて終了を検証する。

検証は明示的に指定した隔離 PostgreSQL で行う。メモリ内実装や SQLite の成功を PostgreSQL の成功へ読み替えない。記憶保存に加えて、所有者が復元を許可した状態の保存、移行、失敗時の稼働継続、起動・停止の結合までが #359 の完了範囲である。


### 28.1 保存形式と所有者の対応

PostgreSQL の初期保存構造は `yura_v2` 名前空間に作成する。記憶と再起動用状態は個別の構造版を持ち、対応していない版の既存データを削除・初期化しない。状態本体と所有者ごとの最大保存版は同じ取引で更新する。不採用にした状態の最大版も保持し、後着した旧版で巻き戻さない。同じ所有者・種類・版の重複保存は競合として扱う。

記憶記録と関係には保存JSONの検査値を保持し、読取り時に検査値、記録の識別子・版、関係の参照先を照合する。状態の写しは既存の `PersistenceSnapshotEnvelope` が計算する検査値とDB上の識別情報を照合する。破損箇所を推測した既定値で修復しない。直接指定した別の正常な記録・所有者は引き続き読み取れる。一括読取りで破損を発見した場合は部分的な結果を完全な結果として返さず、型付き失敗を返す。

#366の初期対応は次に固定する。

- `owner_id`: `goals`
- `snapshot_kind`: `goal_commitment`
- `snapshot_schema_id`: `goals.commitment.snapshot.v1`
- `snapshot_schema_version`: `1`
- 内容: `GoalCommitmentSnapshot.to_dict()` の全フィールド。Goal・Commitmentの状態、条件、参照、由来、時刻、版を省略しない。
- 外側の所有者状態版と取得時刻: 内容の `revision` と `updated_at` に一致させる。

変換処理は既存の `GoalState`、`CommitmentState`、`GoalCommitmentSnapshot` の型検査と `GoalCommitmentStore` の初期化時の参照検査を利用する。未知の形式・他所有者・不正な参照を拒否し、汎用状態変更で適用しない。復元する構成側が、検査済みの型付き初期状態を `GoalCommitmentStore(initial)` へ渡す。保存処理自身は稼働中の所有者へ状態を適用しない。

### 28.2 非同期呼出しと起動停止

`PostgresPersistenceRuntime` は、構成側が渡す接続先、接続方針、記憶検索方針、保存待ち上限、再試行方針を受け取る。接続情報を設定ファイル・環境変数から独自に探索しない。`attach(lifecycle, retry_policy)` で既存の `RuntimeLifecycle` に再接続・終了処理を登録し、`start()` で移行を済ませて利用可能にする。DB接続不能はその依存機能だけの利用不可として記録し、他の依存機能を停止しない。

- 記憶の書込み・検索は、既存の `MemoryStoreAuthority` と PostgreSQL 保存先を専用の上限付き実行群で呼ぶ。
- `PersistenceOperationResult` は成功値と保存機構の失敗分類を分離する。正常な「復元候補なし」は値・失敗とも `None`、失敗時は成功値を含めない。
- 目標状態は、所有者の `apply()` が返った後に、その確定済みの写しを `persist_goals()` へ渡す。所有者のロック内でDBを待たない。返される保存結果を確認するまで再起動後の保持を保証しない。
- 取消後も実行中の同期DB処理を回収する。終了は新規受付停止、保存待ち処理の終了、実行中入出力の回収、接続群の終了、専用実行群の終了の順とする。終了処理自体を取り消されても資源回収を終えてから取消を返す。
- 一部記録の破損、状態版の競合、所有者の形式不一致をDB全体の障害へ昇格させない。

取引全体の期限は `PostgresConnectionPolicy.transaction_timeout_ms` で明示し、PostgreSQL 17以降の `transaction_timeout` に接続する。各SQL文の期限とは区別する。構成側の終了猶予は、受理済み処理の取得待ち・接続・取引・回収に必要な時間を考慮して設定する。期限超過後の接続取消失敗で、元の期限超過の分類を上書きしない。

根拠: [PostgreSQLの取引分離](https://www.postgresql.org/docs/17/transaction-iso.html)、[接続と取引の期限](https://www.postgresql.org/docs/17/runtime-config-client.html)、[psycopgの接続群](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)。

### 28.3 検証と未完範囲

`tests/infrastructure/postgresql/` は、明示された隔離ソケットまたは隔離CIの接続先へ接続し、試験ごとに固有名の空DBを作成・回収する。CIは `YURA_REQUIRE_POSTGRES=1` で実行し、接続先未指定やドライバー不足を試験失敗とする。任意のローカル実行で未指定時に省略された結果は、実DB試験の成功ではない。通常の単体試験だけでなく、実DBの取引取消、同時版競合、再接続、別プロセスの異常終了後の再読取り、破損、派生索引失敗、所有者型での復元、取消と終了、任意依存機能の障害分離を確認する。

現在の最小起動構成は入力意味解析だけを登録する段階であり、この接続口を本体の全活動経路へ配線済みとは扱わない。構成側の接続先・秘密情報・終了方針の供給と本体全活動経路への配線は、構成・結合側の工程で完了を確認する。製品依存は `Pipfile` と `Pipfile.lock` に psycopg 3.3.5（binary追加機能）と psycopg-pool 3.3.1 を記録する。CIは PostgreSQL 17.10 の隔離サービスを起動し、同じ依存の固定記録から全試験を実行する。CI成功、独立レビューと本流採用の結果は、対象HEADの証拠で別途確認する。


## 本体の目標所有者と永続化の接続

`CoreGoalPersistenceBinding`を本体の構成層へ置き、既存の`GoalCommitmentStore`と`PostgresPersistenceRuntime`を接続する。目標の採用・変更・完了判断を追加しない。DBの起動・再接続・停止は既存の永続化実行基盤と起動停止管理が所有し、この接続が二重に所有しない。

起動時は永続化から目標復元候補を取得し、`GoalCommitmentStore(initial)`の公開検査を通して目標所有者を生成する。復元不能は型付き失敗を保持し、保存なしと区別する。起動継続時に古い保存版を削除・上書きして解決したことにしない。再接続によって運転中の目標を保存状態へ差し戻さない。現在の注意・発話待ち行列・実行途中の活動は復元対象にしない。

確定判断を受けた変更は同期的に`GoalCommitmentStore.apply()`へ渡す。戻り値の確定状態を、所有者のロック外で`persist_goals()`へ投入する。DB完了待ちは目標変更の同期区間へ含めず、状態変更結果と保存確認を分けて呼出し元へ返す。保存が利用不可・受付上限到達・形式制約違反であっても、既に確定した目標変更を巻き戻したり、確定結果を失わせたりしない。型付きの保存失敗を対応する所有者版に結び付ける。

保存要求は実行世代と所有者版から一意に識別する。接続側は保存結果の無制限な一覧や追加の待ち行列を作らず、既存の保存待ち件数・版競合・結果回収契約を使う。変更前に非同期実行環境を検査し、受付手段がないまま目標だけを変更することを防ぐ。

この接続は、最小起動で未接続の認知・判断・目標・発話の全経路を完成とするものではない。本体の構成処理がこの入口へ目標変更を集約し、記憶の保存検索、停止時の回収、別プロセス再起動を併せて段階検証する。

### 復元失敗後の保存保護

復元失敗から暫定的な空の目標所有者で稼働を続けた場合、その実行世代では目標スナップショットの保存を禁止する。DBが再接続できても復元失敗の記録を消さず、所有者版が既存保存版を超えたことを保存許可へ使わない。現在の目標変更は既存所有者で確定できるが、保存要求は投入せず、その版の`FAILED`確認に復元失敗の分類を保持して返す。

保存を再開できるのは、新たな起動時に保存済み状態の取得と所有者による復元検査が成功し、その状態を起点とする接続を構成した場合である。運転中の暫定目標と保存済み目標の意味上の統合、または保存状態の置換は、この接続が自動判断しない。保存されていない暫定状態を耐久化済みと表示しない。将来の明示的な調停契約なしに禁止を解除する入口を設けない。

保存済み目標あり、復元時のDB待機失敗、暫定状態での稼働、DB再接続、既存保存版を超える版の保存要求、再起動という順序でも、旧保存目標が復元されることを実DBで検証する。

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

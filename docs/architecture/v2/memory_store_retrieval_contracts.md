# V2 Memory Store / Retrieval Contracts

Owner Issue: #332
Parent: #325
Related: #321, #326, #327, #328, #333, #364, #366
Status: Canonical Supplement / Design Gate

## 1. Purpose

本書は、AI Liver ゆら V2におけるMemoryの**正本Store・統合・矛盾管理・Retrieval**を定義する。

Memoryは「過去の会話をそのまま保存する箱」ではない。

```text
validated MemoryCandidate / trusted typed source
        ↓
Memory validation / routing / reconciliation
        ├─ reject
        ├─ store new
        ├─ merge provenance
        ├─ supersede / refine
        └─ link contradiction
        ↓
Canonical Memory Records
        ↓
Retrieval Query + bounded ranking
        ↓
MemoryEvidenceView
        ↓
Input Meaning / Appraisal / Executive / Reflection context
```

#332はMemory内容をopen-endedに発明するLLM Roleではない。

- #364 Reflection: 何を覚える価値があるかをMemoryCandidateとして提案できる
- #332 Memory Store: candidateを検証し、正本Memoryへどう反映するかを決める
- DB / vector index / embedding provider: #332 Portの外側

Memory canonical store/retrievalは非LLM Authorityとする。

---

## 2. Authority boundary

### #332 owns

- canonical Memory record identity / revision / lifecycle
- Memory kind / retention class
- provenance / source references
- freshness / temporal scope / confidence metadata
- duplicate-safe storage
- refinement / supersession lifecycle
- contradiction links
- bounded retrieval policy
- `MemoryEvidenceView`
- persistence/index degradation state

### #332 does not own

- raw natural-language meaning interpretation
- current Emotion / Desire / Drive / Motivation
- current Relationship state
- current Goal / Commitment
- current Execution Fact
- Character personality definition
- open-ended判断「これは人生で重要だから覚えるべき」
- final Goal / Action choice

### Adjacent authorities

- #326 Input Meaning owns open-ended external NL semantics.
- #327 owns current Appraisal / Internal State / Relationship current state.
- #328 owns conscious Goal / Action selection.
- #366 owns current Goal / Commitment canonical state.
- #329 owns Activity lifecycle / Actual Execution Fact.
- #364 may generate MemoryCandidate, but cannot write the canonical Memory Store directly.

Memory is historical/contextual evidence. It must never silently become a stronger current-fact authority than the module that owns the current state or fact.

---

## 3. Memory categories

Initial V2 categories are closed structural routing categories, not natural-language semantic labels.

```text
WORKING
EPISODIC
SEMANTIC
RELATIONSHIP
PREFERENCE
ACTIVITY_SKILL
```

### WORKING

Short-lived context retained for bounded continuity. It is not automatically durable long-term memory.

Examples of eligible content class:
- recent resolved reference context
- recent interaction state needed across a small number of turns
- temporary task context

### EPISODIC

A time-bounded event/experience record with explicit provenance.

### SEMANTIC

A relatively stable learned fact/belief candidate about the world or a subject, with confidence and temporal scope.

### RELATIONSHIP

Historical evidence relevant to interaction with a specific counterparty. This is not the current Relationship state itself.

### PREFERENCE

Historical/static preference evidence. This is distinct from current Interest/Curiosity.

### ACTIVITY_SKILL

Past activity/result/learning evidence. It is not an Activity lifecycle or Actual Execution Fact authority.

New categories require a schema/design change. Arbitrary natural-language tags must not silently become new authority categories.

---

## 4. Canonical data contracts

### 4.1 MemoryId / revision

Every canonical record has stable identity and monotonic revision.

```text
memory_id
revision
```

A stale expected revision must not overwrite a newer canonical record.

### 4.2 MemoryContent

Memory content is typed structured content, not an unbounded opaque prompt transcript.

Minimum shape:

```text
MemoryContent
- subject_ref?
- predicate / content_kind
- value
- temporal_scope?
- qualifiers[]
```

`value` may contain bounded JSON-compatible structured data, but the Store does not reinterpret arbitrary raw text as a new semantic fact.

Conversation text may be retained as source evidence when explicitly permitted, but raw conversation history is not the canonical semantic identity of every Memory record.

### 4.3 MemoryProvenance

Every non-working durable record must trace back to evidence.

```text
MemoryProvenance
- source_event_refs[]
- source_fact_refs[]
- source_memory_candidate_id?
- source_kind
- observed_at?
- recorded_at
```

Source references are immutable historical evidence references. A later source must not rewrite an earlier source out of history.

### 4.4 Temporal / confidence state

```text
MemoryTemporalState
- valid_from?
- valid_until?
- observed_at?
- freshness_state

MemoryConfidence
- confidence
- basis
```

Freshness and confidence affect retrieval/evidence use but do not alone convert a Memory into a current fact.

A low-confidence record may remain useful historical evidence if clearly labelled. A stale record is not necessarily deleted.

### 4.5 Memory lifecycle

Initial lifecycle:

```text
ACTIVE
SUPERSEDED
ARCHIVED
```

Contradiction is a relation between records, not a destructive lifecycle state by itself.

Deletion/physical purge is a persistence/data-retention concern and is not the ordinary semantic update mechanism.

---

## 5. MemoryCandidate input

#332 accepts only a typed `ValidatedMemoryCandidate` boundary.

Minimum shape:

```text
ValidatedMemoryCandidate
- candidate_id
- memory_kind
- content
- provenance
- confidence
- importance_hint?
- temporal_scope?
- suggested_related_memory_ids[]
- suggested_relation_hints[]
- source_context_revision?
- created_at
```

`importance_hint` and relation hints are **candidate evidence**, not final Store authority.

Candidate may originate from:
- #364 Reflection
- trusted typed user-provided fact path
- Activity/Execution Result projection
- explicit deterministic system event

A module must not bypass this boundary and directly mutate a MemoryRecord.

---

## 6. Write reconciliation

Canonical dispositions:

```text
STORE_NEW
NOOP_DUPLICATE
MERGE_PROVENANCE
SUPERSEDE
LINK_CONTRADICTION
REJECT
```

### STORE_NEW

Use when no canonical record is being replaced/merged and provenance is sufficient.

### NOOP_DUPLICATE

Exact canonical duplicate with no meaningful new provenance. Repeated identical input must not create unbounded duplicate rows.

### MERGE_PROVENANCE

Content identity is already canonical, but the new candidate adds independent supporting provenance. Preserve both old and new source references.

### SUPERSEDE

A newer/stronger record explicitly replaces the current applicability of an older record while preserving history.

Supersede is preferred over destructive overwrite.

Example:

```text
old: user prefers game A, valid_from T1
new: user says they no longer like game A, valid_from T2

→ preserve old historical record
→ create/update new record
→ old record becomes SUPERSEDED for current preference use
```

The Store must not infer this natural-language contradiction itself from surface words. It consumes typed candidate/relation evidence and applies deterministic lifecycle rules.

### LINK_CONTRADICTION

When two records conflict but the system lacks authority/evidence to choose a winner:

- preserve both
- add bidirectional contradiction relation
- expose contradiction in retrieval evidence
- do not silently average or choose the most recent solely because it is recent

### REJECT

Reject at minimum:
- missing/invalid provenance where provenance is required
- malformed typed content
- impossible kind/lifecycle transition
- stale expected revision write
- candidate claiming current-state authority outside Memory
- unsupported relation target
- attempt to treat prepared-but-not-presented speech as actual spoken history

---

## 7. Duplicate / semantic similarity boundary

Embedding/vector similarity is a retrieval/search signal, not Memory identity Authority.

Forbidden:

```text
cosine_similarity > threshold
→ therefore duplicate
→ overwrite/merge automatically
```

Allowed:

```text
index similarity
→ candidate related records
→ typed reconciliation evidence
→ deterministic Store policy
```

Exact stable identity/content digest may be used for deterministic exact duplicate suppression.

Open-ended claims such as synonymy, contradiction, refinement, or temporal replacement require typed upstream observation/evidence; #332 itself does not become a hidden natural-language LLM.

---

## 8. Contradiction model

A canonical record may reference zero or more conflicting records.

```text
MemoryRelation
- relation_id
- left_memory_id
- right_memory_id
- relation_kind
- evidence_refs[]
- created_at
```

Initial relation kinds:

```text
SUPPORTS
REFINES
SUPERSEDES
CONTRADICTS
```

Relation kinds are closed structural relations. Discovery of an open-ended semantic relation may be proposed by #364 or another typed observer, but #332 validates references and owns persistence of the accepted relation.

`CONTRADICTS` does not imply either side is current truth.

Consumers receive enough metadata to avoid treating a conflicted Memory as uncontested evidence.

---

## 9. Actual fact / speech boundary

Memory must preserve the distinction between:

```text
intent
plan
prepared candidate
presented/observed action
actual execution result
historical memory
```

In particular:

- `PreparedSpeechCandidate` is not proof that Yura actually said something.
- `CharacterUtterance` generation is not proof of presentation.
- a speech episode Memory that claims “Yura said X” requires presentation/actual speech evidence from the owning runtime boundary.
- an Activity Memory that claims execution requires #329 Actual Execution Fact evidence.

Memory may record that a plan/candidate existed if the Memory content explicitly says it was a plan/candidate. It must not relabel it as an executed fact.

---

## 10. Relationship / preference / internal-state boundary

### Relationship

`RELATIONSHIP` Memory stores historical evidence such as prior interactions or relationship-relevant events.

It does not directly set #327 current Relationship state.

```text
Relationship Memory evidence
→ Appraisal / State Reducer input
→ current Relationship state transition
```

### Preference

`PREFERENCE` Memory can store evidence that a preference existed/was stated. Current active preference may be derived/evaluated by the consuming authority with freshness/conflict information.

### Internal State

Past Emotion/Desire/Drive may be stored as an episode only when historically useful, but retrieving it must never directly restore that value into current Internal State.

```text
past emotion Memory
≠ current emotion
```

---

## 11. Retrieval contract

### 11.1 MemoryRetrievalQuery

A retrieval query is bounded and typed.

```text
MemoryRetrievalQuery
- query_id
- requester
- purpose
- memory_kinds[]?
- subject_refs[]?
- topic/activity/relationship refs[]?
- temporal_range?
- semantic_query?
- max_items
- max_estimated_tokens
- include_conflicted
- created_at
```

`semantic_query` is optional search input for a semantic-index Port. #332 does not interpret arbitrary natural language itself.

### 11.2 Retrieval signals

Ranking may combine:

- semantic relevance signal
- recency
- importance
- confidence
- relationship relevance
- activity/topic relevance
- current motivation relevance supplied as a typed signal
- freshness
- contradiction status

Weights/policy are explicit deterministic configuration, not hidden LLM judgment.

No one signal is universal Authority.

### 11.3 Bounded output

Both limits are enforced:

- `max_items`
- `max_estimated_tokens`

The Store must not return unbounded conversation/memory history to downstream LLMs.

Stable tie-breaking is required for deterministic tests.

---

## 12. MemoryEvidenceView

Downstream modules receive immutable read-only evidence views, not repository objects.

Minimum item shape:

```text
MemoryEvidenceItem
- memory_id
- kind
- content
- provenance
- confidence
- freshness
- temporal_scope
- lifecycle
- contradiction_refs[]
- retrieval_score_components
```

Envelope:

```text
MemoryEvidenceView
- query_id
- generated_at
- items[]
- truncated
- degraded
- degradation_reasons[]
```

Consumers must be able to distinguish:
- historical evidence
- stale evidence
- conflicted evidence
- current authoritative facts supplied by other modules

Memory evidence must never hide this distinction by flattening everything into one plain-text summary.

---

## 13. Persistence / index ports

### MemoryRepositoryPort

Owns persistence mechanism behind the Domain boundary.

Required capabilities:
- read by id/revision
- atomic create/update with expected revision
- relation persistence
- bounded candidate listing/filtering
- lifecycle preservation

Repository implementation may be in-memory, PostgreSQL, or another provider. Provider-specific types do not enter Domain contracts.

### MemorySemanticIndexPort

Optional derived search/index capability.

- add/update/remove index entries
- semantic similarity retrieval
- provider-specific embedding/vector types stay outside Domain

The semantic index is **not canonical Memory state**.

If index update fails after canonical store commit:
- canonical Memory remains valid
- index state is marked degraded/pending repair
- do not roll back an already committed canonical Memory solely because a derived index failed

If the semantic index is unavailable, exact/filter/recency retrieval may continue in degraded mode where safe.

---

## 14. Concurrency / revision

Memory writes must not use a Core-global lock.

- record/relation mutation uses atomic expected-revision semantics
- independent Memory writes may proceed independently
- slow persistence/index operation must not block unrelated Brain/Body/Speech lanes
- Reflection #364 may be cancelled/deferred without blocking foreground retrieval
- stale write loses to current canonical revision
- retrieval observes a coherent snapshot/version or clearly reports partial/degraded state

A delayed Memory operation must not mutate current Emotion/Goal/Attention as a side effect.

---

## 15. Degraded operation

### Repository unavailable

Durable write returns typed failure/degraded result. It must not pretend persistence succeeded.

Depending on policy, ephemeral working context may continue in-memory without claiming durable persistence.

### Semantic index unavailable

Canonical record access continues where possible. Retrieval returns `degraded=true` with safe degradation reasons.

### Partial failure

Canonical repository and derived semantic index must have explicit recovery/rebuild semantics. Hidden divergence is not accepted as success.

---

## 16. Security / privacy boundary

#332 must not log or duplicate unbounded raw conversations merely for diagnostics.

- secret/provider credentials never enter Memory content or diagnostics
- provider raw objects are not Domain records
- diagnostic logs use IDs/counts/status/reason codes where possible
- retention/privacy policy can further restrict persistence without changing Memory semantic authority

---

## 17. Initial implementation scope

#332 initial implementation SHOULD include:

1. typed contracts/enums
2. deterministic Memory authority / reconciliation service
3. in-memory repository reference implementation for Unit/Adjacent tests
4. repository Port
5. optional semantic-index Port contract with fake implementation
6. bounded deterministic retrieval/ranking
7. immutable `MemoryEvidenceView`
8. typed degradation/failure results

Initial #332 MUST NOT require:
- PostgreSQL deployment
- production embedding provider
- Reflection LLM #364
- whole-app startup
- Character/TTS/Body

Infrastructure persistence/provider implementations can be added through their own Infrastructure ownership without changing #332 Domain semantics.

---

## 18. Required tests

### Store / validation

- store new valid candidate
- malformed candidate reject
- provenance-required durable candidate without provenance reject
- exact duplicate does not create unbounded records
- duplicate with new provenance merges provenance without losing old source
- stale expected revision reject
- invalid lifecycle transition reject

### Update / contradiction

- newer typed replacement can supersede while old record remains historical
- unresolved contradiction preserves both records and links them
- contradiction never auto-selects winner by recency alone
- semantic similarity alone cannot trigger merge/supersede

### Authority boundaries

- Memory does not mutate current Internal State
- Memory does not mutate current Goal/Commitment
- Relationship Memory does not directly set current Relationship
- prepared speech cannot be stored as “actually spoken” without actual presentation evidence
- planned Activity cannot be stored as executed Activity without #329 fact evidence

### Retrieval

- kind/ref/time filters
- deterministic ranking
- item budget
- estimated-token budget
- stale/conflicted metadata visible
- no unbounded history output
- stable tie-breaker

### Degradation / concurrency

- repository unavailable typed failure
- semantic index unavailable -> safe degraded retrieval
- canonical store success + index failure does not lose canonical record
- independent reads continue during slow optional index work

### Immutability / serialization

- returned evidence view cannot mutate canonical store through aliasing
- round-trip/serialization contract as applicable

---

## 19. Adjacent verification

After Unit PASS:

1. #326 ReferenceContext can consume bounded `MemoryEvidenceView` without Memory becoming NL semantic Authority.
2. #327 Appraisal can consume historical Memory evidence without restoring past current-state values.
3. #328 Executive can read bounded Memory evidence without Memory selecting Goal/Action.
4. #364 Reflection fixture can submit MemoryCandidate and receive typed Store disposition.
5. #366 Goal State remains independent from past Goal Memory.

Whole-app startup is not required for #332 completion.

---

## 20. Design acceptance

Design Gate PASS when implementation preserves all of the following:

- canonical Memory Store / Retrieval is non-LLM
- Reflection candidate generation is separate
- historical Memory does not override current Authority
- exact duplicate, refinement/supersession, and unresolved contradiction are distinct
- contradiction is preserved rather than silently erased
- semantic/vector similarity is evidence, not identity Authority
- prepared/intended work is not remembered as actual execution
- retrieval is bounded and provenance/freshness/conflict-aware
- DB/vector provider remains outside Domain
- provider degradation does not falsely claim success
- Memory work does not globally block unrelated runtime lanes

This document is the detailed canonical supplement for Issue #332.
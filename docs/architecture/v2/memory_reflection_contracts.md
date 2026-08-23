# V2 Memory Reflection / Consolidation Contracts

Owner Issue: #364
Parent: #325
Upstream: #321, #323, #327, #329, #332, #333, #348
Downstream: #332 Memory Store / Retrieval
Related:
- `docs/architecture/v2/brain_architecture.md`
- `docs/architecture/v2/cognitive_llm_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/memory_store_retrieval_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#364 Reflectionは、会話・Activity・配信・ゲーム・関係変化・内部状態変化等の**既に起きた経験/evidence**から、長期Memoryへ残す価値がある内容を`ValidatedMemoryCandidate`候補として提案するbackground cognitionである。

```text
trusted historical source evidence
        ↓
Reflection trigger / bounded snapshot
        ├─ simple deterministic capture
        └─ complex open-ended reflection role
                    ↓
            MemoryCandidateProposal
                    ↓
        semantic support observation
                    ↓
          closed Reflection acceptance
                    ↓
          ValidatedMemoryCandidate
                    ↓
#332 deterministic Store reconciliation
        ↓
store / merge provenance / supersede / contradiction / reject
```

#364はMemory Storeを直接書き換えない。

---

## 2. Authority boundary

### #364 owns

- Reflection activation eligibility / trigger snapshot
- bounded source-evidence preparation
- open-ended candidate generation when needed
- candidate semantic support observation
- closed Reflection candidate acceptance/rejection
- importance / novelty / persistence / confidence hints
- relation hints supported by evidence
- background scheduling metadata for Reflection requests

### #364 does not own

- canonical Memory identity/revision/lifecycle (#332)
- final duplicate/merge/supersede/contradiction disposition (#332)
- current Emotion/Desire/Drive/Relationship state (#327)
- Actual Execution Fact (#329)
- conscious Goal/Action selection (#328)
- current Goal/Commitment state (#366)
- open-ended external NL meaning (#326)
- Character language (#330)

Reflection output is a proposal/evidence object, not a new current fact authority.

---

## 3. Reflection source evidence

Reflection only reads bounded typed evidence from trusted owner boundaries.

Initial source kinds:

```text
INPUT_MEANING
PRESENTATION_FACT
EXECUTION_FACT
ACTIVITY_RESULT
INTERNAL_STATE_TRANSITION
RELATIONSHIP_TRANSITION
GOAL_TRANSITION
GAME_RESULT
STREAMING_RESULT
MEMORY_EVIDENCE
LIFECYCLE_EVENT
```

Each source is represented as immutable `ReflectionSourceEvidence`:

```text
ReflectionSourceEvidence
- source_ref
- source_kind
- owner
- source_revision?
- occurred_at
- semantic_payload
- provenance_refs[]
- confidence?
```

`semantic_payload` is bounded structured data supplied by the owning module. Reflection does not receive arbitrary provider objects.

---

## 4. Speech / execution truth boundary

Reflection must preserve:

```text
planned/generated
!= presented/executed
```

### Speech

A `CharacterUtterance` or `PreparedSpeechCandidate` alone is not eligible evidence for a Memory claim “Yura said X”.

Such a claim requires trusted Presentation evidence:
- #348 Presentation report / #329 normalized Actual Fact
- exact utterance/presentation identity

Reflection may remember “a candidate was prepared” only if the candidate state itself is the historical subject.

### Activity

An Activity plan/request is not execution evidence.

A claim about performed action/result requires #329 Actual Execution Fact or trusted subsystem observation.

This rule applies before any LLM invocation; unsupported source classes are not merely discouraged by Prompt.

---

## 5. Reflection trigger

```text
ReflectionTrigger
- trigger_id
- kind
- source_refs[]
- source_context_revision
- priority
- interruptibility
- created_at
```

Initial trigger kinds:
- EPISODE_COMPLETED
- ACTIVITY_COMPLETED
- SESSION_COMPLETED
- RELATIONSHIP_RELEVANT_CHANGE
- SIGNIFICANT_STATE_TRANSITION
- IDLE_CONSOLIDATION
- BATCH_THRESHOLD
- SCHEDULED_LOW_PRIORITY

Trigger kind is scheduling metadata, not a fixed memory outcome.

`ACTIVITY_COMPLETED` does not automatically mean “store Activity Memory”. Reflection can legitimately produce no candidate.

---

## 6. Bounded ReflectionContextSnapshot

```text
ReflectionContextSnapshot
- reflection_id
- trigger
- primary_sources[]
- related_memory_view?
- character_self_model_view?
- value_disposition_view?
- source_context_revision
- memory_store_revision?
- captured_at
- trace_id
```

### Bounds

Configuration defines explicit limits:
- max primary sources
- max related MemoryEvidence items
- max estimated token budget
- max source text excerpt length where text evidence is unavoidable

Unbounded conversation transcript, raw provider response, full DB dump are forbidden.

### Context purpose

Character/self/value views may help judge long-term salience, but they do not authorize invented historical facts.

Static Character preference is not evidence that a specific current event occurred.

---

## 7. Simple deterministic capture path

Not every Memory requires a Reflection LLM.

A deterministic capture path is allowed when source semantics are already closed and direct.

Examples:
- trusted explicit fact designed for durable capture
- completed Activity Result with exact typed outcome
- explicit user preference fact already normalized upstream and policy-marked durable

```text
trusted typed source
+ deterministic capture policy
→ MemoryCandidateProposal
→ same support/acceptance gate
```

The deterministic path must not use keyword/regex/substring over open-ended raw NL as semantic authority.

---

## 8. Complex Reflection role

Logical role candidate:

```text
role_id: memory_reflection
input_schema_id: memory.reflection.context.v1
output_schema_id: memory.reflection.candidates.v1
```

Used for open-ended tasks such as:
- episode summarization
- cross-event stable semantic inference
- relationship-relevant lesson candidate
- preference/interest persistence candidate
- activity/skill learning candidate
- possible contradiction/refinement relation proposal

The role may return zero candidates.

“Nothing worth retaining” is a valid successful Reflection result.

---

## 9. MemoryCandidateProposal

```text
MemoryCandidateProposal
- proposal_id
- proposed_kind
- content
- source_refs[]
- confidence_hint
- importance_hint
- persistence_hint
- novelty_hint
- temporal_scope?
- suggested_related_memory_ids[]
- relation_hints[]
- rationale_evidence_refs[]
```

Hints are bounded normalized data, not final Store decisions.

### Proposed kinds

Must map only to #332 categories:
- WORKING
- EPISODIC
- SEMANTIC
- RELATIONSHIP
- PREFERENCE
- ACTIVITY_SKILL

Reflection cannot invent a new Memory category by string label.

---

## 10. Importance / novelty / persistence hints

Normalized hints:

```text
importance_hint: [0,1]
novelty_hint: [0,1]
persistence_hint: TRANSIENT | SHORT | DURABLE
confidence_hint: [0,1]
```

These influence candidate acceptance/routing but do not become canonical Memory metadata without #332 validation.

Rules:
- high emotion alone does not force durable storage.
- repetition alone does not prove importance.
- novelty alone does not prove truth.
- recency alone does not supersede older Memory.

No single hint is final Authority.

---

## 11. Relation hints

Reflection may propose:

```text
SUPPORTS
REFINES
SUPERSEDES
CONTRADICTS
```

only against exact related memory IDs included in `related_memory_view`.

A relation hint includes evidence refs and confidence.

Reflection cannot directly mutate a canonical relation.
#332 validates and applies accepted relation semantics.

Vector similarity or retrieval proximity alone cannot justify relation type.

---

## 12. Hallucination / support risk

Open-ended Reflection can generate unsupported inferences. Therefore an LLM proposal is **not** directly a `ValidatedMemoryCandidate`.

Initial V2 uses explicit semantic support observation for complex Reflection proposals.

```text
proposal + frozen source evidence
→ Reflection support observer
→ ReflectionSupportObservation
→ deterministic closed acceptance
```

This is separate from #363 speech verification; #364 owns its own memory-evidence support question.

---

## 13. Reflection support observer

Logical role candidate:

```text
role_id: memory_reflection_support
input_schema_id: memory.reflection.support.v1
output_schema_id: memory.reflection.support.observation.v1
```

For each proposal, observes:

```text
ReflectionSupportObservation
- proposal_id
- support_relation
- evidence_refs[]
- unsupported_content_refs[]
- contradiction_refs[]
- confidence
```

Closed `support_relation`:
- SUPPORTED
- PARTIALLY_SUPPORTED
- UNSUPPORTED
- CONTRADICTED
- AMBIGUOUS

The observer does not decide Store disposition.

---

## 14. Support-observer independence

To reduce self-confirmation:
- the support observer receives the immutable proposal and frozen evidence.
- it does not receive the proposal generator's free-form rationale as authority.
- evidence refs must ground to the same ReflectionContextSnapshot.
- provider `accepted=true` or score is not final authority.
- final candidate acceptance is deterministic closed policy.

A future fused provider call may optimize latency only if logical proposal/support roles and evidence separation remain auditable.

---

## 15. Closed Reflection acceptance

`ReflectionCandidateAuthority` converts proposal + support observation into either:

```text
ACCEPTED_FOR_STORE_SUBMISSION
REJECTED_UNSUPPORTED
REJECTED_AMBIGUOUS
REJECTED_CONTRADICTED
REJECTED_INVALID_PROVENANCE
REJECTED_STALE
REJECTED_POLICY
```

Initial policy:
- durable SEMANTIC/RELATIONSHIP/PREFERENCE/ACTIVITY_SKILL candidates require SUPPORTED.
- PARTIALLY_SUPPORTED is not silently upgraded to durable fact; policy may reject or narrow only through a new bounded proposal cycle.
- UNSUPPORTED/AMBIGUOUS reject.
- CONTRADICTED may produce a candidate only when the candidate's content explicitly represents uncertainty/conflict and source evidence supports that representation; otherwise reject and retain contradiction as diagnostic/possible relation evidence.
- deterministic exact-fact capture may use closed source-type validation instead of invoking support LLM, but passes the same acceptance abstraction.

---

## 16. ValidatedMemoryCandidate construction

Accepted proposal is projected into #332 `ValidatedMemoryCandidate`:

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

Projection rules:
- source refs become immutable provenance.
- confidence cannot exceed accepted support evidence policy.
- relation hints remain hints.
- proposal rationale is not stored as Memory truth.
- current state objects are not embedded as mutable aliases.

Then #332 decides STORE_NEW / NOOP_DUPLICATE / MERGE_PROVENANCE / SUPERSEDE / LINK_CONTRADICTION / REJECT.

---

## 17. Staleness

Reflection is background work. Source state may advance while it runs.

### Historical source evidence

An already occurred trusted historical event does not become false merely because `source_context_revision` advances.

### Hard stale

Reject/cancel when:
- referenced source was retracted/corrected and exact source identity is no longer valid
- related memory IDs/revisions required for a relation proposal have changed incompatibly
- trigger was cancelled/superseded before any durable historical source existed
- source provenance can no longer be resolved

### Rebaseable context drift

Changes to unrelated current Emotion/Goal/Attention do not invalidate historical evidence automatically.

The support/acceptance gate re-reads current related Memory revisions when the proposed relation depends on them.

---

## 18. Concurrency / priority

Reflection is background/sparse by default.

- foreground user interaction has higher scheduling priority.
- slow Reflection does not block Input Meaning/Executive/Speech/Body.
- multiple unrelated Reflection jobs may be independently bounded.
- per-provider and global background concurrency limits apply through #322/#323.
- user interaction may cancel/defer low-priority Reflection.
- cancellation does not roll back an already committed #332 Memory record from an earlier completed job.
- no Core-global Memory/Reflection lock across LLM awaits.

---

## 19. Coalescing / batching

High-volume sources must not start one Reflection LLM per event.

Allowed:
- episode/session batch
- bounded source aggregation
- latest/batch threshold triggers
- duplicate trigger coalescing

Forbidden:
- every chat message → mandatory durable-memory LLM call
- every game frame/comment → Reflection call

Batch construction preserves individual source refs required for provenance.

---

## 20. Failure / degradation

### Proposal provider unavailable

- no fabricated candidate.
- return typed `REFLECTION_PROVIDER_UNAVAILABLE`.
- foreground runtime continues.
- source evidence may remain eligible for a later retry if retention policy permits.

### Support observer unavailable

For open-ended candidate:
- fail closed for durable store submission.
- do not treat proposal as validated.

Deterministic exact-fact capture may continue if its closed validation path does not require the observer.

### #332 repository unavailable

A validated candidate may be returned as not-persisted/pending according to explicit bounded policy, but must not claim durable Memory success.

#364 does not create an unbounded hidden retry queue.

---

## 21. Privacy / retention

Reflection source preparation must minimize unnecessary raw content.

- prefer typed summaries/evidence from upstream owners.
- raw conversation excerpt only when required and bounded.
- secret/provider credential never included.
- rejected Reflection proposal need not become durable Memory.
- diagnostics store IDs, result classes, counts and bounded evidence references instead of duplicating full conversation.

Retention/deletion policy may prevent a candidate from durable storage even when semantically supported.

---

## 22. Observability

Events:

```text
reflection_triggered
reflection_deferred/coalesced/cancelled
reflection_context_captured
reflection_proposal_started/completed/failed
reflection_support_started/completed/failed
reflection_candidate_accepted/rejected
memory_store_submission_started/completed/failed
```

Metrics:
- trigger count by kind
- zero-candidate rate
- candidate count by memory kind
- accepted/rejected reason counts
- proposal/support provider latency
- source item/token budget
- store disposition distribution
- foreground preemption/cancellation
- background queue wait

Do not log full raw source bodies by default.

---

## 23. Required tests

### Source authority
- prepared-only speech cannot become “said” episode
- presented speech can become eligible episode evidence
- planned-only Activity cannot become executed memory
- #329 execution fact can become eligible source
- past state transition does not mutate current #327 state

### Candidate generation
- zero candidate valid
- episodic / semantic / relationship / preference / activity-skill proposal
- unknown kind reject
- unknown source ref reject
- unbounded source/context reject

### Support
- supported accepted
- unsupported/ambiguous rejected
- contradicted candidate not silently accepted
- partial support does not become full durable claim
- evidence refs exactly ground to frozen snapshot
- proposal rationale is not support proof

### Store boundary
- accepted proposal becomes `ValidatedMemoryCandidate`
- #332 remains final write disposition authority
- relation hint does not mutate canonical relation directly
- vector similarity alone cannot create contradiction/supersession

### Freshness
- unrelated current-state drift does not erase historical evidence
- corrected/retracted source causes stale reject
- related Memory revision conflict blocks stale relation proposal

### Concurrency
- slow 20s Reflection while foreground conversation continues
- foreground can cancel/defer background Reflection
- burst sources coalesce/batch instead of one LLM each
- cancellation leaves no pending background task

### Failure
- proposal provider unavailable
- support provider unavailable fails closed for open-ended durable candidate
- #332 unavailable does not claim persisted success

---

## 24. Non-goals

- canonical Memory persistence/revision/retrieval
- DB/vector provider implementation
- current Relationship/Emotion/Goal mutation
- Character speech generation
- full conversation archival
- fixed keyword importance rules as open-ended authority
- automatic “AI personality growth” mutation without typed Memory/State/Executive boundaries

---

## 25. Design Gate

#364 implementation starts only after:
- #332 Memory candidate/store contracts are canonical and aligned
- #323 variable Role/failure/concurrency contract remains compatible
- source owners (#327/#329/#348 etc.) expose typed historical evidence rather than mutable internals
- #359 Persistence keeps durable mechanism outside Reflection
- #445 Design Completion Gate PASS

#364 detailed design completion alone does not lift the global Implementation Freeze.

# V2 Speech Runtime / Presentation Contracts

Owner Issue: #348
Parent: #325
Upstream: #322, #328, #333, #362, #330, #363, #331
Downstream: #358, #329, #340
Related:
- `docs/architecture/v2/speech_pipeline_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/speech_performance_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#348は、Speechの各責務を分離したまま、**Preparation / semantic acceptance / audio preparation / queue / revalidation / Presentation**を非直列Runtimeとして調停する。

```text
Committed Executive Speech Intent
        ↓
#362 Speech Semantics
        ↓
#330 Character Language
        ├────────→ #363 Semantic Verification
        └────────→ #331 Speech Performance
                        ↓
                 #358 optional/speculative TTS
        ↓ readiness convergence
PreparedSpeechCandidate
        ↓
queue / revalidation / Presentation commit
        ↓
Presentation Adapter
        ↓
SpeechPresentationReport
        ↓
#329 Actual Execution Fact normalization
```

この図はAuthority/Data dependencyであり、固定serial await列ではない。

---

## 2. Ownership

#348 owns:
- one Speech candidateのPreparation orchestration
- candidate lifecycle
- verifier requirement policyのclosed decision
- semantic repair / bounded regeneration orchestration
- component readiness aggregation
- speculative artifact discard
- bounded prepared queue / priority arbitration
- pre-presentation revalidation
- Presentation commit decision
- interrupt / supersede / cancellation policy
- Presentation operational lifecycle / reports
- speech runtime observability

#348 does not own:
- conscious speech Goal/Action selection (#328)
- What-to-say (#362)
- How-to-say (#330)
- semantic observation truth (#363)
- Voice Style / Performance intent (#331)
- provider-specific synthesis (#358)
- generic Actual Execution Fact authority (#329)
- Body motion / viseme generation (#340)

---

## 3. SpeechPreparationRequest

Speech preparation starts only from a committed Speech intent / eligible runtime request.

```text
SpeechPreparationRequest
- preparation_id
- source_decision_id
- speech_intent_ref
- source_event_ids[]
- source_context_revision
- goal_revision?
- attention_revision?
- priority
- interruptibility
- required_preconditions[]
- expiry_policy
- semantic_verification_policy_ref
- presentation_policy_ref
- created_at
- trace_id
```

`priority` / `interruptibility` come from committed Executive/runtime scheduling authority. #348 does not infer them from raw text.

raw user text is not a Speech Runtime decision input.

---

## 4. Component readiness model

Speech candidate progression is **not** represented as one serial phase per upstream module.

Each candidate has independent component state.

```text
SpeechComponentReadiness
- semantics: PENDING | READY | FAILED | STALE | CANCELLED
- character: PENDING | READY | FAILED | STALE | CANCELLED
- verifier: NOT_REQUIRED | PENDING | ACCEPTED | REJECTED | FAILED | STALE | CANCELLED
- performance: PENDING | READY | FAILED | STALE | CANCELLED
- audio: NOT_REQUESTED | PENDING | READY | FAILED | STALE | DISCARDED | CANCELLED
```

Logical dependencies remain:
- Character requires SpeechSemanticPlan.
- Verifier requires CharacterUtterance + SpeechSemanticPlan.
- Performance requires CharacterUtterance.
- TTS requires CharacterUtterance + SpeechPerformancePlan.

But after Character completes:

```text
CharacterUtterance
├─ #363 verifier
└─ #331 performance → #358 TTS preparation
```

may overlap.

---

## 5. Candidate lifecycle

Aggregate candidate lifecycle:

```text
PREPARING
→ PREPARED
→ QUEUED
→ REVALIDATING
→ READY_TO_PRESENT
→ PRESENTING
→ COMPLETED
```

Terminal/alternate:

```text
CANCELLED
SUPERSEDED
STALE
REJECTED
FAILED
INTERRUPTED
```

Lifecycle constraints:
- no transition from terminal state back to active.
- PREPARED does not mean spoken.
- READY_TO_PRESENT requires current live revalidation.
- PRESENTING requires one successful Presentation commit.
- COMPLETED requires trusted Presentation completion report.
- stale after external effect started must not erase that effect.

---

## 6. PreparedSpeechCandidate

```text
PreparedSpeechCandidate
- candidate_id
- preparation_id
- source_decision_id
- source_event_ids[]
- speech_plan_id
- utterance_id
- performance_plan_id
- revisions
- priority
- interruptibility
- expiry_policy
- required_preconditions[]
- semantic_verification_requirement
- semantic_acceptance_ref?
- prepared_audio_ref?
- presentation_mode_capabilities[]
- lifecycle
- created_at
- updated_at
```

Candidate references immutable artifacts; large raw audio/provider objects are not embedded.

---

## 7. Semantic verification policy

Verifier invocation is policy-driven, not ad-hoc.

```text
SemanticVerificationRequirement
- REQUIRED
- NOT_REQUIRED_BY_CLOSED_POLICY
```

When verification is not required, record:
- policy_id/version
- reason code
- exact closed conditions that allowed skip

Do not allow:
- caller boolean `skip_verifier=true` without policy proof
- Character/provider self-approval
- free-form LLM statement as skip authority

If REQUIRED:
- Presentation commit is blocked until #363 closed acceptance is ACCEPTED.
- Performance and policy-permitted TTS prep may proceed in parallel.

---

## 8. Semantic repair / regeneration

#348 owns runtime repair orchestration, but does not change semantic truth.

### 8.1 Recoverable Character realization failure

When #363 returns a closed rejection that indicates Character realization drift and the original SpeechSemanticPlan is still live:

```text
same SpeechSemanticPlan
+ bounded typed repair constraints derived from #363 observation
→ regenerate #330 CharacterUtterance
→ re-run #363
```

Repair input must be typed/closed and evidence-grounded.

Do not pass a verifier free-form instruction as new What-to-say Authority.

### 8.2 Upstream semantic invalidity

If current facts/revisions invalidate the SpeechSemanticPlan itself:
- do not repair by paraphrase.
- mark candidate STALE/REJECTED.
- emit typed replan/redecision event to the owning upstream layer.

#348 does not rewrite propositions.

### 8.3 Bounded attempts

Each preparation has explicit maximum regeneration attempts.

Initial policy:
- bounded finite attempts
- exact attempt count observable
- repeated same rejection class may stop early
- no infinite Character↔Verifier loop
- no generic fixed-phrase fallback

On regeneration:
- old performance plan becomes superseded
- old speculative audio becomes DISCARDED
- new utterance/performance/audio get new identities

---

## 9. TTS preparation policy

TTS preparation may be:
- deferred until semantic acceptance
- started after performance plan as speculative work

according to closed `TTSPreparationPolicy`.

Speculative audio artifact must be candidate-scoped and identity-bound to:
- utterance_id
- performance_plan_id
- voice binding/config revision
- pronunciation configuration revision when applicable

If verifier rejects, candidate becomes stale, or performance is replanned:
- artifact is discarded
- it must never be presented

Prepared audio is not proof of speech.

---

## 10. Presentation capability / degradation

#348 consumes a bounded `SpeechPresentationCapabilityView`.

Possible capabilities may include:
- text/subtitle presentation
- audio presentation
- timing publication

Provider/output availability is not decided by #348.

Presentation policy determines allowed modes, e.g.:
- AUDIO_WITH_TEXT preferred
- TEXT_ONLY allowed during TTS degradation
- FAIL_CLOSED if audio is mandatory for a specific use case

A degraded text-only presentation must be explicitly recorded and must not pretend audio playback occurred.

---

## 11. Queue / backpressure

Speech future generation is bounded.

Initial invariant:
- at most one active presentation per output channel
- immediate next prepared candidate is bounded
- future/background prepared candidates are bounded by queue policy
- unlimited autonomous speech pre-generation forbidden

Pressure actions:
- drop stale
- cancel/supersede low-priority candidates
- coalesce same-intent candidates only when semantic identity allows
- suppress new background preparation

Foreground direct-user response may outrank background autonomous speech.

Fairness prevents permanent starvation, but fairness does not force obsolete speech to be presented.

---

## 12. Pre-presentation revalidation

Before READY_TO_PRESENT / Presentation commit, obtain a **live** immutable revalidation snapshot.

```text
SpeechPresentationCommitState
- current source_context_revision
- current goal_revision?
- current attention_revision?
- current turn/focus state
- current required preconditions
- current output/TTS capability
- candidate cancellation/supersede state
- current Character definition compatibility
- current expression context revision?
- observed_at
```

Check at minimum:
- candidate not terminal/cancelled/superseded
- expiry valid
- source/goal/attention freshness policy
- turn ownership / response obligation
- required preconditions
- output capability
- semantic acceptance exact candidate identity
- audio artifact exact utterance/performance identity

Do not rely only on the snapshot captured before long awaits.

---

## 13. Expression drift / performance rebind

Normal Internal State evolution should not automatically force semantic regeneration.

If CharacterUtterance remains valid but current expression revision has materially drifted before Presentation, policy may perform:

```text
same CharacterUtterance
+ latest SpeechExpressionContext
→ #331 re-plan Performance
→ invalidate old audio
→ #358 reprepare if audio required
```

This is performance rebind, not speech semantic rewrite.

If delay/priority makes reprepare no longer useful, candidate may be cancelled/superseded instead.

---

## 14. Presentation commit

Presentation commit is a short atomic decision boundary.

Success conditions:
- exact candidate identity still current
- revalidation PASS
- semantic policy satisfied
- required presentation artifacts ready
- no higher-authority cancellation/supersede
- output channel accepts presentation

Commit returns a `SpeechPresentationCommand` referencing immutable candidate assets.

No long TTS/playback await occurs inside the commit lock.

---

## 15. Presentation report / Actual Fact boundary

Presentation Adapter returns trusted typed operational reports.

```text
SpeechPresentationReport
- presentation_id
- candidate_id
- status
- output_modes[]
- started_at?
- completed_at?
- audio_ref?
- timing_ref?
- failure_code?
- interruption_reason?
```

Status examples:
- STARTED
- COMPLETED
- INTERRUPTED
- FAILED_BEFORE_START
- FAILED_AFTER_START

#348 uses reports for speech lifecycle/queue coordination.

System-wide Actual Execution Fact normalization remains #329 responsibility.

```text
SpeechPresentationReport
→ #329 trusted execution observation boundary
→ generic Actual Execution Fact
```

A PREPARED/QUEUED candidate is never “actually spoken”.

A FAILED_AFTER_START report must preserve that partial external effect occurred.

---

## 16. Body / viseme publication

Only committed/started Presentation may drive actual mouth timing.

```text
SpeechPresentation STARTED
+ #358 actual pronunciation/timing track
→ #340 Body Realtime viseme lane
```

Speculative audio/timing must not move the mouth before Presentation commit.

Full-body motion/gaze/blink/breath continue independently.

---

## 17. Interruption

Current Presentation follows trusted `priority / interruptibility / turn` policy.

Possible operational actions:
- continue
- soft finish
- interrupt

New user input does not mechanically interrupt every speech; #333 Focus/Turn and committed scheduling metadata participate.

When interrupted after start:
- preserve actual presented portion/report
- cancel remaining playback where capability permits
- publish interruption result
- do not record full utterance as completed if not fully presented

---

## 18. Cancellation / supersede

Cancellation propagates candidate-locally to:
- in-flight #362/#330/#363 work when cancellable
- #331 plan work
- #358 synthesis
- queued Presentation

No global cancellation of unrelated speech/work.

Late result from cancelled/superseded task:
- may be observed for diagnostics
- must not become current candidate artifact

---

## 19. Concurrency invariants

- Speech A playback does not block Speech B cognition/preparation.
- #363 and #331 run in parallel after Character when possible.
- #358 safe TTS prep can overlap #363 according to policy.
- slow TTS does not block Input Meaning/Executive/Body.
- slow verifier does not block current playback or Body.
- Speech and Body planning are sibling fan-out from Executive.
- no Core-global speech lock across awaits.
- bounded per-candidate short locks only for lifecycle/commit transitions.

---

## 20. Observability

Required events:

```text
speech_preparation_requested
semantics_started/completed/failed
character_started/completed/failed
verifier_started/accepted/rejected/failed
performance_started/completed/failed
tts_started/completed/failed/discarded
candidate_prepared
candidate_queued
candidate_revalidation_started/completed
candidate_ready_to_present
presentation_committed
presentation_started
presentation_completed/interrupted/failed
candidate_cancelled/superseded/stale
repair_attempt_started/completed
```

Metrics:
- queue wait per component
- provider latency
- user input→first preparation
- user input→presentation start
- previous playback→next generation start overlap
- verifier repair count
- speculative TTS discard rate
- prepared candidate discard rate
- p50/p95/p99 critical path
- foreground/background starvation metrics

---

## 21. Required tests

### Lifecycle
- valid PREPARING→PREPARED→QUEUED→READY→PRESENTING→COMPLETED
- terminal state cannot reactivate
- prepared != presented
- duplicate Presentation commit rejected

### Parallel readiness
- slow verifier while Performance completes
- slow verifier while policy-permitted TTS completes
- previous 5s/20s playback while next Character/Verifier/Performance run

### Semantic repair
- recoverable #363 rejection causes bounded #330 regeneration with same Plan
- typed repair evidence only
- max attempt stop
- old performance/audio discarded after regeneration
- upstream semantic stale does not get paraphrase-repaired

### Freshness
- source/goal/attention stale reject
- turn/focus change revalidation
- expression-only drift rebinds Performance without semantic rewrite where policy allows
- stale audio identity reject

### Queue/backpressure
- bounded queue
- foreground outranks background
- stale background candidate discarded
- no call explosion under burst

### TTS/presentation
- verifier FAIL prevents speculative audio presentation
- TTS unavailable typed degradation
- text-only mode truthfully records no audio
- failed-after-start preserves partial effect

### Body/actual facts
- speculative timing does not drive viseme
- Presentation STARTED allows timing→#340
- #329 receives trusted presentation report, not prepared candidate

### Shutdown
- cancellation leaves no pending speech tasks
- retry/synthesis loops do not block shutdown

---

## 22. Non-goals

- Speech proposition generation
- Character text generation
- Semantic observer logic
- Voice performance calculation itself
- Provider synthesis implementation
- Body motion generation
- Goal/Attention authority
- finite fixed response fallback

---

## 23. Design Gate

#348 implementation starts only after:
- #331 / #358 detailed contracts align with this document
- #330 / #363 active-lineage canonical documents are reconciled
- #322/#333 lifecycle/priority semantics remain compatible
- #329 Actual Fact boundary is confirmed
- #445 Design Completion Gate PASS

#348 detailed design completion alone does not lift the global Implementation Freeze.

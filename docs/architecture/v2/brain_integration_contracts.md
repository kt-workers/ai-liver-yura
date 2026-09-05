# V2 Brain Integration Contracts

Owner Issue: #334
Parent: #325
Upstream: #326 / #327 / #328 / #366 / #361 / #329 / #362 / #330 / #363 / #331 / #332 / #364 / #333 / #348
Related: #322 / #323 / #350 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#334はBrain各Moduleを、Authorityを保ったまま**event-driven / snapshot-based / sparse activation / non-serial**に結合するIntegration契約を定義する。

Integrationは「Cognitive Loop」という新しい万能判断Authorityを作らない。

```text
Typed Event / internal trigger
        ↓
#326 Meaning ───────────────┐
        ↓                   │
#327 Appraisal/State        │
        ↓ salience          │
#333 Attention/Turn ←───────┤
        ↓ eligible trigger  │
#328 Executive              │
   ├─ Goal transition → #366
   ├─ optional Plan → #361 → #329
   ├─ Speech intent → #362/#330/#363/#331/#348
   └─ Attention intent → #333

#332 Memory evidence ───────→ #326/#327/#328 bounded context
#364 Reflection ← historical trusted results (background)
```

矢印はAuthority/data dependencyであり、全段を1 request内で順番にawaitする意味ではない。

---

## 2. Integration owns / does not own

### #334 owns

- module composition/wiring
- typed trigger routing
- immutable snapshot acquisition coordination
- cross-module identity/revision propagation
- background/foreground lane admission integration
- cancellation/supersede propagation wiring
- integration trace/timeline
- fake-provider integration topology
- degraded optional-module routing

### #334 does not own

- NL meaning (#326)
- current Internal State (#327)
- Goal/Action decision (#328)
- Goal/Commitment state (#366)
- Attention/Turn state (#333)
- Plan semantics (#361)
- Activity execution truth (#329)
- What-to-say (#362)
- Character realization (#330)
- semantic observation (#363)
- Performance (#331)
- Memory canonical state (#332)
- Reflection candidate judgment (#364)
- Speech presentation lifecycle (#348)

Integration code must not contain fallback decision logic that duplicates those owners.

---

## 3. Brain integration envelope

Cross-module work carries a shared correlation envelope.

```text
BrainWorkEnvelope
- trace_id
- trigger_id
- source_event_ids[]
- source_context_revision
- goal_revision
- attention_revision
- priority
- created_at
```

Module-native revisions remain separate where required:
- internal_state_revision
- memory/retrieval snapshot identity
- character definition revision
- speech plan/utterance identity

One global revision is not used to replace owner-native revisions.

---

## 4. Trigger sources

Executive is not triggered only by user text.

Eligible typed source classes include:

```text
EXTERNAL_INPUT
ATTENTION_ELIGIBLE_EVENT
GOAL_COMMITMENT_REVIEW
ACTIVITY_RESULT
EXTERNAL_OBSERVATION
INTERNAL_STATE_THRESHOLD_OR_CHANGE
MEMORY_RELEVANCE_SIGNAL
SYSTEM_LIFECYCLE_SIGNAL
```

Trigger eligibility is determined by owning contracts (#333 etc.), not a raw event-type string switch that reinterprets meaning.

Pending Goal/Commitment may create an autonomy trigger without user input.

---

## 5. Input / Meaning / Appraisal flow

External natural-language input:

```text
Input Gateway
→ #326 StructuredInputMeaning
→ #327 Appraisal candidate/reducer
→ #333 salience/attention scheduling
→ eligible Executive trigger
```

Rules:
- Executive never receives raw text as alternate semantic Authority.
- Input Meaning completion is not a global barrier for unrelated ongoing work.
- a slow Meaning request does not stop current Speech presentation, Body, Game or other independent input reception.
- same source event cannot be committed twice as conflicting Meaning generations without owner rules.

---

## 6. Internal State integration

#327 owns state mutation.

Integration passes:
- typed Meaning/evidence
- Memory evidence where requested
- Activity/external observation evidence

to #327 through its contract.

State updates can independently generate:
- Appraisal/State read models
- salience candidates
- later Executive triggers
- Body expression inputs

No integration callback writes state directly.

---

## 7. Attention / Turn integration

#333 sits between high-volume event sources and Executive eligibility.

```text
salience hints + current Goal/Activity/Turn
→ #333 bounded scheduling
→ ExecutiveTrigger
```

Integration rules:
- not every event invokes Executive.
- direct user interaction may outrank background Reflection.
- Game/Streaming burst uses bounded inputs.
- Body gaze is downstream projection only.
- stale attention revision is propagated to relevant long-running work and checked by owner commit gates.

---

## 8. Executive fan-out

A committed Executive decision may contain multiple sibling intents.

```text
CommittedExecutiveDecision
├─ Goal/Commitment transition → #366
├─ Activity/Planning path
├─ Speech path
├─ Body path (outside #334 integration scope, consumed by #341)
└─ Attention intent → #333
```

Sibling work may begin in parallel where their prerequisites are satisfied.

Character/Speech completion is not prerequisite for Body intent dispatch.

Goal transition application ordering must respect #366 expected revision semantics. If a sibling Plan requires the new Goal revision, it starts only after that revision is committed; unrelated siblings need not wait.

---

## 9. Goal / Planning / Activity integration

```text
Executive transition intent
→ #366 atomic state apply
→ current GoalContextView

Executive Activity intent
or active complex Goal requiring decomposition
→ #361 planning
→ #329 Activity admission/execution
→ Actual Execution Fact / result event
→ #327/#333/#328 as evidence/trigger
```

Rules:
- #361 cannot change Goal.
- stale `goal_revision` Plan rejected.
- #329 execution result does not auto-complete Goal; Executive/#366 transition required.
- capability unavailable returns evidence for later decision; Integration does not silently choose another Goal.

---

## 10. Speech integration

Speech path uses D2 contracts.

```text
Executive SpeechIntent
→ #362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├─ #363 semantic observation
   └─ #331 performance
→ #348 readiness / queue / revalidation / Presentation
```

Simple path may avoid a dedicated #362 LLM while still producing the same `SpeechSemanticPlan` Authority contract.

#334 does not require actual TTS/Avatar for minimum Brain text Integration. #348 can use a fake/text Presentation adapter for deterministic Integration.

Human Character quality is not #334 automated acceptance.

---

## 11. Memory integration

### Retrieval

Owner modules request bounded `MemoryEvidenceView` from #332.

- Input Meaning: reference/context evidence
- Appraisal: historical contextual evidence
- Executive: bounded relevant evidence

Memory does not select Goal or set current State.

### Reflection

Historical trusted outcomes are submitted to #364 asynchronously.

```text
Activity/Speech/external result
→ Reflection source queue
→ #364 candidate/support gate
→ #332 Store
```

Reflection is never a foreground response dependency.

---

## 12. Work scheduling model

Initial logical lanes:

```text
FOREGROUND_INTERACTION
COGNITIVE_NORMAL
SPEECH_PREPARATION
BACKGROUND_REFLECTION
```

These are scheduling categories, not Domain Authorities.

#322 owns queue/priority/backpressure mechanics.

Integration maps module work to scheduler metadata from trusted owner inputs.

No single global async lock surrounds Brain cognition.

---

## 13. Sparse LLM activation

Logical Role presence does not imply API call every cycle.

Examples:
- simple typed response semantics can use deterministic #362 path
- Appraisal may use deterministic reducer without deep LLM if evidence sufficient
- Planner only for complex decomposition
- Reflection only at background policy points
- Verifier according to explicit semantic-risk policy

Integration does not infer open-ended semantics to skip an owner Role; activation policy is explicit/typed.

---

## 14. Stale / cancel / supersede propagation

Long-running work records relevant revisions.

### Hard stale examples
- source input/reference changed
- Goal revision invalidates Plan
- Attention/Turn ownership invalidates queued response
- candidate explicitly superseded
- owner precondition/capability changed where required

### Non-global stale
A revision change only invalidates work whose owner contract declares dependency on that revision.

Example:
- unrelated Memory write does not cancel current Speech.
- current BodyState realtime revision does not invalidate all Brain work.

Integration never implements `any revision changed -> cancel everything`.

---

## 15. Degraded optional dependencies

Brain minimum text cognition must support:
- no TTS
- no Avatar
- no DB persistence
- no Plugin
- no Streaming/Game

Memory persistence unavailable:
- #332/#359 expose degradation; current interaction can continue if safe.

LLM提供サービスが利用できない場合:
- 影響を受ける役割は型付き失敗を返す。
- 入力意味解析の本番境界では`InputMeaningInterpretationResult`を受け取り、`meaning / role_failure / boundary_failure`を型で判定する（#564）。
- 統合側は架空の`StructuredInputMeaning`や確認要求を生成せず、例外文字列を解析せず、サービス失敗を成功へ書き換えない。
- 影響を受けない処理経路は継続できる。失敗の分類と採用判断は各所有者の契約に従う。

---

## 16. Execution and observation return loop

Results from Activity/Subsystem/Speech presentation become typed evidence/events.

```text
trusted result/observation
→ event/fact projection
→ Appraisal and/or Attention
→ optional Executive trigger
```

Integration does not automatically translate every success into a new Goal transition.

Intent/Plan/generated speech cannot substitute for actual result evidence.

---

## 17. BrainIntegrationTrace

```text
BrainIntegrationTrace
- trace_id
- root_trigger_id
- source_event_ids[]
- intervals[]
- revision_events[]
- decision_ids[]
- goal_transition_ids[]
- activity_ids[]
- speech_candidate_ids[]
- terminal_outcome
```

Work interval:

```text
BrainWorkInterval
- work_id
- module
- lane
- queued_at?
- started_at
- completed_at?
- status
- source_context_revision?
- goal_revision?
- attention_revision?
```

Tracing is read-only evidence and not state Authority.

---

## 18. Integration fake topology

Minimum deterministic setup:
- fake Input Gateway/events
- fake/deterministic Meaning/Appraisal/Executive roles where needed
- real Domain Authorities/stores
- fake LLM Port with controllable delay/result
- fake Capability execution adapter
- fake text Presentation adapter
- in-memory Memory repository
- fake clock

TTS/Body/Avatar/Streaming are not mandatory for #334 minimum Brain Integration.

---

## 19. Required scenarios

### Cognition
- normal question/answer
- user request not treated as unconditional command
- clarification required
- farewell
- reference such as prior-action request using bounded Memory/Context
- capability unavailable

### Persistent autonomy
- Goal persists across turns
- suspend/resume/complete/abandon/supersede
- pending Goal/Commitment creates internal trigger without user input

### Responsibility
- Meaning vs Appraisal
- Executive vs Goal Store vs Planner
- Goal vs Activity
- What-to-say vs How-to-say
- Verifier observer only
- Reflection vs Memory Store

### Concurrency
- slow Deep Appraisal while new input accepted
- slow Planner while current Speech/unrelated work continues
- slow Verifier while safe Speech preparation continues
- slow Reflection while foreground conversation completes
- background LLM burst without foreground starvation
- Speech A presenting while Speech B preparation begins

### Freshness
- stale source context result reject
- stale goal revision Plan reject
- stale attention/turn queued speech reject
- cancelled/superseded result noncommit

---

## 20. Acceptance metrics

- event→Meaning latency
- event→Attention eligible
- event→Executive decision
- event→speech preparation
- event→Presentation
- foreground queue wait
- background starvation/fairness
- concurrent in-flight count
- stale/cancel/supersede count
- Reflection queue delay

Playback duration must not linearly postpone next Speech generation start.

---

## 21. Defect ownership

Integration failure is classified before fix:

```text
CONTRACT_MISMATCH
MODULE_DEFECT
INTEGRATION_WIRING_DEFECT
PROVIDER_DEFECT
TEST_HARNESS_DEFECT
```

If one Work's semantic/authority behavior is wrong, defect returns to that Work Issue; #334 does not absorb a local workaround.

---

## 22. #445 Gate

Brain Integration implementation remains frozen until #445 D1-D9 and final user confirmation PASS.

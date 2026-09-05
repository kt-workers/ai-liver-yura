# V2 System Integration Contracts

Owner Issue: #360
Root: #317
Depends on: #334 / #341 / #344 / #350 / #356 / #345 and subordinate completed Work
Related: #347 / #352 / #365 / #396 / #434 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#360は、V2のCore / Body / Plugin / Infrastructure / Subsystemsを段階的に結合し、AI Liver ゆらが**継続主体として非直列・degraded-safe・fact-groundedに動作すること**をSystem levelで検証する。

System Integrationは各Moduleのlogicを再実装しない。

```text
Foundation / Runtime
        ↓
Brain Integration
  ├─ Speech runtime / TTS
  ├─ Memory / Persistence
  └─ Goal / Attention / Activity
        ↓ sibling fan-out
Body Integration → Avatar
        ↓
Plugin capabilities
        ↓
Streaming / Game / GUI / Labs
```

責務グラフを巨大な起動時serial pipelineへ変換しない。

---

## 2. System Integration owns / does not own

### #360 owns

- composition topology verification
- startup/degraded composition verification
- cross-domain identity/revision propagation verification
- system-wide cancellation/shutdown verification
- cross-lane latency isolation verification
- staged integration gates
- end-to-end trace/evidence aggregation
- system boundary scans
- final Verification matrix coordination
- defect routing to owner Work

### #360 does not own

- any Domain decision/state Authority
- provider-specific semantic mapping
- subsystem-specific operational logic
- new fallback rules for failed modules
- Character quality judging automatically

---

## 3. System component classes

### Required Core foundation

Minimum process requires:
- Foundation typed contracts
- Runtime Kernel
- Brain minimum cognition
- lifecycle coordinator

### Core-native optional-at-boot service capability

Core semantic responsibilities remain defined even if a concrete external provider is absent.

Examples:
- LLM-backed roles may become unavailable/degraded
- Persistence may be unavailable
- TTS may be unavailable
- Avatar may be unavailable

Optional provider absence must not redefine module ownership.

### External Subsystems

- Avatar
- Streaming
- Game Skill
- GUI/Admin
- Validation Labs
- Development Tooling

Their absence does not invalidate Core identity.

---

## 4. SystemCompositionSnapshot

Integration records the concrete composition under test.

```text
SystemCompositionSnapshot
- composition_id
- git_head
- config_revision
- runtime_epoch
- component_bindings[]
- provider_bindings[]
- subsystem_bindings[]
- character_definition_revision
- created_at
```

Each binding records:
- logical owner/capability
- implementation identity/version
- availability
- generation/revision

Secrets are excluded.

This snapshot is test/operations provenance, not Domain State.

---

## 5. Staged integration gates

System Integration proceeds incrementally.

### S1 Foundation / Runtime

Verify:
- bounded scheduling
- priority/backpressure
- cancellation
- lifecycle
- no pending task leaks

### S2 Brain minimum

Use #334 with fake providers/text presentation.

Verify:
- Meaning/Appraisal/Attention/Executive/Goal/Activity/Speech/Memory boundaries
- user input not unconditional command
- internal trigger without user input

### #561 早期起動の境界

#561の早期起動に必要な登録集合と版付き初期データは、[最小Brainの本番初期構成](minimum_brain_production_configuration.md)を参照する。

#561の必須Brainモジュール登録は`INPUT_MEANING`のみであり、上記S2の全検証対象を起動時に必須登録することを意味しない。4レーンの定義要件は維持する。提供サービス未構成時の型付き利用不可、プロセス継続、取消・停止後の所有タスク回収までを早期に証明し、通常会話の成功や#360のS2最終検証は後続工程で確認する。

### S3 Full Speech

Add:
- #331 Performance
- #348 Runtime
- #358 actual/fake TTS

Verify actual speech preparation/presentation separation.

### S4 Body / Avatar

Add #341 and #346.

Verify sibling Speech/Body fan-out and continuous realtime Body.

### S5 Memory / Persistence

Add #364/#332/#359 persistence behavior.

Verify restart-safe state only.

### S6 Plugin zero/one

Use #344.

### S7 GUI / Validation Labs

Observe/control only through public contracts.

### S8 Streaming / Game

Verify simultaneous real-time Subsystem behavior.

### S9 Complete lifecycle

Verify degraded failure/reconnect/shutdown/restart.

A later stage does not replace earlier Unit/Adjacent evidence.

---

## 6. Startup topology

Startup is dependency-aware but not one long blocking readiness barrier for every optional service.

Logical sequence:

```text
load static configuration / Character Definition
→ initialize Core stores/runtime
→ establish minimum Brain service
→ publish availability of Providers/Plugins/Subsystems as they initialize
→ admit normal work when minimum required Core gate is ready
```

Optional provider/subsystem initialization may continue asynchronously.

Rules:
- TTS unavailable does not block text cognition.
- Avatar unavailable does not block Body Core.
- DB unavailable does not block ephemeral safe Core boot.
- Streaming/Game absent does not block normal operation.
- Plugin 0 is valid.
- unavailable LLM-required semantic path fails typed; no invented result.

---

## 7. Availability propagation

Availability is provider/module owned and projected as typed state.

System Integration verifies:
- unavailable does not become successful fact
- recovery changes appropriate descriptor/generation/revision
- old in-flight results cannot cross reconnect generation fences
- repeated failures do not cause log/queue storms
- one provider failure does not stop unrelated provider/lane

---

## 8. End-to-end interaction lineage

A user interaction may have correlation across multiple independent works.

```text
External Event
→ Meaning
→ Appraisal
→ Attention eligibility
→ Executive Decision
   ├─ Goal/Activity
   ├─ Speech
   └─ Body
```

System trace must retain:
- source event IDs
- decision ID
- source_context_revision
- goal_revision
- attention_revision
- Activity execution IDs
- Speech candidate/presentation IDs
- Body intent/plan/execution refs

No requirement that every branch exists for every decision.

---

## 9. Speech System path

Full speech Verification:

```text
#328 SpeechIntent
→ #362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├─ #363 Semantic Verification
   └─ #331 SpeechPerformancePlan
→ #358 safe audio preparation when policy allows
→ #348 live revalidation / Presentation commit
→ actual playback/report
→ #329 execution fact evidence where applicable
→ actual timing → #340 viseme
```

System acceptance:
- verifier-required speech never externally presents before acceptance.
- Performance/TTS safe work may overlap verifier.
- Speech A playback does not block Speech B cognition/preparation.
- stale queued speech never presents.
- TTS artifact ≠ spoken fact.
- failed/interrupted-after-start preserves partial effect.

Formal #434 Human Character quality may be resumed only after this actual Presentation path exists.

---

## 10. Body System path

```text
Executive BODY intent
→ #338 Plan
→ #339 physical solve/controller
+ #337 expression
+ #340 realtime overlays
→ BodyState / BodyPoseFrame
→ #346 Avatar
```

System acceptance:
- Character and Body planning sibling fan-out.
- Planner delay does not stop current trajectory/gaze/blink/breath/viseme.
- no Home reset.
- true 3D canonical directions/composite motion/jump.
- renderer slowdown/unavailable does not stop BodyState.
- 2D renderer limitation is Adapter degradation, not Core capability deletion.

---

## 11. Memory / continuity System path

```text
trusted historical results
→ #364 Reflection
→ #332 Store
→ #359 persistence
→ later bounded retrieval
```

Verify:
- Reflection background/nonblocking.
- LLM proposal support gate.
- contradiction preserved.
- vector similarity not truth authority.
- actual result evidence required for actual-history memory.
- restart restores only owner-declared restart-safe state.
- old Emotion/Attention/queued Speech/current Body pose/in-flight Activity not blindly restored.
- Goal/Commitment uses owner rehydration contract.

---

## 12. Plugin System path

Verify both:

### Zero plugin

Core normal operation with empty capabilities.

### One plugin

```text
Registry
→ CapabilityDescriptor
→ Executive/Planner view
→ #329 preflight
→ Plugin execution
→ effect evidence
→ #329 Actual Fact
```

Permission revoke/lifecycle stop/generation races must preserve already-applied effects and reject stale new work.

---

## 13. Streaming System path

```text
NL request
→ #326 semantic meaning
→ Executive
→ generic Activity/Capability
→ Streaming Subsystem provider operation
→ report / external observation
→ Actual Fact/Appraisal/Attention
```

Verify:
- no provider-specific Core classes/IDs/SDK.
- no literal NL matcher outside #326.
- provider observation vs user report provenance.
- start intent/Character claim not `LIVE` fact.
- comments bounded/aggregated.
- reconnect/API delay does not block Core.
- stream end does not shut down Core.

---

## 14. Game + Streaming simultaneous scenario

Required system stress scenario:

```text
Game Skill foreground realtime loop
+ Streaming secondary comment monitor
+ active Body realtime
+ possible current Speech presentation
+ background Reflection
```

Then direct user interaction arrives.

Expected:
- Game frame loop continues unless Core explicitly pauses/quits.
- Streaming ingestion continues bounded.
- #333 may prioritize direct interaction.
- Executive handles trigger without waiting for TTS/current playback completion.
- Body continues realtime.
- background Reflection yields/deprioritizes without starving foreground.

---

## 15. Natural-language semantic generalization

System Verification confirms #326 remains the only open-ended NL Authority.

Test categories include Streaming request/state reports and general interaction.

Paraphrases vary:
- vocabulary
- word order
- politeness
- colloquial form
- ellipsis
- contextual references

Deleting/changing a single literal fixture must not disable semantic category behavior.

Boundary scan forbids finite keyword/regex/substring semantic fallback in Executive/Activity/Streaming/Game etc.

---

## 16. Cross-lane latency isolation

Inject deliberate delays:

- Input Meaning 10s
- Deep Appraisal 10s
- Planner 10s
- Verifier 10s
- Reflection 20s
- Body Planner 20s
- TTS 10s
- Streaming provider 10s
- slow Avatar renderer

For each, specify unrelated lanes that must continue.

Evidence uses timestamped intervals/heartbeats, not subjective observation only.

Pass criteria must demonstrate overlap and bounded queue behavior.

---

## 17. Foreground starvation gate

Under simultaneous background load:
- multiple Reflection requests
- autonomous speech preparation
- Streaming aggregation
- Game observations

inject direct user input.

Verify foreground:
- admitted within bound
- provider work receives priority policy
- background queued work coalesces/cancels if necessary
- no unbounded LLM/task growth

Exact latency SLO values may be environment-specific, but bounded/non-starved behavior is required and measured p50/p95/p99.

---

## 18. Actual Fact invariant

Across all System scenarios:

```text
intent != plan != prepared candidate != external effect != observed result
```

Verify:
- speech generated ≠ spoken
- Body plan ≠ physically applied
- Plugin request ≠ external operation success
- Streaming start intent ≠ LIVE
- Game selected action ≠ applied action
- user report ≠ provider-confirmed observation

Actual Fact owner consumes trusted result/effect evidence only.

---

## 19. Revision / generation fences

System Integration verifies owner-specific freshness jointly:
- source_context_revision
- goal_revision
- attention_revision
- character definition revision
- capability descriptor revision
- plugin/subsystem/provider generation
- Body model identity
- persistence schema/payload versions

No universal `all revisions must equal` rule.

Only declared dependencies invalidate a work item.

---

## 20. Restart / rehydration

System restart scenario:

1. run and create eligible persistent state.
2. persist via #359.
3. simulate clean/unclean termination.
4. new runtime epoch.
5. load `RehydrationCandidate`.
6. owner validates/apply only restart-safe state.

Verify operational/in-flight state from prior epoch is not automatically resumed.

Memory historical data remains historical evidence.

---

## 21. Graceful shutdown

Use #350 sequence.

System acceptance:
- stop external admission
- stop new speech candidates
- cancel/supersede queued work
- bounded handling of interruptible/non-interruptible work
- stop frame/event producers
- close Subsystems/Providers in dependency-safe order
- best-effort persistence without blocking resource close forever
- stop retry loops
- pending task count = 0
- repeated stop idempotent

Streaming ending is not equivalent to System shutdown.

---

## 22. System trace

```text
SystemVerificationTrace
- verification_run_id
- composition_snapshot
- scenario_id
- timeline_events[]
- work_intervals[]
- revision_conflicts[]
- availability_transitions[]
- actual_effect_observations[]
- metrics
- machine_gate
- human_gate_refs[]
```

This is Verification evidence only.

---

## 23. Metrics

Minimum:
- Role queue wait/provider latency/token/cost where available
- end-to-end interaction p50/p95/p99
- user input→Meaning
- user input→Attention eligible
- user input→Executive
- user input→speech preparation/presentation
- playback中next generation start
- concurrent in-flight
- stale/cancel/supersede
- foreground starvation metrics
- Body frame interval/jitter
- Game frame stability/deadline misses
- Streaming ingress/aggregation/drop
- provider request/reconnect latency
- Memory Reflection/persistence metrics

---

## 24. Human Verification matrix

Machine contract tests precede Human Verification.

Human-required examples:
- actual LLM conversational behavior
- #434 Character naturalness/fidelity in full speech context
- actual TTS/performance quality
- Body natural motion / coordination
- Stick/Live2D/Avatar visuals
- real Streaming lifecycle/comments
- real Game operation
- GUI usability

Human PASS cannot be inferred solely from automated schema/timing PASS.

---

## 25. Boundary scans

Automated/static scans include:
- Core imports no YouTube/OBS concrete SDK/type.
- Core imports no renderer/Live2D concrete type.
- Provider SDK object absent from Domain DTO.
- no finite raw-NL matcher outside approved #326 internals/contracts.
- Development Tooling not imported by production Core.
- GUI/Lab does not own direct Domain mutation.
- Character/Body/Skill AI do not own Executive Goal.

Findings route to owning Work.

---

## 26. Defect ownership

Classify failure:

```text
MODULE_CONTRACT_DEFECT
MODULE_IMPLEMENTATION_DEFECT
ADJACENT_CONTRACT_MISMATCH
SYSTEM_WIRING_DEFECT
PROVIDER_OR_ENVIRONMENT_DEFECT
VALIDATION_HARNESS_DEFECT
HUMAN_QUALITY_DEFECT
```

Do not patch #360 with special-case logic to mask module defects.

An independent defect is filed/returned to owner Issue and System scenario re-run after fix.

---

## 27. System release gate

System PASS requires:
- all required Unit/Adjacent/Integration machine gates
- no unresolved blocking boundary defect
- actual required provider/system Verification
- Human Verification for subjective/external surfaces
- current-head evidence/provenance
- no stale review/evidence acceptance

#360 completion does not by itself change branch/release policy; #207/project management rules remain authority.

---

## 28. #445 Gate

System Integration implementation and final Verification remain frozen until #445 D1-D9 and final user Design Completion confirmation PASS.

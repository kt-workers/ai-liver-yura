# V2 Detailed Design Cross-Audit Report

Owner: #445
Root: #317
Status: D8 Cross-Design Audit
Audit date: 2026-08-23

## 1. Purpose

本書は、D1〜D7で揃えたV2詳細設計を個別文書の存在確認で終わらせず、**System全体として実装時に矛盾・Authority重複・循環依存・暗黙の意味解釈・誤ったFact昇格を生まないか**を横断監査する正本である。

D8がPASSするまで「全詳細設計完了」としない。

---

## 2. Audit dimensions

横断監査は最低限次を対象とする。

1. Authority ownership
2. Dependency graph / Work vs Integration dependency
3. DTO / identity / provenance
4. Revision / freshness / generation fencing
5. lifecycle / cancellation / supersede / stale
6. intent / plan / prepared / actual-effect truth boundary
7. concurrency / backpressure / starvation
8. static Character / dynamic State / Memory separation
9. open-ended natural-language Authority
10. provider / SDK / secret boundary
11. Plugin / Infrastructure / Subsystem classification
12. Presentation / renderer boundary
13. persistence / rehydration / shutdown ordering
14. Human Verification readiness / evidence class
15. active implementation lineage vs current canonical generation

---

## 3. Canonical Authority map after D8

| Concern | Authority owner | Explicit non-owner examples |
|---|---|---|
| open-ended external NL meaning | #326 Input Meaning | Executive, Streaming, Game, GUI, Plugin |
| subjective appraisal / current Internal State | #327 reducer | Character, Memory, Body, GUI |
| conscious Goal / Action selection | #328 Executive | Planner, Skill AI, Plugin, Character |
| current Goal / Commitment | #366 | Memory, Activity, Character |
| Attention / Focus / Turn / scheduling | #333 | Body gaze, Game Skill, Streaming |
| complex Goal planning | #361 | Executive Goal authority unchanged |
| Activity lifecycle / Actual Execution Fact | #329 | Intent, Plan, Character claim, Plugin report alone |
| What-to-say | #362 | #330/#331/#363 |
| How-to-say words | #330 | #331/TTS/Body |
| speech semantic observation | #363 | not Character quality / repair authority |
| speech performance intent | #331 | not TTS provider values |
| Speech preparation/presentation lifecycle | #348 | not What-to-say |
| provider TTS/audio/timing | #358 | not Character Voice Style authority |
| canonical Body Model / State identity | #336 | renderer |
| Body expression projection | #337 | not Motion/Goal authority |
| high-level Body motion plan | #338 | not physical fact |
| physical solve / final BodyState commit | #339 | #340/Avatar cannot write BodyState |
| realtime Body overlays | #340 | not cognitive Focus / final physical commit |
| canonical Memory / retrieval | #332 | Reflection / DB / embedding |
| Memory candidate reflection | #364 | cannot mutate Store directly |
| persistence mechanism | #359 | not Domain semantic authority |
| Plugin registry/capability availability | #343 | not Goal/Actual Fact |
| Plugin execution fact | #329 path | Plugin cannot self-certify effect |
| Avatar rendering | #346 | not Body/Speech semantic authority |
| Streaming external execution/observation | #347 | Core decision remains #328/#329 |
| Game frame-level skill | #365 | high-level Goal remains Core |
| GUI/Admin presentation/control | #351 typed read/command boundary | no direct state mutation |
| Validation evidence/harness | #352 | no production semantic authority |
| Development tooling evidence | #353 | no production authority |

Audit result: no known same-state dual Authority remains after the resolutions below.

---

## 4. Findings and resolutions

### D8-F01 — Runtime shutdown / Persistence ordering conflict

**Severity:** BLOCKING design conflict

Conflict:
- old #350 order could close adapters/workers before optional final persistence;
- #359 requires persistence transport to remain usable during bounded final snapshot flush.

Resolution:
- `runtime_lifecycle_contracts.md` corrected;
- #350 Issue synchronized;
- canonical order is:

```text
admission close
→ cancel/supersede queued/new work
→ bounded grace
→ producer stop
→ owner-declared final snapshot capture
→ bounded persistence flush while persistence is writable
→ persistence retry/admission stop
→ persistence settle/close
→ remaining resource close
→ owned task join
→ pending task 0
```

Final flush remains best-effort. Runtime durability is not shutdown-only.

Status: RESOLVED.

### D8-F02 — #331 SpeechExpressionContext mapping was implementation-defined

**Severity:** BLOCKING design gap

Problem:
- type existed, but mapping from #327 Internal State and Human-readable #355 Voice Style into normalized performance axes could be implemented as hidden `Emotion -> preset` or free-text interpretation.

Resolution:
- added `speech_expression_projection_contracts.md`;
- versioned `SpeechPerformanceProjectionPolicy` owns projection semantics;
- Character Voice Style values use exact confirmed-value bindings;
- substring / embedding / LLM implicit interpretation is forbidden;
- Yura baseline softness/calmness and dynamic expressiveness/energy semantics are policy data;
- generic dynamic modulation initially uses standardized ENERGY/AROUSAL evidence;
- unknown Emotion/state key has no hidden Voice preset;
- policy revision/provenance is observable;
- #331 direct dependency updated to include #327.

Status: RESOLVED.

### D8-F03 — #340 Work dependency cycle / indirect speech dependency

**Severity:** BLOCKING implementation-order ambiguity

Old Issue dependency:
`#331, #333, #336, #339`

Problem:
- #339 consumes #340 overlays in final composition, while #340 listed #339 as a Work prerequisite;
- #331 is not direct viseme timing source; #358 is.

Resolution:
- #340 direct dependencies are now `#333, #336, #337, #358`;
- #339 is consumer/Adjacent target, not #340 Unit prerequisite;
- #331 remains Related through #358;
- #341 owns #339/#340 integration.

Status: RESOLVED.

### D8-F04 — Game Skill incorrectly depended on Plugin Integration

**Severity:** architecture classification conflict

Problem:
- #365 is a dedicated Subsystem/Skill Runtime but depended on #344 Plugin Integration.

Resolution:
- removed #344 from #365 dependencies;
- #344/#342 are Related classification context;
- Game Skill uses generic Core Activity/Execution boundary without becoming a Plugin;
- a future lightweight game Plugin may exist separately.

Status: RESOLVED.

### D8-F05 — Avatar Issue title implied direct Speech timing ownership

**Severity:** responsibility ambiguity

Problem:
- old #346 title implied Avatar consumes/interprets Speech timing directly.

Resolution:

```text
#348 Presentation STARTED
+ #358 actual timing
→ #340 mouth/face realtime channels
→ #339 BodyState / BodyPoseFrame
→ #346 renderer projection
```

- #346 renamed to BodyPoseFrame projection only;
- Avatar cannot regenerate viseme from Character text/TTS.

Status: RESOLVED.

### D8-F06 — #434 Human gate evaluated Character text too early

**Severity:** Verification validity blocker

Problem:
- text-only CharacterUtterance did not expose sufficient conversation/situation context or actual speech performance;
- Human could not validly judge context fit / spoken Yura quality.

Resolution:
- #434 renamed to Speech Character Quality Human Gate;
- formal Human Verification deferred until #331/#348/#358 actual production speech Presentation exists;
- Human context must be source-grounded and separately displayed from LLM input;
- Machine semantic PASS cannot auto-become Human PASS;
- historical text-only Lab evidence remains diagnostic only.

Status: RESOLVED.

### D8-F07 — #332 Issue still instructed Codex implementation during #445 Freeze

**Severity:** process/canonical conflict

Resolution:
- #332 design-only PR #444 explicitly marked historical design lineage;
- its design was exact-recovered into #445;
- old Codex implementation instruction withdrawn;
- future implementation lineage is resolved from live trunk after D9.

Status: RESOLVED.

### D8-F08 — #330/#363 Issue states were stale relative to live implementation PRs

**Severity:** resume/canonical integrity risk

Resolution:
- #330 now records PR #423 exact HEAD `827eb66797e8ab1c38990bf5f0228eeae1e6e223`;
- #363 now records PR #428 exact HEAD `a08d88373b9f294b547e98a06bd99b7dd5c3e0d3`;
- both are Draft/Open/unmerged and frozen under #445;
- old “implementation unstarted/provider path incomplete” text removed where stale;
- design supplements exact-recovered into #445 authority.

Status: RESOLVED.

### D8-F09 — #338 active implementation is based on an older V2 trunk generation

**Severity:** future reconciliation blocker, not current design blocker

Evidence:
- PR #422 head `e3376f07d1d88c0dafcb4f4b384cc3887e8b40fa`;
- base is historical `rebuild/v2-foundation@7b251d9...`.

Resolution for Design Gate:
- #338 design blob exact-recovered into #445;
- PR #422 preserved, no product changes under Freeze;
- after D9, Resume Gate must compare current trunk/canonical and choose rebase/reconciliation/new lineage without assuming old branch is current.

Status: RESOLVED_FOR_DESIGN / IMPLEMENTATION_RECONCILIATION_REQUIRED_AFTER_D9.

### D8-F10 — Root #317 unfreeze rule predates #445

**Severity:** management Gate conflict

Problem:
- #317 still states only final user canonical confirmation remains before product unfreeze.

Required resolution:
- synchronize #317 to #445: D1–D7 detailed design, D8 cross-audit PASS, D9 explicit user Design Completion confirmation, then implementation planning/Resume Gates.

Status: RESOLUTION_REQUIRED before D8 PASS.

### D8-F11 — PR #435 scope no longer equals current #434 formal work

**Severity:** implementation lineage classification risk

Problem:
- PR #435 implements the earlier Character Language diagnostic Lab, while #434 now owns full actual-Speech Human quality.

Required resolution:
- preserve PR #435 as Draft/historical diagnostic validation lineage;
- explicitly state it is not the future full #434 implementation or merge gate;
- future #434 implementation after #331/#348/#358 is re-resolved from current live trunk.

Status: RESOLUTION_REQUIRED before D8 PASS.

### D8-F12 — PR #446 description is stale

**Severity:** progress metadata inconsistency

Problem:
- PR body still says D2 started / D3 next.

Required resolution:
- update PR body to D1–D7 DONE, D8 audit current, D9 pending.

Status: RESOLUTION_REQUIRED before D8 PASS.

---

## 5. Dependency graph rules after audit

### Work dependencies

`Depends on` means implementation of this Work cannot satisfy its own direct contract without the upstream contract/implementation.

Do not use `Depends on` merely because modules interact later in Integration.

Examples after correction:
- #331 directly depends on #327/#330/#355.
- #340 directly depends on #333/#336/#337/#358; #339 is Adjacent consumer.
- #365 does not depend on Plugin Integration #344.
- #346 depends on Body-produced BodyPoseFrame path, not raw Speech timing.

### Integration dependencies

Integration Work may depend on multiple completed Work contracts because its purpose is to bind them.

Examples:
- #341 binds #336/#337/#338/#339/#340.
- #334 binds Brain modules.
- #344 validates Registry + #329 execution integration.
- #360 binds system stages.

No Work should depend on its downstream Integration just to define its own Unit contract.

---

## 6. DTO / truth boundary audit

Across detailed contracts, preserve:

```text
Event / Meaning
!= Appraisal candidate
!= Executive intent
!= Goal state
!= Plan
!= Prepared candidate
!= Provider artifact
!= external effect
!= observed/applied result
!= historical Memory
```

Specific invariants:
- CharacterUtterance generated != spoken.
- PreparedAudioArtifact generated != played.
- BodyMotionPlan generated != body moved.
- Plugin operation accepted != external side effect occurred.
- Game action selected != controller action applied.
- Streaming start requested != stream live.
- Memory candidate proposed != canonical Memory stored.

Actual effect/history requires the owning execution/observation evidence.

Audit result: no known design intentionally collapses these states after resolutions.

---

## 7. Revision / freshness audit

Global equality of every revision is forbidden.

Each long-running result validates only declared dependencies.

Examples:
- Deep Appraisal: source context + state revision.
- Character: source/goal/attention/Profile/constraint generation.
- Speech Performance: utterance/Character/projection policy + relevant current expression.
- Body Planner: source/goal/attention/intent/model/constraint/capability; normal BodyState drift is rebaseable.
- Plugin: capability descriptor revision + plugin generation.
- Game Skill: goal revision + strategy revision.
- Avatar: model/binding generation + frame ordering.

`any revision changed -> cancel all` is not a valid System strategy.

---

## 8. Concurrency / backpressure audit

The following are independent lanes unless an explicit data dependency exists:

- new Input reception
- current Speech playback
- next Speech preparation
- Body realtime
- Body planning
- Game realtime
- Streaming ingestion/provider work
- background Reflection
- Persistence/index repair

Required invariants:
- current playback does not gate next cognition.
- Body realtime does not wait for Motion LLM/TTS/Character.
- Game frame loop does not wait for Executive/Character/TTS.
- Reflection does not starve foreground interaction.
- comment/frame bursts are aggregated/bounded.
- Provider retries are bounded and shutdown-aware.
- no Integration global async lock.

Audit result: no known intended global serial barrier remains.

---

## 9. Character / State / Memory audit

- Character Definition: stable personality/content authority.
- Internal State: current dynamic causal state.
- Memory: historical/contextual evidence.
- Goal/Commitment: current persistent intention/obligation state.

Forbidden conversions remain:
- Character trait -> current Emotion fact.
- past Emotion Memory -> current Emotion restore.
- Preference Memory -> current Interest without owner evaluation.
- Character Profile -> Speech proposition.
- Body expression -> cognitive Focus.
- Character utterance -> Execution Fact.

Speech/Body projection policies may translate source evidence into presentation tendencies, but those projections are derived read-only views and cannot mutate source Authority.

---

## 10. Natural-language audit

Open-ended external natural-language meaning Authority is #326 only.

No other module may use keyword/regex/substring/finite phrase allowlist as semantic fallback for open-ended input.

Provider-internal closed identifiers such as typed operation IDs, enum names, exact configuration keys and exact Character style bindings are not natural-language semantic fallback; they operate only after meaning/authoring has already been established by the owning contract.

---

## 11. Provider / security audit

- SDK/HTTP objects remain Infrastructure/Subsystem Adapter side.
- Domain receives typed result/failure only.
- Provider operational diagnostics are safe closed metadata (#437), not Domain semantics.
- credentials/API keys/raw headers/raw bodies/raw arbitrary exception strings do not enter Domain/GUI/Lab exports.
- GUI/Tooling browser does not receive server credentials.

---

## 12. Human Verification audit

Machine contract PASS is not subjective quality PASS.

Human gates occur only when the relevant observable experience exists.

Examples:
- #434: actual speech Presentation required.
- Avatar visual quality: actual renderer output required.
- Body naturalness: actual motion/visual output required.
- Game/Streaming real service behavior: live provider/runtime required.
- GUI usability: real browser interaction required.

Human evidence must bind exact implementation/config/Character/provider provenance.

---

## 13. Active implementation lineage audit

During #445 Freeze, preserved implementation lineages are evidence/implementation history, not automatic current canonical Authority.

Known preserved lineages:
- #330 / PR #423 / `827eb667...`
- #363 / PR #428 / `a08d8837...`
- #338 / PR #422 / `e3376f07...`
- #434 old diagnostic Lab / PR #435 / `30291dfd...`

Before any post-D9 implementation/merge:
1. fetch live trunk;
2. fetch target Issue/current canonical;
3. compare active PR base/head/delta;
4. verify no competing implementation lineage;
5. issue a new Resume Certificate;
6. reconcile only if the lineage still matches current design ownership.

No old branch is presumed to be the implementation starting point merely because it exists.

---

## 14. D8 PASS conditions

D8 may be marked PASS only when:

- [x] D1–D7 dedicated design documents exist.
- [x] known Authority overlaps audited.
- [x] truth/effect boundary audited.
- [x] concurrency/backpressure audited.
- [x] provider/security boundary audited.
- [x] #350/#359 shutdown conflict resolved.
- [x] #331 projection gap resolved.
- [x] #340 dependency ambiguity resolved.
- [x] #365 Plugin dependency misclassification resolved.
- [x] #346 Speech timing ownership ambiguity resolved.
- [x] #434 Human Gate scope corrected.
- [x] #332 stale implementation instruction removed.
- [x] #330/#363/#338 current lineage status synchronized.
- [ ] Root #317 synchronized to #445 Gate.
- [ ] PR #435 reclassified as historical diagnostic validation lineage.
- [ ] PR #446 progress body synchronized.
- [ ] Architecture Index includes all final supplements + this report.
- [ ] Design Completion Matrix marks all planned detail/integration areas resolved.
- [ ] final open-Issue dependency scan has no known blocking cycle/misclassification.
- [ ] PR #446 docs-only diff / CI / review gate checked at final D8 HEAD.

After all boxes pass, D9 is the only remaining Design Completion Gate: explicit user review/confirmation.

# V2 Detailed Design Cross-Audit Report

Owner: #445
Root: #317
Status: D8 Cross-Design Audit — PASS candidate
Audit date: 2026-08-23

## 1. Purpose

D1〜D7で揃えたV2詳細設計をSystem全体で横断し、実装前にAuthority重複、循環/過剰依存、暗黙意味解釈、Fact誤昇格、revision誤用、serial blocking、provider leakage、Verification不成立が残っていないかを確認する。

D8の最終PASSは、本書のresolutionとPR #446 exact-head CI/review確認をもって確定する。

## 2. Audit dimensions

1. Authority ownership
2. Work / Integration dependency graph
3. DTO / identity / provenance
4. revision / freshness / generation fencing
5. lifecycle / cancel / stale / supersede
6. intent / plan / prepared / actual-effect truth
7. concurrency / backpressure / starvation
8. Character / dynamic State / Memory separation
9. open-ended natural-language Authority
10. Provider / SDK / secret boundary
11. Plugin / Infrastructure / Subsystem classification
12. Presentation / renderer boundary
13. persistence / rehydration / shutdown
14. Human Verification readiness
15. active implementation lineage vs canonical generation

---

## 3. Authority result

| Concern | Authority |
|---|---|
| open-ended external NL meaning | #326 |
| subjective Appraisal / current Internal State | #327 |
| conscious Goal / Action selection | #328 |
| persistent Goal / Commitment | #366 |
| Attention / Focus / Turn / scheduling | #333 |
| complex Goal planning | #361 |
| Activity lifecycle / Actual Execution Fact | #329 |
| What-to-say | #362 |
| Character words / How-to-say | #330 |
| speech semantic observation | #363 |
| speech performance intent | #331 |
| Speech preparation / Presentation lifecycle | #348 |
| TTS/audio/pronunciation timing | #358 |
| canonical Body identity/state model | #336 |
| Body expression projection | #337 |
| high-level Body motion plan | #338 |
| physical solve / final BodyState commit | #339 |
| realtime Body overlays | #340 |
| canonical Memory / retrieval | #332 |
| Memory candidate Reflection | #364 |
| persistence mechanism | #359 |
| Plugin registry / capability availability | #343 |
| Avatar renderer projection | #346 |
| Streaming execution/observation | #347, while Core decision/fact stays #328/#329 |
| Game frame-level skill | #365, subordinate to Core Goal |
| GUI/Admin read/control surface | #351 typed boundary only |
| Validation evidence/harness | #352 |
| Development tooling evidence | #353 |

Result: no known same-state dual Authority remains.

---

## 4. Blocking findings resolved

### F01 — #350 shutdown vs #359 Persistence ordering

Old shutdown could close adapters before final persistence.

Resolved order:

```text
admission close
→ cancel/supersede queued work
→ bounded grace
→ producer stop
→ owner-declared restart-safe snapshot capture
→ bounded flush while Persistence remains writable
→ Persistence retry/admission stop
→ Persistence settle/close
→ remaining resource close
→ owned task join / pending 0
```

Runtime durability remains continuous/best-effort and is not shutdown-only.

### F02 — #331 Speech Expression projection gap

`SpeechExpressionContext` existed without a sufficiently explicit semantic projection policy.

Resolution:
- added `speech_expression_projection_contracts.md`;
- versioned `SpeechPerformanceProjectionPolicy`;
- exact confirmed Character Voice value binding;
- no substring/embedding/LLM free interpretation of Voice Style text;
- no hidden Emotion→Voice preset;
- standardized ENERGY/AROUSAL evidence for generic modulation;
- policy revision/provenance is explicit;
- #327 is now direct #331 dependency.

### F03 — #340 dependency cycle / indirect source

Old: #340 depended on #331 and #339.

Resolved direct dependencies:
`#333, #336, #337, #358`.

#339 is final overlay consumer/Adjacent target; #341 integrates #339/#340. #331 is indirect through #358.

### F04 — #365 Game Skill misclassified through Plugin dependency

Removed #344 from #365 `Depends on`.

Game Skill is a dedicated realtime Subsystem/Skill Runtime. It may use generic Activity/Execution contracts without becoming a Plugin.

### F05 — #346 implied direct Speech timing ownership

#346 title/responsibility corrected to BodyPoseFrame renderer projection.

```text
#348 Presentation STARTED + #358 timing
→ #340 mouth/face channel
→ #339 BodyPoseFrame
→ #346 renderer
```

### F06 — #434 Human quality happened too early

Text-only Character output was insufficient for final Human context/performance judgment.

#434 now requires full actual Speech Presentation after #331/#348/#358 and source-grounded Conversation/Situation Context. Machine semantic PASS remains separate from Human quality PASS.

### F07 — #332 stale Codex implementation instruction

PR #444 is historical design-only. Its contract is exact-recovered into #445. It is not the future implementation branch.

### F08 — stale #330/#363/#338 Issue and PR state

Current preserved heads are recorded and frozen:
- #330 / PR #423 / `827eb66797e8ab1c38990bf5f0228eeae1e6e223`
- #363 / PR #428 / `a08d88373b9f294b547e98a06bd99b7dd5c3e0d3`
- #338 / PR #422 / `e3376f07d1d88c0dafcb4f4b384cc3887e8b40fa`

Their Issue/PR descriptions now say HOLD under #445 and require a post-D9 Resume Gate.

### F09 — #338 historical base generation

PR #422 uses historical trunk base `7b251d9...`.

Design is recovered; implementation remains preserved only. Post-D9 live reconciliation decides reuse vs new lineage.

### F10 — Root #317 pre-#445 unfreeze rule

#317 synchronized. Product unfreeze now requires:
D1–D7 complete → D8 PASS → D9 explicit user confirmation → per-Work Resume Gate.

### F11 — PR #435 no longer matches formal #434 scope

PR #435 reclassified as historical diagnostic validation lineage, not future full #434 implementation/merge gate.

### F12 — PR #446 stale progress metadata

PR #446 synchronized to D1–D7 DONE, D8 current, D9 pending.

### F13 — #358 depended on downstream Presentation Runtime

Old #358 depended on #348 although #348 is its consumer/orchestrator.

Resolved:
- #358 direct dependency: #331 only;
- #348/#340/#434 are Related/Adjacent consumers.

### F14 — #346 depended on downstream Body Integration

Avatar Unit implementation only needs canonical body identity and final BodyPoseFrame producer contract.

Resolved direct dependencies:
`#336, #339`.

#340/#341 are Related/Integration context.

### F15 — #347 depended on Brain Integration

Streaming Work can implement execution/observation/ingestion against #329/#333 without waiting for #334.

Resolved direct dependencies:
`#329, #333`.

#334 is Adjacent/System integration context.

### F16 — #345 Parent ↔ #360 completion dependency cycle

#345 completion expects System Integration evidence, while old #360 `Depends on` included #345.

Resolved #360 direct dependencies to concrete integration/work surfaces:
`#334, #341, #344, #350, #346, #347, #351, #352, #358, #359, #365`.

#345/#356 are Related parent architecture, not implementation prerequisites.

---

## 5. Dependency semantics after correction

`Depends on` means the Work cannot satisfy its own direct implementation/Unit contract without the upstream contract/implementation.

Do not use it merely because two modules are later integrated.

Integration Issues may depend on multiple Work outputs because binding them is the Integration responsibility.

No known Work now depends on its own downstream Integration solely to define its Unit implementation.

Final high-risk chains:

```text
#327 + #330 + #355 → #331 → #358
                           ↘
#330 → #363                 #348 consumes readiness/artifacts

#333 + #336 + #337 + #358 → #340
#336 + #337 + #338 → #339
#339 + #340 → #341 Integration
#336 + #339 → #346 Avatar

#329 + #333 → #347 Streaming
#328/#366/#333/#361/#329 → #365 Game Skill

#334/#341/#344/#350/#346/#347/#351/#352/#358/#359/#365
→ #360 System Integration
```

No known blocking cycle remains in these chains.

---

## 6. Truth boundary audit

System-wide invariant:

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

Examples:
- CharacterUtterance generated != spoken.
- PreparedAudioArtifact != played audio.
- BodyMotionPlan != body moved.
- Plugin request accepted != external side effect.
- Game action selected != controller action applied.
- Streaming start requested != stream live.
- Memory candidate != canonical stored Memory.

Actual fact/history requires trusted owner execution/observation evidence.

Result: PASS.

---

## 7. Revision / freshness audit

Global revision equality and `any revision changed -> cancel all` are forbidden.

Long-running work validates declared dependencies only.

Examples:
- Deep Appraisal: source context + State revision.
- Character: source/goal/attention/Profile/constraints.
- Speech Performance: utterance/Profile/projection policy/current expression.
- Body Planner: intent/model/constraints/capabilities; ordinary BodyState drift is rebaseable.
- Plugin: descriptor revision + plugin generation.
- Game: goal + strategy revision.
- Avatar: binding/model generation + frame ordering.

Result: PASS.

---

## 8. Concurrency / backpressure audit

Independent lanes remain able to progress unless an explicit data edge exists:
- new Input reception
- current Speech playback
- next Speech preparation
- Body realtime
- Body planning
- Game realtime
- Streaming ingestion/provider work
- background Reflection
- Persistence/index repair

Required:
- playback does not gate next cognition;
- Body realtime does not wait for Motion LLM/TTS/Character;
- Game frame loop does not wait for Executive/Character/TTS;
- Reflection does not starve foreground;
- burst input is bounded/coalesced;
- retries are bounded/shutdown-aware;
- no Integration global async lock.

Result: PASS.

---

## 9. Character / State / Memory audit

- Character Definition = stable personality/content authority.
- Internal State = current dynamic causal state.
- Memory = historical/contextual evidence.
- Goal/Commitment = persistent current intention/obligation.

Forbidden:
- Character trait → current Emotion fact.
- old Memory Emotion → current Emotion restore.
- Preference Memory → current Interest without owner evaluation.
- Character Profile → new Speech fact.
- Body gaze/expression → cognitive Focus truth.
- Character utterance → Execution Fact.

Derived Speech/Body projection policies are read-only and cannot mutate their source Authority.

Result: PASS.

---

## 10. Natural-language audit

Open-ended external NL meaning Authority is #326 only.

No Streaming/Game/Executive/GUI/Plugin/Lab finite keyword/regex/substring fallback may become semantic Authority.

Typed operation IDs, enums, exact configuration IDs and exact authoring-style bindings operate only after semantics/authoring are already established and are not open-ended NL fallbacks.

Result: PASS.

---

## 11. Provider / security audit

- SDK/HTTP objects stay inside Infrastructure/Subsystem adapters.
- Domain receives typed results/failures.
- #437 operational diagnostics are safe metadata, not semantics.
- API keys/credentials/raw headers/raw bodies/arbitrary exception strings stay out of Domain/GUI/Lab Export.
- GUI/Tooling browser does not receive server credentials.

Result: PASS.

---

## 12. Human Verification audit

Machine PASS does not imply subjective quality PASS.

Human evaluation starts only when the observable surface exists:
- #434 after actual Speech Presentation;
- Body/Avatar after real visual motion;
- Game/Streaming after real provider/runtime;
- GUI after browser interaction.

Human evidence binds exact implementation/config/Character/provider provenance.

Result: PASS.

---

## 13. Active implementation lineage audit

Exact open-head searches confirm the expected preserved PR heads:
- `feature/v2-character-language` → PR #423 only
- `feature/v2-semantic-verification` → PR #428 only
- `feature/v2-body-motion-planner` → PR #422 only
- `test/v2-character-language-lab` → PR #435, explicitly historical diagnostic
- `feature/v2-memory-store-retrieval` → PR #444, explicitly historical design-only

These are preserved history/implementation evidence, not automatic current canonical Authority.

Before any post-D9 implementation/merge:
1. fetch live trunk;
2. fetch target Issue/current canonical;
3. inspect active PR/branch/base/head/diff;
4. verify no competing implementation lineage;
5. issue Resume Certificate;
6. reconcile or supersede from live evidence.

Result: PASS_FOR_DESIGN. Implementation reconciliation remains intentionally deferred until after D9.

---

## 14. PR #446 design-lineage integrity

PR #446 changed-file enumeration contains only `docs/architecture/v2/*.md` files.

No Python/product/config/runtime code is present in the design PR diff.

The branch is therefore architecture-only as required by #445.

---

## 15. D8 final gate

Completed:
- [x] D1–D7 dedicated design documents exist.
- [x] Authority overlaps audited.
- [x] truth/effect boundary audited.
- [x] revision/freshness audited.
- [x] concurrency/backpressure audited.
- [x] Character/State/Memory separation audited.
- [x] NL authority audited.
- [x] provider/security audited.
- [x] Human Verification gate audited.
- [x] dependency cycles/overdependencies corrected.
- [x] Root #317 synchronized.
- [x] active implementation PR metadata synchronized to Freeze.
- [x] PR #435 reclassified.
- [x] Architecture Index synchronized.
- [x] Design Completion Matrix shows no remaining B/C/D detail gaps.
- [x] PR #446 diff is docs-only.
- [x] active lineage scan found no competing open head for the preserved Work lineages.
- [ ] exact final HEAD deterministic CI SUCCESS.
- [ ] exact final HEAD design review/checkpoint recorded.

If the final two items PASS without new branch mutation, D8 is PASS and D9 is the only remaining Design Completion Gate.

# V2 Detailed Design Completion Matrix

Owner: #445
Root: #317
Status: Architecture Freeze / Design Completion Gate

## 1. Purpose

AI Liver ゆら V2について、実装前に詳細設計が十分に確定しているかを一元管理する。

2026-08-23以降、#445がPASSし、D9でユーザーが完成設計を明示確認するまで新規production implementationを開始しない。

高レベルArchitectureやIssue本文だけでは設計完了とみなさない。実装担当が重要な責務、型、lifecycle、failure、freshness、concurrencyを推測しなくてよいことを基準とする。

## 2. Status definition

- **A — DETAILED_CANONICAL**: trunkまたは#445 architecture-only lineageに詳細canonicalが存在する。
- **POST_D9_RECONCILIATION**: 設計はAだが、既存implementation lineageを現行canonical generationへ照合する必要がある。

D1〜D8後、planned V2 Work/IntegrationにB/C/Dの詳細設計不足は残していない。

---

## 3. Foundation / Character

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Foundation typed contracts | #321 | A | Foundation contract set |
| Runtime Kernel | #322 | A | `runtime_kernel_contracts.md` |
| Variable LLM Role | #323 | A | `llm_role_contracts.md` |
| Runtime lifecycle | #350 | A | `runtime_lifecycle_contracts.md` |
| Character Bible | #354 | A | `docs/character/v2/yura_character_bible.md` |
| production Character Definition | #442 | A | `character_definitions/v2/yura.yaml` |
| Character Projection | #355 | A | `character_projection_contracts.md` / psychological projection |

#350/#359 shutdown ordering is reconciled: bounded final snapshot/flush occurs before Persistence close.

---

## 4. Brain

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Input Gateway | #349 | A | `input_gateway_contracts.md` |
| Input Meaning | #326 | A | `input_meaning_contracts.md` |
| Appraisal / Internal State | #327 | A | `appraisal_internal_state_contracts.md` |
| Executive | #328 | A | `executive_authority_contracts.md` |
| Goal / Commitment | #366 | A | `goal_commitment_state_contracts.md` |
| Goal Planning | #361 | A | `goal_planning_contracts.md` |
| Activity / Actual Fact | #329 | A | `activity_execution_contracts.md` |
| Attention / Turn / Autonomy | #333 | A | `attention_turn_contracts.md` + source lifecycle supplements |
| Speech Semantics | #362 | A | `speech_semantics_contracts.md` |
| Character Language | #330 | A / POST_D9_RECONCILIATION | 4 supplements exact-recovered from PR #423 |
| Semantic Verification | #363 | A / POST_D9_RECONCILIATION | 6 supplements exact-recovered from PR #428 |
| Speech Performance | #331 | A | `speech_performance_contracts.md` + `speech_expression_projection_contracts.md` |
| Speech Runtime / Presentation | #348 | A | `speech_runtime_presentation_contracts.md` |
| Memory Store / Retrieval | #332 | A | `memory_store_retrieval_contracts.md` |
| Reflection | #364 | A | `memory_reflection_contracts.md` |
| Brain Integration | #334 | A | `brain_integration_contracts.md` |

Speech:

```text
#362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├→ #363 Semantic Verification
   └→ #331 SpeechPerformancePlan
          ↓
       #358 TTS preparation
   ↓ readiness convergence
#348 revalidation / Presentation
→ trusted report → #329 Actual Fact normalization
```

No fixed serial await chain is implied.

Memory:

```text
trusted historical evidence
→ #364 proposal/support
→ ValidatedMemoryCandidate
→ #332 reconciliation/retrieval
→ #359 persistence
```

Historical Memory never directly becomes current Emotion/Goal/Relationship truth.

---

## 5. Body

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Canonical Body Model / State | #336 | A | `body_architecture.md` D01/D02 |
| Body Expression | #337 | A | `body_expression_contracts.md` |
| Body Motion Planning | #338 | A / POST_D9_RECONCILIATION | `body_motion_planning_contracts.md` exact-recovered from PR #422 |
| Solver / Controller | #339 | A | `body_solver_controller_contracts.md` |
| Realtime Layers | #340 | A | `body_realtime_layers_contracts.md` |
| Body Integration | #341 | A | `body_integration_contracts.md` |

```text
Executive BODY intent → #338 Plan → #339 physical trajectory
#327/#333/#355 → #337 expression ─┐
#333 + #358 timing → #340 overlay ├→ #339 final composition
                                  ↓
                         BodyState / BodyPoseFrame
                                  ↓
                              #346 Avatar
```

D8 direct dependencies:
- #340: #333/#336/#337/#358; #339 is Adjacent consumer.
- #346: #336/#339; #340/#341 are Related integration context.

Body invariants: #339 sole BodyState writer, #340 overlays only, no Home reset, no fixed preset canonical path, 3D Canonical not reduced by renderer, realtime does not wait for LLM/TTS/renderer.

---

## 6. Plugin / Infrastructure

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Plugin Registry / Permission | #343 | A | `plugin_registry_contracts.md` + permission supplement |
| Plugin Integration | #344 | A | `plugin_integration_contracts.md` |
| LLM Provider | #357 | A | `llm_provider_adapter_contracts.md` |
| LLM operational diagnostics | #437 | A | `llm_provider_operational_diagnostics_contracts.md` |
| TTS Provider | #358 | A | `tts_provider_contracts.md` |
| Persistence | #359 | A | `persistence_repository_contracts.md` |

D8 direct dependency correction: #358 directly depends on #331; #348 is downstream Presentation consumer/orchestrator.

Invariants: Plugin 0 valid; Plugin adds Capability not Core Authority; actual effect flows through #329; Provider/Adapter != Plugin; Subsystem != Plugin; raw provider detail/secrets remain outside Domain.

---

## 7. Subsystems

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Avatar | #346 | A | `avatar_presentation_contracts.md` |
| Streaming | #347 | A | `streaming_subsystem_contracts.md` |
| GUI/Admin | #351 | A | `gui_admin_contracts.md` |
| Validation Labs | #352 | A | `validation_lab_contracts.md` |
| Development Tooling | #353 | A | `development_tooling_contracts.md` |
| Game Skill | #365 | A | `game_skill_runtime_contracts.md` |
| Speech Character Human Gate | #434 | A design / implementation HOLD | Validation + Speech canonical set |

D8 corrections:
- #347 direct dependencies #329/#333; #334 is Adjacent/System target.
- #365 does not depend on Plugin Integration.
- #346 projects BodyPoseFrame and does not interpret raw Speech timing.
- #434 waits for actual #331/#348/#358 speech Presentation and source-grounded Human context.

---

## 8. Integration / System

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Brain Integration | #334 | A | `brain_integration_contracts.md` |
| Body Integration | #341 | A | `body_integration_contracts.md` |
| Plugin Integration | #344 | A | `plugin_integration_contracts.md` |
| System Integration | #360 | A | `system_integration_contracts.md` |

#360 direct dependencies after D8:
`#334, #341, #344, #350, #346, #347, #351, #352, #358, #359, #365`.

Parent #345/#356 are Related architecture context, avoiding Parent completion ↔ #360 dependency cycles.

System Verification stages:

```text
S1 Foundation / Runtime
→ S2 Brain
→ S3 Speech / TTS / Presentation
→ S4 Body / Avatar
→ S5 Memory / Persistence
→ S6 Plugin zero/one
→ S7 GUI / Labs
→ S8 Streaming / Game
→ S9 Lifecycle / restart / shutdown
```

This is staging order, not runtime serialization.

---

## 9. D8 Cross-design audit

Canonical: `design_cross_audit_report.md`

PASS content audit covers:
- Authority ownership
- dependency graph / overdependency/cycle corrections
- DTO/provenance
- intent/plan/effect/history truth
- revision/freshness/generation
- concurrency/backpressure
- Character/State/Memory separation
- open-ended NL authority
- provider/security
- Human Verification readiness
- implementation lineage/canonical-generation separation

Resolved findings include #350/#359, #331 projection, #340 dependency, #365 classification, #346 responsibility, #434 scope, #332 stale implementation direction, active PR metadata, #358/#347 overdependency and #360 Parent cycle.

PR #446 changed-file scan is architecture-only (`docs/architecture/v2/*.md`).

Preserved implementation heads were rechecked and remain one open head per intended Work lineage:
- #330 / PR #423 / `827eb667...`
- #363 / PR #428 / `a08d8837...`
- #338 / PR #422 / `e3376f07...`
- historical diagnostic #434 / PR #435 / `30291dfd...`
- historical design-only #332 / PR #444

Final D8 evidence still requires exact final HEAD CI/review/checkpoint without further branch mutation.

---

## 10. Design Completion stages

- [x] D1 Existing detailed-design audit
- [x] D2 Speech end-to-end detailed design
- [x] D3 Memory detailed design
- [x] D4 Body detailed design
- [x] D5 Plugin / Infrastructure detailed design
- [x] D6 Subsystems detailed design
- [x] D7 Brain / Body / Plugin / System Integration design
- [x] D8 Cross-design content audit and corrections
- [ ] D9 explicit User Design Completion confirmation

## 11. Implementation Freeze

Implementation Freeze remains active through D9.

After D9 PASS, implementation does not resume from old branches automatically. Every Work must run a fresh GitHub-live Resume Gate and emit a Resume Certificate before code/reconciliation/merge.

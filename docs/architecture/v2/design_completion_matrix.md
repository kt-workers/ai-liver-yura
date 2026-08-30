# V2 Detailed Design Completion Matrix

Owner: #445
Root: #317
Status: Architecture Reconciliation / D10 Implementation Decidability Gate

## 1. Purpose

AI Liver ゆら V2について、実装前に詳細設計が十分に確定しているかを一元管理する。

D1〜D9は2026-08-23に一度PASSし、ユーザーによるDesign Completion確認まで完了した。しかし2026-08-30、#339製造再開時に実装者が追加設計判断を行わないと製造できないBody physical/numerical gapを検出した。

このため#445を再openし、D10 `Implementation Decidability Reconciliation`を追加する。D10では「設計書が存在する」ことではなく、実装担当が重要な責務、型、lifecycle、failure、freshness、concurrency、数値変換、数学表現、依存順を推測しなくてよいことを設計完了基準とする。

D10 PASSまでproduction implementationを再凍結する。

## 2. Status definition

- **A — DETAILED_CANONICAL**: 詳細canonicalが存在し、D9時点の設計内容として有効。
- **POST_D9_RECONCILIATION**: 設計はAだが、既存implementation lineageを現行canonical generationへ照合する必要がある。
- **D10_RECONCILIATION_REQUIRED**: D9後の製造再開でimplementation-decidability gapが見つかり、canonical補修とowner Work再評価が必要。
- **D10_REAUDIT_PENDING**: D9設計は存在するが、D10追加監査dimensionでの再確認がまだ完了していない。

D10の監査基準は `design_implementation_decidability_audit.md` を正本とする。

---

## 3. Foundation / Character

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Foundation typed contracts | #321 | A / D10_REAUDIT_PENDING | Foundation contract set |
| Runtime Kernel | #322 | A / D10_REAUDIT_PENDING | `runtime_kernel_contracts.md` |
| Variable LLM Role | #323 | A / D10_REAUDIT_PENDING | `llm_role_contracts.md` |
| Runtime lifecycle | #350 | A / D10_REAUDIT_PENDING | `runtime_lifecycle_contracts.md` |
| Character Bible | #354 | A / D10_REAUDIT_PENDING | `docs/character/v2/yura_character_bible.md` |
| production Character Definition | #442 | A / D10_REAUDIT_PENDING | `character_definitions/v2/yura.yaml` |
| Character Projection | #355 | A / D10_REAUDIT_PENDING | `character_projection_contracts.md` / psychological projection |

#350/#359 shutdown orderingはD8でreconcile済み。D10では実装に必要なtyped lifecycle/failure値が不足していないかを再確認する。

---

## 4. Brain

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Input Gateway | #349 | A / D10_REAUDIT_PENDING | `input_gateway_contracts.md` |
| Input Meaning | #326 | A / D10_REAUDIT_PENDING | `input_meaning_contracts.md` |
| Appraisal / Internal State | #327 | A / D10_REAUDIT_PENDING | `appraisal_internal_state_contracts.md` |
| Executive | #328 | A / D10_REAUDIT_PENDING | `executive_authority_contracts.md` |
| Goal / Commitment | #366 | A / D10_REAUDIT_PENDING | `goal_commitment_state_contracts.md` |
| Goal Planning | #361 | A / D10_REAUDIT_PENDING | `goal_planning_contracts.md` |
| Activity / Actual Fact | #329 | A / D10_REAUDIT_PENDING | `activity_execution_contracts.md` |
| Attention / Turn / Autonomy | #333 | A / D10_REAUDIT_PENDING | `attention_turn_contracts.md` + source lifecycle supplements |
| Speech Semantics | #362 | A / D10_REAUDIT_PENDING | `speech_semantics_contracts.md` |
| Character Language | #330 | A / POST_D9_RECONCILIATION / D10_REAUDIT_PENDING | 4 supplements exact-recovered from PR #423 |
| Semantic Verification | #363 | A / POST_D9_RECONCILIATION / D10_REAUDIT_PENDING | 6 supplements exact-recovered from PR #428 |
| Speech Performance | #331 | A / D10_REAUDIT_PENDING | `speech_performance_contracts.md` + `speech_expression_projection_contracts.md` |
| Speech Runtime / Presentation | #348 | A / D10_REAUDIT_PENDING | `speech_runtime_presentation_contracts.md` |
| Memory Store / Retrieval | #332 | A / D10_REAUDIT_PENDING | `memory_store_retrieval_contracts.md` |
| Reflection | #364 | A / D10_REAUDIT_PENDING | `memory_reflection_contracts.md` |
| Brain Integration | #334 | A / D10_REAUDIT_PENDING | `brain_integration_contracts.md` |

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
| Canonical Body Model / State | #336 | **D10_RECONCILIATION_REQUIRED** | `body_architecture.md` D01/D02 + `body_physical_numeric_contracts.md` |
| Body Expression | #337 | A / D10_REAUDIT_PENDING | `body_expression_contracts.md` |
| Body Motion Planning | #338 | **D10_RECONCILIATION_REQUIRED** / POST_D9_RECONCILIATION | `body_motion_planning_contracts.md` + `body_physical_numeric_contracts.md` |
| Solver / Controller | #339 | **D10_RECONCILIATION_REQUIRED** | `body_solver_controller_contracts.md` + `body_physical_numeric_contracts.md` |
| Realtime Layers | #340 | A / D10_REAUDIT_PENDING | `body_realtime_layers_contracts.md` |
| Body Integration | #341 | A / D10_REAUDIT_PENDING | `body_integration_contracts.md` |

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

D10 correction:
- scalar DOF state is physical joint-coordinate Authority; quaternion is derived projection.
- fixed rest-local X→Y→Z composition eliminates hard-limit quaternion decomposition ambiguity.
- model revision/fingerprint, dynamic limits, segment CoM, end-effector frame, contact/support geometry are explicit.
- `TARGET_REF` geometry comes from trusted typed resolver; ref文字列から推測しない。
- `extent` is converted by closed effect-specific rules.
- numerical tolerance/iteration/residual/completion policy is versioned canonical data.

Body invariants remain: #339 sole BodyState writer, #340 overlays only, no Home reset, no fixed preset canonical path, 3D Canonical not reduced by renderer, realtime does not wait for LLM/TTS/renderer.

---

## 6. Plugin / Infrastructure

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Plugin Registry / Permission | #343 | A / D10_REAUDIT_PENDING | `plugin_registry_contracts.md` + permission supplement |
| Plugin Integration | #344 | A / D10_REAUDIT_PENDING | `plugin_integration_contracts.md` |
| LLM Provider | #357 | A / D10_REAUDIT_PENDING | `llm_provider_adapter_contracts.md` |
| LLM operational diagnostics | #437 | A / D10_REAUDIT_PENDING | `llm_provider_operational_diagnostics_contracts.md` |
| TTS Provider | #358 | A / D10_REAUDIT_PENDING | `tts_provider_contracts.md` |
| Persistence | #359 | A / D10_REAUDIT_PENDING | `persistence_repository_contracts.md` |

D8 direct dependency correction: #358 directly depends on #331; #348 is downstream Presentation consumer/orchestrator.

Invariants: Plugin 0 valid; Plugin adds Capability not Core Authority; actual effect flows through #329; Provider/Adapter != Plugin; Subsystem != Plugin; raw provider detail/secrets remain outside Domain.

---

## 7. Subsystems

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Avatar | #346 | A / D10_REAUDIT_PENDING | `avatar_presentation_contracts.md` |
| Streaming | #347 | A / D10_REAUDIT_PENDING | `streaming_subsystem_contracts.md` |
| GUI/Admin | #351 | A / D10_REAUDIT_PENDING | `gui_admin_contracts.md` |
| Validation Labs | #352 | A / D10_REAUDIT_PENDING | `validation_lab_contracts.md` |
| Development Tooling | #353 | A / D10_REAUDIT_PENDING | `development_tooling_contracts.md` |
| Game Skill | #365 | A / D10_REAUDIT_PENDING | `game_skill_runtime_contracts.md` |
| Speech Character Human Gate | #434 | A design / implementation HOLD / D10_REAUDIT_PENDING | Validation + Speech canonical set |

D8 corrections:
- #347 direct dependencies #329/#333; #334 is Adjacent/System target.
- #365 does not depend on Plugin Integration.
- #346 projects BodyPoseFrame and does not interpret raw Speech timing.
- #434 waits for actual #331/#348/#358 speech Presentation and source-grounded Human context.

---

## 8. Integration / System

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Brain Integration | #334 | A / D10_REAUDIT_PENDING | `brain_integration_contracts.md` |
| Body Integration | #341 | A / D10_REAUDIT_PENDING | `body_integration_contracts.md` |
| Plugin Integration | #344 | A / D10_REAUDIT_PENDING | `plugin_integration_contracts.md` |
| System Integration | #360 | A / D10_REAUDIT_PENDING | `system_integration_contracts.md` |

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

## 9. Original production sequence authority

V2初期製造順の根拠は `project_sync_manifest.md` の `工程`。

```text
100 #321
110 #322
120 #323
130 #320
140 #354
150 #355
160 #324
170 #357
200〜380 Brain / Speech / Memory / Infrastructure / Brain Integration
400〜460 Body
500〜520 Plugin
600〜650 Subsystems
700 #360 System Integration
```

工程は日付から逆算しない。元工程作成後に発見された必須Taskは、`design_implementation_decidability_audit.md`の規則に従い既存Workへ回収するか、独立責務ならIssue化して依存上の正しい工程へ挿入する。

計画にないことを理由に必須機能を未対応のままV2完成扱いしてはならない。

---

## 10. D8 Cross-design audit

Canonical: `design_cross_audit_report.md`

D8 PASS content audit covered:
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

D10はD8を否定するものではなく、D8で不足していたimplementation-decidability / data sufficiency / completion-state consistency / plan coverageを追加する。

---

## 11. Design Completion stages

- [x] D1 Existing detailed-design audit
- [x] D2 Speech end-to-end detailed design
- [x] D3 Memory detailed design
- [x] D4 Body detailed design
- [x] D5 Plugin / Infrastructure detailed design
- [x] D6 Subsystems detailed design
- [x] D7 Brain / Body / Plugin / System Integration design
- [x] D8 Cross-design content audit and corrections
- [x] D9 explicit User Design Completion confirmation — PASS 2026-08-23
- [ ] **D10 Implementation Decidability / Plan Coverage / Completion-State reconciliation**

## 12. Implementation Freeze

D9で一度解除したImplementation Freezeは、2026-08-30にblocking design gapを検出したためD10完了まで再有効化する。

D10 PASSまで:
- production implementationを増やさない。
- architecture-only reconciliationを行う。
- PR #501等の既存production成果は保全する。

D10 PASS後:
1. `project_sync_manifest.md`の元工程を基準にする。
2. 後発必須Taskを依存位置へ挿入したcurrent工程へProject #7を同期する。
3. 工程先頭からclosed/implementation responsibilityを順に照合する。
4. 最初の未完了Workをfresh Resume Gateする。
5. 1 Work = 1 active implementation lineage、1 commit = 1 taskで製造を再開する。

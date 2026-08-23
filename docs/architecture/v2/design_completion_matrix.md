# V2 Detailed Design Completion Matrix

Owner: #445
Root: #317
Status: Architecture Freeze / Design Completion Gate

## 1. Purpose

本書は、AI Liver ゆら V2について、**実装前に詳細設計が十分に確定している領域と、追加設計が必要な領域を一元管理する正本**である。

2026-08-23以降、V2は本書とIssue #445のDesign Completion GateがPASSするまで新規production implementationを開始しない。

高レベルArchitectureやIssue本文が存在することだけを「設計完了」とみなさない。実装担当が重要な責務・型・lifecycle・failure・concurrencyを推測しなくてよい状態を詳細設計完了とする。

## 2. Design completeness levels

- **A — DETAILED_CANONICAL**: trunkまたは#445 architecture-only lineage上に詳細canonicalが存在。final Gateで同一設計世代としてtrunkへ統合する。
- **B — ACTIVE_LINEAGE_DETAILED**: 詳細設計は別active lineageにあり、#445 Authorityへexact回収が必要。
- **C — DETAIL_REQUIRED**: 上位Architecture/Issueだけでは実装時の推測が残るため専用詳細contractが必要。
- **D — INTEGRATION_DETAIL_REQUIRED**: 結合Acceptanceはあるがorchestration/identity/tracing/degradation/test topology等の専用詳細contractが必要。

## 3. Foundation / common Core

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Foundation typed contracts | #321 | A | `foundation_contracts.md`系を最終横断監査 |
| Runtime Kernel | #322 | A | `runtime_kernel_contracts.md` |
| Variable LLM Role | #323 | A | `llm_role_contracts.md` |
| Runtime lifecycle | #350 | A | `runtime_lifecycle_contracts.md` |
| Character Definition | #354/#442 | A | Character Bible + production YAML |
| Character Projection | #355 | A | `character_projection_contracts.md` / psychological projection |

## 4. Brain

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Input Gateway | #349 | A | `input_gateway_contracts.md` |
| Input Meaning | #326 | A | `input_meaning_contracts.md` |
| Appraisal / Internal State | #327 | A | `appraisal_internal_state_contracts.md` + Executive facts境界 |
| Executive | #328 | A | `executive_authority_contracts.md` |
| Goal / Commitment | #366 | A | `goal_commitment_state_contracts.md` |
| Goal Planning | #361 | A | `goal_planning_contracts.md`を最終再監査 |
| Activity / Actual Fact | #329 | A | `activity_execution_contracts.md` |
| Attention / Turn / Autonomy | #333 | A | `attention_turn_contracts.md` + source-owner lifecycle |
| Speech Semantics | #362 | A | `speech_semantics_contracts.md` |
| Character Language | #330 | A | 4 supplementsをPR #423 reviewed HEADからexact回収済み |
| Semantic Verification | #363 | A | 6 supplementsをPR #428 reviewed HEADからexact回収済み |
| Speech Performance | #331 | A | `speech_performance_contracts.md` |
| Speech Runtime / Presentation | #348 | A | `speech_runtime_presentation_contracts.md` + pipeline architecture |
| Memory Store / Retrieval | #332 | A | `memory_store_retrieval_contracts.md`をPR #444 design HEADからexact回収済み |
| Reflection | #364 | A | `memory_reflection_contracts.md` |
| Brain Integration | #334 | D | `brain_integration_contracts.md`をD7で新規作成 |

### Brain cross-audit pending

- Meaning / Appraisal / State / Memory / Goal / Attention / ExecutiveのAuthority重複なし。
- Memory過去値をcurrent Stateへ直接復元しない。
- Character/Verifier/PerformanceがWhat-to-sayを変更しない。
- Speech playback中も次のcognition/preparationを進められる。
- background Reflectionでforeground interactionをstarveさせない。

## 5. D2 Speech design — DONE

Completed:
- [x] #330 Character Language 4 supplements exact reconciliation
- [x] #363 Semantic Verification 6 supplements exact reconciliation
- [x] #331 `speech_performance_contracts.md`
- [x] #348 `speech_runtime_presentation_contracts.md`
- [x] #358 `tts_provider_contracts.md`
- [x] Architecture Index updated

Resulting authority/data topology:

```text
#362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├─ #363 Semantic Verification
   └─ #331 SpeechPerformancePlan
             ↓
        #358 TTS preparation
   ↓ readiness convergence
#348 live revalidation / Presentation commit
→ Presentation Adapter
→ trusted Presentation report
→ #329 Actual Execution Fact normalization
→ committed/started timing only → #340 viseme
```

This is not a fixed serial await chain.

## 6. D3 Memory design — DONE

Completed:
- [x] #332 `memory_store_retrieval_contracts.md` exact reconciliation from design-only PR #444
- [x] #364 `memory_reflection_contracts.md`
- [x] #359 `persistence_repository_contracts.md`
- [x] Architecture Index updated

Resulting topology:

```text
trusted historical evidence
→ #364 bounded Reflection
   ├─ deterministic exact capture
   └─ proposal LLM → support observer → closed acceptance
→ ValidatedMemoryCandidate
→ #332 deterministic reconciliation
   ├─ store / duplicate / provenance merge
   ├─ supersede
   └─ contradiction link
→ canonical Memory / bounded MemoryEvidenceView
→ #359 durable Memory repository

#366 GoalCommitmentSnapshot
→ #359 asynchronous restart-safe snapshot persistence
→ owner-validated rehydration candidate on next runtime
```

Key invariants:
- LLM proposal never writes Memory directly.
- prepared speech / planned Activity are not actual-history evidence.
- old Memory never directly restores current Emotion/Relationship/Goal/Execution state.
- vector similarity is retrieval evidence, not merge/supersede authority.
- DB schema is not Domain authority.
- only owner-declared restart-safe snapshots can be restored as current state.
- #366 commit lock contains no DB await; durability truth is separately observable.

## 7. D4 Body design — DONE

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Canonical Body Model / State | #336 | A | PR #411 merged; `body_architecture.md` detailed D01/D02 contract is current authority |
| Body Expression | #337 | A | `body_expression_contracts.md` |
| Body Motion Planning | #338 | A | `body_motion_planning_contracts.md` exact-recovered from PR #422 current design blob |
| Solver / IK / Kinematics / Controller | #339 | A | `body_solver_controller_contracts.md` |
| Realtime Layers | #340 | A | `body_realtime_layers_contracts.md` |
| Body Integration | #341 | A | `body_integration_contracts.md` |

Completed:
- [x] #336 current trunk authority verified
- [x] #337 expression contract reused
- [x] #338 active-lineage design exact reconciliation
- [x] #339 physical solver/controller contract
- [x] #340 realtime overlay contract
- [x] #341 integration contract
- [x] Architecture Index updated

Resulting topology:

```text
Committed Executive BODY intent
→ #338 BodyMotionPlan
→ #339 deterministic physical solve / current trajectory

#327/#333/#355 → #337 BodyExpressionContext ─┐
#333 Focus / low-level timing → #340 overlays ├→ #339 final composition
#348+#358 actual speech timing → #340 viseme ──┘
                                              ↓
                                   BodyState / BodyPoseFrame
                                              ↓
                                          #346 Avatar
```

Key invariants:
- #339 is the single physical BodyState writer.
- #340 emits overlays only and cannot bypass hard limits/balance.
- fixed Pose/Motion preset is not the canonical path.
- motion starts from current pose/velocity; no Home/Neutral snap-back.
- canonical 3D capability is not reduced to a 2D renderer's limits.
- Planner/Character/TTS/renderer latency does not stop realtime Body continuation.
- Character text is never Body motion semantic authority.
- anatomical left/right remains canonical; mirroring is Adapter responsibility.
- Prepared speech/speculative TTS does not drive viseme; actual Presentation timing does.
- BODY intent/plan is not Actual Execution Fact; physical observation is required.

## 8. Plugin

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Manifest / Registry / Capability | #343 | A | `plugin_registry_contracts.md` + permission principal contracts |
| Zero/One Plugin Integration | #344 | D | `plugin_integration_contracts.md`をD5で作成 |

## 9. Infrastructure

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| LLM Provider | #357 | A | `llm_provider_adapter_contracts.md` |
| LLM operational diagnostics | #437 | A/B audit | existing evidenceを#357とD5で整合監査 |
| TTS Provider | #358 | A | `tts_provider_contracts.md` |
| Persistence | #359 | A | `persistence_repository_contracts.md` |

Infrastructure invariant:
- provider SDK型/HTTP object/secretをCore Domainへ露出しない。
- timeout/cancel/errorをtyped failureへ変換。
- Provider unavailableでDomain semantic contractを変更しない。
- TTS/DB待ちでunrelated laneをblockしない。

## 10. Subsystems

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Avatar Presentation | #346 | C | `avatar_presentation_contracts.md` |
| Streaming | #347 | B/C audit | #394/#396を統合し詳細contractを一本化 |
| GUI/Admin | #351 | C | `gui_admin_contracts.md` |
| Validation Labs | #352 | C | `validation_lab_contracts.md` |
| Development Tooling | #353 | C | `development_tooling_contracts.md` |
| Game Skill Runtime | #365 | C | `game_skill_runtime_contracts.md` |

## 11. Integration / System

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Brain Integration | #334 | D | `brain_integration_contracts.md` |
| Body Integration | #341 | A | `body_integration_contracts.md` completed in D4 |
| Plugin Integration | #344 | D | `plugin_integration_contracts.md` |
| System Integration | #360 | D | `system_integration_contracts.md` |

Integration design must define composition topology, startup/degraded topology, identity/revision/cancellation propagation, trace schema, fake-provider test topology, system acceptance and defect ownership without reimplementing Work logic.

## 12. Design work sequence

```text
D1 Existing detailed-design audit                    [DONE]
↓
D2 Speech end-to-end design                          [DONE]
↓
D3 Memory design                                     [DONE]
↓
D4 Body design                                       [DONE]
↓
D5 Plugin / Infrastructure boundary design           [NEXT]
   #343 audit → #344 detailed integration + #357/#437 cross-provider audit
↓
D6 Subsystems
↓
D7 Remaining Integration
↓
D8 Cross-design authority / DTO / lifecycle / failure / concurrency audit
↓
D9 User Design Completion Gate
↓ PASS only
Implementation planning / Codex coding
```

## 13. Active implementation lineage treatment during Freeze

Existing product implementation PRs remain preserved and receive no new product code.

Current preserved lineages include:
- #330 / PR #423
- #363 / PR #428
- #338 / PR #422
- #434 / PR #435 validation-only

#332 / PR #444 is design-only historical lineage; its design has now been recovered into #445. It is not automatically the future implementation starting point. After D9 PASS, implementation lineage is resolved from live trunk under Resume Gate.

## 14. Gate

Current status:
- [x] D1 detailed-design audit
- [x] D2 Speech
- [x] D3 Memory
- [x] D4 Body
- [ ] D5 Plugin/Infrastructure
- [ ] D6 Subsystems
- [ ] D7 Remaining Integrations
- [ ] D8 cross-design audit PASS
- [ ] D9 User Design Completion confirmation

Implementation Freeze remains active through D9.

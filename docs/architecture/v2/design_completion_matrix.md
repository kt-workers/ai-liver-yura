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

## 5. D2 Speech design — DONE

Completed:
- [x] #330 Character Language 4 supplements exact reconciliation
- [x] #363 Semantic Verification 6 supplements exact reconciliation
- [x] #331 `speech_performance_contracts.md`
- [x] #348 `speech_runtime_presentation_contracts.md`
- [x] #358 `tts_provider_contracts.md`

Topology:

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

Key invariant: responsibility graph is not a fixed serial await chain.

## 6. D3 Memory design — DONE

Completed:
- [x] #332 `memory_store_retrieval_contracts.md` exact reconciliation from design-only PR #444
- [x] #364 `memory_reflection_contracts.md`
- [x] #359 `persistence_repository_contracts.md`

Topology:

```text
trusted historical evidence
→ #364 bounded Reflection
   ├─ deterministic exact capture
   └─ proposal LLM → support observer → closed acceptance
→ ValidatedMemoryCandidate
→ #332 deterministic reconciliation
→ canonical Memory / bounded MemoryEvidenceView
→ #359 durable Memory repository

#366 GoalCommitmentSnapshot
→ #359 asynchronous restart-safe persistence
→ owner-validated rehydration candidate
```

Key invariants:
- LLM proposal never writes Memory directly.
- prepared speech / planned Activity are not actual-history evidence.
- old Memory never directly restores current Emotion/Relationship/Goal/Execution state.
- vector similarity is retrieval evidence, not merge/supersede authority.
- only owner-declared restart-safe snapshots can be restored as current state.

## 7. D4 Body design — DONE

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Canonical Body Model / State | #336 | A | `body_architecture.md` D01/D02; PR #411 merged |
| Body Expression | #337 | A | `body_expression_contracts.md` |
| Body Motion Planning | #338 | A | `body_motion_planning_contracts.md` exact-recovered from PR #422 |
| Solver / IK / Kinematics / Controller | #339 | A | `body_solver_controller_contracts.md` |
| Realtime Layers | #340 | A | `body_realtime_layers_contracts.md` |
| Body Integration | #341 | A | `body_integration_contracts.md` |

Topology:

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
- #339 single physical BodyState writer.
- #340 overlay only; hard limits/balanceを迂回しない。
- current pose/velocity continuity; no Home reset.
- 3D Canonical capabilityをrenderer都合で縮退しない。
- Planner/Character/TTS/renderer latencyでBody realtime停止なし。
- Character textはBody motion Authorityではない。

## 8. D5 Plugin / Infrastructure design — DONE

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Plugin Registry / Permission | #343 | A | `plugin_registry_contracts.md` + permission principal supplement |
| Plugin Integration | #344 | A | `plugin_integration_contracts.md` |
| LLM Provider | #357 | A | `llm_provider_adapter_contracts.md` |
| LLM operational diagnostics | #437 | A | `llm_provider_operational_diagnostics_contracts.md` |
| TTS Provider | #358 | A | `tts_provider_contracts.md` |
| Persistence | #359 | A | `persistence_repository_contracts.md` |

Key invariants:
- zero-plugin is valid Core state.
- Plugin adds capabilities only through public extension contract.
- Plugin execution/Actual Fact flows through #329.
- permission/health/lifecycle/generation races are fenced.
- Provider/Adapter != Plugin; Subsystem != Registry-owned Plugin process.
- Provider HTTP/SDK cause stays Infrastructure diagnostic, not Domain semantic detail.
- 429 is not uniformly retryable; quota/non-transient and unknown classification fail closed against immediate retry.
- secrets/raw provider response/exception remain outside Domain/GUI/Export.

## 9. D6 Subsystem design — DONE

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Avatar Presentation | #346 | A | `avatar_presentation_contracts.md` |
| Streaming | #347 | A | `streaming_subsystem_contracts.md`, reconciles #394/#396 |
| GUI/Admin | #351 | A | `gui_admin_contracts.md` |
| Validation Labs | #352 | A | `validation_lab_contracts.md` |
| Development Tooling | #353 | A | `development_tooling_contracts.md` |
| Game Skill Runtime | #365 | A | `game_skill_runtime_contracts.md` |

Subsystem invariants:
- public typed boundary only; no Core internal object ownership.
- Subsystem AI never takes Executive Goal Authority.
- open-ended raw NL semantic Authority remains #326.
- high-volume/realtime workload uses bounded aggregation/backpressure.
- Subsystem absence/failure does not stop Core.
- provider-specific SDK/credential/ID remains outside Core.
- observed external effect and requested/intended effect remain distinct.

Special reconciliations:
- Streaming uses Core Decision / Subsystem Execution / External Observation three-way boundary.
- Streaming provider observation and user report preserve distinct provenance.
- Validation fixtures are not production trigger rules.
- Human context-dependent rating receives source-grounded context; explanatory UI context is not silently fed into LLM.
- #434 formal Character Human quality remains deferred until actual speech Presentation chain exists.
- Game frame loop is independent from Executive/Character/TTS latency.
- Avatar projects canonical BodyPoseFrame only; renderer limitations do not shrink Body contract.

## 10. Integration / System

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Brain Integration | #334 | D | `brain_integration_contracts.md` — D7 |
| Body Integration | #341 | A | `body_integration_contracts.md` — completed D4 |
| Plugin Integration | #344 | A | `plugin_integration_contracts.md` — completed D5 |
| System Integration | #360 | D | `system_integration_contracts.md` — D7 |

Integration design must define composition topology, startup/degraded topology, identity/revision/cancellation propagation, trace schema, fake-provider test topology, system acceptance and defect ownership without reimplementing Work logic.

## 11. Design work sequence

```text
D1 Existing detailed-design audit                    [DONE]
↓
D2 Speech end-to-end design                          [DONE]
↓
D3 Memory design                                     [DONE]
↓
D4 Body design                                       [DONE]
↓
D5 Plugin / Infrastructure boundary design           [DONE]
↓
D6 Subsystems                                        [DONE]
↓
D7 Remaining Integration                             [NEXT]
   #334 Brain Integration → #360 System Integration
↓
D8 Cross-design authority / DTO / lifecycle / failure / concurrency audit
↓
D9 User Design Completion Gate
↓ PASS only
Implementation planning / Codex coding
```

## 12. Active implementation lineage treatment during Freeze

Existing product implementation PRs remain preserved and receive no new product code.

Current preserved lineages include:
- #330 / PR #423
- #363 / PR #428
- #338 / PR #422
- #434 / PR #435 validation-only

#332 / PR #444 is design-only historical lineage; its design has been recovered into #445. It is not automatically the future implementation starting point. After D9 PASS, implementation lineage is resolved from live trunk under Resume Gate.

## 13. Gate

Current status:
- [x] D1 detailed-design audit
- [x] D2 Speech
- [x] D3 Memory
- [x] D4 Body
- [x] D5 Plugin/Infrastructure
- [x] D6 Subsystems
- [ ] D7 Remaining Integrations
- [ ] D8 cross-design audit PASS
- [ ] D9 User Design Completion confirmation

Implementation Freeze remains active through D9.

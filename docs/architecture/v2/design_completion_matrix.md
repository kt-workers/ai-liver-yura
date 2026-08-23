# V2 Detailed Design Completion Matrix

Owner: #445
Root: #317
Status: Architecture Freeze / Design Completion Gate

## 1. Purpose

本書は、AI Liver ゆら V2について、**実装前に詳細設計が十分に確定しているかを一元管理する正本**である。

2026-08-23以降、#445と本書がPASSし、D9でユーザーが完成設計を明示確認するまで新規production implementationを開始しない。

高レベルArchitectureやIssue本文だけでは設計完了とみなさない。実装担当が責務、型、lifecycle、failure、freshness、concurrencyを重要箇所で推測しなくてよい状態を詳細設計完了とする。

## 2. Status definition

- **A — DETAILED_CANONICAL**: trunkまたは#445 architecture-only lineageに、実装前提となる詳細正本が存在する。
- **POST_D9_RECONCILIATION**: 設計はAだが、既存implementation lineageを現行canonical generationへ照合する必要がある。設計未完成を意味しない。

D1〜D7終了後、B/C/D（別lineageのみ / detail不足 / integration detail不足）は解消済みである。

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

D8 correction:
- #350 shutdown sequence was aligned with #359 so bounded final snapshot/flush occurs before Persistence close.

---

## 4. Brain

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Input Gateway | #349 | A | `input_gateway_contracts.md` |
| Input Meaning | #326 | A | `input_meaning_contracts.md` |
| Appraisal / Internal State | #327 | A | `appraisal_internal_state_contracts.md` |
| Executive | #328 | A | `executive_authority_contracts.md` + appraisal facts boundary |
| Goal / Commitment | #366 | A | `goal_commitment_state_contracts.md` |
| Goal Planning | #361 | A | `goal_planning_contracts.md` |
| Activity / Actual Fact | #329 | A | `activity_execution_contracts.md` |
| Attention / Turn / Autonomy | #333 | A | `attention_turn_contracts.md` + source lifecycle supplements |
| Speech Semantics | #362 | A | `speech_semantics_contracts.md` |
| Character Language | #330 | A / POST_D9_RECONCILIATION | 4 Character Language supplements exact-recovered from PR #423 |
| Semantic Verification | #363 | A / POST_D9_RECONCILIATION | 6 Semantic Verification supplements exact-recovered from PR #428 |
| Speech Performance | #331 | A | `speech_performance_contracts.md` + `speech_expression_projection_contracts.md` |
| Speech Runtime / Presentation | #348 | A | `speech_runtime_presentation_contracts.md` + pipeline architecture |
| Memory Store / Retrieval | #332 | A | `memory_store_retrieval_contracts.md` exact-recovered from historical PR #444 |
| Reflection | #364 | A | `memory_reflection_contracts.md` |
| Brain Integration | #334 | A | `brain_integration_contracts.md` |

### Speech topology

```text
#362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├→ #363 Semantic Verification
   └→ #331 SpeechPerformancePlan
          ↓
       #358 TTS preparation
   ↓ readiness convergence
#348 live revalidation / Presentation commit
→ Presentation report
→ #329 Actual Execution Fact normalization
```

#331 projection policy explicitly separates:
- #355 static Character Voice Style
- #327 current dynamic State
- provider-independent normalized performance
- #358 provider-specific parameters

No hidden Emotion→Voice preset or free-text Character Voice interpretation is canonical.

### Memory topology

```text
trusted historical evidence
→ #364 proposal/support
→ ValidatedMemoryCandidate
→ #332 deterministic Store reconciliation/retrieval
→ #359 persistence
```

Memory remains historical evidence, not current Emotion/Goal/Relationship Authority.

---

## 5. Body

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Canonical Body Model / State | #336 | A | `body_architecture.md` D01/D02; PR #411 merged |
| Body Expression | #337 | A | `body_expression_contracts.md` |
| Body Motion Planning | #338 | A / POST_D9_RECONCILIATION | `body_motion_planning_contracts.md` exact-recovered from PR #422 |
| Solver / Controller | #339 | A | `body_solver_controller_contracts.md` |
| Realtime Layers | #340 | A | `body_realtime_layers_contracts.md` |
| Body Integration | #341 | A | `body_integration_contracts.md` |

Topology:

```text
Executive BODY intent → #338 plan → #339 physical trajectory
#327/#333/#355 → #337 expression ─┐
#333 gaze + #358 timing → #340 ──┼→ #339 final composition
                                  ↓
                         BodyState / BodyPoseFrame
                                  ↓
                              #346 Avatar
```

D8 dependency correction:
- #340 directly depends on #333/#336/#337/#358.
- #339 is #340 overlay consumer/Adjacent target rather than #340 Unit prerequisite.
- #341 owns #339/#340 integration.

Body invariants:
- #339 is sole physical BodyState writer.
- #340 emits overlays only.
- no fixed Home/Neutral reset.
- no finite Pose/Motion preset canonical path.
- canonical 3D capability is not reduced to renderer limits.
- Body realtime does not wait for LLM/TTS/renderer.

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

Invariants:
- Plugin 0 is valid.
- Plugin adds Capability, not Core Authority.
- Plugin Actual Fact flows through #329.
- Provider/Adapter != Plugin.
- Subsystem != Plugin by optionality alone.
- raw HTTP/SDK errors remain safe Infrastructure diagnostics.
- Persistence is storage authority only; Domain owner defines rehydration semantics.

---

## 7. Subsystems

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Avatar Presentation | #346 | A | `avatar_presentation_contracts.md` |
| Streaming | #347 | A | `streaming_subsystem_contracts.md`, includes #394/#396 reconciliation |
| GUI/Admin | #351 | A | `gui_admin_contracts.md` |
| Validation Labs | #352 | A | `validation_lab_contracts.md` |
| Development Tooling | #353 | A | `development_tooling_contracts.md` |
| Game Skill Runtime | #365 | A | `game_skill_runtime_contracts.md` |
| Speech Character Human Gate | #434 | A design / implementation HOLD | `validation_lab_contracts.md` + Speech canonical set |

D8 corrections:
- #346 responsibility/title now reflects BodyPoseFrame projection only; Speech timing is interpreted upstream by #340.
- #365 no longer depends on #344 Plugin Integration; it is a dedicated Skill Runtime.
- #434 formal Human quality is deferred until actual #331/#348/#358 Speech Presentation path exists.

Subsystem invariants:
- public typed boundaries only.
- open-ended NL Authority remains #326.
- Skill AI does not own Executive Goal.
- high-volume/realtime work is bounded/aggregated.
- external requested effect != observed/applied effect.
- Subsystem absence does not destroy Core identity.

---

## 8. Integration / System

| Area | Issue | Status | Canonical |
|---|---:|---|---|
| Brain Integration | #334 | A | `brain_integration_contracts.md` |
| Body Integration | #341 | A | `body_integration_contracts.md` |
| Plugin Integration | #344 | A | `plugin_integration_contracts.md` |
| System Integration | #360 | A | `system_integration_contracts.md` |

System stages:

```text
S1 Foundation / Runtime
→ S2 Brain
→ S3 Speech / TTS / Presentation
→ S4 Body / Avatar
→ S5 Memory / Persistence
→ S6 Plugin zero/one
→ S7 GUI / Validation Labs
→ S8 Streaming / Game Skill
→ S9 Lifecycle / restart / shutdown
```

This is a verification staging order, not a global runtime serial chain.

---

## 9. D1–D7 status

- [x] D1 Existing detailed-design audit
- [x] D2 Speech end-to-end design
- [x] D3 Memory design
- [x] D4 Body design
- [x] D5 Plugin / Infrastructure design
- [x] D6 Subsystem design
- [x] D7 Brain / Body / Plugin / System Integration design

No planned V2 product Work/Integration remains in B/C/D detail status.

---

## 10. D8 Cross-design audit

Canonical: `design_cross_audit_report.md`

Resolved findings include:
- #350/#359 shutdown ordering conflict
- #331 implicit Speech Expression projection gap
- #340 dependency ambiguity/cycle risk
- #365 Plugin dependency misclassification
- #346 direct Speech timing responsibility ambiguity
- #434 too-early text-only Human Gate
- #332 stale Codex implementation instruction
- stale #330/#363/#338 implementation-state Issue text
- Root #317 pre-#445 unfreeze rule
- PR #435 scope reclassification
- PR #446 stale progress metadata

Remaining D8 checks:
- final open-V2 dependency/classification scan
- final active implementation lineage vs canonical-generation audit
- exact final PR #446 docs-only diff/CI/review gate

---

## 11. Preserved implementation lineages during Freeze

Preserved, not automatically merge-ready:
- #330 / PR #423 / head `827eb66797e8ab1c38990bf5f0228eeae1e6e223`
- #363 / PR #428 / head `a08d88373b9f294b547e98a06bd99b7dd5c3e0d3`
- #338 / PR #422 / head `e3376f07d1d88c0dafcb4f4b384cc3887e8b40fa`
- historical #434 diagnostic PR #435 / head `30291dfdff53f68d59472565772b85d6a58e6799`

Historical design-only #332 PR #444 is not the future implementation starting point.

After D9 PASS, every Work gets a new GitHub-live Resume Gate before implementation/reconciliation.

---

## 12. Gate

Current status:
- [x] D1
- [x] D2
- [x] D3
- [x] D4
- [x] D5
- [x] D6
- [x] D7
- [ ] D8 final audit verification PASS
- [ ] D9 explicit User Design Completion confirmation

Implementation Freeze remains active through D9.

D9 PASS is required before implementation planning / Codex coding begins.
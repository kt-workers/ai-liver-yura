# V2 Detailed Design Completion Matrix

Owner: #445
Root: #317
Status: Architecture Freeze / Design Completion Gate

## 1. Purpose

本書は、AI Liver ゆら V2について、**実装前に詳細設計が十分に確定している領域と、追加設計が必要な領域を一元管理する正本**である。

2026-08-23以降、V2は本書とIssue #445のDesign Completion GateがPASSするまで新規production implementationを開始しない。

高レベルArchitectureやIssue本文が存在することだけを「設計完了」とみなさない。実装担当が重要な責務・型・lifecycle・failure・concurrencyを推測しなくてよい状態を詳細設計完了とする。

---

## 2. Design completeness levels

### A — DETAILED_CANONICAL

現行V2 trunk、または#445のarchitecture-only Design Completion lineage上に、実装に必要な主要境界を定めた詳細canonical supplementが存在する。

#445 final Gateでは全A文書を同一設計世代としてtrunkへ統合してからImplementation Freezeを解除する。

### B — ACTIVE_LINEAGE_DETAILED

詳細設計は存在するが、#445設計Authorityへまだ回収されていないactive design/implementation lineage上にある。

内容をレビュー済みblobから回収し、Authorityを一本化する必要がある。

### C — DETAIL_REQUIRED

Issue本文または上位Architectureには責務があるが、typed contract / lifecycle / failure / freshness / adjacent boundary等が実装前提として不足している。

専用canonical supplementを作成する。

### D — INTEGRATION_DETAIL_REQUIRED

結合シナリオとAcceptanceは定義されているが、integration orchestration / identity / tracing / degradation / start-stop / test topologyの詳細が不足している。

Integration専用canonical supplementを作成する。

---

## 3. Foundation / common Core

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Foundation typed contracts | #321 | A | `foundation_contracts.md`系を現行System/Concurrencyと再監査 |
| Runtime Kernel | #322 | A | `runtime_kernel_contracts.md` |
| Variable LLM Role | #323 | A | `llm_role_contracts.md` |
| Runtime lifecycle | #350 | A | `runtime_lifecycle_contracts.md` |
| Character Definition | #354/#442 | A | Character Bible + production YAML |
| Character Projection | #355 | A | `character_projection_contracts.md` / psychological projection |

Common invariant:
- Runtime/FoundationはDomain判断を所有しない。
- Role separationを固定serial call graphへ変換しない。
- stale/cancelled/supersededをtypedに扱う。

---

## 4. Brain

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Input Gateway | #349 | A | `input_gateway_contracts.md` |
| Input Meaning | #326 | A | `input_meaning_contracts.md` |
| Appraisal / Internal State | #327 | A | `appraisal_internal_state_contracts.md` + Executive facts境界 |
| Executive | #328 | A | `executive_authority_contracts.md` |
| Goal / Commitment | #366 | A | `goal_commitment_state_contracts.md` |
| Goal Planning | #361 | A | `goal_planning_contracts.md`を再監査 |
| Activity / Actual Fact | #329 | A | `activity_execution_contracts.md` |
| Attention / Turn / Autonomy | #333 | A | `attention_turn_contracts.md` + source-owner lifecycle |
| Speech Semantics | #362 | A | `speech_semantics_contracts.md` |
| Character Language | #330 | A | 4 detailed supplementsをPR #423 reviewed HEADから#445へexact blob回収済み |
| Semantic Verification | #363 | A | 6 detailed supplementsをPR #428 reviewed HEADから#445へexact blob回収済み |
| Speech Performance | #331 | A | `speech_performance_contracts.md`新規作成済み |
| Speech Runtime / Presentation | #348 | A | `speech_runtime_presentation_contracts.md`新規作成済み + pipeline architecture |
| Memory Store / Retrieval | #332 | B | `memory_store_retrieval_contracts.md`はdesign-only #444に存在。D3で#445へexact回収 |
| Reflection | #364 | C | `memory_reflection_contracts.md`を新規作成 |
| Brain Integration | #334 | D | `brain_integration_contracts.md`を新規作成 |

Brain横断で最終監査する事項:
- Meaning / Appraisal / State / Memory / Goal / Attention / ExecutiveのAuthority重複なし。
- Memory過去値をcurrent Stateへ直接復元しない。
- Character/Verifier/PerformanceがWhat-to-sayを変更しない。
- Speech playback中も次のcognition/preparationを進められる。
- background Reflectionでforeground interactionをstarveさせない。

### D2 Speech design status

D2新規詳細設計:
- [x] #331 `speech_performance_contracts.md`
- [x] #348 `speech_runtime_presentation_contracts.md`
- [x] #358 `tts_provider_contracts.md`

D2 active-lineage canonical reconciliation:
- [x] #330 Character Language 4 supplements copied exactly from reviewed `827eb667...`
- [x] #363 Semantic Verification 6 supplements copied exactly from reviewed `a08d8837...`
- [x] Architecture Index updated

D2で確定した主要flow:

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

これは固定serial await列ではない。

---

## 5. Body

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Canonical Body Model / State | #336 | A/B audit | current Body detailed contractsとtrunk/active lineageを照合しAuthorityを一本化 |
| Body Expression | #337 | A | `body_expression_contracts.md` |
| Body Motion Planning | #338 | B | `body_motion_planning_contracts.md`がactive #338 lineageに存在。D4でexact回収 |
| Solver / IK / Kinematics / Controller | #339 | C | `body_solver_controller_contracts.md`を新規作成 |
| Realtime Layers | #340 | C | `body_realtime_layers_contracts.md`を新規作成 |
| Body Integration | #341 | D | `body_integration_contracts.md`を新規作成 |

Body横断invariant:
- fixed Pose/Motion presetを正規経路にしない。
- current poseから連続運動する。
- 3D canonical能力を2D/Live2D制約で縮退させない。
- Body realtimeをLLM/TTS/Character待ちで停止しない。
- Character textをBody motion Authorityにしない。
- anatomical left/rightをCanonicalとしmirrorはAdapter責務。

---

## 6. Plugin

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Manifest / Registry / Capability | #343 | A | `plugin_registry_contracts.md` + permission principal contracts |
| Zero/One Plugin Integration | #344 | D | `plugin_integration_contracts.md`を新規作成 |

Plugin横断invariant:
- PluginはCore-native State/Authorityを所有しない。
- Provider/AdapterをPluginと呼ばない。
- Plugin 0件でもCore基本責務が成立する。
- external effect前後のstale境界をActual Factと混同しない。

---

## 7. Infrastructure

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| LLM Provider | #357 | A | `llm_provider_adapter_contracts.md` |
| LLM operational diagnostics | #437 | A/B audit | existing design/implementation evidenceを#357 contractと整合監査 |
| TTS Provider | #358 | A | `tts_provider_contracts.md`新規作成済み |
| Persistence | #359 | C | `persistence_repository_contracts.md`を新規作成 |

Infrastructure横断invariant:
- provider固有SDK型/HTTP object/secretをCore Domainへ露出しない。
- timeout/cancel/errorをtyped failureへ変換する。
- Provider unavailableでDomain semantic contractを変更しない。
- TTS/DB待ちでBrain/Body等のunrelated laneをblockしない。

---

## 8. Subsystems

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Avatar Presentation | #346 | C | `avatar_presentation_contracts.md`を新規作成 |
| Streaming | #347 | B/C audit | #394/#396のboundary/semantic reconciliationを統合し詳細contractを一本化 |
| GUI/Admin | #351 | C | `gui_admin_contracts.md`を新規作成 |
| Validation Labs | #352 | C | `validation_lab_contracts.md`を新規作成 |
| Development Tooling | #353 | C | `development_tooling_contracts.md`を新規作成 |
| Game Skill Runtime | #365 | C | `game_skill_runtime_contracts.md`を新規作成 |

Subsystem横断invariant:
- Core public contract / typed Event / Read Model / Resultだけを利用する。
- SubsystemがExecutive Goal Authorityを持たない。
- raw external NLをSubsystemが独自keyword/regexで意味判断しない。
- high-volume/realtime workloadをCore decision laneへ無制限同期投入しない。
- Subsystem unavailableでもCoreはdegraded継続できる。

---

## 9. Integration / System

| Area | Issue | Status | Canonical / action |
|---|---:|---|---|
| Brain Integration | #334 | D | `brain_integration_contracts.md` |
| Body Integration | #341 | D | `body_integration_contracts.md` |
| Plugin Integration | #344 | D | `plugin_integration_contracts.md` |
| System Integration | #360 | D | `system_integration_contracts.md` |

Integration設計は個別Workのlogicを再実装しない。

確定対象:
- composition topology
- startup/degraded topology
- identity/revision propagation
- cancellation/supersede propagation
- trace/timeline schema
- fake-provider test topology
- system acceptance scenarios
- independent defectのownerへの戻し方

---

## 10. Design work sequence under #445

```text
D1 Existing detailed-design audit                    [DONE]
↓
D2 Speech end-to-end design                          [DONE]
   #330/#363 reconcile + #331 + #348 + #358
↓
D3 Memory design                                     [NEXT]
   #332 reconcile → #364 → #359
↓
D4 Body design
   #336/#337/#338 reconcile → #339 → #340 → #341
↓
D5 Plugin / Infrastructure boundary design
   #343 reconcile → #344 + cross-provider audit
↓
D6 Subsystems
   #346 / #347 / #351 / #352 / #353 / #365
↓
D7 Integration
   #334 / #341 / #344 / #360
↓
D8 Cross-design authority / DTO / lifecycle / failure / concurrency audit
↓
D9 User Design Completion Gate
↓ PASS only
Implementation planning / Codex coding
```

---

## 11. Active implementation lineage treatment during Freeze

既に存在するproduct implementation PRは削除・作り直ししない。

- current HEAD / base / ownershipを保持する。
- 新機能コードを追加しない。
- canonicalが更新されたら、Implementation Freeze解除前に設計世代との整合だけ監査する。
- implementation branch上だけに存在する重要な設計文書は、最終Design Gateまでに#445 Authorityへ回収する。

現在保全対象:
- #330 / PR #423
- #363 / PR #428
- #434 / PR #435（validation-only）

#332 / PR #444はdesign-only成果をD3で#445設計lineageへ回収し、product implementation開始点としては使用しない。Freeze解除後にlive trunkからimplementation lineageを改めて確定する。

---

## 12. Gate

Current status:
- [x] D1 主要V2 Work/IntegrationをA/B/C/Dへ分類
- [x] D1 Active lineage上だけにある詳細設計を識別
- [x] D1 新規詳細設計が必要な領域を識別
- [x] D1 設計順序を確定
- [x] D2 Speech新規詳細契約 #331/#348/#358
- [x] D2 #330/#363 active-lineage canonical Authority回収
- [x] D2 Speech関連Architecture Index更新
- [ ] D3 Memory
- [ ] D4 Body
- [ ] D5 Plugin/Infrastructure
- [ ] D6 Subsystems
- [ ] D7 Integrations
- [ ] D8 全体cross-design audit PASS
- [ ] D9 User Design Completion確認

Implementation Freezeは最後のUser Design Completion確認まで維持する。

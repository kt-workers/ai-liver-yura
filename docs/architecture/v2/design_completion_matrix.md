# V2 詳細設計完了マトリクス

Owner: #445
Root: #317
Status: **D10 PASS / 製造起点統合待ち**

## 1. 目的

AI Liver ゆら V2について、実装担当が重要な意味・Authority・数値規則・失敗境界・鮮度・並行性・依存順を追加発明せず製造できる詳細設計が揃っていることを一元管理する。

D1〜D9は2026-08-23に一度PASSした。2026-08-30の#339製造再開時に実装決定可能性の不足を検出したためD10を追加し、2026-08-31に全planned Work / Integrationの再監査とblocking design gap補修を完了した。

D10後は設計不足を理由とするproduction freezeを解除する。ただし、散在したIssue / PR / branchをcurrent canonicalへ照合して`rebuild/v2-foundation`へ収束させるまで、新しい無関係な製造lineageを追加しない。

## 2. 状態定義

- **A / D10_PASS**: 詳細正本が存在し、D10実装決定可能性監査PASS。
- **A / POST_D9_RECONCILIATION / D10_PASS**: 設計PASS。既存未マージimplementation lineageをcurrent canonical generationへ照合する必要がある。
- **A design / D10_PASS / HOLD**: 設計PASSだが、Human Verificationや下流production path等の実施前提が未成立。

設計PASSは実装完了を意味しない。Issue completionはPost-D10全Issue監査でactual evidenceから再判定する。

## 3. Foundation / Character

| Area | Issue | Design status | Canonical |
|---|---:|---|---|
| Foundation typed contracts | #321 | A / D10_PASS | `foundation_contracts.md` |
| Runtime Kernel | #322 | A / D10_PASS | `runtime_kernel_contracts.md` + `runtime_operational_numeric_contracts.md` |
| Variable LLM Role | #323 | A / D10_PASS | `llm_role_contracts.md` + `llm_execution_numeric_contracts.md` |
| Runtime lifecycle | #350 | A / D10_PASS | `runtime_lifecycle_contracts.md` + `runtime_operational_numeric_contracts.md` |
| Character Bible | #354 | A / D10_PASS | `docs/character/v2/yura_character_bible.md` |
| production Character Definition | #442 | A / D10_PASS | `character_definitions/v2/yura.yaml` |
| Character Projection | #355 | A / D10_PASS | `character_projection_contracts.md` / psychological projection |

## 4. Brain / Speech / Memory

| Area | Issue | Design status | Canonical |
|---|---:|---|---|
| Input Gateway | #349 | A / D10_PASS | `input_gateway_contracts.md` + `brain_operational_bounds_contracts.md` |
| Input Meaning | #326 | A / D10_PASS | `input_meaning_contracts.md` |
| Appraisal / Internal State | #327 | A / D10_PASS | `appraisal_internal_state_contracts.md` + `appraisal_decay_numeric_contracts.md` |
| Executive | #328 | A / D10_PASS | `executive_authority_contracts.md` + `brain_operational_bounds_contracts.md` |
| Goal / Commitment | #366 | A / D10_PASS | `goal_commitment_state_contracts.md` + `brain_operational_bounds_contracts.md` |
| Goal Planning | #361 | A / D10_PASS | `goal_planning_contracts.md` + `brain_operational_bounds_contracts.md` |
| Activity / Actual Fact | #329 | A / D10_PASS | `activity_execution_contracts.md` |
| Attention / Turn / Autonomy | #333 | A / D10_PASS | `attention_turn_contracts.md` + source lifecycle supplements |
| Speech Semantics | #362 | A / D10_PASS | `speech_semantics_contracts.md` + `brain_operational_bounds_contracts.md` |
| Character Language | #330 | A / POST_D9_RECONCILIATION / D10_PASS | Character Language 4 supplements + bounds |
| Semantic Verification | #363 | A / POST_D9_RECONCILIATION / D10_PASS | Semantic Verification supplements + bounds |
| Speech Performance | #331 | A / D10_PASS | `speech_performance_contracts.md` + projection contracts |
| Speech Runtime / Presentation | #348 | A / D10_PASS | `speech_runtime_presentation_contracts.md` + `speech_operational_numeric_contracts.md` |
| Memory Store / Retrieval | #332 | A / D10_PASS | `memory_store_retrieval_contracts.md` + `memory_operational_numeric_contracts.md` |
| Reflection | #364 | A / D10_PASS | `memory_reflection_contracts.md` + `memory_operational_numeric_contracts.md` |
| Brain Integration | #334 | A / D10_PASS | `brain_integration_contracts.md` |

共有multi-owner snapshot mechanicsは`snapshot_consistency_contracts.md`を正本とする。

Speech責務:

```text
#362 SpeechSemanticPlan
→ #330 CharacterUtterance
   ├→ #363 Semantic Verification
   └→ #331 SpeechPerformancePlan
          ↓
       #358 TTS preparation
   ↓ readiness convergence
#348 live revalidation / Presentation
→ trusted report → #329 Actual Fact normalization
```

Memory責務:

```text
trusted historical evidence
→ #364 proposal/support
→ ValidatedMemoryCandidate
→ #332 reconciliation/retrieval
→ #359 persistence
```

## 5. Body

| Area | Issue | Design status | Canonical |
|---|---:|---|---|
| Canonical Body Model / State | #336 | A / D10_PASS | `body_architecture.md` + `body_physical_numeric_contracts.md` |
| Body Expression | #337 | A / D10_PASS | `body_expression_contracts.md` + `body_expression_projection_policy.md` |
| Body Motion Planning | #338 | A / POST_D9_RECONCILIATION / D10_PASS | `body_motion_planning_contracts.md` + physical numeric contracts |
| Solver / Controller | #339 | A / D10_PASS | solver contracts + physical numeric + trajectory timing |
| Realtime Layers | #340 | A / D10_PASS | realtime contracts + `body_realtime_numeric_contracts.md` |
| Body Integration | #341 | A / D10_PASS | `body_integration_contracts.md` |

```text
Executive BODY intent → #338 Plan → #339 physical trajectory
#327/#333/#355 → #337 expression ─┐
#333 + #358 timing → #340 overlay ├→ #339 final composition
                                  ↓
                         BodyState / BodyPoseFrame
                                  ↓
                              #346 Avatar
```

D10で固定した主要事項:
- scalar DOFがphysical joint-coordinate Authority、quaternionはderived projection。
- trusted geometry resolver、model revision/fingerprint、dynamic limit、CoM/contact/end-effector frameを明示。
- extent→physical targetをclosed rulesで変換。
- solver tolerance/iteration/residual/completion policyをversioned data化。
- relative duration weight→実秒trajectoryをdeterministic time-scaling化。
- gaze/blink/breath/articulation/subtle motionのrate/frame boundを固定。
- Yura Body Style→normalized expression axisをversioned production policy化。

## 6. Plugin / Infrastructure

| Area | Issue | Design status | Canonical |
|---|---:|---|---|
| Plugin Registry / Permission | #343 | A / D10_PASS | registry + permission supplements |
| Plugin Integration | #344 | A / D10_PASS | `plugin_integration_contracts.md` + external surface numeric contracts |
| LLM Provider | #357 | A / D10_PASS | provider adapter + LLM execution numeric contracts |
| LLM operational diagnostics | #437 | A / D10_PASS | operational diagnostics contracts |
| TTS Provider | #358 | A / D10_PASS | `tts_provider_contracts.md` + speech operational numeric contracts |
| Persistence | #359 | A / D10_PASS | persistence contracts + external surface numeric contracts |

Plugin 0件Core成立、Plugin≠Provider、Subsystem≠Plugin、Actual Effectは#329を通す境界を維持する。

## 7. Subsystems

| Area | Issue | Design status | Canonical |
|---|---:|---|---|
| Avatar | #346 | A / D10_PASS | presentation + avatar binding numeric contracts |
| Streaming | #347 | A / D10_PASS | streaming + subsystem realtime numeric contracts |
| GUI/Admin | #351 | A / D10_PASS | GUI contracts + external surface numeric contracts |
| Validation Labs | #352 | A / D10_PASS | Validation contracts + external surface numeric contracts |
| Development Tooling | #353 | A / D10_PASS | Tooling contracts + external surface numeric contracts |
| Game Skill | #365 | A / D10_PASS | Game contracts + subsystem realtime numeric contracts |
| Speech Character Human Gate | #434 | A design / D10_PASS / HOLD | Validation + Speech canonical set |

#434は#331/#348/#358を含むactual Presentation path完成後にHuman Verificationする。historical text-only Labをfinal gateとしてmergeしない。

## 8. Integration / System

| Area | Issue | Design status | Canonical |
|---|---:|---|---|
| Brain Integration | #334 | A / D10_PASS | `brain_integration_contracts.md` |
| Body Integration | #341 | A / D10_PASS | `body_integration_contracts.md` |
| Plugin Integration | #344 | A / D10_PASS | `plugin_integration_contracts.md` |
| System Integration | #360 | A / D10_PASS | `system_integration_contracts.md` + external surface numeric contracts |

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

staging orderでありruntime serial chainではない。

## 9. 製造順Authority

current正本は`production_sequence_authority.md`。

元工程の大枠:

```text
100 #321 Foundation
110 #322 Runtime Kernel
120 #323 LLM Role
130 #320 Parent gate
140 #354 Character Bible
150 #355 Character Projection
160 #324 Parent gate
170 #357 LLM Provider
200〜380 Brain / Speech / Memory / Infrastructure / Brain Integration
400〜460 Body
500〜520 Plugin
530 Infrastructure Parent
600〜650 Subsystems
700 #360 System Integration
```

元工程後に発見されたmandatory workはowner Workへ回収するか、独立責務なら依存上の正しい位置へ挿入する。

## 10. Design Completion stages

- [x] D1 Existing detailed-design audit
- [x] D2 Speech end-to-end detailed design
- [x] D3 Memory detailed design
- [x] D4 Body detailed design
- [x] D5 Plugin / Infrastructure detailed design
- [x] D6 Subsystems detailed design
- [x] D7 Brain / Body / Plugin / System Integration design
- [x] D8 Cross-design content audit and corrections
- [x] D9 explicit User Design Completion confirmation — PASS 2026-08-23
- [x] **D10 Implementation Decidability / Plan Coverage / Completion-State design reconciliation — PASS 2026-08-31**

## 11. D10後の製造起点統合Gate

設計freezeはD10 PASSで解除する。ただし現在はbranch/Issue/PRの状態が散在しており、actual implementation completionがIssue stateと一致しない既知例がある。

このため新しい通常製造へ入る前に次を実施する。

```text
D10 architectureをrebuild/v2-foundationへmerge
→ Open/Closed全V2 Issueを工程先頭から監査
→ merged lineageはそのまま
→ unmerged completed lineageをcurrent canonicalへ照合してmerge
→ unmerged partial lineageをcurrent canonicalまで完成させてmerge
→ validation-only / historical / superseded lineageは有効知見回収だけ確認してmergeしない
→ current dependency/工程を確定
→ Project #7日程を刷新
→ earliest incomplete production Workから継続製造
```

旧V1/legacy branchは#317/#318方針どおりproduct codeをV2へ直接merge/cherry-pickしない。未回収要求が見つかった場合だけcurrent V2 ownerへ回収する。

最終的な製造起点は、上記収束を終えた`rebuild/v2-foundation`の単一HEADとする。

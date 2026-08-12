# AI Liver ゆら V2 Canonical System Architecture

Status: Draft / V2 Design Gate
Canonical branch: `rebuild/v2-foundation`
Root: #317
Base lineage: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`

## 1. 役割

AI Liver ゆら V2の最上位システム構造正本。

旧実装を継ぎ足さず、V1 Issue/PR/docs/Verificationから要求・failure knowledgeだけを回収し、最古mainから再構築する。

詳細:

- Brain: `brain_architecture.md`
- Cognitive / LLM: `cognitive_llm_architecture.md`
- Goal / Commitment: `goal_commitment_architecture.md`
- Concurrency: `concurrency_architecture.md`
- Speech: `speech_pipeline_architecture.md`
- Body: `body_architecture.md`
- Plugin: `plugin_architecture.md`
- Subsystem / Skill AI: `subsystem_architecture.md`
- Migration: `legacy_migration_matrix.md`
- Project sync: `project_sync_manifest.md`

---

## 2. 最終目標

**自由意志をもった「ゆら」という継続主体**を作る。

User Messageへの返信器ではない。

ゆらは持続する:

- Internal State
- Emotion / Desire / Drive / Motivation
- Values / Moral context
- Interest / Curiosity
- Relationship
- Memory
- current Goals / Commitments
- **Attention / Focus / Turn state**
- Current Activities
- Body State

を持ち、外界と自身の変化を受けながら行動を選択する。

代表活動:

- ユーザーとの会話
- YouTube等のライブ配信 / VTuber活動
- ユーザーとのゲーム対戦
- 配信中ゲーム実況・対戦
- 観察 / 探索 / 沈黙 / 休止
- 将来のActivity / Capability

ユーザー発言は重要Eventだが無条件命令ではない。

---

## 3. System Boundary

```text
AI Liver Yura
│
├─ Core
│  ├─ Brain
│  ├─ Body
│  └─ Plugin Architecture
│
├─ Infrastructure / Providers
│  ├─ LLM
│  ├─ TTS
│  ├─ Persistence
│  └─ Transport / Adapter
│
└─ Subsystems / Skill Runtimes
   ├─ Avatar
   ├─ Streaming
   ├─ Game Skill
   ├─ GUI/Admin
   ├─ Validation Labs
   └─ Development Tooling
```

---

## 4. Core Ownership

Coreは「ゆら自身」の正本責務を所有する。

Core membershipをruntime optionalityで決めない。

Core正本例:

- Brain cognition
- Internal State
- Executive Authority
- Goal / Commitment State #366
- Attention / Focus / Turn State #333
- Body / Body State
- Plugin extension contract

Avatar不在でもBodyはPluginにならない。
Persistence不在でもGoal/Memory Domain ownershipはInfrastructureへ移らない。

### Degradation

- Plugin 0件でもCore基本責務維持
- Avatar/Streaming/Game/GUI不在でもCore継続
- TTS unavailableでも可能なText/Silence/cognition継続
- Persistence unavailable時durabilityを偽らず安全縮退
- 1 LLM Role failureでunrelated lane停止なし
- external output切断でCore停止なし
- shutdown/cancellationは正常経路

---

## 5. Clean Architecture

```text
Domain / Contracts
        ↑
Application / Use Cases
        ↑
Ports
        ↑
Adapters / Providers / UI / External systems
```

DomainはOpenAI SDK、FastAPI、VOICEVOX、PostgreSQL、Live2D等の具体型を知らない。

Infrastructure ProviderはPluginではない。

---

## 6. Plugin Boundary

Pluginをoptional性だけで定義しない。

> **PluginはCore自身の構成要素ではなく、Core公開拡張契約から外部Capabilityを追加する機構。**

Core固有State/Authorityを所有しない。

`Plugin 0件でもCore基本責務維持`は別のSystem invariant。

---

## 7. Subsystem / Skill AI Boundary

Subsystemは独立lifecycle/process/resource ownershipを持てる。

専門AIは「選択済みActivityを実行する技能」であり、ゆらの意思そのものではない。

- Game Agent
- Streaming classifier/moderation/aggregation
- Vision / recognition

Skill AIはExecutive Goal Authorityを奪わない。

---

## 8. 認知因果モデル

```text
External / Internal Events
        ↓
Perception / Input Meaning
        ↓
Subjective Appraisal / salience
        ↓
Internal State
        ↓
Attention / Focus eligibility
        ↓
Executive Deliberation
        ↓
Goal / Commitment transition
        ↓
Persistent Goal / Commitment State
        ↓
Planning / Realization / Execution
   ├─ Goal / Activity Planning
   ├─ Speech
   ├─ Body
   ├─ Plugin Capability
   └─ Subsystem / Skill Runtime
        ↓
Actual Result / New Events
        ↓
Appraisal / Attention / Executive / Goal / Reflection / Memory
```

因果図であり固定blocking Pipelineではない。

---

## 9. Runtime Model

- Event-driven
- snapshot-based
- sparse activation
- concurrent lanes
- bounded queues
- priority / backpressure
- cancellation / stale / supersede
- source_context_revision
- goal_revision where relevant
- attention_revision where relevant

```text
                         ┌─ Input / Meaning
                         ├─ Appraisal / State
Typed Event Stream ──────┼─ Attention / Turn
                         ├─ Executive
                         ├─ Goal State / Planning
                         ├─ Speech Preparation
                         ├─ Speech Presentation
                         ├─ Body Realtime
                         ├─ Skill / Subsystem
                         └─ Reflection / Persistence
```

### Concurrency Invariant

- slow LLM中もunrelated lane継続
- Speech playback中next cognition/generation可能
- TTS待機中new input可能
- Goal/Focus mutationをCore global lockにしない
- Body realtimeはLLM/TTS/DB/Game AI待ちで停止しない
- Reflectionはforeground interactionをblockしない
- Game frame loopはExecutive LLM latency非依存
- Streaming burstでCore starvationなし
- background workがforeground interactionをstarveしない

---

## 10. LLM Design

旧4-role固定は撤回。

LLM個数をArchitecture invariantにしない。

初期Role候補:

- Input Meaning
- Subjective Appraisal（必要時）
- Executive Deliberation
- Goal / Activity Planning
- Speech Semantics
- Character Language
- Independent Semantic Verification
- Body Motion Planning
- Reflection

ただし:

> **conscious Goal / Action Authority = Executive #328 only**

Goal State #366、Attention #333、Internal State Reducer、Activity/Execution、Body physical/realtime等はtyped deterministic ownershipを基本とする。

### Logical Role != API Call

責務分離を直列Provider callへ変換しない。

- simple pathでRole省略/非LLM化
- complex caseだけ専用Role
- independent fan-out
- safe speculative preparation
- low-priority background defer/cancel

---

## 11. System Authority Map

| Authority | Owner |
|---|---|
| open-ended NL meaning | Input Meaning #326 |
| subjective appraisal / salience candidate | #327 |
| current Internal State | State Reducer #327 |
| conscious Goal / Action selection | Executive #328 |
| current Goal / Commitment | #366 |
| **current Attention / Focus / Turn scheduling** | **#333** |
| complex Goal planning | #361 |
| Activity lifecycle / Actual Fact | #329 |
| What to say | #362 |
| How to say | #330 |
| semantic observation | #363 |
| Speech performance/presentation | #331/#348 |
| current Body / physical continuity | #335〜#341 |
| Memory canonical store/retrieval | #332 |
| Memory Candidate generation | #364 |
| Game frame-level skill | #365, subordinate to Core Goal |

LLM自由文をState/Factへ直接代入しない。

---

## 12. Persistent Goal / Commitment — #366

```text
Executive chooses Goal
→ validated transition
→ Goal State
→ later Snapshot / Attention / Planner
```

必須:

- turn/context windowを跨ぐ
- Activity変更でsuspend/resume可能
- CommitmentをMemory/Speechと混同しない
- stale goal_revision plan非実行
- pending Goal/Commitmentがautonomous triggerになり得る

---

## 13. Attention / Focus / Turn — #333

Game、Streaming、Conversation、Reflection等が並行しても全EventをExecutiveへ同期投入しない。

```text
Game realtime             → Skill aggregation
Streaming burst           → aggregation
User direct speech        → high priority
Reflection                → background
         ↓
#333 Focus / Turn scheduling
         ↓ eligible trigger / AttentionFocusView
Executive
```

#333 owns:

- foreground focus
- secondary monitors
- turn / response obligation
- attention/source budgets
- interrupt thresholds
- fairness / anti-starvation

Appraisalはsalience候補、Executiveはdeliberate attention intent、#333はFocus State/schedulingを所有。

意味/Goal/Speech内容は決めない。

Body gazeはFocusの表現でありcognitive Authorityではない。

---

## 14. Speech Summary

```text
Executive SpeechIntent
→ SpeechSemanticPlan       # What
→ CharacterUtterance       # How
→ Semantic Observation
→ closed acceptance
→ Performance / Prepared candidate
→ Presentation
```

論理責務を固定直列LLM chainにしない。

- simple Semantics pathは専用LLM省略可
- Character後Verifier/Performance/safe TTS prep並列可
- required PASS前にexternal Presentation commitしない
- Speech A playback中にSpeech B generation可

---

## 15. Body Summary

- Canonical Skeleton / DOF / limits
- current pose / velocity
- Expression Projection
- Motion Planning（LLMは必要時）
- deterministic IK/FK/balance/trajectory
- Continuous Controller
- gaze/blink/breath/viseme/subtle realtime
- BodyPoseFrame

fixed presets/no Home reset/current-pose continuity。

Motion Planner遅延でもrealtime停止なし。

CharacterとBodyはExecutiveから兄弟fan-out。

---

## 16. Streaming / Game Summary

### Streaming #347

bounded comment ingress / aggregation / backpressure。Skill AIは分類等を担当可。reply/stream continuation/What-to-sayはCore Authority。

### Game #365

```text
Core Executive / Goal State
→ High-level Strategy
→ Game Skill Runtime
→ realtime agent
→ controller
→ salient Event / Result
→ Appraisal / Attention / Executive
```

実況台詞はGame Agentが直接発話しない。

---

## 17. Natural Language Policy

open-ended意味Authorityとしてfinite keyword/marker/regex/substring/startswith等を使わない。

protocol token / enum / exact technical ID / finite-domain vocabularyは例外。

解決不能はunresolved / clarification / fail-closed。

---

## 18. Execution Truth

Intent / Plan / Actual Factを分離する。

```text
requested → accepted → planned → started → observable/applied → completed
or rejected / unsupported / failed / cancelled / timed_out / superseded
```

```text
I want X        → internal/goal semantic
I decided X     → Executive / Goal transition
I am doing X    → Activity/Execution Fact
I did X         → completed Fact
I promised X    → Commitment State
I said promise  → Speech Presentation Fact
```

---

## 19. Module Development Gate

```text
Canonical Design
→ Work Issue
→ Unit Acceptance
→ implementation lineage / Draft PR
→ Unit PASS
→ Adjacent Contract PASS
→ Integration
→ User Verification if required
→ Done
```

1 Work Issue = 1 active implementation lineage。

---

## 20. Design Gate Status

- [x] System / Brain / Cognitive / Goal / Concurrency canonical
- [x] Speech / Body / Plugin / Subsystem canonical
- [x] Legacy requirements inventory / cognitive remapping
- [x] 4 LLM固定撤回 / Single Executive
- [x] non-sequential LLM/runtime
- [x] persistent Goal #366
- [x] Attention/Focus #333
- [x] Game/Streaming Skill AI boundary
- [x] Plugin structural definition
- [ ] Legacy Migration Matrixへ#366/#333 Attention最終追補
- [ ] subordinate canonical / Issue final cross-audit
- [ ] Projects v2 actual mutation #319（環境制約でBlocked）
- [ ] #317 Design Reconciliation Checkpoint
- [ ] **ユーザーによるV2 canonical architecture確認**

ユーザー確認前にproduct implementationをunfreezeしない。

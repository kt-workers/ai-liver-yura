# AI Liver ゆら V2 Canonical System Architecture

Status: Draft / V2 Design Gate
Canonical branch: `rebuild/v2-foundation`
Root management: #317
Base lineage: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`

## 1. この文書の役割

AI Liver ゆら V2の**最上位システム構造正本**。

旧実装を継ぎ足さず、V1 Issue / PR / docs / Verificationから要求・失敗知見・設計原則だけを回収して最古mainから再構築する。

詳細正本:

- Brain: `brain_architecture.md`
- Cognitive / LLM: `cognitive_llm_architecture.md`
- Persistent Goal / Commitment: `goal_commitment_architecture.md`
- Concurrency: `concurrency_architecture.md`
- Speech: `speech_pipeline_architecture.md`
- Body: `body_architecture.md`
- Plugin: `plugin_architecture.md`
- Subsystem / Skill AI: `subsystem_architecture.md`
- Legacy migration: `legacy_migration_matrix.md`
- Project sync: `project_sync_manifest.md`

---

## 2. 最終目標

作るものはユーザー入力への返信器ではない。

**自由意志をもった「ゆら」という継続主体**を作る。

ゆらは持続する:

- Internal State
- Emotion / Desire / Drive / Motivation
- Values / Moral context
- Interest / Curiosity
- Relationship
- Memory
- **current Goals / Commitments**
- Current Activities
- Body State

を持ち、外界と自身の変化を受けながら行動を選択する。

代表活動:

- ユーザーとの会話
- YouTube等のライブ配信 / VTuber活動
- ユーザーとのゲーム対戦
- ライブ配信中のゲーム実況・対戦
- 観察 / 探索 / 沈黙 / 休止
- 将来追加されるActivity / Capability

ユーザー発言は重要な社会的Eventだが、常に無条件命令として扱わない。

---

## 3. System Boundary

```text
AI Liver Yura System
│
├─ Core
│  ├─ Brain
│  ├─ Body
│  └─ Plugin Architecture
│
├─ Infrastructure / Providers
│  ├─ LLM Providers
│  ├─ TTS Providers
│  ├─ Persistence
│  └─ Transports / Adapters
│
└─ Subsystems / Skill Runtimes
   ├─ Avatar / Live2D / 3D presentation
   ├─ Streaming
   ├─ Game Skill Runtime
   ├─ GUI / Administration
   ├─ Validation Labs
   └─ Development Tooling
```

---

## 4. Core ownership

Coreは「ゆら自身」の正本責務を所有する。

Core membershipは「一時的に無くてもdegraded運転できるか」で決めない。

Core正本例:

- Brain cognition
- Internal State
- Executive Authority
- **Goal / Commitment State #366**
- Body / Body State
- Plugin extension contract

Avatarが無くてもBodyはPluginにならない。
Persistenceが無くてもGoal StateやMemoryのDomain ownershipがInfrastructureへ移るわけではない。

### Core degradation invariant

- Plugin 0件でもCore基本責務を維持
- Avatar不在でもBody State維持
- Streaming/Game/GUI不在でもCore維持
- TTS unavailableでも可能な認知 / Text / Silence処理継続
- Persistence unavailableでもdurabilityを偽らず安全縮退
- specific LLM Role failureでunrelated lane停止なし
- external output切断でCore停止なし
- graceful shutdown / cancellationを正常経路として扱う

---

## 5. Clean Architecture dependency

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

Infrastructure ProviderはCore Portの実装手段でありPluginではない。

---

## 6. Plugin boundary

Pluginをoptional性だけで定義しない。

> **Pluginは、BrainやBody等のCore自身の構成要素ではなく、Core公開拡張契約から外部Capabilityを追加する機構。**

PluginはCore固有State / Authorityを所有しない。

`Plugin 0件でもCore基本責務維持`はPlugin定義とは別のSystem invariant。

詳細: `plugin_architecture.md`。

---

## 7. Subsystem / Skill AI boundary

SubsystemはCoreとは別のlifecycle / process / resource ownershipを持てる。

専門AIは**選択済みActivityを実行する技能**であり、ゆらの意思そのものではない。

- Game Agent
- Streaming comment classifier / moderation / aggregation
- Vision / recognition skill

Skill AIはExecutive Goal Authorityを奪わない。
Game frame-level actionをCore Executive LLMへ毎frame問い合わせない。

詳細: `subsystem_architecture.md`。

---

## 8. 認知因果モデル

```text
External / Internal Events
        ↓
Perception / Input Meaning
        ↓
Subjective Appraisal
        ↓
Internal State / Motivation
        ↓
Executive Deliberation
        ↓
Goal / Commitment transition
        ↓
Persistent Goal / Commitment State
        ↓
Planning / Realization / Execution
   ├─ Goal / Activity Planning
   ├─ Speech Semantics
   ├─ Character Language
   ├─ Body Motion
   ├─ Plugin Capability
   └─ Subsystem / Skill Runtime
        ↓
Actual Execution / Presentation Result
        ↓
Appraisal / Executive / Goal transition / Reflection / Memory
```

**この図は因果関係であり固定blocking Runtime Pipelineではない。**

---

## 9. Runtime execution model

正規構造:

- Event-driven
- snapshot-based
- sparse activation
- concurrent lanes
- bounded queues
- priority / backpressure
- cancellation / stale / supersede
- source_context_revision
- goal_revision where relevant

```text
                         ┌─ Input / Meaning lane
                         ├─ Appraisal / State lane
Typed Event Stream ──────┼─ Executive lane
                         ├─ Goal State / Planning lane
                         ├─ Speech Preparation lanes
                         ├─ Speech Presentation lane
                         ├─ Body Realtime lane
                         ├─ Skill / Subsystem lanes
                         └─ Reflection / Memory lane
```

### Concurrency invariant

- slow LLM中もunrelated lane継続
- Speech playback中にnext cognition/generation可能
- TTS待機中もnew input受付可能
- Body realtimeはLLM/TTS/DB/Game AI待ちで停止しない
- Goal State mutationをglobal Core lockにしない
- Reflectionはforeground interactionをblockしない
- Game frame loopはExecutive LLM latency非依存
- Streaming burstでCore starvationなし
- background workがforeground user interactionをstarveしない

詳細: `concurrency_architecture.md`。

---

## 10. LLM設計原則

旧「system-wideでLLMを4責務に固定」は撤回する。

LLM個数をArchitecture invariantにしない。

独立したopen-ended責務があり、deterministic処理では不足する場合に専用Roleを設ける。

初期候補:

- Input Meaning
- Subjective Appraisal（必要時）
- Executive Deliberation
- Goal / Activity Planning
- Speech Semantics
- Character Language
- Independent Semantic Verification
- Body Motion Planning
- Reflection / Memory Consolidation

ただし:

> **conscious Goal / Action selectionの最終AuthorityはExecutive #328だけ。**

Goal / Commitment State #366はLLM Roleではなくtyped persistent state ownership。

### Logical Role != API Call

責務分離とProvider invocation topologyを分離する。

禁止:

```text
Meaning LLM
→ await Appraisal LLM
→ await Executive LLM
→ await Planner LLM
→ await Semantics LLM
→ await Character LLM
→ await Verifier LLM
→ await TTS
→ await Playback
```

許可/推奨:

- simple pathの不要Role省略 / deterministic projection
- complex caseだけ専門Role起動
- independent fan-out
- safe speculative preparation
- fused/batched provider callでもlogical contract維持
- low-priority background role defer/cancel

---

## 11. System Authority Map

| Authority | Owner |
|---|---|
| open-ended外部自然言語の意味 | Input Meaning #326 |
| 出来事の主観的評価 | Appraisal #327 |
| current Internal State | State Reducer #327 |
| conscious Goal / Action選択 | Executive #328 |
| **current Goal / Commitment正本** | **Goal State #366** |
| 複雑Goalの実行計画 | Goal Planner #361 |
| Activity lifecycle | Activity Runtime #329 |
| Actual Execution Fact | Execution Coordination #329 |
| What to say | Speech Semantics #362 |
| How to say it | Character Language #330 |
| 発話意味保持の観測 | Semantic Verifier #363 |
| Speech performance/presentation lifecycle | #331 / #348 |
| Body current state / physical continuity | Body #335〜#341 |
| Memory persistent truth / retrieval | Memory Store #332 |
| Memory candidate generation | Reflection #364 |
| Game frame-level技能 | Game Skill #365（Core Goal従属） |

Intent / Plan / Character claimをActual Factへ昇格させない。
LLM自由文をDomain Stateへ直接代入しない。

---

## 12. Persistent Goal / Commitment

詳細: `goal_commitment_architecture.md`。

```text
Executive chooses Goal
→ validated transition
→ #366 current Goal State
→ later Snapshot / Autonomy / Planner
```

必須:

- turnを跨ぐ
- LLM context windowを跨ぐ
- current Activity変更でも必要に応じsuspend/resume
- CommitmentをMemoryやCharacter speechと混同しない
- stale `goal_revision`のPlanを実行しない
- pending Goal/Commitmentがautonomous triggerになり得る

これにより「毎turnゼロからLLMが意思を作り直す」構造を避ける。

---

## 13. Speech architecture summary

詳細: `speech_pipeline_architecture.md`。

```text
Executive SpeechIntent
→ SpeechSemanticPlan       # What to say
→ CharacterUtterance       # How to say it
→ Semantic Observation
→ closed acceptance policy
→ Speech Performance
→ Prepared candidate
→ Presentation
```

論理依存を固定直列LLM chainにしない。

- simple SpeechはSemantics LLM省略可
- Character後Verifier/Performance/safe TTS prepを並行可能
- required Verifier PASS前にexternal Presentation commitしない
- Speech A playback中にSpeech B generation可
- stale queued speechを再生しない

---

## 14. Body architecture summary

詳細: `body_architecture.md`。

- Canonical Skeleton / DOF / limits
- current pose / velocity
- Body Expression Projection
- generative Motion Planning（LLMは必要時）
- deterministic IK/FK/balance/trajectory
- Continuous Controller
- gaze/blink/breath/viseme/subtle realtime layers
- BodyPoseFrame

fixed Pose/Motion presetを主経路にしない。
current poseから連続生成しHome/Neutralへ強制帰還しない。

Motion Plannerが遅くてもBody realtimeは停止しない。
CharacterとBodyはExecutiveから兄弟fan-outする。

---

## 15. Streaming / Game architecture summary

### Streaming #347

- YouTube / OBS / comment ingest / moderation / health
- bounded ingress / aggregation / backpressure
- Skill AIは分類等を行える
- response / stream continuation / What-to-say AuthorityはCore

### Game #365

```text
Core Executive / Goal State
→ High-level Strategy
→ Game Skill Runtime
→ realtime agent
→ controller action
→ typed game event/result
→ Core Appraisal / Executive
```

GameとStreaming、Speech、Bodyを並行可能。
ゲーム実況台詞はGame Agentが直接出さずCore Speech pathへ戻す。

---

## 16. Character Definition

static Character Definitionとdynamic stateを分離する。

```text
static trait       → Character Definition
current affect     → Internal State
current commitment → Goal / Commitment State
past experience    → Memory
```

Projection:

- Language Style
- Voice Style
- Body Expression Style

Character ProfileをFact / Goal Authorityにしない。

---

## 17. Natural Language semantic policy

open-ended自然言語の意味Authorityとして以下を使わない。

- finite keyword list
- marker list
- regex
- substring
- startswith / endswith

例外:

- protocol token
- enum
- exact technical identifier
- domain自体が有限語彙

意味解決不能ならunresolved / clarification / fail-closed。

---

## 18. Execution Truth

```text
requested
→ accepted
→ planned
→ started
→ observable/applied
→ completed

or
rejected / unsupported / failed / cancelled / timed_out / superseded
```

区別:

- `I want X` → internal/goal semantic state
- `I decided X` → Executive / Goal transition
- `I am doing X` → Activity/Execution Fact
- `I did X` → completed Fact
- `I promised X` → validated Commitment State
- `I said "I promise X"` → Speech Presentation Fact only

Characterは対応Fact/Stateより先にclaimしない。

---

## 19. Character / Body / Skill sibling boundary

```text
                    ExecutiveDecision
                  /        |          \
          SpeechIntent   BodyIntent   Activity/Goal
              ↓             ↓             ↓
          Speech path    Body path    Plugin/Subsystem
```

Character textからBody gestureをsemantic authorityとして作らない。
Body poseからSpeech意味を決めない。
Skill AIからCore Goalを作らない。

---

## 20. Memory / Reflection

- #364 Reflection: open-ended MemoryCandidate生成
- #332 Memory Store: validation / persistence semantics / retrieval
- #359 Persistence Provider: DB implementation

Memoryはcurrent Internal State / current Goal State / current Execution Factより強いAuthorityを持たない。

過去Goal Memoryをcurrent Goalへ直接復元しない。

---

## 21. Module Development Gate

原則:

```text
Canonical design
→ Work Issue
→ Unit Acceptance
→ implementation lineage / Draft PR
→ Unit PASS
→ Adjacent Contract PASS
→ Integration
→ User-required Verification
→ Done
```

全体起動だけをModule品質証明に使わない。

1 Work Issue = 1 active implementation lineage。

実LLM/実TTS/実画面/実Game等でユーザー確認が必要なものはVerificationで止める。

---

## 22. V2 Design Gate

製品コード実装はDesign Gate解除まで開始しない。

解除条件:

- [x] System / Brain / Cognitive / Concurrency正本作成
- [x] Speech / Body / Plugin / Subsystem正本作成
- [x] Persistent Goal / Commitment正本 #366追加
- [x] 旧Open Issue/PR requirementsをMigration Matrixへ回収
- [x] LLM 4-role固定撤回 / Single Executive Authority反映
- [x] non-sequential LLM/runtime invariant反映
- [x] Game Skill / Streaming Skill AI境界反映
- [x] Plugin structural definition反映
- [ ] subordinate canonical / Issue全体の最終整合監査
- [ ] Projects v2 actual fields / formal parent sync（#319、実行環境制約あり）
- [ ] #317 Design Reconciliation Checkpoint
- [ ] **ユーザーによるV2 canonical architecture確認**

Projects v2実mutationの環境制約は設計内容そのものを変更する理由にはしない。ただしProject live同期完了までは#319をBlockedとして明示する。

ユーザー確認前にproduct implementationをunfreezeしない。

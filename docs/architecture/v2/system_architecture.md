# AI Liver ゆら V2 Canonical System Architecture

Status: Draft / V2 Design Gate / Design Reconciliation Complete
Canonical branch: `rebuild/v2-foundation`
Root: #317
Base lineage: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`

## 1. 役割

AI Liver ゆら V2の最上位システム構造正本。

旧実装を継ぎ足さず、V1 Issue/PR/docs/Verificationから要求・failure knowledgeだけを回収し、最古mainから再構築する。

詳細正本:

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

- Emotion / Desire / Drive / Motivation
- Values / Moral context
- Interest / Curiosity
- Relationship
- Memory
- current Goals / Commitments
- Attention / Focus / Turn state
- Current Activities / Actual Execution state
- Body State

を持ち、外界と自身の変化を受けながら会話・YouTube配信・ゲーム対戦/実況・観察・沈黙等を自ら選択する。

ユーザー発言は重要Eventだが無条件命令ではない。

「ゆらが配信する」「ゆらがゲームをする」等の主体性はCoreのGoal / Activity Authorityで表現し、外部サービス固有の実装をCoreへ持ち込むことでは表現しない。

---

## 3. System Boundary

```text
AI Liver Yura
├─ Core
│  ├─ Brain
│  ├─ Body
│  └─ Plugin Architecture
├─ Infrastructure / Providers
└─ Subsystems / Skill Runtimes
   ├─ Avatar
   ├─ Streaming
   ├─ Game Skill
   ├─ GUI/Admin
   ├─ Validation Labs
   └─ Development Tooling
```

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

---

## 4. Clean Architecture

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

外部サービス固有のSDK / protocol / credential / resource IDをCore Domain / Runtimeへ持ち込まない。

---

## 5. Plugin Boundary

Pluginをoptional性だけで定義しない。

> **PluginはCore自身の構成要素ではなく、Core公開拡張契約から外部Capabilityを追加する機構。**

Core固有State/Authorityを所有しない。
`Plugin 0件でもCore基本責務維持`は別System invariant。

---

## 6. Subsystem / Skill AI Boundary

Subsystemは独立lifecycle/process/resource ownershipを持てる。

専門AIは「選択済みActivityを実行する技能」であり、ゆらの意思そのものではない。

- Game Agent
- Streaming classifier/moderation/aggregation
- Vision / recognition

Skill AIはExecutive Goal Authorityを奪わない。

### 6.1 Core Decision / Subsystem Execution / External Observation

外部サービスを伴うActivityでは3つのAuthorityを分ける。

```text
Core Executive
  decides what Yura does
        ↓
generic Activity / Capability Request
        ↓
Subsystem
  executes provider-specific operation
        ↓
Execution Result / External Observation
        ↓
Core
  recognizes actual result and re-appraises
```

Coreは「配信を準備する」「配信を開始する」「配信を終了する」といった高レベルActivityを選択できる。

ただしYouTube API、OBS WebSocket、OAuth、provider固有IDやscene等はStreaming Subsystem側だけが所有する。Core production codeはYouTube/OBS等のprovider固有class・port・runtime責務を持たない。

外界状態はSubsystem/API観測だけでなくユーザー報告等からも認知できる。source / provenance / confidenceを保持し、報告とprovider確認済み事実を無条件に同一視しない。

IntentやCharacter発話は外部操作成功Factではない。Actual Factはtrusted Execution Result / Observationで確定する。

---

## 7. 認知因果モデル

```text
External / Internal Events
→ Perception / Input Meaning
→ Subjective Appraisal / salience
→ Internal State
→ Attention / Focus eligibility
→ Executive Deliberation
→ Goal / Commitment transition
→ Persistent Goal / Commitment State
→ Planning / Realization / Execution
→ Actual Result / New Events
→ Appraisal / Attention / Executive / Goal / Reflection / Memory
```

因果図であり固定blocking Pipelineではない。

---

## 8. Runtime Model

- Event-driven
- snapshot-based
- sparse activation
- concurrent lanes
- bounded queues
- priority / backpressure
- cancellation / stale / supersede
- source_context_revision
- goal_revision / attention_revision where needed

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

必須:

- slow LLM中もunrelated lane継続
- Speech playback中next cognition/generation可能
- TTS待機中new input可能
- Goal/Focus mutationをCore global lockにしない
- Body realtimeはLLM/TTS/DB/Game AI待ちで停止しない
- Reflectionはforeground interactionをblockしない
- Game frame loopはExecutive LLM latency非依存
- Streaming burstでCore starvationなし
- background workがforeground interactionをstarveしない

Subsystemの外部API待ちをCore Runtimeの専用配信処理として抱え込まず、generic async Capability / Event境界で隔離する。

---

## 9. LLM Design

旧system-wide 4-role固定は撤回。
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

Goal State #366、Attention #333、State Reducer、Activity/Execution、Body physical/realtime等はtyped deterministic ownershipを基本とする。

`Logical Role != API Call`。
責務分離をserial Provider chainへ変換しない。

---

## 10. System Authority Map

| Authority | Owner |
|---|---|
| open-ended NL meaning | #326 |
| subjective Appraisal / salience candidate | #327 |
| current Internal State | #327 State Reducer |
| conscious Goal / Action selection | #328 Executive |
| current Goal / Commitment | #366 |
| current Attention / Focus / Turn scheduling | #333 |
| complex Goal planning | #361 |
| Activity lifecycle / Actual Fact | #329 |
| What to say | #362 |
| How to say | #330 |
| semantic observation | #363 |
| Speech performance / presentation | #331/#348 |
| Body current state / physical continuity | #335〜#341 |
| Memory canonical store / retrieval | #332 |
| Memory Candidate generation | #364 |
| Game frame-level skill | #365, subordinate to Core Goal |
| Streaming provider execution / observation | #347 Subsystem, subordinate to Core Activity |

LLM自由文をState/Factへ直接代入しない。
Intent / Plan / Character claimをActual Factへ昇格させない。

---

## 11. Persistent Goal / Commitment — #366

```text
Executive chooses Goal
→ validated transition
→ Goal State
→ later Attention / Executive / Planner
```

- turn/context windowを跨ぐ
- GoalとActivityを分離
- GoalとMemoryを分離
- CommitmentとCharacter utteranceを分離
- stale goal_revision Plan非実行
- pending Goal/Commitmentがautonomous triggerになり得る

---

## 12. Attention / Focus / Turn — #333

Game、Streaming、Conversation、Reflection等の全EventをExecutiveへ同期投入しない。

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

## 13. Speech Summary

```text
Executive SpeechIntent
→ SpeechSemanticPlan       # What
→ CharacterUtterance       # How
→ Semantic Observation
→ closed acceptance
→ Performance / Prepared candidate
→ Presentation
```

logical dependencyをfixed serial LLM chainにしない。

- simple Semantics pathは専用LLM省略可
- Character後Verifier/Performance/safe TTS prep並列可
- required PASS前にexternal Presentation commitしない
- Speech A playback中にSpeech B generation可
- context/goal/attention revisionでpre-presentation revalidation

---

## 14. Body Summary

- Canonical Skeleton / DOF / limits
- current pose / velocity
- Expression Projection
- Motion Planning（LLMは必要時）
- deterministic IK/FK/balance/trajectory
- Continuous Controller
- gaze/blink/breath/viseme/subtle realtime
- BodyPoseFrame

fixed presetsを主経路にせず、current pose continuity / no Home reset。
Motion Planner遅延でもrealtime停止なし。
CharacterとBodyはExecutiveから兄弟fan-out。

---

## 15. Streaming / Game Summary

### Streaming #347

Streamingは**Coreの配信Moduleではなく独立Subsystem**。

Coreが所有する:

- 配信を準備/開始/継続/終了するかというActivity/Goal判断
- viewer commentへ反応するか
- 何を言うか

Streaming Subsystemが所有する:

- provider固有のreadiness / prepare / start / end実行
- YouTube/OBS等のAPI・protocol・authentication
- 配信状態/healthのprovider観測
- comment ingestion / aggregation / backpressure
- provider結果のtyped Execution Result / External Observation化

```text
User / Internal Goal
→ Input / Executive
→ generic Capability Request
→ Streaming Subsystem
→ external provider operation
→ Execution Result / Observation
→ Appraisal / Attention / Executive
```

OBS profile / scene graph / encoder等の構成は原則事前準備し、任意構成の自動生成を#347の必須責務にしない。

API観測がなくてもユーザーから「配信が始まった」等の報告を受けて認知候補にできるが、`user_report` provenanceを保持しprovider確認済みFactと区別する。

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

Game Agentが実況台詞を直接発話しない。

---

## 16. Natural Language Policy

open-ended意味Authorityとしてfinite keyword/marker/regex/substring/startswith等を使わない。

protocol token / enum / exact technical ID / finite-domain vocabularyは例外。

解決不能はunresolved / clarification / fail-closed。

---

## 17. Execution Truth

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

外部Subsystem操作も同じTruth boundaryに従う。`start broadcast`をIntentしたことと、provider上で実際にliveになったことを分離する。

---

## 18. Character / Body / Skill sibling boundary

```text
                    ExecutiveDecision
                  /        |          \
          SpeechIntent   BodyIntent   Activity/Goal
              ↓             ↓             ↓
          Speech path    Body path    Plugin/Subsystem
```

Character textからBody semantic commandを作らない。
Body poseからSpeech meaningを決めない。
Skill AIからCore Goalを作らない。
Subsystem Execution Resultからのみ外部実行Factを確定し、Character claimから逆算しない。

---

## 19. Memory / Reflection

- #364 Reflection: open-ended MemoryCandidate
- #332 Memory Store: validation/store/retrieval
- #359 Persistence Provider: implementation

Memoryはcurrent Internal State / Goal State / Execution Factより強いAuthorityを持たない。

---

## 20. Module Development Gate

```text
Canonical Design
→ Work Issue
→ Unit Acceptance
→ implementation lineage / Draft PR
→ Unit PASS
→ Adjacent PASS
→ Integration
→ User Verification if required
→ Done
```

1 Work Issue = 1 active implementation lineage。

---

## 21. Design Reconciliation Status

設計反映・Issue整合監査は完了済み。

- [x] System / Brain / Cognitive / Goal / Concurrency canonical
- [x] Speech / Body / Plugin / Subsystem canonical
- [x] Legacy 44 Open Issue / initial 23 PR requirement mapping
- [x] variable LLM / Single Executive
- [x] non-serial LLM/runtime
- [x] persistent Goal #366
- [x] Attention/Focus #333
- [x] Game/Streaming Skill AI boundary
- [x] Plugin structural definition
- [x] current V2 Issueのactive Commander/fixed Role numbering排除
- [x] subordinate canonical / Issue cross-audit
- [x] Project sync Manifest / Runbook
- [x] #394 Streaming Core Decision / Subsystem Execution / External Observation boundary reconciliation

#319 actual Projects v2 field / formal Parent-Subissue mutationは現実行環境の制約で別途Blocked管理する。

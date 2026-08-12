# AI Liver ゆら V2 Canonical System Architecture

Status: Draft / V2 Design Gate
Canonical branch: `rebuild/v2-foundation`
Root management: #317
Base lineage: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`

## 1. この文書の役割

この文書はAI Liver ゆら V2の**最上位システム構造正本**である。

V2では旧実装を継ぎ足さず、旧Issue / PR / branch / docsから要求・失敗知見・設計原則を回収して最古mainから再構築する。

詳細責務はsubordinate canonicalへ委譲する。

- Brain: `docs/architecture/v2/brain_architecture.md`
- Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
- Concurrency / LLM invocation: `docs/architecture/v2/concurrency_architecture.md`
- Speech: `docs/architecture/v2/speech_pipeline_architecture.md`
- Body: `docs/architecture/v2/body_architecture.md`
- Plugin: `docs/architecture/v2/plugin_architecture.md`
- Subsystem / Skill AI: `docs/architecture/v2/subsystem_architecture.md`
- Legacy migration: `docs/architecture/v2/legacy_migration_matrix.md`
- Project sync: `docs/architecture/v2/project_sync_manifest.md`

---

# 2. 最終目標

作るものはユーザー入力へ返信するチャットボットではない。

**自由意志をもった「ゆら」という存在**を作る。

ゆらは持続する:

- Internal State
- Emotion / Desire / Drive / Motivation
- Values / Moral context
- Interest / Curiosity
- Relationship
- Memory
- Goals / Commitments
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

# 3. System Boundary

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

# 4. Core

Coreは「ゆら自身」の正本責務を所有する。

Core membershipは「その機能が一時的になくてもdegraded運転できるか」で決めない。

例:

- BrainはCore
- BodyはCore
- Internal StateはCore
- Executive AuthorityはCore

Avatarが未接続でもBodyがPluginになるわけではない。
TTSが unavailableでもCharacter責務がPluginになるわけではない。

## Core degradation invariant

- Plugin 0件でもCore固有責務を維持
- Avatar不在でもBody State維持
- Streaming不在でもCore維持
- GUI不在でもCore維持
- TTS unavailableでも可能な認知・Text/Silence処理継続
- Persistence unavailableでも安全縮退
- 外部Output切断でCore停止なし
- specific LLM Role failureで無関係lane停止なし
- graceful shutdown / cancellationを正常経路として扱う

---

# 5. Plugin

Pluginはoptional性だけで定義しない。

> **Pluginは、BrainやBodyなどCore自身の構成要素ではなく、Coreが公開する拡張契約を通して外部から新しいCapabilityを追加する機構である。**

PluginはCore固有Domain State / Authorityを所有しない。

追加・削除でBrain / Bodyの責務境界を変えない。

`Plugin 0件でもCore基本責務を維持`は別のSystem invariant。

詳細: `plugin_architecture.md`

---

# 6. Infrastructure Provider / Adapter

OpenAI / local LLM / VOICEVOX / PostgreSQL / HTTP等はCore Portの実装手段であり、外部実装だからという理由でPluginとは呼ばない。

```text
Domain / Contracts
        ↑
Application / Use Cases
        ↑
Ports
        ↑
Providers / Adapters / External systems
```

DomainはOpenAI SDK、FastAPI、VOICEVOX、PostgreSQL、Live2D等の具体型を知らない。

---

# 7. Subsystem / Skill AI

SubsystemはCoreとは別のlifecycle / process / resource ownershipを持てる独立system boundary。

Core public contractだけで接続する。

専門AIを持ってよいが、それは「ゆらの意思」ではなく**選択済みActivityを実行する技能**である。

例:

- Streaming comment aggregation / moderation AI
- Game realtime Agent
- Vision / recognition skill

Skill AIはExecutive Goal Authorityを奪わない。

Game frame-level actionをCore Executive LLMへ毎frame問い合わせない。

詳細: `subsystem_architecture.md`

---

# 8. ゆらの認知因果モデル

```text
External / Internal Events
  ├─ user conversation
  ├─ stream / viewers
  ├─ game events / results
  ├─ camera / microphone / touch
  ├─ time / environment
  ├─ memory activation
  ├─ internal state changes
  └─ execution results
            ↓
Perception / Meaning
            ↓
Subjective Appraisal
            ↓
Internal State / Motivation / Goal relevance
            ↓
Executive Deliberation
            ↓
Intent / Goal / Commitment
            ↓
Planning / Realization
   ├─ Goal / Activity planning
   ├─ Speech semantics
   ├─ Character language
   └─ Body motion
            ↓
Execution / Presentation / Skill Runtime
            ↓
Actual Result / World change
            ↓
Appraisal / Memory / Reflection
```

**この図は因果関係であり、全箱を毎回順番にawaitするRuntime Pipelineではない。**

---

# 9. Runtime実行モデル

正規構造:

- Event-driven
- snapshot-based
- sparse activation
- concurrent lanes
- bounded queues
- priority / backpressure
- cancellation / stale / supersede

```text
                         ┌─ Input / Meaning lane
                         ├─ Appraisal / State lane
Typed Event Stream ──────┼─ Executive lane
                         ├─ Goal / Activity Planning lane
                         ├─ Speech Preparation lanes
                         ├─ Speech Presentation lane
                         ├─ Body Realtime lane
                         ├─ Skill / Subsystem lanes
                         └─ Reflection / Memory lane
```

## Concurrency invariant

- slow LLM中も無関係lane継続
- Speech playback中にnext cognition / generation可能
- TTS待機中もnew input受付可能
- Body realtimeはLLM / TTS / DB / Game AI待ちで停止しない
- Reflectionはforeground interactionをblockしない
- Game frame loopはExecutive LLM latency非依存
- Streaming burstでCore starvationなし
- background cognitionがforeground user interactionをstarveしない

詳細: `concurrency_architecture.md`

---

# 10. LLM設計原則

旧「system-wideでLLMを4責務に固定」は撤回する。

LLM個数をArchitecture invariantにしない。

> open-endedな意味理解・主観評価・推論・計画・言語実現・意味検証・身体運動構成・内省に独立責務があり、LLMが適切な場合に専用Roleを設ける。

ただし:

> **意識的Goal / Action selectionの最終AuthorityはExecutive Deliberatorただ1つ。**

初期Core cognitive role候補:

- Input Meaning
- Subjective Appraisal（LLM利用が適切な場合）
- Executive Deliberation
- Goal / Activity Planning
- Speech Semantics Planning
- Character Language Realization
- Independent Semantic Verification
- Body Motion Planning
- Reflection / Memory Consolidation

これらを毎cycle全て呼ばない。

## Logical Role != API Call

責務分離とProvider invocation topologyを分離する。

禁止:

```text
Input Meaning LLM
→ await Appraisal LLM
→ await Executive LLM
→ await Semantics LLM
→ await Character LLM
→ await Verifier LLM
→ await TTS
```

許可・推奨:

- simple pathで不要Role省略 / deterministic projection
- complex caseだけ専門Role起動
- independent workをparallel fan-out
- safe speculative preparation
- fused/batched Provider callを将来利用してもlogical contract維持
- low-priority background Roleをdefer/cancel

---

# 11. Authority Map

| Authority | Owner |
|---|---|
| open-ended外部自然言語の意味 | Input Meaning |
| 出来事の主観的評価 | Appraisal contract |
| current Internal State | Internal State Reducer |
| 意識的Goal / Action選択 | Executive Deliberator |
| 複雑Goalの実行計画 | Goal / Activity Planner（Executive従属） |
| Activity lifecycle | Activity Runtime |
| 実際に起きたこと | Execution Result / Runtime Facts |
| 発言として何を伝えるか | Speech Semantics |
| どうゆららしく言うか | Character Language Realizer |
| 発話意味保持の観測 | Independent Semantic Verifier |
| 身体意図の運動実現 | Body Motion Planner + deterministic Body |
| current Body State | Body |
| Memory永続正本 | Memory Store + validation |
| game frame-level技能 | Game Skill Agent（Core Goal従属） |

LLM自由文をDomain State / Execution Factへ直接代入しない。

---

# 12. Brain summary

Brain詳細: `brain_architecture.md`

主要責務:

- Input Gateway / Meaning
- Subjective Appraisal
- Internal State
- Memory / Reflection
- Executive Deliberation
- Goal / Activity Planning
- Activity Runtime
- Execution Coordination
- Speech Semantics
- Character Language
- Semantic Verification
- Speech Performance / Pipeline
- Autonomy / Turn

Runtime KernelはBrain判断ModuleではなくCore Foundation。

---

# 13. Speech summary

詳細: `speech_pipeline_architecture.md`

V1で得た:

```text
What to say != How to say it
```

を維持する。

```text
Executive SpeechIntent
→ SpeechSemanticPlan
→ CharacterUtterance
→ Semantic Observation / closed gate
→ Speech Performance
→ Prepared candidate
→ Presentation
```

ただし固定直列LLM chainではない。

simple speechではSemantics専用LLMを省略可能。
Character後、required Verifierとsafe Performance / speculative TTS準備を並行可能。
Verifier PASS前にexternal presentation commitはしない。

Speech A playback中にSpeech Bの生成を進められる。

---

# 14. Body summary

詳細: `body_architecture.md`

Bodyは:

- Canonical Skeleton / DOF / limits
- current pose / velocity
- Expression Projection
- generative Motion Planning
- deterministic IK / FK / balance / trajectory
- Continuous Controller
- gaze / blink / breath / viseme / subtle realtime layers
- BodyPoseFrame

を持つ。

fixed Pose/Motion presetを主経路にしない。
current poseから連続生成しHome/Neutralへ強制帰還しない。

Body Motion LLMが遅くてもrealtime layerは停止しない。

CharacterとBodyはExecutiveから兄弟fan-outする。

---

# 15. Plugin summary

詳細: `plugin_architecture.md`

Core公開Capability Contractから新能力を追加する。

Plugin executionは:

- typed request/result
- permission
- availability
- timeout / cancel
- revision / stale

を持つ。

slow Pluginで無関係Core laneをblockしない。

---

# 16. Streaming / Game summary

詳細: `subsystem_architecture.md`

## Streaming

- YouTube / OBS / comments / moderation / health
- comment burst aggregation / backpressure
- Core Executiveがresponse / Activity Authority維持

## Game

```text
Core Executive Goal / Strategy
→ Game Skill Runtime
→ realtime game-specific agent
→ controller action
→ typed game event / result
→ Core Appraisal
```

実況台詞はGame Agentが直接発話せず、salient typed game eventをCore Speech pathへ戻す。

GameとStreaming、Speech、Bodyは同時並行可能。

---

# 17. Character Definition

static Character Definitionとdynamic current stateを分離する。

```text
static trait → Character Definition
current emotion/desire/drive → Internal State
current relationship → Relationship State
current interest → Interest / Memory
```

Projection:

- Language Style
- Voice Style
- Body Expression Style

Character設定からcurrent stateを捏造しない。

---

# 18. Natural Language semantic policy

open-ended自然言語の意味Authorityとして次を使わない。

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

意味解決不能ならunresolved / clarification / fail-closedへ落とす。

---

# 19. Execution Truth

Intent / Plan / Actual Factを分離する。

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

CharacterはExecution Factより先に「やった」「できた」と主張しない。

stale resultでも外部効果が既に発生している場合、事実を無かったことにしない。

---

# 20. Revision / stale / cancellation

long-running requestは最低限:

```text
request_id
source_event_ids
source_context_revision
priority
interruptibility
preconditions
stale policy
```

を持つ。

新user input / Goal change / execution result / capability change等で前提が崩れたcandidateを無条件commitしない。

可能なrequestは不要時cancelする。

---

# 21. Priority / Backpressure

概念的優先:

1. foreground user interaction
2. safety / interruption / execution failure
3. active Activity decision
4. autonomous initiative
5. Reflection / consolidation
6. low-priority enrichment

low-priority workがhigh-priority interactionをstarveしない。

burst inputはSubsystem/Roleごとにbounded queue / coalesce / latest-wins等を定義する。

---

# 22. Observability

最低限:

- trace / event / request id
- module / role
- source_context_revision
- priority
- queued / started / completed timestamps
- queue wait
- provider latency
- outcome
- cancellation / stale / superseded
- execution lifecycle

性能:

- user input→Executive decision
- user input→speech preparation / presentation
- Role別p50/p95/p99
- previous playback中next generation start
- Body frame interval / jitter
- Game frame stability
- Streaming burst impact
- background starvation

---

# 23. Development Gate

## Gate 0 Design

各Module / Roleについて:

- responsibility
- authority
- typed input/output
- trigger / sparse activation
- blocking / non-blocking dependency
- revision / stale / cancellation
- priority / backpressure
- failure / degradation
- non-goals
- acceptance

を定義する。

## Gate 1 Unit

対象Module単体。

## Gate 2 Adjacent Contract

隣接DTO / Authority / Event boundary。

## Gate 3 Integration

concurrency / failure / cancellation / backpressureを含む。

## Gate 4 System Verification

実LLM / TTS / Body / Avatar / Streaming / Game Skill等。

ユーザー確認が必要ならVerificationで止める。

---

# 24. V1から継承する教訓

維持:

- 責務分離
- Input Meaning / Decision分離
- What to say / How to say it分離
- Independent Semantic Verification
- typed contracts
- Characterへraw internal state意味決定を押し付けない
- finite natural-language dictionaryをsemantic authorityにしない
- Body generative motion / deterministic constraints分離
- Streaming subsystem分離
- Module単位検証

改善:

- LLM総数を先に固定しない
- AuthorityはExecutiveへ一本化
- Responsibility分離を直列API call列へしない
- slow LLM/TTS/playback/DB/Game/Streamingで無関係laneをblockしない
- Pluginをoptional性だけで定義しない
- Game Skill AIを正式境界化

---

# 25. V2 Design Gate完了条件

- [ ] 本文書をユーザーが確認
- [ ] Brain / Cognitive / Concurrency canonical整合
- [ ] Speech canonical整合
- [ ] Body canonical整合
- [ ] Plugin canonical整合
- [ ] Subsystem / Game Skill canonical整合
- [ ] Legacy Migration Matrix全件対応
- [ ] 新Issue hierarchyが新責務と一致
- [ ] Project manifestへ#361〜#365を同期
- [ ] LLM Role数固定が残っていない
- [ ] Single Executive Authorityが全Issueで一致
- [ ] Logical Role数とAPI call数を分離
- [ ] slow Roleが無関係laneをblockしないAcceptanceあり
- [ ] stale/cancelled resultを誤commitしない
- [ ] Game frame loopがCore LLM latency非依存
- [ ] Streaming burstがCore starvationを起こさない
- [ ] user review / explicit Design Gate acceptance
- [ ] Gate acceptance前に製品コードを変更しない

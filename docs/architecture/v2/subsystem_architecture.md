# AI Liver ゆら V2 Subsystem / Skill AI Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Plugin architecture: `docs/architecture/v2/plugin_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #345
Root management: #317

## 1. 目的

Subsystemは、ゆらCoreとは独立したsystem boundaryを持ち、Core public contractを通して協調する。

YouTube配信・ゲーム・Avatar等の専門機能がCore Executiveの自由意志・Goal Authorityを奪わず、高速・専門的なAIを独立利用できる構造を定義する。

---

## 2. Subsystemの定義

Subsystem:

- Coreとは別のlifecycle / resource ownershipを持てる
- 独立process / serviceになり得る
- Core内部Domain objectへ直接import依存しない
- Core public Event / Command / DTO / Port / APIで接続
- failure / restartがCore停止を意味しない
- 専門AI / model / external APIを独自利用可能

Pluginとは別概念。

PluginはCore拡張契約からCapabilityを追加する仕組み、Subsystemは独立system boundary。
Subsystem機能をCoreへ公開するbridgeとしてCapability Adapterを利用してよい。

---

## 3. Authority境界

Subsystemが専門AIを持っても、ゆらのconscious Goal / Action selectionはCore Executive #328が所有する。

```text
Core Executive / Goal State
→ high-level Intent / Goal / Strategy
→ public subsystem/capability contract
→ Subsystem Skill Runtime
→ actual external action / observation
→ typed Event / Execution Result
→ Core Appraisal / Executive
```

Subsystem AIは勝手に次を決めない。

- ゆら自身の最上位Goal
- current Goal / Commitment正本
- Characterの人格・発話意味
- Internal State current value
- Body canonical state
- userとの関係の正本

---

## 4. Skill AI

Skill AIは「ゆらが選択済みActivityを上手く実行するための専門技能」でありCore cognitive AIとは別に扱う。

例:
- Game Agent
- large-volume chat classifier
- moderation model
- vision detector
- game strategy search
- OCR/recognition model
- domain-specific planner

LLM / VLM / RL / search / deterministic / hybridのどれを使うかはCapabilityごとに選ぶ。

Skill AI数をCore cognitive LLM Role数へ数える必要はない。

---

## 5. Streaming Subsystem — #347

責務:

- YouTube Live lifecycle
- OBS lifecycle / scene / stream control
- comment ingestion
- rate limit / reconnect
- moderation support
- chat aggregation / ranking / summarization signal
- stream health
- typed viewer / stream events

自然言語commentはInput Meaningへ渡せる。
大量commentをCore Executiveへ1件ずつsync blocking投入しない。

### Streaming Skill AI

利用可能:
- spam / duplicate grouping
- topical clustering
- moderation candidate
- representative comment selection
- rolling summary / trend signal

ただし「どのcommentへ反応するか」「配信を続けるか」「何を言うか」の最終判断はCore Executive / Speech責務。

### Output

accepted activity/capability requestに従いstream start/stop、scene、metadata、authorized moderation等を実行しExecution Resultを返す。

---

## 6. Game Skill Subsystem — #365

### 目的

ゲームActivityをCore Executive LLMがframe-by-frame操作する構造にせず、高速なGame Skill Runtimeへ委譲する。

```text
Core Executive / Goal State
        ↓
GameSessionIntent / HighLevelGameStrategy
        ↓
Game Skill #365
  perception / game state
  game-specific planning
  realtime action policy
  controller output
        ↓
Game Event / Result / Strategy feedback
        ↓
Core Appraisal / Executive
```

### Core Authority

Coreが決める例:

- gameを始める/続ける/やめる
- 誰と遊ぶか
- matchへ参加するか
- high-level strategy
- 配信しながら続けるか
- pause / quit
- game resultをどう評価するか

### Game Skill Authority

Skill側:

- frame-level observation
- opponent estimation
- pathfinding
- combat/action selection
- controller input timing
- tactical search
- reaction timing

これをExecutive LLMへ毎frame問い合わせない。

### Game AI implementation

- deterministic bot logic
- planning/search
- RL policy
- vision model
- LLM/VLM
- hybrid

Core public contractは具体model非依存。

### Streamingとの同時動作

Game中にもCore Executive/Appraisal、Speech preparation、Body、Streaming comments、Game realtime agentを並行可能。

Game frame loopをCharacter LLM / TTS / Semantic Verifierへ依存させない。

ゲーム実況はGame Skill AIが最終台詞を直接生成せず、typed game event/salient momentをCore Speech pathへ返す。

---

## 7. Game Session Contract

```text
GameSessionIntent
- session_request_id
- game_capability_id
- participant_refs[]
- goal_id / goal_revision?
- high_level_goal
- high_level_strategy?
- stream_context?
- priority
- interruptibility
- source_context_revision
```

```text
GameObservationEvent
- session_id
- observation_type
- structured_state
- occurred_at
- salience_hint
- confidence
```

```text
GameActionFact
- session_id
- action_id
- game_action_type
- started_at
- applied_at?
- result?
```

```text
GameSessionResult
- session_id
- outcome
- score / rank if applicable
- key_events[]
- completed_at
- failure?
```

Coreへ巨大frame stateを無制限送信せず、必要なtyped read model/eventへ集約する。

---

## 8. Avatar Subsystem — #346

```text
BodyPoseFrame
+ Presentation metadata
→ Avatar projection
→ Live2D / 3D / Stick / future renderer
```

Avatarは:

- Motion Intentを決めない
- Emotionを推測してCoreへ上書きしない
- BodyPoseFrameをrenderer parameterへ投影
- capability / limitation / healthをCoreへ返す

Avatar FPS低下でCore Body Stateの正本を失わない。

---

## 9. GUI / Admin — #351

GUIはtyped Read Model / explicit Command APIを使う。

禁止:
- Domain object直接書換え
- GUI都合でExecutive/Emotion/Goal/Body Motionを決定
- secret/raw prompt無制限表示

Debug overrideが必要なら明示Debug Authority / environment gateを通す。

---

## 10. Validation Labs — #352

Production contractを再利用してRole/Moduleを独立検証する。

特に:
- LLM latency
- concurrency
- stale/cancel
- priority/backpressure
- Game Skill realtime independence
- Streaming burst isolation

を可視化する。

Lab独自Prompt/decision logicをproduction正本にしない。

---

## 11. Development Tooling — #353

- architecture visualizer
- issue/dependency visualization
- fixture/export
- diagnostics viewers
- reference analysis

Toolingはproduction decision Authorityを持たない。

---

## 12. Public Contract

Subsystem接続は用途に応じて:

- typed Event stream
- async request/result
- HTTP / SSE / WebSocket
- message queue
- process-local Port

を選べる。

Transport形式とDomain意味Contractを混同しない。

---

## 13. Concurrency / Isolation

各Subsystemは独立lane / worker / processで実行可能にする。

### Streaming burst

- bounded ingress
- aggregation / coalescing
- priority
- representative event extraction
- backpressure

Core event queueを無制限に埋めない。

### Game

realtime loopをCore LLM latencyへ従属させない。

### Avatar

rendering slowdownでBody Core loopをblockしない。

### GUI

slow clientでCore state publicationをblockしない。

---

## 14. Failure / Recovery

```text
available
→ degraded
→ unavailable
→ recovering
→ available
```

Coreはtyped availability eventを受け、必要ならExecutiveがGoal/Activityを再評価する。

Subsystem側でCore Goalを勝手に変更しない。
retry/reconnectはbounded。

---

## 15. Lifecycle

Core process lifecycleとSubsystem lifecycleを分離する。

- Core起動前/後にSubsystem接続可能
- Subsystem restart可能
- shutdown順序明示
- pending operation cancellation
- health/readiness

Streaming停止 / Game session終了 / Avatar切断をCore shutdownと同一視しない。

---

## 16. V1から継承する教訓

維持:
- Streaming Subsystem分離
- Avatar output separation
- Render/Browser validation labs
- typed Event/Result
- GUI non-authority

追加/改善:
- Game Skill AIを正式境界化
- Skill AIとCore cognitive AIを分離
- frame-level Game controlをExecutive LLMから分離
- massive stream inputをCoreへsync serial投入しない
- skill/subsystem latencyをCore loopへ伝播させない

---

## 17. Acceptance

### Common
- Subsystem failureでCore停止なし
- Core内部Domain object直接依存なし
- typed public contract
- cancellation / reconnect
- bounded queues
- slow subsystemでunrelated Core lane停止なし

### Streaming
- burst commentsでCore starvationなし
- aggregated signal / natural-language inputをtyped経路へ渡す
- Core Executiveがresponse/activity authority維持

### Game
- Core high-level Goal/Strategy→Game Skill
- goal_revision/context revisionを必要時保持
- frame-level loopはCore Executive LLM latency非依存
- game event/result→Core Appraisal
- game commentaryはCore Speech path
- user interruption / quit intentでsession control可能
- Game AgentがCore Goal Authorityを持たない

### Avatar
- BodyPoseFrame projection only
- renderer unavailableでもCore Body維持

---

## 18. Design Reconciliation Status

- [x] #345が本書をcanonicalとして参照
- [x] Streaming #347 / Avatar #346 / GUI #351 / Labs #352 / Tooling #353がpublic contract原則に一致
- [x] Game Skill Work Issue #365を追加
- [x] Game Skill AIとCore cognitive AIを分離
- [x] Streaming burst / Game realtime / Avatar renderingをCore LLM latencyから独立
- [x] Skill AIがExecutive Authorityを奪わない

残るのは#317全体Design Gate確認と、実装後のSubsystem Verificationである。

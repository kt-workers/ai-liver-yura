# AI Liver ゆら V2 Subsystem / Skill AI Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Plugin architecture: `docs/architecture/v2/plugin_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #345
Root management: #317

## 1. 目的

Subsystemは、ゆらCoreとは独立したシステム境界を持ち、Core public contractを通して協調する。

この文書は特に、YouTube配信・ゲーム・Avatar等の専門機能が、Core Executiveの自由意志・Goal Authorityを奪わず、高速・専門的なAIを独立して利用できる構造を定義する。

---

## 2. Subsystemの定義

Subsystemは次の特徴を持つ。

- Coreとは別のlifecycle / resource ownershipを持てる
- 独立process / serviceになり得る
- Core内部Domain objectへ直接import依存しない
- Core public Event / Command / DTO / Port / APIで接続
- failure / restartがCoreの停止を意味しない
- 専門AI / model / external APIを独自に利用可能

SubsystemはCore Pluginとは別概念。

PluginはCore拡張契約からCapabilityを追加する仕組みであり、Subsystemは独立したsystem boundary。

Subsystemの機能をCoreへ公開するbridgeとしてPlugin/Capability Adapterを利用してよい。

---

## 3. Authority境界

Subsystemが専門AIを持っても、ゆらの意識的Goal / Action selectionはCore Executiveが所有する。

```text
Core Executive
→ high-level Intent / Goal / Strategy
→ public subsystem/capability contract
→ Subsystem Skill Runtime
→ actual external action / observation
→ typed Event / Execution Result
→ Core Appraisal / Executive
```

Subsystem AIは以下を勝手に決めない。

- ゆら自身の最上位Goal
- Characterの人格・発話意味
- Internal State current value
- Body canonical state
- userとの関係の正本

---

## 4. Skill AIという概念

Skill AIは「ゆらが特定Activityを上手く実行するための専門技能」であり、Core cognitive AIとは別に扱う。

例:

- Game Agent
- large-volume chat classifier
- moderation model
- vision detector
- game strategy search
- OCR/recognition model
- domain-specific planner

Skill AIがLLM/VLM/RL/検索/決定論的アルゴリズムのどれかはCapabilityごとに選ぶ。

`Core cognitive LLM Role数`へSkill AI数を含める必要はない。

---

## 5. Streaming Subsystem

Issue: #347

### 責務

- YouTube Live lifecycle
- OBS lifecycle / scene / stream control
- comment ingestion
- rate limit / reconnect
- moderation support
- chat aggregation / ranking / summarization signal
- stream health
- typed viewer / stream events

### Coreへの入力

```text
StreamEvent
- stream/session id
- event kind
- actor/viewer ref
- typed payload
- occurred_at
- priority/salience hints if purely operational
```

自然言語commentはInput Meaningへ渡せる。

大量コメントすべてをCore Executiveへ1件ずつ同期blocking投入しない。

### Streaming Skill AI

大量コメントについて:

- spam / duplicate grouping
- topical clustering
- moderation candidate
- representative comment selection
- rolling summary / trend signal

等に専用AIを利用可能。

ただし「どのコメントへ実際に反応するか」「配信を続けるか」「何を言うか」の最終判断はCore Executive / Speech責務。

### Output

Coreからのaccepted activity/capability requestに従い:

- start/stop stream
- scene operation
- stream metadata operation
- moderation operation if authorized

を実行し、Execution Resultを返す。

---

## 6. Game Skill Subsystem

新Work Issueで所有する。

### 6.1 目的

ゲームActivityを、Core Executive LLMがframe-by-frame操作する構造にせず、高速なGame Skill Runtimeへ委譲する。

```text
Core
  Executive Goal / Activity
        ↓
GameSessionIntent / HighLevelGameStrategy
        ↓
Game Skill Subsystem
  perception / game state
  game-specific planning
  realtime action policy
  controller output
        ↓
Game Event / Result / Strategy feedback
        ↓
Core Appraisal / Executive
```

### 6.2 High-level Core Authority

Coreが決める例:

- gameを始めたいか
- 誰と遊ぶか
- matchへ参加するか
- aggressive / defensive等の大まかなstrategyを採用するか
- 配信しながら続けるか
- pause / quitするか
- game resultをどう感じるか

### 6.3 Game Skill Authority

Skill側が担当できる例:

- frame-level observation
- opponent state estimation
- pathfinding
- combat move selection
- controller input timing
- tactical search
- reaction timing

これをCore Executive LLMへ毎frame問い合わせない。

### 6.4 Game AI implementation

ゲーム種別に応じて選べる。

- deterministic bot logic
- planning/search
- RL policy
- vision model
- LLM/VLM
- hybrid

Core public contractは具体modelに依存しない。

### 6.5 Streamingとの同時動作

Game中にも:

- Core Executive / Appraisal
- Character Speech preparation
- Body
- Streaming comments
- Game realtime agent

が並行できる。

Game frame loopをCharacter LLM / TTS / Semantic Verifierへ依存させない。

ゲーム実況の発話はGame Skill AIが最終台詞を生成せず、typed game event / salient momentをCoreへ返し、Core Speech pathで発話する。

---

## 7. Game Session Contract

例:

```text
GameSessionIntent
- session_request_id
- game_capability_id
- participant_refs[]
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

Coreへゲーム固有巨大frame stateを無制限送信せず、必要なtyped read model / eventへ集約する。

---

## 8. Avatar Subsystem

Issue: #346

```text
BodyPoseFrame
+ Character/Presentation metadata
→ Avatar projection
→ Live2D / 3D / Stick / future renderer
```

Avatarは:

- Motion Intentを決めない
- Emotionを推測してCoreへ上書きしない
- BodyPoseFrameをrenderer parameterへ投影
- capability / limitation / healthをCoreへ返す

Avatar FPSが落ちてもCore Body Stateの正本を失わない。

---

## 9. GUI / Admin

Issue: #351

GUIはtyped Read Model / explicit Command APIを使う。

禁止:
- GUIからDomain object直接書換え
- GUI都合でExecutive/Emotion/Body Motionを決定
- secret/raw promptの無制限表示

Debug overrideが必要なら明示Debug Authority / environment gateを通す。

---

## 10. Validation Labs

Issue: #352

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

## 11. Development Tooling

Issue: #353

- architecture visualizer
- issue/dependency visualization
- fixture/export tools
- diagnostics viewers

等。

Toolingはproduction decision Authorityを持たない。

---

## 12. Public Contract classes

Subsystem接続は用途に応じて:

- typed Event stream
- async request/result
- HTTP / SSE / WebSocket
- message queue
- process-local Port

を選べる。

Transport形式をDomain意味Contractと混同しない。

---

## 13. Concurrency / Isolation

各Subsystemは独立lane / worker / processで実行可能にする。

### Streaming burst

大量comment時:
- bounded ingress
- aggregation / coalescing
- priority
- representative event extraction
- backpressure

Core event queueを無制限に埋めない。

### Game

realtime loopをCore LLM latencyへ従属させない。

### Avatar

rendering/output slowdownでBody Core loopをblockしない。

### GUI

slow clientでCore state publicationをblockしない。

---

## 14. Failure / Recovery

Subsystem failure:

```text
available
→ degraded
→ unavailable
→ recovering
→ available
```

Coreはtyped availability eventを受け、必要ならExecutiveがGoal/Activityを再評価する。

Subsystem側で勝手にCore Goalを変更しない。

retry/reconnectはbounded。

---

## 15. Lifecycle

Core process lifecycleとSubsystem lifecycleを分離する。

- Core起動前/後にSubsystem接続可能
- Subsystem restart可能
- shutdown順序を明示
- pending operation cancellation
- health/readiness

Streaming停止がCore shutdownを意味しない。
Game session終了がCore shutdownを意味しない。
Avatar切断がBody Core停止を意味しない。

---

## 16. V1から継承する教訓

維持:
- Streaming Subsystem分離
- Avatar output separation
- Render/Browser validation labs
- typed Event/Result
- GUI non-authority

追加:
- Game Skill AIを正式境界化
- Skill AIとCore cognitive AIを分離
- frame-level Game controlをExecutive LLMから分離
- massive stream inputをCoreへ同期直列投入しない
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
- frame-level loopはCore Executive LLM latency非依存
- game event/result→Core Appraisal
- game commentaryはCore Speech path
- user interruption / quit intentでsession control可能
- game agentがCore Goal Authorityを持たない

### Avatar
- BodyPoseFrame projection only
- renderer unavailableでもCore Body維持

---

## 18. Design Gate

- [ ] #345が本書をcanonicalとして参照
- [ ] Streaming / Avatar / GUI / Labs / Toolingがpublic contract原則に一致
- [ ] Game Skill Work Issueを追加
- [ ] Game Skill AIとCore cognitive AIを分離
- [ ] Streaming burst / Game realtime / Avatar renderingがCore LLM latencyから独立
- [ ] Skill AIがExecutive Authorityを奪わない

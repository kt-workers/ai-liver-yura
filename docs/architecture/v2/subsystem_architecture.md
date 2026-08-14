# AI Liver ゆら V2 Subsystem / Skill AI Architecture

Status: Draft / V2 Design Gate / Streaming Boundary Reconciled 2026-08-14
Parent architecture: `docs/architecture/v2/system_architecture.md`
Plugin architecture: `docs/architecture/v2/plugin_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #345
Streaming boundary reconciliation: #394
Root management: #317

## 1. 目的

Subsystemは、ゆらCoreとは独立したsystem boundaryを持ち、Core public contractを通して協調する。

YouTube配信・ゲーム・Avatar等の専門機能がCore Executiveの自由意志・Goal Authorityを奪わず、高速・専門的なAIや外部APIを独立利用できる構造を定義する。

特に外部サービスを伴う機能では、**ゆらが何をするかを決めるAuthority**と、**外部サービスを具体的に操作・観測する実装**を分離する。

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

外部サービス固有のSDK、認証、resource ID、protocol、retry/rate-limit処理はSubsystemまたはInfrastructure側に閉じ、Core Domain / Runtimeへ流出させない。

---

## 3. Authority境界

Subsystemが専門AIを持っても、ゆらのconscious Goal / Action selectionはCore Executive #328が所有する。

```text
Core Executive / Goal State
→ high-level Intent / Goal / Strategy
→ generic Activity / Capability Request
→ Subsystem Capability Adapter
→ Subsystem Skill Runtime / External Adapter
→ actual external action / observation
→ typed Event / Execution Result
→ Core Appraisal / Attention / Executive
```

### 3.1 Decision Authority

Coreが所有する:

- 何をしたいか
- Activityを開始/継続/停止するか
- 外部Capabilityを利用するか
- 外部結果を受けてGoalを再評価するか

ユーザー発言は重要なEventだが無条件命令ではない。外部操作要求も通常のInput Meaning → Executive → Activity/Capability経路を通す。

### 3.2 Execution Authority

Subsystemが所有する:

- 受理済みCapability Requestを具体的外部API / protocolへ変換すること
- provider固有precondition / readiness / rate-limit / retry
- 実際の外部操作結果をExecution Resultとして返すこと

SubsystemはCoreのGoalを勝手に作らず、受理済み要求の実行者として振る舞う。

### 3.3 Observation Authority

外界の状態は複数sourceから認知できる。

- Subsystem / Provider APIによる観測
- 外部sensor / adapterによる観測
- ユーザーからの自然言語報告

provider観測はtyped External ObservationとしてCoreへ渡す。ユーザー報告は通常のInput Meaningを通し、`user_report`等のprovenanceを保持する。

API確認済み事実とユーザー報告を無条件に同一Authorityへ昇格しない。source / provenance / confidence / observed_atを保持し、必要なら後続観測でreconcileする。

### 3.4 Actual Fact

Intent、Capability Request、Character発話だけで外部操作成功を確定しない。

```text
intent/requested
→ accepted
→ subsystem started
→ provider applied/observable
→ completed | failed | cancelled | timed_out
```

外部操作のActual FactはSubsystemのtrusted Execution Result / Observationによって確定する。

### 3.5 Coreに持ち込まないもの

Core production codeはSubsystemの存在をgeneric Capability / Event / Resultとして扱う。

Core Domain / Runtimeのclass、file、port、state、scheduler責務へ次を持ち込まない:

- YouTube API / Google SDK
- OBS WebSocket
- OAuth / credential / token cache
- broadcast ID / liveChat ID
- OBS scene / source / input固有型
- provider固有error / rate-limit型
- `YouTube*` / `OBS*` / `LiveChat*`等のprovider固有class
- 配信ドメインとしての`stream/streaming`をCore専用class/file/runtime責務として固定すること

汎用programming conceptとしてのevent stream等は別だが、配信SubsystemのDomainをCore所有物として表現してはならない。

Subsystem側は自らのpublic contract / capability metadata内で配信Domain語彙を持ってよい。

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

Streaming Subsystemは、**ゆらが選択した配信Activityを外部配信環境で実行し、配信環境を観測し、viewer comment等をCoreへ入力する独立Subsystem**である。

### 5.1 責務

- 配信Capabilityの公開
  - prepare / readiness check
  - start
  - end / stop
  - status observation
- YouTube等の配信サービスAdapter
- OBS等の配信実行環境Adapter
- comment ingestion
- rate limit / reconnect
- moderation support
- chat aggregation / ranking / summarization signal
- external stream/broadcast health observation
- typed viewer / broadcast observation events
- provider固有Execution Resultの正規化

自然言語commentはInput Meaningへ渡せる。
大量commentをCore Executiveへ1件ずつsync blocking投入しない。

### 5.2 Coreから見た配信操作

Coreは`YouTubeStartRequest`や`OBSSceneCommand`を生成しない。

Subsystemが登録したCapabilityをgeneric Capability境界から利用する。

```text
User: 「配信準備して」
→ Input Meaning
→ Executive decision
→ Activity / generic Capability Request
→ Streaming Subsystem
→ provider readiness / preparation
→ Execution Result
→ Actual Fact / Appraisal
```

```text
User: 「配信を開始して」
→ Input Meaning
→ Executive decision
→ generic Capability Request
→ Streaming Subsystem
→ OBS / YouTube等のprovider操作
→ applied/completed | failed
→ Execution Result
→ Coreが結果を認知
```

ゆら自身が配信を開始・終了したように振る舞えるが、Core実装そのものはprovider非依存である。

### 5.3 OBS / 配信環境の準備範囲

OBS profile、scene graph、source配置、encoder等の**設定構築は原則として事前に用意する**。

Streaming Subsystemは、利用可能なpreconfigured環境についてreadiness確認や、配信実行に必要な限定的runtime操作を行える。

任意のOBS構成をゆらがゼロから設計・再構築することは#347の必須責務にしない。将来必要なら別Capability / Work Issueとして追加する。

### 5.4 配信状態の認知

ゆらは最低限、次の外界状態を認知可能にする。

- 準備前 / unavailable
- preparing / ready
- starting
- live / broadcasting
- ending
- ended
- degraded / disconnected / unknown

状態sourceは1つに固定しない。

#### Provider/API観測

```text
YouTube / OBS / other provider
→ Streaming Subsystem observation
→ typed External Observation
→ Appraisal / Attention / Executive
```

#### ユーザー報告

```text
User: 「配信始まったよ」
→ Input Meaning
→ reported external fact candidate
→ source=user_report
→ Appraisal / Attention / Executive
```

後からprovider観測が得られた場合はprovenanceを保持したままreconcileできる。

### 5.5 Streaming Skill AI

利用可能:
- spam / duplicate grouping
- topical clustering
- moderation candidate
- representative comment selection
- rolling summary / trend signal

ただし次の最終Authorityは持たない:

- どのcommentへ反応するか
- 配信を開始/継続/終了するGoal
- What-to-say
- #333 AttentionFocusState直接mutation

### 5.6 Output / Execution Result

accepted Activity / Capability Requestに従い、Subsystemは利用可能な外部Capabilityを実行する。

provider固有operationはSubsystem内で完結し、Coreへ返すのはprovider非依存のExecution Result / External Observationである。

Characterが「配信を始めた」と発話しただけでは開始Factにしない。provider適用結果または信頼済み観測が必要。

### 5.7 Streaming Subsystemが存在しない場合

Streaming Subsystem未導入・停止・認証不能でもCoreは通常稼働する。

Capabilityは`unavailable`となり、Executiveはその事実を受けて別行動を選択できる。

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

### Core側共通境界

CoreはSubsystemごとの具象Client/DTOを増やすのではなく、Foundationのgeneric contractを利用する。

候補:

```text
CapabilityDescriptor
CapabilityRequest
ExecutionResult
ExternalObservationEvent
AvailabilityEvent
```

`CapabilityDescriptor`はSubsystemが提供する意味・前提・入出力schemaを記述できるが、Core Runtime自身がYouTube/OBS等のprovider型を定義しない。

Subsystem固有のprovider-neutral contractが必要な場合はSubsystem側public boundaryに置き、Core Domain ownershipへ昇格させない。

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

配信操作中の外部API待ち、OBS接続待ち、comment polling/reconnectもCore Executive/Body/Speech laneをblockしない。

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

外部操作がpartial failureの場合、成功扱いへ丸めない。provider適用状態を可能な範囲で観測し、`failed` / `partial` / `unknown`等のtyped resultとして返す。

---

## 15. Lifecycle

Core process lifecycleとSubsystem lifecycleを分離する。

- Core起動前/後にSubsystem接続可能
- Subsystem restart可能
- shutdown順序明示
- pending operation cancellation
- health/readiness

配信終了 / Game session終了 / Avatar切断をCore shutdownと同一視しない。

配信Activity lifecycleとStreaming Subsystem process lifecycleも分ける。配信が終了してもSubsystemはcomment/history/status finalizationや次回準備のため稼働し得る。

---

## 16. V1から継承する教訓

維持:
- Streaming Subsystem分離
- Avatar output separation
- Render/Browser validation labs
- typed Event/Result
- GUI non-authority
- CoreからYouTube/OBS具象を排除する責務境界

追加/改善:
- 「Coreから分離したのでSubsystemが自由にGoalを決める」という誤解を禁止
- ゆらの配信意思決定とprovider操作実装を分離
- 配信状態観測をprovider API / user report等の複数provenanceで扱う
- external operation Actual FactをExecution Resultで確定
- OBS構成作成とruntime配信実行を分離
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
- user request→Input Meaning→Executive→generic Capability Requestの経路で配信準備/開始/終了を要求できる
- CoreにYouTube/OBS SDK・OAuth・provider ID・provider固有class/portを持たない
- 配信ドメインのstreaming専用Runtime責務をCoreへ置かない
- Streaming Subsystemがprovider固有操作を所有する
- preconfigured OBS環境のreadiness / runtime executionを扱え、OBS構成作成を必須責務にしない
- API等から配信開始前/ready/live/ended/degradedを観測できる
- user reportによる配信状態とprovider観測のprovenanceを区別できる
- Execution Result / trusted Observationより前に外部操作成功Factを作らない
- burst commentsでCore starvationなし
- aggregated signal / natural-language inputをtyped経路へ渡す
- Core Executiveがresponse/activity authority維持
- Subsystem unavailableでもCore通常稼働

### Boundary Scan
- Core production codeに`YouTube*` / `OBS*` / `LiveChat*` provider固有型・SDK importがない
- 配信ドメインの`stream/streaming`がCore専用class/file/runtime責務として流入していない
- Subsystem→Core内部Domain object直接importがない

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
- [x] #394でStreamingのCore Decision / Subsystem Execution / External Observation境界を再整理
- [x] 配信操作をゆらのActivityとして許可しつつYouTube/OBS具象をSubsystemへ隔離
- [x] provider観測とuser reportのprovenance差を明記
- [x] 外部操作Actual FactをExecution Result / trusted Observationに限定

実装時は#347で本境界をUnit / Adjacent / 実OBS・YouTube Verificationする。

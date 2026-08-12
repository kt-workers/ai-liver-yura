# AI Liver ゆら V2 Canonical System Architecture

Status: Draft / V2 Design Gate
Canonical branch: `rebuild/v2-foundation`
Root management: #317
Base lineage: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`

## 1. この文書の役割

この文書は、AI Liver ゆら V2の**唯一のシステム構造正本**である。

V2では現行実装を修復し続けない。旧Issue / PR / branch / docsから重要な要求と設計判断を回収するが、旧コードを正本として継承しない。

設計→Module Contract→Unit→Adjacent Contract→Integration→System Verificationの順で再構築する。

詳細設計は本書の責務境界を変更せず補足する subordinate canonical として置く。

- Speech Pipeline: `docs/architecture/v2/speech_pipeline_architecture.md`

---

# 2. システム境界

```text
AI Liver Yura System
│
├─ Core
│  ├─ Brain
│  ├─ Body
│  └─ Plugin Architecture
│
└─ Subsystems
   ├─ Avatar / Live2D / 3D presentation
   ├─ Streaming
   ├─ GUI / Administration
   ├─ Validation Labs
   └─ Reference / Development Tooling
```

## 2.1 Core

Coreは「ゆら自身」の最小実行単位である。

Coreは以下を満たさなければならない。

- Pluginが0個でも起動できる
- Avatarがなくても起動できる
- Streamingがなくても起動できる
- GUIがなくても起動できる
- TTSが利用不能でもText/Silence判断と内部状態更新を継続できる
- Persistenceが利用不能でも安全に縮退できる
- 外部Outputが切断されてもCore loopを破壊しない
- graceful shutdown / cancellationを正常経路として扱う
- Speech playbackやTTS待機でBrain decision loopを停止しない
- Body realtime更新がLLMやTTSの待機時間に引きずられない

## 2.2 Subsystem

SubsystemはCoreの外側にある独立システムである。

SubsystemはCoreの内部Domain objectへ直接import依存しない。Coreが公開するPort / Event / DTO / HTTP / SSE / WebSocket等の明示契約を介して接続する。

Subsystem障害でCoreが停止してはならない。

## 2.3 Plugin

PluginはCoreへ「追加能力」を与える拡張である。

定義:

> **Pluginを1つも登録しなくてもCore本体が成立するものだけをPluginと呼ぶ。**

Pluginは次を行ってよい。

- Capabilityを登録する
- Activityを追加する
- 外部Tool / Game / Search等の能力を提供する
- CoreのCommandに対してtyped execution resultを返す

Pluginは次を行ってはならない。

- Core Domainの正本になる
- Bootstrap必須依存になる
- Brain内部状態を直接書き換える
- raw user textを独自解釈してCoreの意思決定を迂回する
- Character / Bodyへ直接命令しCommanderを迂回する

---

# 3. Clean Architectureの依存方向

原則:

```text
Domain / Contracts
        ↑
Application / Use Cases / Runtime orchestration
        ↑
Ports
        ↑
Adapters / Providers / UI / External systems
```

内側は外側を知らない。

禁止:

```text
Domain → OpenAI SDK
Domain → FastAPI
Domain → VOICEVOX
Domain → Live2D
Brain → concrete GUI
Body → concrete Avatar model
Core → concrete Plugin implementation
```

許可:

```text
Domain → Protocol / typed contract
Adapter → Domain Port implementation
Subsystem → Core public API / Event contract
Plugin → Plugin Port / Capability contract
```

---

# 4. Core全体の因果フロー

```text
External Input / Internal Timer / Execution Result
    ↓
Input Gateway / Event normalization
    ↓
[LLM-1] Input Meaning           # natural-language input only
    ↓ StructuredInputMeaning
Situation / Appraisal
    ↓
Internal State + Memory + Current Activity + Capability Snapshot
    ↓
[LLM-2] Commander
    ↓ SystemCommand
    ├───────────────┬───────────────────┬───────────────────┐
    ↓               ↓                   ↓                   ↓
Activity         SpeechIntent        BodyIntent          Silence/Wait
Execution           ↓                   ↓
    ↓           [LLM-3]             [LLM-4]
Execution       Character Speech     Body Motion
Result          Realizer             Planner
    ↓               ↓                   ↓
    │         CharacterUtterance     BodyMotionPlan
    │               ↓                   ↓
    │         Semantic Validation   Deterministic Body
    │               ↓              Constraints / IK /
    │         Speech Performance    Continuous Control
    │               ↓                   ↓
    │         PreparedSpeech        BodyPoseFrame
    │         Candidate                 ↓
    │               ↓             Avatar/Output Port
    │         Speech Presentation
    │         Pipeline
    │               ↓
    │         Text / TTS / Audio
    │
    └──────────── execution / presentation results ────────┘
                         ↓
                Event / Appraisal feedback
                         ↓
                   next Core cycle
```

重要:

- CharacterとBodyは**兄弟Realizer**である。
- Characterの出力をBodyの意思決定正本にしない。
- Bodyの出力をCharacterの発言意味正本にしない。
- 両方がCommanderの同じSystemCommandに従う。
- Speechの**生成**と**提示・再生**は別の実行レーンとして扱う。
- Presentation完了は次Core cycleの開始条件ではない。

---

# 5. LLM責務を4つに固定する

## 5.1 LLM-1: Input Meaning LLM

### 責務

外部自然言語を、下流が再解釈不要な型付き意味へ変換する。

入力例:

- user text
- normalized source metadata
- bounded conversation reference context
- current interaction context needed for anaphora/reference resolution

出力例:

```text
StructuredInputMeaning
- speech_act
- primary_intent
- expected_response
- target
- entities
- references
- information_provided
- negated
- hypothetical
- temporal_relation
- confidence
- unresolved_fields
```

### Authority

**open-ended user natural languageのsemantic authorityはここだけ。**

下流Runtime / Activity / Plugin / Confirmation / Bodyはraw textをkeyword / regex / substringで再分類しない。

### 失敗時

- schema invalid
- confidence不足
- target/reference unresolved

の場合はfinite lexical fallbackへ戻さない。

typed `unresolved / clarification_required` としてCommanderへ渡す。

---

## 5.2 LLM-2: Commander LLM

### 責務

「今、ゆらは何をする／しない」を決める**意識的行動の唯一のauthority**。

入力:

- StructuredInputMeaning
- Situation/Appraisal
- Emotion / Desire / Drive / Motivation
- Moral / Values appraisal
- Memory evidence
- Relationship context
- Current Activity snapshot
- Capability registry
- execution facts
- turn / interruption context
- prepared / queued / presenting speech facts
- safety / authority constraints

出力:

```text
SystemCommand
- command_id
- intent
- priority
- speech_intent?      # 何を伝えるか。文体ではない
- body_intent?        # 何を身体で表現/実行するか。関節角ではない
- activity_request?   # start/stop/continue/switch/execute
- attention_intent?
- memory_operation_intent?
- silence_intent?
- question_budget
- new_direction_budget
- interruptibility
- preconditions
- forbidden_claims
- rationale_summary   # 診断用の有限情報のみ
```

### Commanderがしないこと

- Characterらしい最終日本語を書く
- TTS speed/pitch等のengine parameterを決める
- Body joint angle / Live2D parameterを直接生成する
- execution前に「実行済み」という事実を作る
- Plugin固有内部APIを直接呼ぶ

### Command validation

LLM出力はそのまま実行しない。

```text
Commander output
→ Schema validation
→ Capability validation
→ Authority / Safety validation
→ Execution preflight
→ accepted command
```

実行結果は`ExecutionResult`としてBrainへ戻す。

Speechの場合、候補準備とPresentation commitを同一時点に固定しない。先行準備済み候補を実際に提示する前に、最新turn/contextでrevalidateする。

---

## 5.3 LLM-3: Character Speech LLM

### 責務

Commanderが確定した`SpeechIntent / SemanticUtterancePlan`を、Character Definitionに沿った自然な発話へ変換する。

```text
SpeechIntent
+ Character Language Profile
+ Interpersonal Style
+ Discourse Context
+ high-level Expression Intent
        ↓
Character Speech LLM
        ↓
CharacterUtterance
```

### 入力してよいもの

- 発言すべき意味
- required / optional / forbidden semantic content
- speech act
- target
- question/new-direction budget
- Character language style
- bounded discourse information
- high-level expression tone

### 入力してはいけないもの

原則として、Characterが再解釈して意味決定できるraw内部情報を渡さない。

- raw Emotion / Desire / Drive numeric state
- raw Activity implementation state
- raw execution payload
- provider secret
- Body joint state
- TTS engine parameter

### 出力

```text
CharacterUtterance
- speech
- phrase boundaries
- linguistic emphasis
- linguistic hesitation/filler
- semantic realization references
```

音響的pause / pitch / speedの実数はここで生成しない。

### 意味保持

Characterらしさは**意味を変えてよい権限ではない**。

CharacterUtteranceは独立semantic verifierでSpeechIntentとの整合を検証する。

Character生成は、別Speechのaudio playback完了を待つ必要がない。

---

## 5.4 LLM-4: Body Motion LLM

### 責務

Commanderが確定した`BodyIntent`を、Canonical Bodyが実行可能な構造化Motion Planへ変換する。

```text
BodyIntent
+ current pose / velocity
+ Skeleton Profile
+ DOF / Joint Limits
+ Body Expression Style
+ current Emotion-derived expression baseline
+ Attention / Speech synchronization context
        ↓
Body Motion LLM
        ↓
BodyMotionPlan
```

### Body LLMが生成するもの

- target body region / chain
- end-effector goals
- spatial direction / target
- trajectory phases
- timing category
- coordination intent
- balance requirements
- expression overlays
- priority / interruptibility

### Body LLMが生成しないもの

- Live2D Parameter名
- model固有Bone名
- raw renderer command
- 安全検証なしの最終関節値
- 毎フレームの高頻度Streaming token

### なぜLLMの後にdeterministic solverが必要か

LLMは意味から自由度の高い動作構成を作るが、身体制約の最終authorityにはしない。

```text
BodyMotionPlan
→ Structural validation
→ Joint/DOF/limit validation
→ Motion compiler
→ IK / Kinematics / Balance
→ trajectory smoothing
→ Continuous Controller
→ BodyPoseFrame
```

これにより、創造性と身体安全性・連続性を分離する。

---

# 6. Brain modules

Brainは以下の独立Module Contractへ分ける。

## B01 Input Gateway

外部入力をSource非依存Eventへ正規化する。

Raw device/API差をBrain Domainへ持ち込まない。

## B02 Input Meaning

LLM-1とschema validator。

## B03 Situation / Appraisal

外部出来事・意味・内部状態・記憶を「ゆらにとって何を意味するか」へ評価する。

## B04 Internal State

少なくとも以下を独立facetとして保持する。

- Emotion
- Desire
- Drive
- Motivation
- Moral / Values appraisal
- Interest / curiosity toward targets
- Relationship state
- arousal / energy等の必要な連続状態

`current value / delta / cause / observed_at`を分離し、LLMの自由文で直接上書きしない。

## B05 Memory

Memoryは最低限次を区別する。

- Working / Short-term
- Episodic
- Semantic
- Relationship
- Preference / Interest
- Activity / Skill memory（必要な場合）

Memory書込みはCandidate→importance/novelty/persistence/confidence→routing→merge/update/contradictionの境界を持つ。

Memoryは現在実行事実より強いauthorityを持たない。

## B06 Commander

LLM-2 + Command validator。

## B07 Activity Runtime

- Activity definition
- Activity instance
- state
- start / stop / continue / switch
- capability requirements
- execution result

Activityの意味選択はCommanderが所有し、Activity implementationがraw textから意思決定を奪わない。

## B08 Action / Execution Coordination

SystemCommandをtyped actionへ分配し、resultを収集する。

- Speech preparation / presentation intent
- Body
- Plugin capability
- Memory operation
- Silence / Wait

## B09 Character Speech Realizer

LLM-3 + semantic validation。

## B10 Speech Performance

CharacterUtteranceとExpression Intentからengine-independentなspeech performanceを作る。

- phrase timing
- acoustic pause
- speed intent
- pitch contour intent
- intonation
- volume/breathiness intent

具体的provider値への変換はTTS Adapter。

## B11 Speech Pipeline

発話のDecision/PreparationとPresentation/Playbackを分離する。

```text
Decision / Preparation Lane
  Appraisal
  → Commander
  → Character Speech
  → Semantic Verification
  → Speech Performance
  → PreparedSpeechCandidate
             ↓
        bounded queue
             ↓
Presentation Lane
  pre-play revalidation
  → optional TTS preparation
  → text/audio presentation
  → Body/viseme synchronization
  → SpeechPresentationResult
```

### 不変条件

- 現在Speechの再生完了を次候補生成開始条件にしない
- TTS/audio playbackをBrain decision loopのblocking awaitにしない
- Speech A再生中でも条件が許せばSpeech BのAppraisal/Commander/Character生成を進められる
- queueはboundedとし無制限先読みしない
- prepared candidateは発話確定ではない
- Presentation直前にturn/context/state/execution factsを再検証する
- user input等でstaleになった未再生候補をcancel/supersedeできる
- 次候補を生成できることと、次候補を実際に喋ることを分離する

詳細: `docs/architecture/v2/speech_pipeline_architecture.md`

## B12 Autonomy / Turn Management

Eventがなくても時間経過と内部状態からAppraisal→Motivation→Commanderを起動できる。

ただし「自律発話専用の別人格/別意思決定器」を作らず、ユーザー応答と同じCommander authorityを使う。

型付きで管理する。

- turn ownership
- interruption
- pending response
- autonomous initiative
- silence
- speech preparing / prepared / queued / presenting / completed
- candidate stale / superseded / cancelled

自律発話間隔を固定sleepや「前発話終了後に次生成開始」という直列構造で作らない。

## B13 Runtime Kernel

- Event Queue / Buffer
- prioritization
- RuntimeCoordinator
- cancellation
- clock
- scheduler
- health
- diagnostics
- Decision / Preparation / Presentation / Body realtime worker coordination

Domain判断を持たず、各Moduleを協調させる。

一つのTask/workerが長時間awaitしても他レーンを停止しない。

---

# 7. Body modules

## D01 Canonical Body Model

モデル非依存の身体正本。

- joint hierarchy
- normalized segment lengths
- DOF
- joint limits
- relaxed ranges
- anatomical left/right
- end effectors
- kinematic chains
- root / center-of-mass representation

## D02 Body State

- current pose
- current velocity
- motion history
- active motion plan
- attention state
- speech synchronization state

## D03 Body Expression Projection

Emotion / Motivation / Interaction / Character Body Styleを、高レベルBody expression contextへ投影する。

固定Pose名に変換しない。

## D04 Body Motion Planner

LLM-4を所有する。

BodyIntent→BodyMotionPlan。

## D05 Motion Compiler / Solver

- IK
- forward/inverse kinematics
- joint limit
- balance
- collision/self-intersection constraint（必要な範囲）
- trajectory
- continuity

## D06 Continuous Controller

BodyMotionPlanとbaseline expressionを高頻度で合成し、current poseから次frameを生成する。

必ずNeutral/Homeへ戻す設計を禁止する。

## D07 Realtime Layers

Body full-motion計画とは独立して低遅延で重ねる。

- blink
- eye tracking / gaze
- breathing
- viseme / lip sync
- tiny continuous motion

Speech PipelineのPresentation Laneでcommitされた実Speechだけをviseme/speech sync対象にする。

## D08 BodyPoseFrame

Core Bodyのcanonical output。

Avatar / GUI / Stick modelはこれを投影するだけで、Body意思決定を持たない。

---

# 8. Character Definition

Characterの人物設定はHuman-readableな`Character Definition / Character Bible`を正本とする。

Runtime Profileはそのprojectionであり正本ではない。

分離:

```text
Character trait       → static Character Definition
current emotion       → dynamic Internal State
current desire        → dynamic Internal State
recent interest       → Memory / Interest
relationship closeness→ Relationship State
```

Character設定を根拠に、現在存在しないEmotion/Desire/Interestを捏造しない。

Projection先:

- Character Language Profile
- Character Voice Style
- Character Body Expression Style

---

# 9. Plugin Architecture

## Plugin contract

```text
PluginManifest
- plugin_id
- version
- provided_capabilities
- required_core_contract_version
- permissions
- health policy

CapabilityDescriptor
- capability_id
- input schema
- output schema
- side effect class
- authority requirements
- timeout / cancellation policy
```

## Plugin lifecycle

```text
discovered
→ validated
→ registered
→ available / degraded
→ executing
→ unavailable / stopped
```

CoreはPlugin未登録時でも起動する。

Plugin failureはtyped `unavailable / failed / timed_out`としてCoreへ返す。

---

# 10. Provider / AdapterとPluginを混同しない

OpenAI / local LLM / VOICEVOX / PostgreSQL / HTTP / Live2D等は、DomainのPortを実装する**Infrastructure Adapter / Provider**である。

「Core Plugin」とは別概念。

例:

```text
InputMeaningGeneratorPort
CommanderGeneratorPort
CharacterSpeechGeneratorPort
BodyMotionGeneratorPort
SpeechSynthesizerPort
MemoryRepositoryPort
ClockPort
```

各LLM roleは同じProviderを共有してもよいが、**role contract / prompt / schema / model policyは別**にする。

Provider failureをrole semanticsへ漏らさない。

TTS Providerの待機時間をCore decision loopへ伝播させない。

---

# 11. Subsystems

## S01 Avatar Presentation

Core BodyPoseFrame / speech timing / expression outputをLive2D / 3D / Stick Figureへ投影する。

モデル固有parameterをCoreへ逆流させない。

## S02 Streaming

YouTube / OBS / chat ingestion / moderation / ranking / streaming health等を所有する独立Subsystem。

Core Pluginではない。

StreamingなしでCoreは成立する。

## S03 GUI / Administration

- status
- config
- diagnostics
- read models
- operator command boundary

GUIがEmotion判定・Commander判断・Body motion生成を持たない。

## S04 Validation Labs

Moduleを単体で実LLM/実Provider検証する再利用可能Harness。

Lab専用ロジックをproduction logicの代わりにしない。

Speech Pipeline Lab/traceではgeneration timingとpresentation timingを別々に観測できるようにする。

## S05 Reference / Development Tooling

Character reference analysis、architecture graph、Issue graph等。

Product Runtimeとは分離する。

---

# 12. 実行事実とTruthfulness

Commandの「意図」と「実際に起きたこと」を分離する。

```text
requested
→ accepted
→ planned
→ started
→ observable/applied
→ completed

or
→ rejected / unsupported / failed / cancelled / timed_out
```

Characterはexecution statusより先に実行完了を主張できない。

Speech/Body/Pluginの結果は独立Resultとして保持する。

Speechではさらに、内容準備と実際の提示を分離する。

```text
prepared
→ queued
→ revalidating
→ ready_to_present
→ presenting
→ completed

or
→ cancelled / superseded / stale / rejected / failed
```

`prepared`は「話した」という事実ではない。

結果は次cycleのAppraisalへ戻す。

---

# 13. Natural Language Semantic Policy

禁止:

- `_KEYWORDS`
- `_MARKERS`
- finite phrase list
- regex
- substring
- startswith / endswith

をopen-ended自然言語の意味・意図・感情強度・claim・speech actのauthorityにすること。

例外:

- protocol token
- enum
- exact technical identifier
- domain dataそのものが語彙である機能

自然言語の意味理解が必要なら、担当Semantic LLM/Interpreterへ戻す。

Interpreter失敗時はfail closed / clarification。

---

# 14. Memory設計原則

```text
Event / Conversation / ActivityResult / StateChange
→ Memory Candidate
→ Importance / Novelty / Persistence / Confidence / Relation
→ Router
→ Store / Merge / Update / Contradiction
→ Deferred Consolidation
→ Retrieval Ranking
```

Retrievalは少なくとも次を考慮する。

- semantic relevance
- recency
- importance
- relationship relevance
- current activity/topic
- current motivation
- confidence

無関係なMemory本文を大量にLLMへ渡さない。

Speech Pipelineのprepared候補はMemoryの確定発話履歴にしない。実際にcommit/presentされた事実を区別する。

---

# 15. Body不変条件

- fixed Pose/Motion Presetを主経路にしない
- Emotion名→Motion名の1対1変換をしない
- process phase→Motion名の1対1変換をしない
- raw user text→Body motionを直接行わない
- current poseから連続生成する
- Home/Neutral snap-backをしない
- anatomical left/rightをCore正本とする
- renderer mirrorはAdapter責務
- 360度は3D全方向
- 2D/Live2D制約をCanonical Bodyへ逆流させない
- Character Body Styleは固定Poseではなくcost/timing/coordination/styleへ作用させる
- TTS timingがある場合はphoneme/viseme timelineを利用する
- Speech presentation待機でBody realtime updateを停止しない

---

# 16. Speech Pipeline不変条件

詳細正本: `docs/architecture/v2/speech_pipeline_architecture.md`

## 16.1 生成と再生を別レーンにする

```text
Decision / Preparation Lane
  Appraisal → Commander → Character → Validation → Performance → PreparedSpeechCandidate

Presentation Lane
  revalidate → TTS/audio → playback → Body/viseme → result
```

Presentation LaneはDecision Laneをblockしない。

## 16.2 開発初期要求の明文化

**現在の発言が終わるまで次発話内容の生成処理が滞らないこと。**

Speech Aを再生中でも、Commanderが次候補準備を許可すればSpeech BのCharacter generationを進める。

禁止:

```text
await speech_A_playback_complete()
→ next Appraisal
→ next Commander
→ speech_B generation
```

## 16.3 先行生成と連続発話を混同しない

先行生成した候補は無条件に再生しない。

Presentation commit直前に最低限次を確認する。

- turn ownership
- user input
- topic/context revision
- Emotion/Motivationの重大な変化
- capability/execution facts
- candidate preconditions / expiry
- cancellation / supersede

## 16.4 bounded queue

prepared候補は有限数に制限する。

無制限の未来発話生成、固定3発話先読み、queueの機械的全消化を禁止する。

## 16.5 latency acceptance

fake playback durationを5秒→20秒へ伸ばしても、次Character generation startが同じ15秒だけ後ろへ移動する構造をFAILとする。

発話間隔は自然なTurn/Discourse/Motivationから生じてもよいが、**前Speech再生待ち + 次LLM生成待ちの不要な直列加算**で長くしてはならない。

---

# 17. Graceful Degradation / Shutdown

Coreは以下を正常なdegraded stateとして扱う。

- Body output unavailable
- TTS unavailable
- DB unavailable
- Plugin unavailable
- Subsystem unavailable

retryはbounded backoff / rate-limited diagnosticsを使い、高頻度失敗ログでCoreを飽和させない。

TTS unavailable時もSpeech Decision / Character generation / Text presentationを可能な範囲で継続する。

Shutdown:

```text
shutdown requested
→ stop accepting new external work
→ stop creating new prepared speech candidates
→ cancel/supersede queued candidates
→ cancel/finish current interruptible work/presentation
→ stop frame/event production
→ close adapters/workers
→ await RuntimeCoordinator
→ persist minimum state if available
→ event loop close
```

pending task / unretrieved exceptionを残さない。

---

# 18. Observability

全Moduleは本文ではなくtyped traceを優先する。

最低共通field:

- trace_id
- event_id
- command_id
- activity_id
- candidate_id / presentation_id（Speechの場合）
- module
- revision
- started_at / completed_at
- outcome
- error_class

Speech Pipelineは少なくとも次を時刻付きで観測する。

```text
command_decision_started_at
command_decision_completed_at
character_generation_started_at
character_generation_completed_at
candidate_queued_at
preplay_revalidation_at
tts_prepare_started_at / completed_at
presentation_started_at / completed_at
candidate_cancelled_at / superseded_at / stale_at
```

`next_character_generation_started_at`がprevious presentation durationに比例して遅延する構造を検出可能にする。

Raw Prompt / API key /不必要なuser text / memory bodyをdiagnosticsへ無制限に複製しない。

---

# 19. Module Development Gate

すべてのWork Issueは次の順を守る。

## Gate 0: Design

- responsibility
- input contract
- output contract
- authority
- failure policy
- non-goals
- acceptance cases

をcanonical docsへ記録。

## Gate 1: Unit

対象Module単体。

隣接Moduleを修正して通してはいけない。

Speech Pipelineではfake clock / fake playbackでnon-blocking concurrencyをUnit acceptanceに含める。

## Gate 2: Adjacent Contract

実際の隣接ModuleとのDTO/schema/authority boundaryを検証。

## Gate 3: Integration

複数Workを接続し、failure/cancellationも含めて確認。

Speech Integrationではplayback中next-generationを必須確認する。

## Gate 4: System Verification

`python -m app`等の全体起動は最後。

実LLM/実画面/実TTSが必要ならVerificationでユーザー確認まで止める。

---

# 20. V2実装順序

重要Moduleから依存順に進める。

```text
Phase A: Foundation
A1 Contracts / Runtime Kernel
A2 Character Definition minimum contract
A3 LLM Role Ports / structured output contract

Phase B: Brain minimum closed loop
B1 Input Meaning LLM
B2 Internal State / Appraisal minimum
B3 Commander LLM
B4 Activity / Execution coordination
B5 Character Speech LLM + semantic verification
B6 Speech Performance
B7 Speech Pipeline: Decision/Preparation vs Presentation concurrency
B8 Core text-loop integration

Phase C: Body
C1 Canonical Body / Skeleton
C2 Body expression context
C3 Body Motion LLM
C4 Motion compiler / IK / continuous controller
C5 Realtime gaze/blink/viseme
C6 Brain↔Body integration

Phase D: Core resilience / memory / extension
D1 Memory pipeline
D2 Autonomy / turn management
D3 Plugin architecture
D4 zero-plugin Core verification
D5 graceful degradation / shutdown

Phase E: Subsystems
E1 Avatar
E2 Streaming
E3 GUI/Admin
E4 Validation Labs
E5 Development/reference tooling

Phase F: System
F1 complete Integration
F2 performance / cost / reliability
F3 user Verification
```

Phase番号はIssue分割理由ではない。1つの責務として独立実装・検証できる単位だけWork Issueにする。

---

# 21. V2で旧設計から持ち込まないもの

- 旧branchの実装そのもの
- Compatibility pathを正規経路とみなす判断
- finite natural language semantic dictionaries
- Character LLMへの責務集中
- Character→Bodyの暗黙命令
- fixed Body pose/gesture preset中心設計
- GUI/Lab内へのproduction判断複製
- PluginをCore必須依存にする構造
- StreamingをCore Pluginとして扱う構造
- 全体起動だけでModule品質を判断する運用
- 同一Work Issueに複数active implementation lineageを持つ運用
- Speech playback完了を次LLM生成の開始条件にする直列発話Pipeline
- future speechを大量に固定生成してqueue順に必ず再生する設計

---

# 22. V2 Design Gate 完了条件

- [ ] 本文書をユーザーが確認
- [ ] 旧Open Issue/PR要求がMigration Matrixへ全件対応付けられている
- [ ] 新V2 Issue hierarchyが本文書のModule境界と一致する
- [ ] 各新Work IssueにStart / Target /依存 /検証Gateがある
- [ ] 旧実装lineageをV2へ直接mergeしないことが確認される
- [ ] V2 trunkが最古mainから開始している
- [ ] #348 Speech PipelineがBrain hierarchyへ含まれている
- [ ] playback中next-generationをRuntime/Brain Integration acceptanceへ含めている
- [ ] playback durationがnext generation startをblockしない自動テスト条件がある
- [ ] Design Gateを通過するまで製品コードを変更しない

# AI Liver ゆら V2 Canonical System Architecture

Status: Draft / V2 Design Gate
Canonical branch: `rebuild/v2-foundation`
Root management: #317
Base lineage: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`

## 1. この文書の役割

この文書は、AI Liver ゆら V2の**唯一のシステム構造正本**である。

V2では現行実装を修復し続けない。旧Issue / PR / branch / docsから重要な要求と設計判断を回収するが、旧コードを正本として継承しない。

設計→Module Contract→Unit→Adjacent Contract→Integration→System Verificationの順で再構築する。

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
External Input
    ↓
Input Gateway / Perception normalization
    ↓
[LLM-1] Input Meaning
    ↓ StructuredInputMeaning
Situation / Appraisal
    ↓
Internal State + Memory + Current Activity + Capability Snapshot
    ↓
[LLM-2] Commander
    ↓ SystemCommand / InternalDirective
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
    │         Text / TTS Port       BodyPoseFrame
    │                                   ↓
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

- Speech
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

## B11 Autonomy / Turn Management

Eventがなくても時間経過と内部状態からAppraisal→Motivation→Commanderを起動できる。

ただし「自律発話専用の別人格/別意思決定器」を作らず、ユーザー応答と同じCommander authorityを使う。

- turn ownership
- interruption
- pending response
- autonomous initiative
- silence

を型付きで管理する。

## B12 Runtime Kernel

- Event Queue / Buffer
- prioritization
- RuntimeCoordinator
- cancellation
- clock
- scheduler
- health
- diagnostics

Domain判断を持たず、各Moduleを協調させる。

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

---

# 16. Graceful Degradation / Shutdown

Coreは以下を正常なdegraded stateとして扱う。

- Body output unavailable
- TTS unavailable
- DB unavailable
- Plugin unavailable
- Subsystem unavailable

retryはbounded backoff / rate-limited diagnosticsを使い、高頻度失敗ログでCoreを飽和させない。

Shutdown:

```text
shutdown requested
→ stop accepting new external work
→ cancel/finish current interruptible work
→ stop frame/event production
→ close adapters/workers
→ await RuntimeCoordinator
→ persist minimum state if available
→ event loop close
```

pending task / unretrieved exceptionを残さない。

---

# 17. Observability

全Moduleは本文ではなくtyped traceを優先する。

最低共通field:

- trace_id
- event_id
- command_id
- activity_id
- module
- revision
- started_at / completed_at
- outcome
- error_class

Raw Prompt / API key /不必要なuser text / memory bodyをdiagnosticsへ無制限に複製しない。

---

# 18. Module Development Gate

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

## Gate 2: Adjacent Contract

実際の隣接ModuleとのDTO/schema/authority boundaryを検証。

## Gate 3: Integration

複数Workを接続し、failure/cancellationも含めて確認。

## Gate 4: System Verification

`python -m app`等の全体起動は最後。

実LLM/実画面が必要ならVerificationでユーザー確認まで止める。

---

# 19. V2実装順序

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
B6 Core text-loop integration

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

# 20. V2で旧設計から持ち込まないもの

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

---

# 21. V2 Design Gate 完了条件

- [ ] 本文書をユーザーが確認
- [ ] 旧Open Issue/PR要求がMigration Matrixへ全件対応付けられている
- [ ] 新V2 Issue hierarchyが本文書のModule境界と一致する
- [ ] 各新Work IssueにStart / Target /依存 /検証Gateがある
- [ ] 旧実装lineageをV2へ直接mergeしないことが確認される
- [ ] V2 trunkが最古mainから開始している
- [ ] Design Gateを通過するまで製品コードを変更しない

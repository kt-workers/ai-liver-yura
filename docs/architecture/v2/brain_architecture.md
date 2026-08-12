# AI Liver ゆら V2 Brain Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Parent Issue: #325
Root management: #317

## 1. 目的

Brainは、入力を理解し、出来事を評価し、内部状態と記憶を更新し、現在の状況で「ゆらが何をする／しない」を決めるCore領域である。

V2ではBrainを巨大な1本のLLM Pipelineにしない。各責務を独立Module Contractへ分け、Module単位で設計・Unit・Adjacent Contractを検証する。

Brainが使用するLLM責務は次の3つだけである。Body側のLLM-4を合わせ、システム全体で4責務に固定する。

1. LLM-1 Input Meaning
2. LLM-2 Commander
3. LLM-3 Character Speech
4. LLM-4 Body Motion（Body所有）

**Semantic Validator、Memory Summarizer、Appraisal等のために第5のLLM Roleを追加しない。**

---

# 2. Brainの境界

```text
External / Internal Event
        ↓
B01 Input Gateway
        ↓
B02 Input Meaning  ← Working Reference Context
        ↓
B03 Situation / Appraisal
        ↓
B04 Internal State
        ↓
Decision Context ← B05 Memory / Activity / Capability / Execution Facts / Turn State
        ↓
B06 Commander
        ↓ SystemCommand
B08 Execution Coordination
  ├─ B07 Activity Runtime / Plugin Capability
  ├─ B09 Character Speech → B10 Speech Performance → B11 Speech Pipeline
  ├─ Body public contract
  ├─ B05 Memory operation
  └─ Wait / Silence
        ↓
Typed Result / Fact / Event
        └────────→ next Appraisal cycle

B12 Autonomy / Turn Management
  └─ 「いつDecision Cycleを起動できるか」を管理
     「何をするか」はB06 Commanderが決める
```

Runtime KernelはBrain Domainではない。Event Queue / Scheduler / Task Coordination / cancellation / clock等はCore Foundation (#322) が所有し、BrainはPortとして利用する。

---

# 3. Authority Map

| Authority | Owner | 他Moduleがしてはいけないこと |
|---|---|---|
| open-ended外部自然言語の意味 | B02 Input Meaning / LLM-1 | Runtime/Plugin/Activityがraw textをregex等で意味分類する |
| 出来事の状態への影響 | B03 Appraisal + B04 State Reducer | LLMがEmotion等を自由文で直接上書きする |
| 現在内部状態 | B04 Internal State | Memory/Character/GUIを現在状態の正本にする |
| 過去の証拠・想起 | B05 Memory | Memoryを現在のExecution Factより優先する |
| 意識的行動選択 | B06 Commander / LLM-2 | Character/Body/Pluginが独自判断で行動を開始する |
| Activity lifecycle | B07 Activity Runtime | Activityがraw inputから勝手にstart/stopを決める |
| 実行事実 | B08 Execution Coordination + typed executor result | Characterが予定を実行済みとして語る |
| 発言の意味 | B06 SpeechIntent / Semantic Plan | B09 Characterが内容を追加・改変する |
| 発言の言い回し | B09 Character Speech / LLM-3 | Commanderが最終台詞を書く |
| 音声演技計画 | B10 Speech Performance | Character LLMがengine parameterを出す |
| 発話提示状態 | B11 Speech Pipeline | TTS playback完了をBrain decision lockにする |
| turn / interruption eligibility | B12 Autonomy / Turn | Turn Managerが発話内容そのものを決める |

---

# 4. B01 Input Gateway

Issue: #349

## 責務

外部Source差をCore内の型付き`NormalizedInputEvent`へ変換する。

```text
NormalizedInputEvent
- event_id
- occurred_at
- source_kind
- modality
- actor_ref?
- language?
- text_payload?          # natural languageの場合
- structured_payload?    # touch/vision/system等
- correlation_id?
- trace_context
```

## 原則

- Text / STT transcriptは同じnatural-language routeへ入る。
- Touch / Vision / System Eventを無理に文章へ変換しない。
- device固有SDK objectをBrainへ渡さない。
- B01は意味・意図を決定しない。

---

# 5. B02 Input Meaning

Issue: #326
LLM Role: 1

## 入力

```text
InputMeaningRequest
- NormalizedInputEvent(text)
- bounded ReferenceContext
- current turn identifier
- source metadata
```

`ReferenceContext`はB05 MemoryとB12 Turn Stateから構築するread-only viewであり、全会話履歴を無制限にPromptへ投入しない。

最低限:

```text
ReferenceContext
- recent_user_turns
- recent_yura_turns
- recent_command_refs
- recent_activity_refs
- unresolved_reference_candidates
- topic/thread refs
```

## 出力

```text
StructuredInputMeaning
- meaning_id
- source_event_id
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

## 「もう一回」等の参照

固定フレーズ専用処理にしない。

```text
User natural language
+ bounded ReferenceContext
→ LLM-1
→ references[]
   - reference_type
   - resolved_target_id?
   - candidate_ids
   - confidence
```

可能なら以前の`command_id / activity_id / speech_id / topic_id`等へ型付き解決する。

解決不能なら`clarification_required`とし、BodyやActivityがraw文面を再解釈しない。

## 禁止

- downstream regex/substring/finite phrase dictionaryによる意味fallback
- Parserによるraw textの意味再判定
- Character/Activityが独自にユーザー意図を再解釈

---

# 6. B03 Situation / Appraisal

Issue: #327

## 位置付け

Appraisalは**LLM Roleではない**。

入力済みのtyped semantics / events / factsと現在状態から「この出来事がゆらにとってどういう意味を持つか」を計算するDomain/Application moduleである。

## 入力

```text
AppraisalInput
- StructuredInputMeaning? / typed SystemEvent
- CurrentInternalStateSnapshot
- MemoryEvidenceView
- RelationshipView
- ActivitySnapshot
- CapabilitySnapshot
- ExecutionFactSnapshot
- TurnState
- time context
```

## 出力

```text
AppraisalResult
- appraisal_id
- source_event_ids
- salience
- novelty
- relevance
- valence factors
- goal/need compatibility
- social/relationship factors
- uncertainty
- attention recommendation
- StateDeltaProposal[]
- memory_candidate_hints[]
```

Appraisalは最終行動を決めない。それはCommanderの責務。

## Awakening / 起動

起動も特別な固定Presetではなくtyped lifecycle eventとしてAppraisalへ入れる。

```text
StartupContext
→ Appraisal
→ normal StateDeltaProposal
```

`sleepy → あくび`、`ready → おはよう`のような固定1:1対応は作らない。

---

# 7. B04 Internal State

Issue: #327

## State facets

最低限:

- Emotion
- Desire
- Drive
- Motivation
- Moral / Values appraisal
- Interest / Curiosity per target
- Relationship state
- Arousal / Energy等の連続状態

各状態は少なくとも以下を区別する。

```text
StateFacet
- current
- previous
- delta
- causes[]
- updated_at
- confidence / stability if needed
```

## State ownership

LLMの出力値をそのままStateへ代入しない。

```text
AppraisalResult
→ StateTransitionValidator
→ StateReducer
→ NewInternalStateSnapshot
```

StateReducerが唯一の書込みauthority。

## 不変条件

- EmotionとInterestを混同しない。
- DesireとDriveを同一概念に潰さない。
- Characterの発言内容をState更新の直接根拠にしない。
- Memory上の過去状態をcurrent stateへ直接復元しない。
- UIがStateを書き換える場合も明示Command/Debug contractを経由する。

---

# 8. B05 Memory

Issue: #332

## Memory categories

- Working / Short-term
- Episodic
- Semantic
- Relationship
- Preference / Interest
- Activity / Skill（必要な範囲）

## Write pipeline

```text
Typed Event / Meaning / Result / State transition
→ MemoryCandidate
→ importance / novelty / persistence / confidence
→ routing
→ merge / update / contradiction handling
→ MemoryRecord
```

Memory用の別LLM Summarizerは追加しない。

V2初期は、既に構造化されたMeaning / Fact / State transitionを中心に保存し、raw conversation全文の自由要約をMemory正本にしない。

## Retrieval

```text
MemoryQuery
- target/topic/entity refs
- temporal scope
- relation type
- memory categories
- max_items / token budget
```

出力は`MemoryEvidenceView`。

## Authority

優先順位:

```text
current Execution Fact
> current Internal State
> current Input Meaning
> recent typed interaction context
> retrieved Memory
```

Memoryは参考証拠であり、現在の事実を上書きしない。

---

# 9. B06 Commander

Issue: #328
LLM Role: 2

## Decision Context

Commanderへraw implementation objectを渡さず、型付きViewを組み立てる。

```text
DecisionContext
- current meaning / event
- AppraisalResult
- InternalStateView
- MemoryEvidenceView
- RelationshipView
- ActivitySnapshot
- CapabilitySnapshot
- ExecutionFactSnapshot
- TurnState
- SpeechPipelineState
- BodyCapabilityView
- authority / safety constraints
```

## 出力

```text
SystemCommand
- command_id
- source_context_revision
- priority
- speech_intent?
- body_intent?
- activity_request?
- attention_intent?
- memory_operation_intent?
- silence_intent?
- question_budget
- new_direction_budget
- interruptibility
- preconditions[]
- forbidden_claims[]
```

## Authority

Commanderが唯一「今何をする／しない」を決める。

ただしLLM出力は必ず以下を通す。

```text
Schema
→ Authority
→ Capability
→ Preconditions
→ Safety
→ accepted / rejected SystemCommand
```

## 発話準備と提示

`SpeechIntent`生成はPresentation完了を待たない。

Prepared候補の前提が変化した場合は、deterministic revalidationで失効判定し、意味判断が必要なら新しいAppraisal→Commander cycleへ戻す。

---

# 10. B07 Activity Runtime

Issue: #329

## Contract

```text
ActivityDefinition
- activity_type
- required_capabilities
- supported_operations
- interruption policy

ActivityInstance
- activity_id
- definition_ref
- lifecycle_state
- started_at
- current_step_ref?
- capability bindings
- latest_result_refs
```

Lifecycle例:

```text
requested
→ accepted
→ starting
→ active
→ completing
→ completed

or paused / interrupted / cancelled / failed / unsupported
```

## 原則

- start/stop/switchの意味決定はCommander。
- Activity implementationはraw user textを見て独自判断しない。
- Activityの進捗はtyped event/resultとしてBrainへ戻す。
- ActivityがCharacterやBodyへ直接命令しない。必要な表現はCommanderの次cycleで決める。

---

# 11. B08 Action / Execution Coordination

Issue: #329

## 責務

accepted `SystemCommand`を各executorへ非同期dispatchし、実行状態を事実として集約する。

```text
AcceptedSystemCommand
→ ExecutionCoordinator
   ├─ Activity / Plugin executor
   ├─ Speech preparation/presentation
   ├─ Body intent channel
   ├─ Memory operation
   └─ Wait / Silence state
```

## Execution Fact

```text
ExecutionFact
- execution_id
- command_id
- target_kind
- lifecycle_state
- accepted_at
- started_at?
- observable_at?
- completed_at?
- failure?
- capability_ref?
- result_ref?
```

事実Lifecycle:

```text
requested
→ accepted
→ planned
→ started
→ observable/applied
→ completed

or rejected / unsupported / failed / cancelled / timed_out
```

Characterはこの事実より先に「やった」「できた」と言えない。

## Non-blocking

あるexecutorの長いawaitでCommander/Appraisal/Event処理を止めない。

---

# 12. B09 Character Speech Realizer

Issue: #330
LLM Role: 3

## 入力

```text
SpeechSemanticPlan
- speech_plan_id
- speech_act
- target
- propositions[]
- required_content[]
- optional_content[]
- forbidden_content[]
- question_budget
- new_direction_budget
- interpersonal/discourse facets
- expression tone
```

加えてCharacter Language Profileを渡す。

raw Emotion / Desire / Drive数値、raw execution payload、Body joint state等は渡さない。

## 出力

```text
CharacterUtterance
- utterance_id
- speech_plan_id
- speech
- phrase_boundaries
- linguistic_emphasis
- hesitation/filler metadata
- semantic_realizations[]
```

`semantic_realizations[]`は各planned proposition/content idと、speech中の実現spanを対応付ける。

## Semantic realization validation

**第5のLLM Validatorを追加しない。**

V2 Productionの基本形:

```text
LLM-3 Structured Output
→ schema validation
→ proposition/realization coverage validation
→ forbidden structure / execution-claim validation
→ span existence validation
→ accepted CharacterUtterance
```

- required propositionのrealization欠落はreject/同じLLM-3 roleでrepair。
- unknown extra semantic idはreject。
- execution claimはExecution Factと照合。
- open-ended自然語をruntime finite dictionaryで再分類しない。

自然言語意味の完全な再解釈を別Modelへ委ねる設計は採用しない。Live Verificationで意味保持不足が見つかった場合も、直ちに第5LLMを足さず、まずSpeechSemanticPlanとLLM-3 structured realization contractを改善する。

---

# 13. B10 Speech Performance

Issue: #331

CharacterUtteranceからengine-independentな音声演技計画を作る。LLM Roleは追加しない。

```text
SpeechPerformancePlan
- utterance_id
- phrase_plan[]
- pause intents
- speed intent
- pitch contour intent
- intonation intent
- volume intent
- breathiness intent
- emphasis mapping
- degradation policy
```

Character Voice Styleは#355 Character Projectionから受け取る。

VOICEVOX等の具体parameterへ変換するのはInfrastructure Adapter #358。

---

# 14. B11 Speech Pipeline

Issue: #348
Canonical: `docs/architecture/v2/speech_pipeline_architecture.md`

## Core invariant

**現在の発話再生完了を次の発話内容生成開始条件にしない。**

Speech A presenting中に、B12がDecision Cycle開始可能と判定しB06 Commanderが許可すれば、Speech BのB09/B10まで進められる。

```text
Speech A presenting
while
  Appraisal B
  → Commander B
  → Character B
  → Performance B
  → Prepared B
```

Prepared Bは再生確定ではない。Presentation直前に最新Contextでrevalidateする。

詳細なqueue/backpressure/invalidation/trace acceptanceはSpeech Pipeline canonicalを参照する。

---

# 15. B12 Autonomy / Turn Management

Issue: #333

## 責務

「新しいDecision Cycleを開始してよい状況か」を型付きに管理する。

```text
TurnState
- ownership
- pending_user_response
- pending_yura_response
- interruption_state
- presenting_speech?
- prepared_speech_count
- current_activity_ref?
- recent_interaction_at
- initiative_eligibility
```

## 自律発話

自律発話専用の別意思決定器を作らない。

```text
Timer / state change / environment typed event
→ B12 eligibility
→ B03 Appraisal
→ B06 Commander
→ speech / body / activity / silence
```

B12は「喋れ」とは決めない。Commanderを起動可能にするだけ。

## 発話中の次Decision

`presenting_speech != null` はDecision Cycle禁止条件ではない。

次の条件を満たす範囲で、再生中にも次Appraisal/Commanderを起動できる。

- prepared queueにcapacityがある
- user response待ちを侵害しない
- current activity/interrupt policyに反しない
- backpressure policyに反しない

これにより発話再生時間を次LLM生成待ちへ加算しない。

## 固定sleep禁止

自律発話間隔の正本を`前発話完了 → sleep N秒 → 次生成`にしない。

時間経過はtriggerの一要素であり、最終判断は現在State/Appraisal/Commanderで行う。

---

# 16. Core Foundationとの境界

Runtime KernelはBrain Moduleに含めない。

Core Foundation #322が所有:

- Event Queue / Buffer
- clock
- scheduler
- task/worker lifecycle
- cancellation propagation
- RuntimeCoordinator
- health / diagnostics primitives

Brainは以下のPortとして利用する。

```text
EventPort
ClockPort
SchedulerPort
TaskDispatchPort
CancellationPort
TracePort
```

Runtime KernelはEmotion、Intent、Activity selection、Speech contentを判断しない。

---

# 17. Concurrency Model

最低限、次は互いの長時間awaitで停止しない。

```text
Event / Appraisal / Commander lane
Character / Speech preparation lane
Speech Presentation / TTS lane
Activity / Plugin execution lane
Body realtime lane
Persistence lane
```

因果関係が必要な箇所はtyped id/revisionで接続し、巨大なグローバルlockで順序を保証しない。

主要ID:

- event_id
- meaning_id
- appraisal_id
- state_revision
- command_id
- execution_id
- speech_plan_id
- utterance_id
- candidate_id
- presentation_id
- activity_id

---

# 18. Failure / Degradation

- LLM-1 failure → typed unresolved / clarification path
- Appraisal failure → eventを破棄せずdiagnostic + safe no-op / bounded fallback
- LLM-2 failure → unsafe actionを推測せずwait/degraded state
- LLM-3 failure → speech candidate failure。Body/Activity/Core loopは継続
- TTS failure → text presentationまたはspeech failedとして継続
- Memory unavailable → no-memory degraded mode
- Plugin unavailable → capability absent/failedとしてCommanderへ戻す
- Body unavailable → BodyIntentをunsupported/degraded fact化。Brain loop継続

一つの障害を全Core停止へ連鎖させない。

---

# 19. Module Gate

各Moduleは次の順で検証する。

1. Design Gate
2. Module Unit Gate
3. Adjacent Contract Gate
4. Brain Integration Gate (#334)
5. System Verification (#360)

隣接Moduleを同時修正してUnit testを通すことを禁止する。

---

# 20. Brain Integration Acceptance

Issue: #334

最低限:

1. text input → Input Meaning → Appraisal → State → Commander → Character text responseが成立する。
2. raw user text semantic authorityがB02以外に存在しない。
3. 「もう一回」等がReferenceContextからtyped referenceへ解決され、下流でphrase matchingしない。
4. Emotion / Desire / Drive / Interest等が別facetとして更新される。
5. Memory unavailableでも会話loopが継続する。
6. execution予定と実行事実が分離され、Characterが未実行を完了済みと主張しない。
7. Activity start/stop/continueがCommander authorityを経由する。
8. Character wordingがSpeechSemanticPlanのrequired propositionを落とさない。
9. 第5LLM Roleを追加しない。
10. Speech A再生中にSpeech BのCharacter generationを開始できる。
11. user input到着でstale autonomous prepared speechをcancel/supersedeできる。
12. Runtime Kernelの長時間Task待機がBrain decision laneを停止しない。
13. Body/Plugin/TTS/PersistenceがなくてもBrain minimum text loopを成立させられる。

---

# 21. 非目標

この文書では以下の具体実装を決めない。

- OpenAI model名
- Prompt全文
- DB schema
- VOICEVOX parameter
- Live2D parameter
- GUI layout
- Body joint solver
- Streaming implementation

これらは各Module/AdapterのDesign Gateで決める。

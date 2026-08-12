# AI Liver ゆら V2 Canonical System Architecture

Status: Draft / V2 Design Gate
Canonical branch: `rebuild/v2-foundation`
Root management: #317
Base lineage: `main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`

## 1. この文書の役割

この文書は、AI Liver ゆら V2の**唯一のシステム構造正本**である。

V2では旧実装を継ぎ足して修復し続けない。旧Issue / PR / branch / docsから重要な要求・失敗知見・設計判断を回収するが、旧コードを正本として継承しない。

設計→Module Contract→Unit→Adjacent Contract→Integration→System Verificationの順で再構築する。

詳細設計は本書を補足するsubordinate canonicalとして置く。

- Brain: `docs/architecture/v2/brain_architecture.md`
- Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
- Concurrency / LLM Invocation: `docs/architecture/v2/concurrency_architecture.md`
- Speech Pipeline: `docs/architecture/v2/speech_pipeline_architecture.md`

---

# 2. 最終目標

V2の目標は、ユーザー入力に返答するチャットボットではない。

ゆらは、持続する内部状態・記憶・関係・欲求・目標・約束・活動を持ち、外界と自身の変化を受け取りながら、自ら行動を選択できる存在として設計する。

代表的な活動:

- ユーザーとの会話
- YouTube等でのライブ配信 / VTuber活動
- ユーザーとのゲーム対戦
- ライブ配信中のゲーム実況・対戦
- 観察、探索、沈黙、休止
- 将来追加されるActivity / Capability

ユーザー発言は非常に重要な社会的Eventだが、常に無条件の命令として扱わない。

---

# 3. システム境界

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

## 3.1 Core

Coreは「ゆら自身」の最小実行単位である。

Coreは以下を満たす。

- BrainとBodyをCore固有責務として持つ
- Pluginが0個でもCore固有責務を維持できる
- AvatarがなくてもCore状態を維持できる
- StreamingがなくてもCoreを破壊しない
- GUIがなくても成立する
- TTSが利用不能でもText/Silence判断と内部状態更新を可能な範囲で継続する
- Persistenceが利用不能でも安全に縮退する
- 外部Output切断でCore loopを破壊しない
- graceful shutdown / cancellationを正常経路として扱う
- Speech playbackやTTS待機で認知判断を停止しない
- Body realtime更新をLLM/TTS/DB/Game AIの待機時間へ従属させない

## 3.2 BodyはPluginではない

「機能がなくても一時的にdegraded運転できるか」と「Core固有責務か」は別軸である。

Bodyは、ゆら自身の身体状態・身体表現・運動実現を所有するためCoreである。

Avatar OutputがなくてもBodyがCoreから消えるわけではない。

## 3.3 Plugin

Pluginは、BrainやBodyなどCore自身の構成要素ではなく、**Coreが公開する拡張契約を利用して外部から能力を追加する機構**である。

Pluginの追加・削除によって、Coreが所有するDomain Stateや責務境界を変更してはならない。

Pluginは次を行ってよい。

- Capabilityを登録する
- Activity / Tool能力を追加する
- 外部Tool / Game / Search等の能力を提供する
- Coreのtyped requestへtyped resultを返す

Pluginは次を行ってはならない。

- Core Domain Stateの正本になる
- Brain/Body固有責務を所有する
- Brain内部状態を直接書き換える
- raw user textを独自解釈してExecutive Authorityを迂回する
- Character / Bodyへ直接命令してCore意思決定を迂回する

別の不変条件として、Pluginが登録されていない構成でもCoreは自身の基本責務を維持できること。

## 3.4 Subsystem

SubsystemはCoreの外側にある独立システムである。

Core内部Domain objectへ直接依存せず、Port / Event / DTO / API等の公開契約で接続する。

Subsystem障害でCoreが停止してはならない。

---

# 4. Clean Architecture

```text
Domain / Contracts
        ↑
Application / Use Cases
        ↑
Ports
        ↑
Adapters / Providers / UI / External systems
```

内側は外側を知らない。

禁止例:

```text
Domain → OpenAI SDK
Domain → FastAPI
Domain → VOICEVOX
Domain → Live2D
Brain → concrete GUI
Body → concrete Avatar model
Core → concrete Plugin implementation
```

許可例:

```text
Domain → Protocol / typed contract
Adapter → Domain Port implementation
Subsystem → Core public API / Event contract
Plugin → Plugin / Capability contract
```

---

# 5. ゆらの認知モデル

認知は継続的な因果循環として扱う。

```text
External / Internal Events
  ├─ user conversation
  ├─ YouTube viewers / stream events
  ├─ game state / result
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
   ├─ Activity planning
   ├─ Speech semantics
   ├─ Character language
   └─ Body motion
            ↓
Execution / Presentation
            ↓
Actual Result / World change
            ↓
Appraisal / Memory / Reflection
```

**この図は依存・因果関係であり、実行時に全箱を毎回順番にawaitするPipelineを意味しない。**

---

# 6. 実行モデル: 1本のサイクルにしない

正規RuntimeはEvent-driven / snapshot-based / concurrent lanesとする。

```text
                         ┌─ Input / Meaning lane
                         ├─ Appraisal / State lane
Typed Event Stream ──────┼─ Executive lane
                         ├─ Speech Preparation lanes
                         ├─ Speech Presentation lane
                         ├─ Body Realtime lane
                         ├─ Activity / Skill lanes
                         └─ Reflection / Memory lane
```

各laneは必要なtyped eventだけを購読し、結果をtyped event / candidate / factとしてpublishする。

## 6.1 Core concurrency invariant

- Speech A再生中に次のInput Meaning / Appraisal / Executive / Speech preparationを進められる
- TTS待機中でも新しいInputを受け取れる
- Body realtimeはLLM/TTS/DB/Game AIを待たない
- Memory consolidationは通常会話をblockしない
- Game frame loopをCore Executive LLM待ちにしない
- Streaming大量コメント処理をCore decision loopへ直結しない
- 1 Provider timeoutで無関係Roleを停止しない
- background処理がforeground user interactionをstarveしない

詳細: `docs/architecture/v2/concurrency_architecture.md`

## 6.2 Revision / stale policy

長時間処理は少なくとも次を持つ。

```text
request_id
source_event_ids
source_context_revision
priority
interruptibility
preconditions
expires_at / stale_policy
```

古いcontextから生成された候補を無条件commitしない。

---

# 7. LLM設計原則

旧方針の「システム全体でLLMを4責務に固定する」は撤回する。

LLMの個数をArchitecture invariantにしない。

> open-endedな意味理解・主観評価・推論・計画・言語実現・意味検証・身体運動構成・内省に独立した責務が存在し、LLMが適切な場合に専用Roleを設ける。

ただし、Role数を増やすこととAuthorityを増やすことは別である。

## 7.1 Single Executive Authority

ゆらの意識的なGoal / Action selectionの最終Authorityは**Executive Deliberatorただ1つ**とする。

Character、Body、Activity Planner、Game Agent、Streaming AI、Verifier等はExecutive Authorityを奪わない。

## 7.2 Responsibility separation != API call chain

責務が分かれていても、必ず別LLM API callを一つずつ直列にawaitする必要はない。

禁止:

```text
Input Meaning LLM
→ await Appraisal LLM
→ await Executive LLM
→ await Speech Semantics LLM
→ await Character LLM
→ await Verifier LLM
→ await TTS
```

正規方針:

- sparse activation
- minimal critical path
- parallel fan-out
- optional deep evaluation
- speculative preparation where safe
- cancellation / stale discard
- priority / backpressure

詳細: `docs/architecture/v2/concurrency_architecture.md`

## 7.3 Core Cognitive Role候補

初期設計候補:

1. Input Meaning / Perception Interpretation
2. Subjective Appraisal
3. Executive Deliberation
4. Activity / Goal Planning
5. Speech Semantics Planning
6. Character Language Realization
7. Independent Semantic Verification
8. Body Motion Planning
9. Reflection / Memory Consolidation

これらを毎cycle全て呼ぶわけではない。

Roleの追加・統合・非LLM化は、責務・Authority・typed input/output・失敗時挙動・単体検証可能性で判断する。

詳細: `docs/architecture/v2/cognitive_llm_architecture.md`

---

# 8. Authority Map

| Authority | Owner |
|---|---|
| open-ended外部自然言語の意味 | Input Meaning |
| 出来事の主観的評価 | Appraisal contract |
| 現在内部状態 | Internal State Reducer |
| 意識的Goal / Action選択 | Executive Deliberator |
| 複雑Goalの実行計画 | Activity Planner（Executive従属） |
| 発言として何を伝えるか | Speech Semantics Planner（Executive Intent従属） |
| 発言をどう言うか | Character Language Realizer |
| 発話意味保持の観測 | Independent Semantic Verifier |
| 身体意図の運動実現 | Body Motion Planner |
| 実際に何が起きたか | Runtime / Executor Result |
| current Internal Stateの書込み | State Reducer |
| Memory永続正本 | Memory Store + validation |

LLM自由文をDomain State / Execution Factへ直接代入しない。

---

# 9. Brain

詳細正本: `docs/architecture/v2/brain_architecture.md`

Brainの責務:

- Input Gateway / Meaning
- Situation / Appraisal
- Internal State
- Memory evidence / Reflection coordination
- Executive Deliberation
- Goal / Activity planning
- Activity lifecycle
- Execution coordination
- Speech Semantics
- Character Language Realization
- Semantic Verification
- Speech Performance / Pipeline
- Autonomy / Turn Management

Runtime KernelはBrain Domain判断Moduleではない。Core FoundationとしてEvent Queue / Scheduler / cancellation / clock / task coordination等を提供する。

## 9.1 Input Meaning

自然言語をtyped semanticsへ変換する唯一のopen-ended raw text semantic authority。

下流Runtime / Activity / Plugin / Bodyがraw textをregex / substring / finite phrase dictionaryで再分類しない。

## 9.2 Appraisal

「この出来事が現在のゆらにとって何を意味するか」を扱う。

Appraisal責務を非LLMに固定しない。

- 明確な評価はdeterministic処理可能
- open-endedな主観評価にLLMを使ってよい
- LLM出力はtyped AppraisalCandidate / StateDeltaProposal
- State更新はValidator / Reducerが最終Authority

Appraisal LLMをすべてのDecisionのblocking prerequisiteにはしない。

## 9.3 Executive Deliberation

現在状態・Goal・Memory・Relationship・Activity・Capability・Execution Facts等から「今何をする／しない」を決める唯一の意識的Authority。

最終日本語、TTS engine parameter、joint angle、Game frame actionを生成しない。

## 9.4 Activity / Goal Planning

Executiveが決めた複雑Goalをtyped ActivityPlanへ分解する。

単純Actionでは専用Planner LLMを起動しなくてよい。

## 9.5 Speech Semantics

`What to say`を所有する。

- propositions
- required / optional / forbidden semantics
- polarity / certainty / degree
- disclosure
- question / new-direction budget
- execution truth constraints

## 9.6 Character Language Realizer

`How to say it`を所有する。

Characterらしさを実現するが、発言意味や実行事実を変更するAuthorityは持たない。

## 9.7 Independent Semantic Verification

独立VerifierをLLM数だけを理由に排除しない。

```text
SpeechSemanticPlan
+ CharacterUtterance
→ SemanticRelationObservation
→ closed typed acceptance policy
```

VerifierはObserverであり、最終Speech IntentやRuntime Factを書き換えない。

## 9.8 Memory / Reflection

MemoryはWorking / Episodic / Semantic / Relationship / Preference / Skill等を区別する。

Reflection / ConsolidationにLLMを使ってよいが、Memory DBへ直接自由文を書き込ませない。

低優先background処理としてforeground会話をblockしない。

---

# 10. Speech Architecture

詳細正本: `docs/architecture/v2/speech_pipeline_architecture.md`

## 10.1 What to say / How to say it

```text
Executive SpeechIntent
→ Speech Semantic Plan
→ Character Language Realization
→ Semantic Verification
→ Speech Performance
→ PreparedSpeechCandidate
```

ただし、この論理責務分離を常に5段の大型LLM直列呼び出しとして実装しない。

simple speechでは一部Roleを省略・非LLM化できる。

complex speechでは必要なRoleだけ起動する。

## 10.2 Preparation / Presentation分離

```text
Preparation
  semantic / character / verifier / performance / optional TTS prep

Presentation
  pre-present revalidation
  → text/audio commit
  → playback / viseme
  → result
```

Presentation完了を次generation開始条件にしない。

Character生成後にVerifierが必要な場合、Verifierと安全に先行可能なTTS preparation / performance準備を並列化できる。

Verifier PASS前に外部発話commitはしない。

---

# 11. Body

BodyはCore固有責務である。

## D01 Canonical Body Model

- joint hierarchy
- normalized segment lengths
- DOF
- limits
- anatomical left/right
- end effectors
- kinematic chains
- root / center of mass

## D02 Body State

- current pose / velocity
- history
- active motion plans
- attention
- speech synchronization state

## D03 Expression Projection

Internal State / Interaction / Character Body Styleを高レベル身体表現へ投影する。

Emotion名→固定Motion名へしない。

## D04 Body Motion Planning

必要な高レベルmotion planningでLLMを利用できる。

```text
BodyIntent
+ Body State
+ Skeleton / DOF / limits
+ Expression Context
+ Character Body Style
→ BodyMotionPlan
```

## D05 Deterministic Motion

- structural validation
- IK / FK / Kinematics
- joint limits
- balance
- trajectory
- continuity

LLMを身体安全性の最終Authorityにしない。

## D06 Realtime

- current motion continuation
- gaze
- blink
- breathing
- viseme
- tiny motion

これらを新規LLM応答待ちで止めない。

## D07 BodyPoseFrame

Canonical output。

Live2D / 3D / Stick FigureはPresentation Adapterとして投影する。

---

# 12. Skill AI / Subsystem AI

Core Cognitive LLM Role数と、個別技能に使うAIを混同しない。

## 12.1 Game

```text
Core Executive
→ Goal / Strategy / Activity Intent
→ Game capability / subsystem
→ game-specific agent
   - LLM / VLM
   - RL
   - search / planning
   - deterministic policy
→ controller action
→ typed Game Result
→ Core Appraisal
```

Game Agentは高速な技能を担当する。

frame-level actionをCore Executive LLMへ毎frame問い合わせない。

## 12.2 Streaming

コメント大量分類、moderation補助、summary、chat signal extraction等へ専用AIを使ってよい。

ただし「配信するか」「誰にどう反応するか」の最終Authorityを奪わない。

## 12.3 Perception

Vision / audio recognition等へ専用VLM / speech modelを利用してよい。

typed perceptとしてCoreへ渡す。

---

# 13. Provider / Adapter

OpenAI / local LLM / VOICEVOX / PostgreSQL / HTTP / Live2D等はInfrastructure Provider / Adapterであり、Core Pluginとは別概念。

LLM Roleはtyped Port / schema / model policy / timeout / cancellationを持つ。

同じProviderを複数Roleで共有してよい。

さらに、将来1 provider callで複数logical outputを安全に生成できる場合でも、**logical responsibility / authority contractは分離したまま**にできる。

つまり「Role数 = API call数」ではない。

---

# 14. Character Definition

人物設定はHuman-readable Character Bibleを正本とする。

分離:

```text
static character trait → Character Definition
current emotion        → Internal State
current desire         → Internal State
interest               → Interest / Memory
relationship           → Relationship State
```

Projection:

- Language Style
- Voice Style
- Body Expression Style

Character設定から現在存在しないEmotion / Desire等を捏造しない。

---

# 15. Execution Fact / Truthfulness

Commandの意図と実際に起きたことを分離する。

```text
requested
→ accepted
→ planned
→ started
→ observable/applied
→ completed

or rejected / unsupported / failed / cancelled / timed_out
```

CharacterはExecution Factより先に「やった」「できた」と主張できない。

SpeechはさらにPreparationとPresentationを分ける。

```text
prepared
→ queued
→ revalidating
→ ready_to_present
→ presenting
→ completed

or cancelled / superseded / stale / rejected / failed
```

`prepared`は「話した」という事実ではない。

---

# 16. Natural Language Semantic Policy

open-ended自然言語の意味・意図・感情強度・claim等のAuthorityとして次を使わない。

- finite keyword list
- marker list
- regex
- substring
- startswith / endswith

例外:

- protocol token
- enum
- exact technical identifier
- domain dataそのものが有限語彙である場合

自然言語意味理解が失敗した場合はfail closed / unresolved / clarificationへ落とす。

---

# 17. Backpressure / Priority

LLM request queueを無制限に増やさない。

概念的優先順:

1. current user interaction requiring timely decision
2. safety / interruption / execution failure
3. active Activity decision
4. autonomous initiative
5. reflection / consolidation
6. low-priority background enrichment

foreground interaction開始時に不要なbackground LLMを延期・cancelできる。

同種Event burstはRoleごとにcoalesce / latest-wins / bounded queue等を定義する。

---

# 18. Graceful Degradation / Shutdown

正常degraded state:

- Body output unavailable
- TTS unavailable
- DB unavailable
- Plugin unavailable
- Subsystem unavailable
- specific LLM Role unavailable

1 Roleのfailureで無関係Role contractを変えない。

retryはbounded backoff / rate-limited diagnostics。

Shutdownは新規work停止、candidate cancel、interruptible task収束、workers/adapters close、Runtime coordinator awaitの順でpending taskを残さない。

---

# 19. Observability

最低限:

- trace_id
- event_id
- role_id / module
- request_id
- source_context_revision
- queue_wait
- started_at / completed_at
- outcome
- error_class
- cancellation / stale / superseded

Concurrency観測:

- Role別provider latency
- Role別queue wait
- end-to-end critical path latency
- concurrent in-flight数
- stale/cancel/supersede率
- user input→Executive decision latency
- user input→speech preparation latency
- previous playback中のnext generation start
- Body frame timingへのLLM影響

平均だけでなくp95/p99を確認する。

---

# 20. Module Development Gate

## Gate 0 Design

- responsibility
- authority
- typed input/output
- trigger
- blocking/non-blocking dependency
- stale/cancel policy
- failure/degradation
- non-goals
- acceptance cases

## Gate 1 Unit

対象Module / Role単体。

LLM Roleならfake providerでschema / timeout / cancellation / staleを検証する。

## Gate 2 Adjacent Contract

DTO / authority / event boundaryを検証。

## Gate 3 Integration

並行性、failure、cancellation、backpressureを含めて接続する。

## Gate 4 System Verification

全体起動・実LLM・実TTS・実画面・実Game / Streaming等。

ユーザー確認が必要ならVerificationで止める。

---

# 21. V2実装順序

設計確定後、概ね次の順で進める。

```text
Phase A Foundation
- typed Event / Fact / Capability / revision contracts
- Runtime Kernel / task scheduling / cancellation
- LLM Role Port / provider contract
- Character Definition minimum

Phase B Cognitive minimum
- Input / Meaning
- Appraisal / State
- Executive Deliberation
- Execution Coordination
- minimum Speech path
- concurrent text-loop

Phase C Speech quality
- Speech Semantics
- Character Language
- Semantic Verification
- Speech Performance
- Preparation / Presentation concurrency

Phase D Body
- Canonical Body
- Expression
- Motion Planning
- deterministic solver / realtime
- Brain↔Body integration

Phase E Memory / Autonomy / Extension
- Memory / Reflection
- autonomy / turn
- Plugin Architecture
- zero-plugin verification

Phase F Subsystems / Skills
- Avatar
- Streaming
- Game capability / agents as applicable
- GUI
- Labs / tooling

Phase G System Verification
```

Phase番号だけを理由にIssueを分けない。独立して設計・実装・検証できる責務単位でWork Issue化する。

---

# 22. V1から継承する教訓

維持する:

- 責務分離そのもの
- Input MeaningとDecisionの分離
- `What to say`と`How to say it`の分離
- Character発話意味保持の独立検証
- typed contracts
- finite natural-language dictionaryをsemantic authorityにしない
- Characterへraw内部状態の意味決定を押し付けない
- Body generative motion / deterministic constraint分離
- Module単位検証

改善する:

- LLM総数を先に固定しない
- ただしAuthorityは分散させない
- Executiveへ計画・発話内容・表現を過剰集中させない
- Verifierを自由文の最終Authorityにしない
- 責務分離を直列API call列へ変換しない
- LLM/TTS/Playback/Memory/Game処理を1本のblocking chainへしない

---

# 23. V2 Design Gate 完了条件

- [ ] 本文書をユーザーが確認
- [ ] Cognitive/LLM architectureをユーザーが確認
- [ ] Concurrency architectureをユーザーが確認
- [ ] Brain architectureが本文書と一致
- [ ] Body architectureが本文書と一致
- [ ] Plugin definitionがCore membershipとdegradationを混同していない
- [ ] 旧Open Issue/PR要求がMigration Matrixへ全件対応付けられている
- [ ] 新V2 Issue hierarchyが更新後Module境界と一致
- [ ] 各Work IssueにStart / Target /依存 /検証Gateがある
- [ ] LLM Role数固定がIssue/Provider設計に残っていない
- [ ] LLM responsibility separationとinvocation topologyが分離されている
- [ ] single Executive Authorityが全Issueで一致
- [ ] playback中next-generationをCore acceptanceへ含めている
- [ ] slow LLM Roleが無関係laneをblockしない自動テスト条件がある
- [ ] stale LLM resultを誤commitしない条件がある
- [ ] Design Gateを通過するまで製品コードを変更しない

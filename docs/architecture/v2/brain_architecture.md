# AI Liver ゆら V2 Brain Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #325
Root management: #317

## 1. 目的

Brainは、入力や内部Eventを理解・評価し、現在状態・記憶・目標・関係・活動事実を用いて、ゆらが「今何をしたい／する／しない」を決めるCore領域である。

Brainは巨大な1本のLLM Pipelineにしない。

また、責務を分離してもLLM呼び出しをそのまま直列に数珠つなぎにしない。

> **Responsibility graphとRuntime call graphは別物である。**

各Moduleは独立Contractを持ち、Event / Snapshot / Candidate / Factを介して疎結合に協調する。

---

# 2. Brainの基本構造

```text
Typed Event Stream / Runtime Facts
        │
        ├─ B01 Input Gateway
        │      ↓
        ├─ B02 Input Meaning
        │
        ├─ B03 Subjective Appraisal
        │      ↓ candidate
        ├─ B04 Internal State Reducer
        │
        ├─ B05 Memory / Reflection
        │
        ├─ B06 Executive Deliberation
        │      ↓ ExecutiveDecision
        │
        ├─ B07 Goal / Activity Planning
        ├─ B08 Activity Runtime
        ├─ B09 Execution Coordination
        │
        ├─ B10 Speech Semantics
        ├─ B11 Character Language Realizer
        ├─ B12 Semantic Verification
        ├─ B13 Speech Performance
        ├─ B14 Speech Pipeline
        │
        └─ B15 Autonomy / Turn Management

Body is a sibling Core area.
Runtime Kernel is Core Foundation, not Brain decision authority.
```

この図も「B01→B02→…→B15を毎回全部awaitする」という意味ではない。

---

# 3. Concurrency / Snapshot model

Brain Moduleはversion付き`CognitiveSnapshot` / typed read modelを利用する。

```text
CognitiveSnapshot
- revision
- current typed events / meanings
- appraisal facts
- internal state
- memory evidence
- relationship
- goals / commitments
- activity facts
- capability facts
- execution facts
- turn / interruption state
- speech state
- body capability summary
```

長時間LLM requestは開始時点のrevisionを保持する。

結果は直接次LLMを呼び出すのではなく、原則candidate/eventとして返す。

```text
Role result
→ schema / responsibility validation
→ typed candidate/event
→ interested module may react
```

commit前にprecondition / revision / stale policyを確認する。

## 3.1 Brain concurrency invariant

- 1 LLM request中でも他Eventを受信できる
- unrelated decisionを同じLLM request待ちで停止させない
- Deep Appraisalを全Decisionのblocking prerequisiteにしない
- Speech playbackをnext decision/generationのblocking prerequisiteにしない
- Reflectionをforeground conversationのblocking prerequisiteにしない
- background LLM burstでforeground interactionをstarveしない
- stale / superseded candidateを最新状態へ誤commitしない

---

# 4. Authority Map

| Authority | Owner | 禁止 |
|---|---|---|
| open-ended外部自然言語の意味 | B02 Input Meaning | downstream regex/keywordで再解釈 |
| 出来事の主観的評価 | B03 Appraisal contract | Character/Activityが独自評価を正本化 |
| current Internal State | B04 State Reducer | LLM candidateを直接state代入 |
| 過去の証拠・想起 | B05 Memory | current Execution Factより優先 |
| 意識的Goal / Action選択 | B06 Executive | Character/Body/Skill AIが独自Goal開始 |
| 複雑Goalの実行計画 | B07 Planner | Goal自体を勝手に変更 |
| Activity lifecycle | B08 Activity Runtime | raw inputからstart/stopを独自判断 |
| 実行事実 | B09 Execution Coordination | Characterが予定を実行済み扱い |
| 発言内容 / semantic plan | B10 Speech Semantics | Characterが意味を追加・変更 |
| Characterらしい言語表現 | B11 Character | CharacterがExecutive/Fact authorityを奪う |
| 発話意味保持の観測 | B12 Verifier | Verifier自由文を最終accept authority化 |
| Speech performance | B13 Performance | engine parameterをCharacter LLMへ直書き |
| Speech lifecycle / presentation facts | B14 Pipeline | playback完了でBrain全体lock |
| initiative / turn eligibility | B15 Autonomy/Turn | Turn Managerが内容/Goalを決める |

---

# 5. B01 Input Gateway

Issue: #349

外部Source差を`NormalizedInputEvent`へ変換する。

```text
NormalizedInputEvent
- event_id
- occurred_at
- source_kind
- modality
- actor_ref?
- language?
- text_payload?
- structured_payload?
- correlation_id?
- trace_context
```

原則:

- Text / STT transcriptは同じnatural-language routeへ入る
- Touch / Vision / Game state等を無理に文章化しない
- device SDK objectをBrain Domainへ渡さない
- 意味・感情・行動をここで決めない

---

# 6. B02 Input Meaning

Issue: #326
LLM candidate role: Input Meaning

質問:

> 外部から何が伝えられたのか。

入力:

```text
InputMeaningRequest
- NormalizedInputEvent(text)
- bounded ReferenceContext
- current turn / interaction context
- source metadata
```

出力:

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

### Reference resolution

「もう一回」「それ」「さっきの」等を固定phrase専用処理にしない。

bounded `ReferenceContext`からcommand/activity/speech/topic等へtyped解決する。

解決不能なら`clarification_required`等へ落とし、Body/Activity/Pluginがraw textを再解釈しない。

### Authority

open-ended外部自然言語のsemantic authorityはB02。

finite dictionary / regex / substringをfallback authorityにしない。

---

# 7. B03 Subjective Appraisal

Issue: #327

質問:

> この出来事は、現在のゆらにとってどういう意味を持つか。

Input MeaningとAppraisalを分離する。

同じ「配信しない？」という提案でも、Energy、Desire、Current Activity、Relationship、Recent Stream、Values等で主観的評価は変わる。

## 7.1 Implementation policy

Appraisalを「LLMではない」と固定しない。

- 明確・低コストな評価: deterministic model / rules
- open-endedで文脈依存の主観評価: Appraisal LLMを利用可能

LLMを使う場合も出力はcandidateである。

```text
AppraisalCandidate
- source_event_ids
- salience
- novelty
- goal_relevance
- need/desire compatibility
- pleasantness / aversiveness factors
- social significance
- value alignment/conflict
- uncertainty
- attention recommendation
- StateDeltaProposal[]
- memory hints[]
```

```text
AppraisalCandidate
→ validation
→ B04 State Reducer
```

LLMがEmotion / Desire / Drive current valueを直接上書きしない。

## 7.2 Fast / Deep appraisal

Deep LLM Appraisalを毎回blocking dependencyにしない。

```text
Typed Event
├─ fast appraisal / existing deterministic transition
└─ optional deep appraisal async
```

Deep resultが後着した場合、妥当なら新しいState transition / Executive triggerを発生させる。

---

# 8. B04 Internal State

Issue: #327

最低facet:

- Emotion
- Desire
- Drive
- Motivation
- Moral / Values appraisal
- Interest / Curiosity per target
- Relationship state
- Arousal / Energy等

各状態:

```text
StateFacet
- current
- previous
- delta
- causes[]
- updated_at
- confidence / stability if needed
```

唯一の書込みAuthorityはState Reducer。

```text
Validated StateDeltaProposal
→ StateReducer
→ NewInternalStateSnapshot
```

Character speechやMemory過去値をcurrent stateへ直接代入しない。

---

# 9. B05 Memory / Reflection

Issue: #332

Memory categories:

- Working / Short-term
- Episodic
- Semantic
- Relationship
- Preference / Interest
- Activity / Skill

## 9.1 Retrieval

`MemoryEvidenceView`として現在decisionへ必要な範囲だけ提供する。

Memoryはcurrent Execution Fact / current Internal Stateより強いauthorityを持たない。

## 9.2 Reflection / Consolidation

Reflection LLMを数だけを理由に禁止しない。

質問:

> 今回の経験から何を長期的に覚える価値があるか。

```text
Typed events / results / state transitions
→ Reflection / Consolidation
→ MemoryCandidate[]
→ provenance / contradiction / freshness / importance validation
→ Memory Store
```

ReflectionはMemory DBへ直接自由文を書き込まない。

foreground会話をblockしない低優先background laneとして実行できる。

---

# 10. B06 Executive Deliberation

Issue: #328

旧Commanderの責務を再定義する。

質問:

> 私は今、何をしたい／何をする／何をしないか。

ゆらの意識的Goal / Action selectionの唯一の最終Authority。

入力`DecisionContext`:

```text
- current event / meaning
- Appraisal facts
- Internal State
- Memory evidence
- Relationship
- current Goals / Commitments
- Activity snapshot
- Capability snapshot
- Execution facts
- Turn / interruption state
- Speech state
- Body capability summary
- time / environment
- authority / safety constraints
```

出力:

```text
ExecutiveDecision
- decision_id
- source_context_revision
- selected_goal / intent
- priority
- speech_intent?
- body_intent?
- activity_intent?
- attention_intent?
- silence / wait?
- interruptibility
- preconditions[]
- forbidden_claims[]
```

Executiveがしないこと:

- 複雑Activityの全step生成
- Character最終台詞
- detailed Speech propositionsを常に全部生成
- TTS parameter
- Body joint angle
- Game frame-level action
- Memory DB直接更新

OutputはSchema / Authority / Capability / Preconditions / Safety Gateを通す。

---

# 11. B07 Goal / Activity Planning

新規V2 Work Issueを設ける。

質問:

> Executiveが選んだ複雑Goalをどう実行するか。

```text
Executive Goal
+ Capability snapshot
+ Activity facts
+ execution constraints
→ Activity Planner
→ ActivityPlan
```

`ActivityPlan`例:

```text
- plan_id
- goal_ref
- steps[]
- dependencies
- required_capabilities
- checkpoints
- recovery policy
- completion conditions
```

単純ActionではPlanner LLMを呼ばない。

PlannerはGoalを変更するAuthorityを持たず、必要ならExecutiveへ`replan_required / impossible / clarification`を返す。

---

# 12. B08 Activity Runtime

Issue: #329のActivity lifecycle責務。

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
- result refs
```

Lifecycle:

```text
requested
→ accepted
→ starting
→ active
→ completing
→ completed

or paused / interrupted / cancelled / failed / unsupported
```

Activity Runtimeはraw inputを見て独自Goalを決めない。

---

# 13. B09 Execution Coordination

Issue: #329のExecution責務。

accepted decision / planを各executorへ非同期dispatchする。

```text
ExecutionCoordinator
├─ Activity / capability
├─ Speech preparation / presentation
├─ Body intent
├─ Memory operation
└─ Wait / Silence
```

`ExecutionFact`:

```text
requested
→ accepted
→ planned
→ started
→ observable/applied
→ completed

or rejected / unsupported / failed / cancelled / timed_out
```

あるexecutorの長いawaitで他laneを停止しない。

---

# 14. B10 Speech Semantics Planning

新規V2 Work Issueを設ける。

質問:

> Executive SpeechIntentを実現するために、何を伝えるか。

V1の`What to say != How to say it`を継承する。

```text
Executive SpeechIntent
+ facts / appraisal / memory evidence
+ discourse / relationship constraints
+ execution truth
→ Speech Semantics Planner
→ SpeechSemanticPlan
```

```text
SpeechSemanticPlan
- speech_plan_id
- speech_act
- target
- propositions[]
- required_content[]
- optional_content[]
- forbidden_content[]
- certainty / polarity / degree facets
- self_disclosure
- question_budget
- new_direction_budget
- truth constraints
```

### Invocation policy

毎回専用大型LLMを必須化しない。

- simple speech: Executiveが十分なtyped semantic constraintsを持つ場合は軽量/決定論的生成または省略可能
- complex speech:専用Speech Semantics LLMを起動

論理Authorityは分離したまま、call数は最適化できる。

---

# 15. B11 Character Language Realizer

Issue: #330

質問:

> 確定済みの意味を、ゆらならどう言うか。

```text
SpeechSemanticPlan
+ Character Language Projection
+ interpersonal / discourse context
+ high-level expression
→ Character Language Realizer
→ CharacterUtterance
```

出力:

```text
CharacterUtterance
- utterance_id
- speech_plan_id
- speech
- phrase boundaries
- linguistic emphasis
- hesitation / filler metadata
- semantic realization references
```

Characterがraw Emotion/Desire/Drive、raw execution payload等を再解釈して発言意味を作り直さない。

---

# 16. B12 Independent Semantic Verification

新規V2 Work Issueを設ける。

V1の独立意味検証を、Authorityを閉じた形で継承する。

質問:

> CharacterUtteranceはSpeechSemanticPlanの意味を実際に保持しているか。

```text
SpeechSemanticPlan
+ CharacterUtterance
→ Semantic Verifier
→ SemanticRelationObservation
→ deterministic acceptance policy
```

VerifierはObserver。

禁止:

- Speech Intentを変更
- Characterを直接指揮
- Runtime Factを変更
- free-form accepted/reasonを最終Authority化

最終accept/rejectはtyped checksからRuntimeが導出する。

### Latency policy

Verifierを直列滞留要因にしない。

Character生成後、Verifierと安全に先行可能なSpeech Performance / speculative TTS preparationを並列に進めてよい。

Verifier PASS前にPresentation commitはしない。

semantic riskが低く、Verifier不要で同等保証できるcontractが成立した経路は、明示PolicyでVerifierを省略可能にする。

---

# 17. B13 Speech Performance

engine-independent。

- phrase timing
- acoustic pause
- speed intent
- pitch contour intent
- intonation
- volume / breathiness intent

Character LLMへVOICEVOX等の実数parameterを生成させない。

Provider Adapterが具体値へ投影する。

---

# 18. B14 Speech Pipeline

詳細: `docs/architecture/v2/speech_pipeline_architecture.md`

PreparationとPresentationを別laneにする。

```text
Preparation
  Speech Semantics
  → Character
  → Verifier
  → Performance
  → optional TTS prep
  → PreparedSpeechCandidate

Presentation
  pre-present revalidation
  → commit
  → playback / text
  → result
```

論理依存はあっても全処理を固定直列awaitにしない。

- playback中next generation可
- TTS prepとVerifierの安全な並列化可
- prepared candidateはbounded
- stale / superseded / cancelledを扱う

---

# 19. B15 Autonomy / Turn Management

「いつExecutive decisionを起動できるか」を管理する。

「何をするか」はB06 Executiveが決める。

管理:

- turn ownership
- interruption
- user-attention priority
- autonomous initiative eligibility
- silence
- pending/prepared/presenting speech
- stale/cancelled candidate
- cooldown / fairness / anti-starvation

ユーザー入力がなくても、Desire / Interest / Memory activation / time / Activity Result等からExecutive triggerを発生させられる。

固定sleepや「前Speech終了→次生成開始」の直列構造を使わない。

---

# 20. Runtime KernelはBrainではない

Core Foundation (#322) が所有する。

- Event queue / typed stream
- scheduler
- task lifecycle
- cancellation
- clock
- priority / backpressure infrastructure
- health
- diagnostics
- worker coordination

Runtime KernelはDomain判断を持たない。

1 workerの長いawaitで他laneを止めない。

---

# 21. Skill AIとの境界

Brain ExecutiveがGame frame-level操作やStreamingコメント大量分類を直接行わない。

### Game

```text
Executive Goal / Strategy
→ Game capability / agent
→ fast game-specific policy
→ Game Result
→ Brain Appraisal
```

### Streaming

comment classification / summary / moderation signal等はSubsystem側の技能AIを利用可能。

Brainへ必要なtyped eventだけ戻す。

### Vision / Audio

Perception model結果をtyped perceptとしてInput Gatewayへ渡す。

---

# 22. LLM Role追加・統合基準

新Roleは最低限:

1. 独立した質問を1文で言える
2. typed input/outputがある
3. Authority重複がない
4. Unit評価可能
5. 独立交換・停止可能
6. failure/degradationが定義可能
7. LLMが本当に必要

逆に、Role分離しても実行時に必ず別API callを行う必要はない。

Provider optimization / batching / fused callを将来採用しても、logical contractsとAuthorityは維持する。

---

# 23. V1から継承するもの

- Input Meaning / Decision分離
- What to say / How to say it分離
- Characterへの責務過剰集中回避
- Independent semantic observation
- typed semantic facets
- finite phrase dictionaryを意味Authorityにしない
- raw internal stateをCharacterに解釈させない
-実LLM失敗をfailure classとして設計へ戻す

V1から改善するもの:

- Role数を先に固定しない
- Authorityは一本化する
- Logical Role分離を直列LLM call chainへしない
- slow model responseをCore全体へ伝播させない
- background cognitionとforeground interactionを優先度分離する

---

# 24. Brain Acceptance

- [ ] Input Meaningがraw text semantic authorityとして一意
- [ ] AppraisalとMeaningが分離
- [ ] Appraisal LLMがStateを直接書かない
- [ ] Executiveが唯一のconscious Goal/Action authority
- [ ] Activity PlannerがExecutive Goalを変更しない
- [ ] What to say / How to say itが分離
- [ ] Independent VerifierがObserverに限定される
- [ ] CharacterがExecution Factを捏造しない
- [ ] ReflectionがMemory Storeへ直接自由書込みしない
- [ ] LLM Role数が固定されていない
- [ ] Responsibility graphとLLM call graphが分離されている
- [ ] slow Appraisal/Reflection/Verifierが無関係laneをblockしない
- [ ] playback中next generation可能
- [ ] stale LLM resultを誤commitしない
- [ ] foreground interactionがbackground LLMでstarveしない
- [ ] Brain minimum Integration PASS

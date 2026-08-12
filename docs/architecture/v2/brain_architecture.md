# AI Liver ゆら V2 Brain Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Goal / Commitment: `docs/architecture/v2/goal_commitment_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #325
Root management: #317

## 1. 目的

Brainは、入力や内部Eventを理解・評価し、現在状態・記憶・持続Goal/Commitment・関係・Activity/Execution Factを用いて、ゆらが「今何をしたい／する／しない」を決めるCore領域である。

Brainは巨大な1本のLLM Pipelineにしない。

> **Responsibility graphとRuntime call graphは別物である。**

責務は分離するが、LLM callを数珠つなぎにしない。各ModuleはEvent / Snapshot / Candidate / Fact / Revisionを介して疎結合に協調する。

---

## 2. Brain Module Map

```text
B01 Input Gateway                    #349
B02 Input Meaning                    #326
B03 Subjective Appraisal             #327
B04 Internal State Reducer           #327
B05 Memory Store / Retrieval         #332
B06 Reflection / Consolidation       #364
B07 Executive Deliberation           #328
B08 Goal / Commitment State          #366
B09 Goal / Activity Planning         #361
B10 Activity Runtime                 #329
B11 Execution Coordination           #329
B12 Speech Semantics                 #362
B13 Character Language Realizer      #330
B14 Independent Semantic Verifier    #363
B15 Speech Performance               #331
B16 Speech Pipeline                  #348
B17 Autonomy / Turn Management       #333
```

Bodyは兄弟Core領域 #335。
Runtime KernelはBrain判断ModuleではなくCore Foundation #322。

この順序は責務理解用であり、`B01→B02→…→B17`を毎回固定直列awaitする意味ではない。

---

## 3. Cognitive Snapshot / Revision

各long-running処理はmutable Core objectを長時間直接保持せず、version付きread modelを使う。

```text
CognitiveSnapshot
- revision
- typed events / meanings
- appraisal facts
- internal state
- memory evidence
- relationship
- GoalContextView / goal_revision
- activity facts
- capability facts
- execution facts
- turn / interruption state
- speech state
- body capability summary
```

Role / Planner結果は原則candidate/eventとして返す。

```text
Role result
→ schema / responsibility validation
→ typed candidate/event
→ revision / precondition validation
→ owning Module may commit
```

### Concurrency invariant

- 1 LLM request中でも他Eventを受信できる
- unrelated workを同じLLM request待ちで停止しない
- Deep Appraisalを全Decisionのblocking prerequisiteにしない
- Speech playbackをnext decision/generationのblocking prerequisiteにしない
- Reflectionをforeground conversationのblocking prerequisiteにしない
- Body realtime / Game realtimeをBrain LLM待ちで停止しない
- stale context / stale goal revisionをcommitしない
- background LLM burstでforeground interactionをstarveしない

---

## 4. Authority Map

| Authority | Owner | 非Authority |
|---|---|---|
| open-ended外部自然言語の意味 | B02 Input Meaning | downstream regex/keyword |
| 出来事の主観的評価 | B03 Appraisal contract | Character / Activity |
| current Emotion/Desire/Drive等 | B04 State Reducer | LLM candidate |
| Memory永続正本・想起 | B05 Memory Store | Character / current state |
| Memory Candidate生成 | B06 Reflection | DB直接書込み |
| conscious Goal / Action選択 | B07 Executive | Planner / Character / Body / Skill AI |
| current Goal / Commitment正本 | B08 Goal State | Prompt内一時記憶 / Activity / Memory |
| 複雑Goalの実行計画 | B09 Planner | Goal採用・放棄 |
| Activity lifecycle | B10 Activity Runtime | raw input semantic判断 |
| 実際に起きたこと | B11 Execution Coordination | Intent / Plan / Character claim |
| 発言として何を伝えるか | B12 Speech Semantics | Character style |
| どうゆららしく言うか | B13 Character | What-to-say / Fact authority |
| 発話意味保持の観測 | B14 Verifier | final free-form authority |
| Speech performance | B15 Performance | Character semantic authority |
| Speech candidate/presentation lifecycle | B16 Pipeline | playbackによるBrain全体lock |
| Executive trigger / turn eligibility | B17 Autonomy/Turn | Goal / content decision |

---

## 5. B01 Input Gateway — #349

Source差を`NormalizedInputEvent`へ変換する。

- Text / STT transcript
- Streaming input
- Touch
- Vision / Perception output
- Game / Subsystem event
- timers / lifecycle events

意味・感情・Goalをここで決めない。Game stateやTouch等、既に構造化できる入力を無理に自然言語化しない。

---

## 6. B02 Input Meaning — #326

質問:

> 外部から何が伝えられたのか。

自然言語を`StructuredInputMeaning`へ構造化する。

最低限:

```text
- speech_act / primary_intent
- expected_response
- target / entities
- references
- information_provided
- negated / hypothetical
- temporal relation
- confidence
- unresolved fields
```

### Reference resolution

「もう一回」「それ」「さっきの」を固定phrase専用処理にしない。

bounded `ReferenceContext`には必要に応じて:

- recent speech
- Executive decisions
- Goal/Commitment refs
- Activity / Execution facts
- current topic
- Memory evidence

を含める。

解決不能ならclarification/fail-closed。Body/Activity/Pluginがraw textを再解釈しない。

open-ended NLのsemantic authorityにfinite dictionary / regex / substringを使わない。

---

## 7. B03 Subjective Appraisal — #327

質問:

> この出来事は、現在のゆらにとってどういう意味を持つか。

Input Meaningと主観評価を分離する。同じ出来事でもEnergy、Desire、Relationship、Goal、Commitment、Values、Recent Experience等により評価は変わる。

実装は固定しない。

- 明確な評価: deterministic model/rule
- open-endedで文脈依存: Appraisal LLM利用可

LLM出力は`AppraisalCandidate / StateDeltaProposal`でありcurrent stateではない。

```text
Appraisal candidate
→ validation
→ B04 State Reducer
```

Deep Appraisal LLMを毎回blocking dependencyにしない。後着結果が妥当なら新しいState transition / Executive triggerを発生させる。

---

## 8. B04 Internal State Reducer — #327

最低facet:

- Emotion
- Desire
- Drive
- Motivation
- Moral / Values appraisal
- Interest / Curiosity per target
- Relationship state
- Arousal / Energy

```text
StateFacet
- current
- previous
- delta
- causes[]
- updated_at
```

current stateの唯一の書込みAuthorityはState Reducer。
Character speech・Memory過去値・LLM自由文を直接代入しない。

---

## 9. B05 Memory Store / Retrieval — #332

Memory:

- Working / Short-term
- Episodic
- Semantic
- Relationship
- Preference / Interest
- Activity / Skill

`MemoryEvidenceView`としてbounded retrievalを提供する。

Memoryはcurrent Internal State / Goal State / Execution Factより強いAuthorityを持たない。

Storeはprovenance / freshness / confidence / contradictionを管理する。

---

## 10. B06 Reflection / Consolidation — #364

質問:

> 今回の経験から何を長期的に覚える価値があるか。

```text
Typed events / results / state transitions
→ Reflection
→ MemoryCandidate[]
→ B05 validation / store
```

ReflectionはMemory DBへ直接自由文を書き込まない。
foreground会話をblockしない低優先background laneで動作可能。

---

## 11. B07 Executive Deliberation — #328

質問:

> 私は今、何をしたい／何をする／何をしないか。

ゆらのconscious Goal / Action selectionの唯一の最終Authority。

入力には必要な範囲で:

- current event / meaning
- Appraisal / Internal State
- Memory evidence
- Relationship
- B08 GoalContextView
- Activity / Capability / Execution facts
- Turn / Speech state
- Body capability
- time / environment

を含む。

出力`ExecutiveDecision`はhigh-level intentと、必要なGoal/Commitment transition intentを含められる。

Executiveがしないこと:

- 複雑Activityの全step生成
- Character最終台詞
- detailed propositionsを常に全生成
- TTS parameter
- Body joint angle
- Game frame-level action
- Memory/Goal Storeへの直接自由書込み

---

## 12. B08 Goal / Commitment State — #366

詳細: `goal_commitment_architecture.md`

Executiveが選んだGoal/Commitmentをturn・Activity・LLM context windowを跨いで保持するcurrent stateの正本。

```text
Executive Goal transition intent
→ authority / lifecycle / revision validation
→ GoalStateReducer
→ GoalStateChanged event
```

Lifecycle例:

```text
proposed → active → suspended → active → completed
or abandoned / failed / superseded
```

重要:

- ExecutiveがGoal採用/放棄Authority
- B08はvalidated transition適用と正本状態所有
- PlannerはGoalを変えない
- Activity failureでGoalを自動消去しない
- Memoryの過去Goalをcurrent Goalへ直接復元しない
- Character speechだけでCommitmentを自動作成しない
- pending Goal/CommitmentはB17のExecutive trigger sourceになり得る

---

## 13. B09 Goal / Activity Planning — #361

質問:

> active Goalをどう実行するか。

```text
GoalState(goal_id, goal_revision)
+ Capability / Activity snapshot
→ Planner
→ ActivityPlan(goal_id, goal_revision)
```

単純ActionではPlanner LLMを呼ばない。
PlannerはGoal Authorityを持たない。
Goal revision不一致のPlanはstale/replan_required。

---

## 14. B10 Activity Runtime — #329

Activity execution lifecycleを所有する。

```text
requested → accepted → starting → active → completing → completed
or paused / interrupted / cancelled / failed / unsupported
```

Goal正本ではない。Activity failureはExecution Factとなり、ExecutiveがGoal transitionを再判断する。

---

## 15. B11 Execution Coordination — #329

accepted decision/planをSpeech / Body / Plugin / Subsystem / Memory operation等へ非同期dispatchし、actual lifecycle factを記録する。

```text
requested → accepted → planned → started → observable/applied → completed
or rejected / unsupported / failed / cancelled / timed_out
```

一executorの長いawaitで他laneを停止しない。

Intent/PlanとActual Factを混同しない。

---

## 16. B12 Speech Semantics — #362

質問:

> Executive SpeechIntentを実現するため、何を伝えるか。

V1の`What to say != How to say it`を維持する。

`SpeechSemanticPlan`:

- propositions
- required / optional / forbidden content
- polarity / certainty / degree
- self-disclosure
- question / new-direction budget
- execution truth constraints

simple speechでは専用大型LLMを省略/軽量化できる。complex speechのみ専用Roleを起動可能。

---

## 17. B13 Character Language Realizer — #330

質問:

> 確定済みの意味を、ゆらならどう言うか。

`SpeechSemanticPlan + Character Language Projection → CharacterUtterance`。

CharacterがGoal、raw Internal State、Execution Factを再解釈して発言意味を作り直さない。

---

## 18. B14 Independent Semantic Verifier — #363

`SpeechSemanticPlan + CharacterUtterance → SemanticRelationObservation`。

VerifierはObserver。

禁止:

- Speech Intent変更
- Character直接指揮
- Runtime Fact変更
- free-form verdictを最終Authority化

最終accept/rejectはclosed typed policyからRuntimeが導出する。

Verifierを直列滞留要因にしない。Character後、Verifierと安全なPerformance/speculative TTS preparationを並列化可能。required PASS前にexternal Presentation commitはしない。

---

## 19. B15 Speech Performance — #331

engine-independentな音声演技計画を所有する。

- phrase timing
- pause
- speed intent
- pitch / intonation intent
- volume / breathiness intent

VOICEVOX等の具体parameterはProvider Adapterが投影する。

---

## 20. B16 Speech Pipeline — #348

詳細: `speech_pipeline_architecture.md`

PreparationとPresentationを分離する。

- playback中next generation可
- prepared candidateはbounded
- pre-presentation revalidation
- stale / superseded / cancelled
- committed SpeechだけがPresentation Fact / viseme対象

論理責務を固定直列LLM chainへしない。

---

## 21. B17 Autonomy / Turn Management — #333

「いつExecutiveを起動できるか」を管理する。「何をするか」は決めない。

trigger source:

- user interaction
- Desire / Interest / state changes
- time / environment
- Memory activation
- Activity Result
- B08 pending Goal / Commitment

管理:

- turn ownership
- interruption
- autonomous initiative eligibility
- user priority
- pending/prepared/presenting speech
- cooldown / fairness / anti-starvation

固定timer→固定台詞、前Speech終了→次生成開始を正規経路にしない。

---

## 22. Body / Skill AI boundary

### Body

ExecutiveDecisionからSpeechとBodyへ兄弟fan-outする。
CharacterがBodyを指揮しない。

### Game #365

```text
Executive Goal / Strategy
→ Game Skill Runtime
→ realtime game-specific policy
→ Game Result
→ Appraisal / Executive
```

frame-level actionをExecutive LLMへ毎frame問い合わせない。

### Streaming #347

大量comment classification / summary / moderation signalはSubsystem側で処理可能。Coreへ必要なtyped eventだけ戻す。

---

## 23. LLM Role追加・統合基準

新Roleは最低限:

1. 独立した質問を1文で言える
2. typed input/outputがある
3. Authority重複がない
4. Unit評価可能
5. 独立交換・停止可能
6. failure/degradationが定義可能
7. LLMが本当に適切

Role分離しても実行時に必ず別API callを行う必要はない。
Goal/Commitment Stateのような正本状態責務を無理にLLM Role化しない。

---

## 24. V1から継承する教訓

維持:

- Input Meaning / Decision分離
- What to say / How to say it分離
- Character責務過剰回避
- independent semantic observation
- typed semantic facets
- finite phrase dictionaryを意味Authorityにしない
- raw internal stateをCharacterに解釈させない
- 実LLM failureをfailure classとして設計へ戻す

改善:

- Role数を先に固定しない
- conscious AuthorityをExecutiveへ一本化
- current Goal / Commitmentの正本を明示
- Logical Role分離を直列LLM chainへしない
- slow model responseをCore全体へ伝播させない
- foreground/background priorityを分離

---

## 25. Brain Acceptance

- [ ] Input Meaningがopen-ended raw text semantic authorityとして一意
- [ ] AppraisalとMeaningが分離
- [ ] Appraisal LLMがStateを直接書かない
- [ ] Executiveが唯一のconscious Goal/Action authority
- [ ] #366がcurrent Goal/Commitment正本を所有
- [ ] Goal/Commitmentがturn/context windowを跨いで維持
- [ ] PlannerがGoal Authorityを奪わない
- [ ] Goal State / Activity / Memoryが分離
- [ ] What to say / How to say itが分離
- [ ] Independent VerifierがObserver
- [ ] CharacterがExecution Factを捏造しない
- [ ] ReflectionがMemory Storeへ直接自由書込みしない
- [ ] LLM Role数が固定されていない
- [ ] Responsibility graphとcall graphが分離
- [ ] slow LLMがunrelated laneをblockしない
- [ ] playback中next generation可能
- [ ] stale context / goal revisionをcommitしない
- [ ] foreground interactionがbackground workでstarveしない
- [ ] Brain minimum Integration #334 PASS

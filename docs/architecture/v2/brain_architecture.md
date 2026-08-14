# AI Liver ゆら V2 Brain Architecture

Status: Draft / V2 Design Gate
Parent: `docs/architecture/v2/system_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Goal / Commitment: `docs/architecture/v2/goal_commitment_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #325
Root: #317

## 1. 目的

Brainは、外部/内部Eventを理解・評価し、Internal State・Memory・Relationship・persistent Goal/Commitment・Activity/Execution Fact・Attention/Turnを使って、ゆらが「今何をしたい／する／しない」を決めるCore領域である。

責務を分離しても巨大な直列LLM Pipelineにはしない。

> **Responsibility graph != Runtime invocation graph**

---

## 2. Module Map

```text
B01 Input Gateway                       #349
B02 Input Meaning                       #326
B03 Subjective Appraisal                #327
B04 Internal State Reducer              #327
B05 Memory Store / Retrieval            #332
B06 Reflection / Consolidation          #364
B07 Executive Deliberation              #328
B08 Goal / Commitment State             #366
B09 Goal / Activity Planning            #361
B10 Activity Runtime                    #329
B11 Execution Coordination              #329
B12 Speech Semantics                    #362
B13 Character Language Realizer         #330
B14 Independent Semantic Verifier       #363
B15 Speech Performance                  #331
B16 Speech Pipeline                     #348
B17 Attention / Autonomy / Turn         #333
```

Body #335は兄弟Core領域。Runtime Kernel #322はCore FoundationでありBrain判断Authorityを持たない。

番号は責務整理用で、毎回B01→B17を直列awaitする意味ではない。

---

## 3. Cognitive Snapshot / Revision

```text
CognitiveSnapshot
- revision
- typed events / meanings
- appraisal facts
- internal state
- memory evidence
- relationship
- GoalContextView / goal_revision
- AttentionFocusView / attention_revision
- activity facts
- capability facts
- execution facts
- speech / presentation state
- body capability summary
```

long-running workは必要なrevisionを保持する。

```text
result
→ schema/responsibility validation
→ authority validation
→ context / goal / attention revision checks
→ owning Module commits or rejects
```

---

## 4. Authority Map

| Authority | Owner |
|---|---|
| open-ended外部自然言語の意味 | B02 Input Meaning |
| 出来事の主観的評価 / salience candidate | B03 Appraisal |
| current Emotion/Desire/Drive等 | B04 State Reducer |
| Memory永続正本・Retrieval | B05 Memory Store |
| Memory Candidate生成 | B06 Reflection |
| conscious Goal / Action選択 | B07 Executive |
| current Goal / Commitment正本 | B08 Goal State |
| 複雑Goalの実行計画 | B09 Planner |
| Activity lifecycle | B10 Activity Runtime |
| Actual Execution Fact | B11 Execution Coordination |
| What to say | B12 Speech Semantics |
| How to say it | B13 Character Language |
| 発話意味保持の観測 | B14 Verifier |
| Speech performance | B15 Performance |
| Speech candidate / presentation lifecycle | B16 Pipeline |
| **current Focus / Turn state・Event eligibility** | **B17 Attention/Autonomy/Turn** |

B17は意味・Goal・Speech内容を決めない。Appraisalがsalienceを示し、Executiveがdeliberate attention intentを出し、B17がtyped Focus/Turn stateとschedulingを所有する。

---

## 5. B01 Input Gateway — #349

Text/STT、Streaming、Touch、Vision、Game、lifecycle/timer等を`NormalizedInputEvent`へ正規化する。

意味・感情・Goalを決めない。既に構造化されたGame state/Touch等を無理に自然言語化しない。

---

## 6. B02 Input Meaning — #326

質問:

> 外部から何が伝えられたのか。

自然言語を`StructuredInputMeaning`へ変換する。

- speech act / intent
- target / entities
- references
- provided information
- negation / hypothetical / temporal relation
- confidence / unresolved fields

「もう一回」「それ」等はbounded ReferenceContextから解決する。

ReferenceContextには必要に応じrecent speech / Executive decision / Goal ref / Activity fact / Memory evidenceを含める。

finite keyword/regex/substringをopen-ended semantic fallbackにしない。

---

## 7. B03 Subjective Appraisal — #327

質問:

> この出来事は現在のゆらにとってどういう意味を持つか。

Input Meaningと分離する。同じEventでもInternal State、Relationship、Goal/Commitment、Activity、Values等で評価は変わる。

LLM利用は任意。LLMを使う場合も`AppraisalCandidate / StateDeltaProposal`を返しcurrent stateを直接変更しない。

Deep Appraisalを全Decisionのblocking prerequisiteにしない。

salience / relevanceはB17 Attentionへ候補として渡せるが、AppraisalがFocus/Goalを直接決定しない。

---

## 8. B04 Internal State Reducer — #327

保持例:

- Emotion
- Desire
- Drive
- Motivation
- Values/Moral appraisal
- Interest/Curiosity
- Relationship
- Energy/Arousal

current stateの唯一の書込みAuthority。Character、Memory過去値、LLM自由文を直接代入しない。

---

## 9. B05 Memory Store / Retrieval — #332

Working / Episodic / Semantic / Relationship / Preference / Activity/Skill Memoryをtypedに保持し、bounded `MemoryEvidenceView`を返す。

Memoryはcurrent Internal State / Goal State / Execution Factより強いAuthorityを持たない。

---

## 10. B06 Reflection — #364

会話・配信・ゲーム・Activity Result等からlong-term `MemoryCandidate`を生成する。

```text
Reflection
→ MemoryCandidate
→ B05 provenance/freshness/conflict validation
```

低優先background laneとしてforeground interactionをblockしない。

---

## 11. B07 Executive Deliberation — #328

質問:

> 私は今、何をしたい／する／しないか。

唯一のconscious Goal / Action selection Authority。

入力には必要な範囲で:

- Meaning / Appraisal / Internal State
- Memory / Relationship
- GoalContextView
- AttentionFocusView
- Activity / Capability / Execution facts
- Speech / Body state
- time / environment

を含む。

出力:

- selected high-level intent
- Goal/Commitment transition intent
- SpeechIntent
- BodyIntent
- ActivityIntent
- attention_intent
- wait / silence
- priority / preconditions / interruptibility

Store直接mutation、complex Plan全step、最終台詞、joint angle、Game frame actionは生成しない。

LLM完了後のcommitではsource / goal / attentionに加えてInternal Stateの独立revisionをcurrent ownerから再取得する。Capability / Preconditionもcurrent値を再検証し、intentに必要な条件はLLMの自己申告だけでなく信頼済みpolicyまたはupstream typed contractから導出する。

---

## 12. B08 Goal / Commitment State — #366

詳細: `goal_commitment_architecture.md`。

Executive由来validated transitionを適用し、turn/context windowを跨ぐcurrent Goal/Commitmentをrevision付きで保持する。

Planner/Activity/Memory/AttentionはGoal Authorityを持たない。

pending Goal/CommitmentはB17のExecutive trigger sourceになり得る。

---

## 13. B09 Goal / Activity Planning — #361

active Goalを複雑な`ActivityPlan`へ分解する。

`goal_id / goal_revision`を保持し、旧revision planはstale/replan扱い。

simple actionでは専用Planner LLMを呼ばなくてよい。

---

## 14. B10 Activity Runtime — #329

Activity execution lifecycleを所有する。

```text
requested → accepted → starting → active → completing → completed
or paused / interrupted / cancelled / failed / unsupported
```

Goal正本ではない。

---

## 15. B11 Execution Coordination — #329

Speech / Body / Plugin / Subsystem / Memory operation等へaccepted workを非同期dispatchしActual Factを記録する。

```text
requested → accepted → planned → started → observable/applied → completed
or rejected / failed / cancelled / timed_out
```

Intent / Plan / Character claimとActual Factを混同しない。

---

## 16. B12 Speech Semantics — #362

`What to say` Authority。

Executive SpeechIntentからpropositions、required/forbidden、certainty/polarity/degree、question budget、execution truth等を`SpeechSemanticPlan`へ確定する。

simple pathでは専用LLMを省略可能。

---

## 17. B13 Character Language — #330

`How to say it`。

`SpeechSemanticPlan + Character Language Projection → CharacterUtterance`。

Goal / Internal State / Execution Factを再解釈して意味を変更しない。

---

## 18. B14 Independent Semantic Verifier — #363

`SpeechSemanticPlan + CharacterUtterance → SemanticRelationObservation`。

ObserverでありSpeech Intent変更、Character直接指揮、Runtime Fact変更、free-form final Authorityを持たない。

---

## 19. B15 Speech Performance — #331

engine-independent prosody / timing / pause / acoustic intentを所有する。具体TTS parameterはInfrastructure Adapter。

---

## 20. B16 Speech Pipeline — #348

PreparationとPresentationを分離。

- playback中next generation可
- bounded prepared candidate
- revalidation before presentation
- stale / superseded / cancelled
- Verifierとsafe preparationを可能な範囲でparallel

---

## 21. B17 Attention / Autonomy / Turn — #333

複数Activityの注意資源・Focus・Turn・Executive trigger eligibilityを所有する。

```text
AttentionFocusState
- revision
- foreground_focus
- secondary_monitors[]
- current_turn_owner
- response_obligation
- attention_budget
- interruption_thresholds
- source_priority_policy
```

例:

```text
foreground = Game match
secondary = Streaming aggregated comments
high-priority interruption = direct user speech
background = Reflection
```

高頻度Game frameや全commentをExecutiveへ1件ずつ同期投入しない。

B17がする:

- focus / monitor state
- turn ownership
- event eligibility / bounded priority
- interruption / response obligation
- autonomous trigger scheduling
- fairness / anti-starvation

B17がしない:

- NL semantic判断
- Goal採用/放棄
- Speech内容決定
- Internal State mutation

Executiveの`attention_intent`をtyped revision付きでFocus Stateへ適用可能。

Focus StateはBody gaze/expressionへ投影できるがBodyがcognitive Attention Authorityにはならない。

---

## 22. Runtime KernelはBrainではない

#322がqueue / scheduler / cancellation / priority / backpressure / clock / task lifecycle / health / shutdownを所有する。

Domain意味やGoalを決めない。

---

## 23. Skill AI boundary

### Game #365

```text
Executive Goal / Strategy
→ Game Skill Runtime
→ realtime policy
→ Game Result
→ Appraisal / Attention / Executive
```

frame-level actionをExecutive LLMへ毎frame問い合わせない。

### Streaming #347

大量commentはSubsystem側でaggregateし、representative/salient typed eventをB17 Attention経由でExecutive eligibilityへ接続可能。

Skill AIはGoal Authorityを持たない。

---

## 24. Brain Acceptance

- [ ] Input Meaningがopen-ended NL semantic authorityとして一意
- [ ] Meaning / Appraisal / State / Attention / Executiveが分離
- [ ] Appraisal LLMがState/Focusを直接mutationしない
- [ ] Executiveが唯一のconscious Goal/Action authority
- [ ] #366がpersistent Goal/Commitment正本
- [ ] PlannerがGoal Authorityを奪わない
- [ ] Goal State / Activity / Memoryが分離
- [ ] #333がFocus/Turn schedulingを持つが意味/Goalを決めない
- [ ] Game/Streaming event burstをboundedにAttentionへ接続
- [ ] What-to-say / How-to-say分離
- [ ] VerifierはObserver
- [ ] CharacterがExecution Factを捏造しない
- [ ] LLM Role数固定なし
- [ ] Responsibility graph / call graph分離
- [ ] slow workがunrelated laneをblockしない
- [ ] playback中next generation可能
- [ ] stale context / goal / attention revisionを誤commitしない
- [ ] foreground interactionがbackgroundでstarveしない
- [ ] Brain Integration #334 PASS

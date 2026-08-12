# AI Liver ゆら V2 Goal / Commitment Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/brain_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Work Issue: #366
Root management: #317

## 1. 目的

ゆらが「その場のLLM応答」ではなく、turn・会話・Activity・LLM context windowを跨いで、自分が何を目指しているか、何を約束したか、何を後でやるつもりかを保持するための正本状態を定義する。

自由意志に近い継続主体には、毎回のExecutive推論だけでは不十分である。

```text
Executive decides a goal
→ goal is committed into persistent typed state
→ time / input / activity may pass
→ goal remains visible to later cognition
→ execution result / new decision changes its lifecycle
```

Goal/Commitment StateはLLM Roleではない。LLMの自由文ではなく、validated transitionを適用するtyped state ownerを基本とする。

---

## 2. Authority

### Executive #328

唯一のconscious Goal / Action selection Authority。

Executiveが決める:
- new Goalを採用する
- Goalを放棄する
- Goal priorityを変える
- Goalをsuspend / resumeする意図
- Commitmentを引き受ける / 解消する意図

### Goal / Commitment State #366

current Goal / Commitmentの正本を所有する。

Executiveが出したvalidated transitionを適用し、revision付きの現在状態を公開する。

### Goal Planner #361

Goalを「どう実行するか」へ分解する。
Goalそのものを変更しない。

### Activity Runtime #329

現在実行中Activityのexecution lifecycleを所有する。
Goal正本ではない。

### Memory #332 / Reflection #364

過去Goal・約束・結果を記憶できるが、current Goal/Commitmentの正本ではない。

---

## 3. GoalとActivityを分離する

例:

```text
Goal:
  Keiichirouと今夜ゲームをして楽しむ

Activity:
  game_session_123
```

Activityが一度失敗・中断してもGoalが直ちに消えるとは限らない。

```text
Goal active
→ Activity A failed
→ Executive re-evaluates
→ retry with Activity B
or suspend / abandon Goal
```

逆にActivityが動いているからといって、暗黙に新Goalが作られたことにはしない。

---

## 4. Goal State

候補Contract:

```text
GoalState
- goal_id
- goal_type
- subject / target refs
- semantic_goal
- created_from_decision_id
- status
- priority
- motivation_refs[]
- value_refs[]
- relationship_refs[]
- commitment_refs[]
- required_capabilities[]
- preconditions[]
- completion_conditions[]
- interruption_policy
- created_at
- updated_at
- revision
```

`semantic_goal`はtyped semantic representationを基本とし、LLM向けの説明文だけを正本にしない。

### lifecycle

```text
proposed
→ active
→ suspended
→ active
→ completed

or
abandoned / failed / superseded
```

`failed`はActivity failureと同義ではない。Goal自体が達成不能・不要になった等、Goal lifecycleとして確定した場合に用いる。

---

## 5. Commitment State

Commitmentは単なるMemoryではなく、現在の行動選択へ影響する社会的・自己拘束的状態。

```text
CommitmentState
- commitment_id
- commitment_type
- counterparty_ref?
- semantic_commitment
- source_event_ids[]
- source_decision_id
- related_goal_ids[]
- priority / strength
- due_condition?
- release_condition?
- status
- created_at
- updated_at
- revision
```

例:

- 「このゲーム終わったら話そう」
- 「あとで配信する」
- 視聴者へ「次の試合で終わる」と伝え、その内容をExecutiveがCommitmentとして受理した場合

Characterが言っただけで自動Commitment化しない。

```text
CharacterUtterance
≠ Commitment Fact
```

必要なSpeechSemanticPlan / Executive transition / Presentation Factをもとに、明示contractでcommitする。

---

## 6. Transition Contract

```text
GoalTransitionRequest
- transition_id
- goal_id?
- operation
- source_decision_id
- expected_revision?
- payload
- reason_refs[]
- occurred_at
```

Operation例:

- create
- activate
- reprioritize
- suspend
- resume
- complete
- abandon
- fail
- supersede

Validator確認:

- Executive authority
- expected revision
- lifecycle legality
- referenced Goal/Commitment existence
- capability/fact claims if relevant
- duplicate/idempotency

適用:

```text
Validated GoalTransition
→ GoalStateReducer
→ new goal_revision
→ GoalStateChanged event
```

---

## 7. Goal selectionとGoal persistence

Executiveの毎回のPromptへ全Goalを無制限投入しない。

`GoalContextView`をboundedに構築する。

```text
GoalContextView
- active high-priority goals
- relevant suspended goals
- due commitments
- conflicting commitments
- recently changed goals
- current Activity links
- revision
```

Goal Storeが存在することで、LLM context window外へ出たGoalが消滅することを防ぐ。

---

## 8. Autonomous trigger

#333 Autonomy / TurnはGoalを決めないが、次をtrigger sourceとして利用できる。

- active Goal with next action due
- suspended Goal whose resume condition became true
- Commitment due condition
- Activity completed and parent Goal remains active
- Goal deadline/context transition

```text
Goal/Commitment event
→ Autonomy eligibility
→ Executive trigger
→ Executive decides what to do
```

`Goal due → fixed action`にはしない。

---

## 9. Plannerとのrevision contract

Planner request:

```text
GoalPlanningRequest
- goal_id
- goal_revision
- source_context_revision
- GoalContextView
- CapabilitySnapshot
- ActivitySnapshot
```

Plan:

```text
ActivityPlan
- plan_id
- goal_id
- goal_revision
- ...
```

commit前:

```text
current goal_revision == plan.goal_revision ?
```

不一致ならstale / replan_required。

Goalがabandoned/supersededされた後に古いPlanを実行しない。

---

## 10. Execution resultとのfeedback

Activity/Capability/Game/Streaming結果はGoalを直接書き換えない。

```text
Execution Result
→ Appraisal / Executive
→ Executive chooses goal transition
→ Goal State Reducer
```

明白な機械的completion conditionだけは、事前に定義されたclosed deterministic policyでtransition candidateを生成してよいが、意識的Goal AuthorityをRuntimeへ移さない。

---

## 11. Memoryとの境界

### current Goal State

「今も目指している」ことの正本。

### Episodic Memory

「昨日このGoalを持っていた」「達成した」という過去の証拠。

### Semantic / Preference Memory

「このゲームが好き」「配信を続けたい傾向」等。

Memory retrievalで古いGoalを見つけてもcurrent Goalへ直接復元しない。

```text
Memory evidence
→ Executive/Appraisal
→ new validated Goal transition if appropriate
```

---

## 12. Internal Stateとの境界

Emotion / Desire / Drive / MotivationはGoal形成の原因になり得るがGoalそのものではない。

```text
high curiosity
→ Appraisal / Executive
→ Goal: investigate topic
```

Desireが減ったからGoalをdeterministicに即削除しない。CommitmentやValues、進行中Activity等もExecutiveが考慮する。

---

## 13. Persistence

Goal/CommitmentはCore Domain Stateであり、Repository Portを通して永続化可能。

Persistence provider unavailable時:

- in-memory current stateで安全に継続可能な範囲は継続
- persistence healthをtypedに記録
- durable guaranteeを偽らない
- reconnect後の競合解決をrevision/provenanceで行う

DB Providerは#359 InfrastructureでありGoal Authorityを持たない。

---

## 14. Concurrency

Goal State mutationは同一Goal/Commitment単位でatomic / serializedにし、正本競合を防ぐ。

ただしGoal Store処理をCore全体のglobal lockにしない。

```text
Goal transition running
while
  Body realtime continues
  current speech continues
  Game frame loop continues
  unrelated input reception continues
```

long-running LLM/Plannerはsnapshot/revisionを使う。

---

## 15. Truthfulness

次を区別する。

```text
I want to do X        → desire / goal semantic state
I decided to do X     → Executive decision / Goal transition
I am doing X          → Activity/Execution Fact
I did X               → completed Execution Fact
I promised X          → validated Commitment State
I said "I promise X" → Speech Presentation Fact only
```

Character claimは対応するFact/Stateに従う。

---

## 16. V1からの教訓

V1では会話turn・Activity・Memory・Internal Directive等に意図が分散しやすく、持続Goalの正本境界が明瞭ではなかった。

V2では:

- Executive Authorityは1つ
- current Goal/Commitment Stateは1つのtyped正本
- Plannerは実行方法のみ
- Activityはexecution lifecycleのみ
- Memoryは過去/evidenceのみ

として分離する。

---

## 17. Acceptance

### Unit

- create / activate
- reprioritize
- suspend / resume
- complete / abandon / fail / supersede
- invalid lifecycle transition reject
- stale expected_revision reject
- duplicate/idempotent transition
- conflicting commitment representation

### Adjacent

- Executive → Goal transition
- Goal State → Planner
- Goal State → Autonomy trigger
- Activity Result → Executive → Goal transition
- Goal State ↔ Persistence Port

### Integration

- Goal survives multiple conversation turns
- Goal survives unrelated user interaction
- Goal does not vanish because LLM context was truncated
- suspended Goal can later trigger Executive reconsideration
- stale Plan from old goal_revision is rejected
- Activity failure does not automatically erase Goal
- Character speech alone does not create Commitment
- actual Commitment influences later Executive decision

---

## 18. Design Gate

- [x] #366 Work Issue created with Start / Target
- [ ] Brain canonical owns current Goal/Commitment via #366
- [ ] Cognitive Authority Map includes Goal/Commitment State
- [ ] #361 Planner consumes goal_revision
- [ ] #333 Autonomy consumes Goal/Commitment trigger view
- [ ] #334 Brain Integration covers persistent Goal lifecycle
- [ ] #360 System Verification covers turn/context-window persistence
- [ ] Project sync manifest/hierarchy includes #366

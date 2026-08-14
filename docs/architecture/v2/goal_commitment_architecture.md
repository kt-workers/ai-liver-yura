# AI Liver ゆら V2 Goal / Commitment Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/brain_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Work Issue: #366
Root management: #317

## 1. 目的

ゆらが「その場のLLM応答」ではなく、turn・会話・Activity・LLM context windowを跨いで、自分が何を目指しているか、何を約束したか、何を後でやるつもりかを保持する正本状態を定義する。

```text
Executive decides a goal
→ validated transition
→ persistent typed Goal / Commitment State
→ time / input / activity may pass
→ later cognition still sees the goal
→ result / new decision changes lifecycle
```

Goal/Commitment StateはLLM Roleではない。LLM自由文ではなくtyped state owner / reducerを基本とする。

---

## 2. Authority

### Executive #328

唯一のconscious Goal / Action selection Authority。

Executiveが決める:
- new Goal採用
- Goal放棄 / reprioritize
- suspend / resume intent
- Commitmentを引き受ける / 解消するintent

### Goal / Commitment State #366

current Goal / Commitmentの正本。

Executive由来のvalidated transitionを適用し、revision付きcurrent stateを公開する。

### Planner #361

Goalをどう実行するかへ分解する。Goal自体を変更しない。

### Activity Runtime / Execution #329

現在Activityのexecution lifecycle / actual factを所有する。Goal正本ではない。

### Memory #332 / Reflection #364

過去Goal・約束・結果を記憶できるがcurrent Goal/Commitmentの正本ではない。

### Attention / Autonomy / Turn #333

Goal/Commitmentをtrigger source / FocusContextとして利用できるがGoal自体を変更しない。

---

## 3. GoalとActivityを分離

```text
Goal:
  Keiichirouとゲームをして楽しむ

Activity:
  game_session_123
```

Activity failure/interruptでGoalが自動消滅するとは限らない。

```text
Goal active
→ Activity A failed
→ Appraisal / Executive
→ retry / suspend / abandon / alternate Activity
```

Activityが存在するだけで暗黙に新Goalを作らない。

---

## 4. Goal State

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

`semantic_goal`はtyped semantic representationを基本とし、LLM説明文だけを正本にしない。

Lifecycle:

```text
proposed → active → suspended → active → completed
or abandoned / failed / superseded
```

`failed`はActivity failureと同義ではない。

---

## 5. Commitment State

CommitmentはMemoryだけではなく、現在の行動選択へ影響する社会的・自己拘束的current state。

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
- 「次の試合で終わる」と視聴者へ約束しExecutiveがCommitmentとして受理

Characterが言っただけで自動Commitment化しない。

```text
CharacterUtterance != Commitment Fact
```

Speech semantic / Executive transition / Presentation Fact等を明示contractで接続する。

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
- create / activate
- reprioritize
- suspend / resume
- complete / abandon / fail / supersede

Validation:
- Executive authority
- expected revision
- lifecycle legality
- referenced state existence。batch内の全transitionをcopyへ適用した後、Goalの`commitment_refs`とCommitmentの`related_goal_refs`がfinal copy内に存在することを検証し、dangling referenceをatomic rollbackする
- capability/fact claim if relevant
- duplicate/idempotency

operation別payloadはfieldのpresenceでstrictに閉じる。`0`はpriority/strengthの合法値であり、未指定を意味しない。値を使用しないoperationへnullable scalarの`0`を含めて渡した場合もschema外として拒否し、silent ignoreしない。

```text
Validated GoalTransition
→ GoalStateReducer
→ new goal_revision
→ GoalStateChanged event
```

---

## 7. GoalContextView

Executive Promptへ全Goalを無制限投入しない。

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

Goal Storeがあることで、LLM context window外へ出たGoalが消滅することを防ぐ。

---

## 8. Attention / Autonomous Trigger

#333はGoalを決めず、次をExecutive trigger / attention scheduling sourceとして利用する。

- active Goal with next action due
- resume condition fulfilled
- Commitment due condition
- Activity completed while parent Goal remains active
- Goal context/deadline change

```text
Goal/Commitment event
→ #333 Attention / Autonomy eligibility
→ Executive trigger
→ Executive decides what to do
```

`Goal due → fixed action`にはしない。

Goal/CommitmentがGame foregroundやStreaming secondary monitorと競合する場合も#333のbounded Focus/Turn policyを通す。

---

## 9. Planner Revision Contract

```text
GoalPlanningRequest
- goal_id
- goal_revision
- source_context_revision
- GoalContextView
- CapabilitySnapshot
- ActivitySnapshot
```

```text
ActivityPlan
- plan_id
- goal_id
- goal_revision
- ...
```

commit前:

```text
current goal_revision == plan.goal_revision
```

不一致はstale / replan_required。
Goalがabandoned/supersededされた後にold Planを実行しない。

---

## 10. Execution Result Feedback

Activity/Capability/Game/Streaming ResultはGoalを直接書き換えない。

```text
Execution Result
→ Appraisal / Executive
→ Executive chooses transition
→ Goal State Reducer
```

明白なclosed completion conditionではdeterministic transition candidateを生成してよいが、conscious Goal AuthorityをRuntimeへ移さない。

---

## 11. Memory Boundary

- current Goal State: 「今も目指している」の正本
- Episodic Memory: 「昨日このGoalを持っていた/達成した」の過去証拠
- Preference/Semantic Memory: 「このゲームが好き」等の傾向

Memory retrievalで古いGoalを見つけてもcurrent Goalへ直接復元しない。

```text
Memory Evidence
→ Appraisal / Executive
→ validated new Goal transition if appropriate
```

---

## 12. Internal State Boundary

Emotion / Desire / Drive / MotivationはGoal形成原因になり得るがGoalそのものではない。

```text
high curiosity
→ Appraisal / Executive
→ Goal: investigate topic
```

Desire低下だけでGoalをdeterministic即削除しない。Commitment、Values、Activity、Relationship等をExecutiveが考慮する。

---

## 13. Persistence

Goal/CommitmentはCore Domain StateでありRepository Port経由で永続化可能。

Persistence unavailable:
- safe範囲でin-memory継続
- persistence healthをtyped記録
- durabilityを偽らない
- reconnect後競合をrevision/provenanceで解決

DB Provider #359はGoal Authorityを持たない。

---

## 14. Concurrency

同一Goal/Commitment mutationはatomic / serialized。

ただしGoal StoreをCore global lockにしない。

```text
Goal transition running
while
  Body realtime continues
  current Speech continues
  Game frame loop continues
  Streaming ingress continues
  unrelated input reception continues
```

long-running Planner/LLMはgoal_revisionを保持する。

---

## 15. Truthfulness

```text
I want X        → desire / goal semantic state
I decided X     → Executive decision / Goal transition
I am doing X    → Activity / Execution Fact
I did X         → completed Execution Fact
I promised X    → validated Commitment State
I said promise  → Speech Presentation Fact only
```

Character claimは対応Fact/Stateに従う。

---

## 16. V1からの改善

V1では会話turn・Activity・Memory・Internal Directive等に意図が分散しやすく、persistent Goal正本が明瞭でなかった。

V2:
- Executive Authority = 1
- current Goal/Commitment State = 1 typed canonical owner
- Planner = execution method only
- Activity = execution lifecycle only
- Memory = past/evidence only
- Attention/Turn = scheduling/trigger only

---

## 17. Acceptance

### Unit
- create / activate / reprioritize
- suspend / resume
- complete / abandon / fail / supersede
- invalid lifecycle reject
- stale expected_revision reject
- duplicate/idempotent transition
- conflicting commitment

### Adjacent
- Executive → Goal transition
- Goal State → Planner
- Goal State → #333 Attention/Autonomy trigger
- Activity Result → Executive → Goal transition
- Goal State ↔ Persistence Port

### Integration
- Goal survives multiple turns
- Goal survives unrelated user interaction
- Goal does not vanish on LLM context truncation
- suspended Goal can later trigger reconsideration
- stale Plan rejected
- Activity failure does not automatically erase Goal
- Character speech alone does not create Commitment
- actual Commitment influences later Executive decision
- Goal mutation does not block Body/Game/Speech realtime

---

## 18. Design Reconciliation Status

- [x] #366 Work Issue created with Start / Target
- [x] Brain canonical owns current Goal/Commitment via #366
- [x] Cognitive Authority Map includes Goal/Commitment State
- [x] #328 outputs typed Goal/Commitment transition intents
- [x] #361 Planner consumes goal_revision
- [x] #333 Attention/Autonomy consumes Goal/Commitment trigger view
- [x] #334 Brain Integration covers persistent Goal lifecycle
- [x] #360 System Verification covers turn/context-window persistence
- [x] Concurrency canonical covers atomic mutation without global lock
- [x] Project sync manifest/runbook hierarchy includes #366

残るのは#317全体Design Gate確認と実装後Verificationである。

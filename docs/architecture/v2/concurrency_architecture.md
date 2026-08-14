# AI Liver ゆら V2 Concurrency Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Brain: `docs/architecture/v2/brain_architecture.md`
Goal / Commitment: `docs/architecture/v2/goal_commitment_architecture.md`
Runtime Work: #322
LLM Contract Work: #323
Attention / Autonomy: #333
Root management: #317

## 1. 目的

V2では責務を細かく分離するが、それを**1本のblocking処理列**へ変換しない。

特にLLMは最も大きなlatency源のため、Roleを増やした結果として各応答時間を単純加算する構造を禁止する。

> **Responsibility graph != Runtime invocation graph**

認知・発話・Body・Goal・Memory・Plugin・SubsystemをEvent-driven / snapshot-based / bounded concurrent lanesとして実行する。

---

## 2. 禁止するGlobal Cycle

```text
receive event
→ await Input Meaning LLM
→ await Appraisal LLM
→ await Executive LLM
→ await Planner LLM
→ await Speech Semantics LLM
→ await Character LLM
→ await Verifier LLM
→ await TTS
→ await playback
→ await Body completion
→ await Memory write
→ next event
```

この形では1処理の遅延・timeout・failureがSystem全体へ伝播するため採用しない。

---

## 3. 正規Runtime Model

```text
Typed Event Stream / Runtime Facts
        │
        ├─ Input / Meaning lane
        ├─ Appraisal / Internal State lane
        ├─ Attention / Turn scheduling lane
        ├─ Executive lane
        ├─ Goal / Commitment state lane
        ├─ Goal / Activity Planning lane
        ├─ Activity / Execution lane
        ├─ Speech Preparation lanes
        ├─ Speech Presentation lane
        ├─ Body Realtime lane
        ├─ Plugin / Capability lanes
        ├─ Streaming / Game Skill lanes
        └─ Reflection / Persistence lane
```

各laneはtyped Event / Candidate / Result / Snapshot revisionを介して協調する。

1 laneの`await`をCore global waitへ昇格させない。

---

## 4. Request Envelope

long-running処理は最低限:

```text
AsyncWorkRequest
- request_id
- work_kind / role_id
- source_event_ids[]
- source_context_revision
- goal_id?
- goal_revision?
- attention_revision?
- priority
- deadline / timeout_policy
- interruptibility
- preconditions[]
- stale_policy
- created_at
```

Result:

```text
AsyncWorkResult
- request_id
- source_context_revision
- goal_revision?
- result_status
- payload / typed failure
- started_at
- completed_at
```

結果は到着しただけではcommitしない。

```text
result
→ schema validation
→ authority validation
→ revision / precondition validation
→ commit by owning Module
or stale / cancelled / superseded / rejected
```

---

## 5. Snapshot / Revision

### source_context_revision

会話・Internal State・Activity等、認知Context全体の世代を識別する。

### goal_revision

#366 current Goal / Commitment Stateの世代。

Goalをabandon / supersede / reprioritizeした後、旧revisionで生成済みActivityPlanを実行しない。

### attention_revision

#333 AttentionFocusStateの世代。

Focus/turn/priorityが大きく変化した後、旧focusを前提にした低優先候補を無条件commitしない。

### internal_state_revision

#327 `InternalStateSnapshot`の独立世代。Internal State Reducerは`source_context_revision`を変えずにstate revisionだけを進められるため、Emotion / Desire / Drive / Motivation等を読むExecutiveは3要素のFoundation `RevisionVector`に加えてこのrevisionを責務固有の`ExecutiveFreshnessStamp`へ含める。Foundation共通型へ全Module固有revisionを追加しない。

すべての処理へ3 revisionを必須化するわけではない。責務上必要なrevisionだけをContractに含める。

Executiveのlong-running LLMは開始時snapshotをrequestへfreezeするが、開始時に得たcurrent値をcommitへ再利用しない。result到着後に`ExecutiveLiveStatePort`から3 revision、Internal State revision、Capability、Preconditionを一貫したcurrent snapshotとして読み直し、Authorityがrequest時snapshotと照合する。Capability/Preconditionの必須集合はLLMの自己申告ではなく信頼済みpolicy/upstream contractが導出し、候補申告との欠落もfail-closedにする。

---

## 6. Goal / Commitment Concurrency

Goal Stateは主体継続性の正本なので、同一Goal/Commitmentに対するmutationはatomic / serializedにする。

ただし:

```text
Goal transition mutation
≠ Core global lock
```

Goal Store更新中でも:

- current Speech playback
- Body realtime
- Game frame loop
- unrelated input reception
- Streaming ingestion

は継続する。

Planner等long-running workは`goal_id + goal_revision`を保持する。

```text
plan.goal_revision != current.goal_revision
→ stale / replan_required
```

Activity failureがGoal Stateを直接mutationしない。

```text
Execution Result
→ Appraisal / Executive
→ validated Goal transition
```

---

## 7. Attention / Focus Scheduling — #333

複数活動を同時進行する際、全EventをExecutiveへ即時同期投入しない。

```text
Game realtime event stream
Streaming comment burst
User direct interaction
Internal Reflection event
        ↓
aggregation / appraisal salience
        ↓
Attention / Turn scheduling
        ↓ eligible trigger / FocusContext
Executive
```

### 原則

- user direct interactionを高優先にできる
- Game foreground中でもStreamingをsecondary monitor可能
- low-priority Reflectionはbackground
- comment/game high-frequency eventsはbounded aggregation/coalescing
- attention budgetを有限にする
- source fairness / anti-starvationを持つ
- Focus StateをBody gazeへ投影できるがBody gazeがcognitive authorityにはならない

Attention schedulingは意味・Goalを決めない。
Appraisalはsalience候補、Executiveはdeliberate attention intent、本Moduleはtyped scheduling/focus stateを所有する。

---

## 8. LLM Scheduling

LLM Roleごとに:

- priority class
- timeout
- cancellation
- maximum in-flight
- queue size / coalescing policy
- stale policy
- model/reasoning policy

を持てる。

### Foreground

例:
- direct user interactionのInput Meaning
- user responseが必要なExecutive
- required Character generation

### Background

例:
- Reflection
- low-priority autonomous candidate
- optional Deep Appraisal

Foregroundがbackground request burstにstarveされない。

### Sparse activation

すべてのRoleを毎turn起動しない。

- simple speechはSpeech Semantics専用LLM省略可能
- obvious appraisalはdeterministic path可
- Activity Plannerはcomplex goalのみ
- Verifierはrisk/contract policyに従う
- Reflectionはdeferred/background

---

## 9. LLM Parallelism

独立依存はfan-outする。

例:

```text
ExecutiveDecision
├─ Speech preparation
├─ Body Motion planning
└─ Activity / Capability preparation
```

Character後:

```text
CharacterUtterance
├─ required Semantic Verification
├─ Speech Performance
└─ speculative TTS prep (policy permitting)
```

required Verifier PASS前にexternal Speech Presentationはcommitしないが、意味安全性に影響しない準備を並列化できる。

---

## 10. Speech Concurrency

詳細: `speech_pipeline_architecture.md` / #348。

必須:

```text
Speech A presenting
while
  next input may arrive
  Appraisal may run
  Executive may run
  Speech B semantics/Character may prepare
  Verifier B may run
  TTS B may prepare
```

禁止:

```text
await speech_A_playback_complete()
→ begin cognition for B
```

Prepared candidateはboundedで、user input / Goal revision / Attention revision / context changeによりcancel / supersede / stale可能。

---

## 11. Body Realtime Concurrency

Body realtimeは高頻度独立lane。

```text
slow Body Motion Planner
while
  current trajectory continues
  gaze continues
  blink continues
  breath continues
  viseme continues
  balance/subtle correction continues
```

LLM/TTS/DB/Game/Character completionをframe productionのprerequisiteにしない。

new BodyIntentでold planningをcancel/supersede可能。

---

## 12. Plugin / External Capability

slow external operationをCore global awaitにしない。

外部effectについて:

```text
request stale before effect
→ cancel if safe

request stale after effect applied
→ actual effect factを保持
→ Appraisal / Executiveへfeedback
```

staleだから実世界の事実を消さない。

---

## 13. Streaming / Game Isolation

### Streaming

大量comment/event:

- bounded ingress
- aggregation
- coalescing
- representative signal
- priority
- backpressure

を使い、Core queueへ無制限投入しない。

### Game

Game frame loopはCore Executive / Character / TTS / Verifier latency非依存。

Coreへはhigh-level Strategyを渡し、Game Skillからsalient Event / Resultをboundedに返す。

user interruption / quit等のhigh-priority controlはbounded latencyでSkill Runtimeへ反映する。

---

## 14. Backpressure

bounded queueを基本とする。

policy候補:

- reject-new
- drop-oldest
- latest-wins
- coalesce
- replace-same-key
- sample / aggregate
- priority queue

Domain semanticsに応じて選択する。

重要Eventを単純dropしない一方、high-frequency sensor/comment/frameを無制限蓄積しない。

---

## 15. Cancellation / Supersede

Cancellationは少なくとも:

- request_id
- decision_id
- candidate_id
- activity_id
- goal_id/revision when relevant
- presentation_id

へ追跡可能にする。

new user inputやGoal/Focus変更で、不要な低優先in-flight workをcancelできる。

Providerがhard cancellation非対応でも、遅れて返ったResultをcommitしないsoft cancellationを保証する。

---

## 16. Error Isolation

1 lane failureでunrelated laneを落とさない。

例:

- Reflection timeout → current conversation継続
- TTS failure → Text/degraded Speech + cognition継続
- Avatar disconnect → Body State維持
- Game Skill failure → Game capability unavailable/result → Executive再評価
- Plugin failure → affected capabilityのみdegraded
- LLM Role failure → typed role failure、他Role schedulerは継続

---

## 17. Shutdown

shutdownは正常系。

```text
stop accepting new low-priority work
→ publish shutdown/cancellation
→ cancel/deactivate prepared work
→ stop subsystem ingress
→ close presentation/output according to policy
→ await owned tasks/resources
→ assert no pending tasks
```

`Event loop is closed` / orphan task / repeated error spamを正常shutdownの一部として許容しない。

---

## 18. Observability

最低限Role/laneごとに:

- queued_at
- started_at
- completed_at / cancelled_at
- queue_wait
- provider / execution latency
- priority
- source_context_revision
- goal_revision if applicable
- attention_revision if applicable
- stale / superseded reason

System metrics:

- p50 / p95 / p99 latency
- foreground starvation
- queue depth
- concurrent in-flight count
- cancellation/stale rate
- user input→Executive latency
- user input→speech preparation/presentation latency
- previous playback中next generation start
- Body frame interval/jitter
- Game realtime loop stability
- Streaming ingress/backpressure
- Goal revision conflicts / stale plan rejects

平均値だけでなくtail latencyを確認する。

---

## 19. Acceptance Invariants

V2 System Verificationで最低限証明する。

- [ ] 任意の1 LLM Roleを5s/20s遅延させてもunrelated lane継続
- [ ] Speech playback中にnext generation開始可能
- [ ] Deep Appraisal中でもnew input受信可能
- [ ] Reflection中でもforeground conversation可能
- [ ] Body realtimeはMotion Planner/LLM timeoutで停止しない
- [ ] Game realtime agentはExecutive LLM latencyでframe loop停止しない
- [ ] Streaming burstでCore starvationなし
- [ ] Goal State mutationがCore global lockにならない
- [ ] stale goal_revisionのPlanをcommitしない
- [ ] Focus/attention変更で古いlow-priority candidateをrevalidate/cancel可能
- [ ] stale/cancelled LLM resultを最新contextへ誤commitしない
- [ ] background request burstでforeground interactionがstarveしない
- [ ] shutdown後pending taskなし

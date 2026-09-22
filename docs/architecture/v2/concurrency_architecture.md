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

#329 Activity Executionは開始前とdispatch直前にcurrent revision、Capability ID/revision/availability、Precondition identity/actualを再検証する。dispatch awaitをAuthority lockへ含めず、Adapter reportはFoundation `ExecutionResult`の合法edgeとしてのみcommitする。

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

## 20. 所有者の世代更新と最終確定を直列化する（#632）

### 20.1. 適用範囲と安定読取との違い

#632は意味判断を持たない共通同期契約を所有する。公開型は[Foundation契約第15節](foundation_contracts.md#15-所有者の世代と最終確定の共通契約632)に従う。#630は引き続き必須要件の意味を所有し、[実行判断契約第9.6節](executive_authority_contracts.md#96-要求開始から確定までの現在性)を本契約の利用側として実装する。

既存の`SnapshotStabilizationPolicy / SnapshotReadCycle`は一貫した複合読取を成立させる契約である。その成功後も元所有者は更新できるため、最終確定の保護境界として拡大解釈しない。両者を組み合わせる順序は「値と世代の一貫した取得 → 長時間処理 → 最終世代照合と確定」である。前後の再読取だけでは最後の区間を不可分にできない。

### 20.2. 正規の参加者と世代公開

各所有者は構成時に一つの参加者を所有し、既存の状態更新ロックを参加者のロックと同一にする。既存ロックを保持したまま横に別の公開ロックを置くことは禁止する。同じ状態への全読取・全更新がこの同じ境界を通る。構成側が読取値をコピーして別参加者に再公開しても、元所有者の現在性の保証にはならない。

参加者の識別は信頼済み構成で一度登録し、同じ所有者インスタンスへの重複登録、同じ取得順序キーを持つ異なる参加者、利用中のキー変更を拒否する。登録機構が持つ短い初期化時の排他を、通常の全確定処理を覆うロックとして使わない。

世代は非負の厳密な整数であり、同じ所有者インスタンス内で退行・循環・再利用を許さない。当初は、状態を書き得る同期操作がロックを取得した時点で機械的世代を1進める。検査失敗や同値更新でもその操作に入った場合は旧トークンを失効させる。この保守的失効は製品の状態リビジョンや成功事実を進めるものではない。純粋読取では世代を進めない。公開値の変更を世代更新なしで実行できる入口を残さない。

登録解除・回収・停止も、それが読取値の利用可否を変えるなら同じ区間で世代を失効させる。参加者自体の破棄は利用不能を同時公開し、再生成時は新しい起動インスタンス識別子を使う。削除された計画・記録の古いトークンが、同じ識別子の再登録で有効になることを禁止する。

読取公開は、参加者を取得した状態で不変な値とトークンを同時に取得する。複合読取では参照する所有者全部のトークンを保持する。計画進行の観測は計画進行側だけの世代では足りず、その観測が参照した活動記録の所有者も含める。参加者がない汎用読取Portから得た値は、そのまま最終確定用の正規出典にできない。

### 20.3. 集合の確定・ロック順序・再入

参加者集合には全出典と確定先を含める。確定先の操作が区間内で別所有者を読む場合、その読取先も取得前の集合に含める。依存する読取先の宣言と実際の所有者参照の対応を構成時に監査する。取得後に未宣言の所有者を発見した場合、ロックを追加取得せず設定不正として拒否する。出典の不足を空集合で代用しない。

取得順序は、構成時に固定した`(lock_rank, owner_instance_key)`の昇順とする。Foundationは整数と一意なキーだけを扱い、ドメイン名から順位を推測しない。構成は既存の所有者間呼出しを有向辺として監査し、全辺が低順位から高順位へ向くことを検証する。同順位では安定したインスタンスキーで全順序を作る。循環や逆順の呼出しは構成不正であり、タイムアウトや再試行で解決しない。

同じ参加者・同じ発行世代への複数参照は一件へ正規化し、出典との対応は全て保持する。同じ参加者への異なる期待世代、同じキーを名乗る別参加者は拒否する。確定先が出典も兼ねる場合もロックは一回だけ取得する。

既存メソッドを確定操作内から呼ぶときの二重取得を避けるため、参加者の同期プリミティブには同一スレッドの再入を許す。既存所有者のロックもその同じプリミティブへ機械的に置き換える。再入は取得済み参加者だけに許し、内側の操作が保護対象の出典を変更することは認めない。出典と確定先が同一の場合の書込みは、全期待世代の照合後に行う当該確定先の変更だけに限定する。別のFenceや未知の参加者の入れ子取得は禁止する。

通常の所有者メソッドにも同じ順序を適用する。Fenceだけを整列して、通常更新側に逆順取得を残してはならない。既存の呼出しが順位を満たさない場合は、意味を変えずに同じ取得済み集合を渡せるか監査し、保証できなければ設計STOPとする。

### 20.4. 確定手順と保持時間

1. 区間外で型・由来・参加者対応・必要集合を検査し、長い計算やI/Oを終える。必要数の上限は共通設定で明示し、初期値は一確定あたり16参加者とする。超過時は拒否し、一部を省略しない。
2. 取消を検査し、昇順でロックを取得する。Fenceは各ロックを待機なしで一回試行し、競合中なら取得済み分を逆順解放して型付き競合を返す。内部再試行・sleep・タイムアウト解決は持たない。後続の再投入判断は既存の呼出し側が所有する。
3. 全取得後に取消と全期待トークンを再検査する。元所有者の現在世代・起動インスタンス・利用可能状態のどれかが不一致なら、確定操作を呼ばず拒否する。新しい世代へ旧候補を付け替えない。
4. 確定先に登録した短い同期確定操作を一回呼ぶ。意味・参照・期限・権限・同一契機の重複などは従来の所有者が検査する。期限を持つ確定先へ渡す確定時刻は、全取得後に共通基盤の監査済み・非ブロッキングの時計プリミティブから取得し、既存の日時型と期限比較契約を維持する。取得前の時刻やLLM応答完了時刻で代用しない。任意の外部時計コールバック、ネットワーク時刻取得は呼ばない。
5. 確定結果と出典トークンの証拠を確保し、確定先の世代を同じロック内で更新する。成功後に取消が観測されても確定結果を破棄しない。逆順で必ず解放する。

区間内は世代・小さな条件の検査と既存の有界な状態確定だけとする。await、LLM、提供先呼出し、DB・ネットワーク・ファイルI/O、長時間計算、取消待機、sleepは禁止する。任意の利用者が渡したコールバックを実行せず、型と動作を監査済みの確定先所有者の同期操作だけを登録する。外部提供先の操作は確定後に既存実行経路へ渡す。

参加者は所有者単位なので、その所有者内の別リソース更新が旧トークンを失効させることは許す。ただし当該確定に関係しない所有者を参加集合へ追加しない。長いLLM待機中にFenceを保持しない。同期ロックの競合で非同期イベントループを待たせず、Body・発話・無関係な前景処理が独立して進むことを試験する。

### 20.5. 失敗・取消・確定結果

`FinalizationFailure`は少なくとも`GENERATION_MISMATCH / PARTICIPANT_UNAVAILABLE / PARTICIPANT_UNSUPPORTED / INVALID_PARTICIPANT / INVALID_LOCK_CONFIGURATION / PARTICIPANT_BUSY / CANCELLED / TARGET_ALREADY_FINALIZED / TARGET_REJECTED / TARGET_COMMIT_FAULT`を区別する。重複の正規化に失敗した入力は`INVALID_PARTICIPANT`、順序・集合・参加数・未宣言取得の不正は`INVALID_LOCK_CONFIGURATION`とする。

取得途中までの取消・失敗は全解放して確定操作を呼ばない。全取得後の最終取消検査を通過したら、同期確定区間を途中取消しない。直後の取消は確定結果を保持した上で既存の取消伝播へ戻す。取消を後回しにするため長時間処理を区間内へ移すことは禁止する。

確定先は必要な値の構築・拒否可能な検査を状態公開前に終え、型付き拒否では状態を更新しない。Foundationが複数所有者の製品状態を一括書換えするトランザクションを新設するわけではなく、出典は読取専用、製品状態の確定先は一所有者である。

予期しない例外でも全ロックを解放する。ただし状態が未更新だと決めつけず、`TARGET_COMMIT_FAULT`として当該確定先を利用不能にし、失効を公開する。既に公開された効果・成功記録を消さず、自動再発行や自動ロールバックはしない。この障害経路を通常の拒否成功に変換しない。生例外の本文・入力内容を意味分類の正本にせず、診断情報にも秘密を含めない。

### 20.6. 現行所有者への適用監査

監査基底は`1247552291ef2717c6ab22d4e75b5bc56fd226c2`。以下はコードの読取による設計適用判定であり、参加機構の実装済み判定ではない。

| 所有者 | 既存の同期境界と更新 | 機械的な参加方法・注意点 | 判定 |
| --- | --- | --- | --- |
| `GoalPlanningAuthority` | `authority.py`の`commit()`が同じ`_lock`内で`_plans / _current_plans`を更新。`current_plan()`も同じロックで読む | 現在計画の読取とトークン取得を組にし、確定・置換時に同じロックで世代を失効させる。`snapshot(old_id)`が旧計画を保持しても現在計画のトークンとして使わない | PASS、計画・置換・引数の意味変更不要 |
| `PlanExecutionOwner` | `owner.py`の`prepare_scope / activate / reserve_ready / apply_assessment / stop / retire / _finish_dispatch`が`_lock`を使う | 各更新入口を失効対象にする。`progress()`も内部の`_progress()`が`blocked`を変更するため純粋読取に分類しない。`observation()`は進行側と活動側の両トークンを返す | PASS、承認・進行・再試行の意味変更不要 |
| `ActivityExecutionAuthority` | `authority.py`の`admit / start / apply_report / fail_adapter_contract / request_cancellation / supersede`が同じ`_lock`で実行記録を更新。`snapshot()`が同じロックで読む | 各公開更新入口で一度失効し、内部`_commit()`経由の記録更新も取りこぼさない。実行状態・効果参照・記録リビジョンは変更しない | PASS、実行と効果の意味変更不要 |
| `GoalCommitmentStore`（#366） | `store.py`の`apply()`と`snapshot()` | 計画進行が`_goal()`や`reserve_ready()`で実際に目標を読むため、その経路の参加対象。目標採否・遷移の意味は変えない | PASS、必要な読取経路に限定 |
| `AttentionTurnStore`（#333） | `store.py`の状態・方針更新と読取が同じ`_lock`を使う | #630の実行判断が注意リビジョンを確定根拠として使用する場合のみ参加する。`update_policy / offer / resolve / expire / apply / claim_next`と内部状態置換を更新監査する | PASS、選択・公平性・割込みの意味は変えない |

計画進行側はロック保持中に計画・目標・活動の公開同期読取を呼ぶ。今回監査した呼出しグラフは「計画進行 → 計画」「計画進行 → 目標」「計画進行 → 活動」であり、これらから計画進行を逆に呼び戻す経路はない。初期構成は要件方針10、計画進行20、目標計画30、目標状態40、活動50、注意60、実行判断70の順序キーを登録する。この順序をFoundationへドメイン依存として内蔵しない。複数インスタンス間の呼出しも構成時に検査する。

`GoalSnapshotPort`は現状では任意の同期実装を許すが、最終確定の保護内では、参加者を提供しI/Oを行わない監査済みの正規所有者に限る。未対応のPortをロック内から呼んで保証を作らない。外部読取は区間外へ置き、正規参加者がなければ拒否する。

初期の`PLAN_EXECUTION`では要件方針・現在計画・計画進行の登録範囲・確定先が必須であり、対象目標の現在状態を検査する場合は目標所有者も含める。`PLAN_PROGRESS`ではさらに実際に参照した実行記録の活動所有者が必須となる。注意その他の根拠が確定条件に使われる場合はその参加者も必要で、条件を削って集合を小さくしない。未監査の根拠所有者を自動参加させず、必要集合が構成できなければ未対応として拒否する。

計画進行の内部読取を含む集合を先に取得し、既存の同期メソッドの再入を同じ参加者で処理することで、独立したロックの追加や意味変更をせずに参加できる。新しい意味判断、引数由来の具体化、#612の結合側での代行は不要である。実装時にこの監査と異なる逆向き取得・I/O・意味変更が発見された場合はSTOPし、Owner別Workへ分離する。

### 20.7. 競合再現と設計採用後の受入試験

本設計時に、上記基底の独立した作業場所で、既存の所有者と試験用データを使って次を再現した。製品コード・試験コードの変更、私有ロックの置換は行っていない。

- 現在計画を読んだ後に別スレッドで置換すると、旧計画は履歴に残る一方、現在計画は新計画になる。旧値を持つことは現在性の証拠ではない。
- 計画進行から実行観測を読んだ後、別スレッドで実際の活動記録へ終端報告を反映すると、新しい観測文脈は変わり、取得済みの文脈は古くなる。
- 登録された計画範囲を読み、別スレッドで停止、さらに回収した後も、保持済み範囲を渡す現行の`ExecutiveDecisionAuthority.commit()`は承認を生成する。範囲の存在・同一性のコピー比較だけでは停止・回収を検出しない。

設計採用後は次を決定論的なスレッド同期で検証する。時間待ちだけで競合を起こした扱いにしない。

1. 計画Aのトークン取得後に置換Bを確定し、Aのトークンによる確定操作が呼ばれず`GENERATION_MISMATCH`になる。
2. Fenceが計画参加者を保持している間、別スレッドの置換は状態を公開できない。確定と解放の後に置換が進むことを確認する。
3. 範囲の登録・承認・停止・回収・予約・完了評価・内部`blocked`更新について同じ競合を確認し、意味上の動作を既存試験と比較する。
4. 実行記録更新の前後で、進行と活動の全トークンを検査する。片方のトークンを省略した組は受付を拒否する。出典の計画が置換される場合も現在計画の参加者で拒否する。
5. 二スレッドが逆の入力順で同じ参加者集合を指定しても内部取得順序は同じになる。競合時は全解放して型付き競合を返す。重複・衝突キー・退行・再起動・回収再登録・未宣言の入れ子取得も拒否する。
6. 取得前・途中・全取得後・確定直後の取消、確定先拒否・例外で解放と結果保持を確認する。同一契機の確定は従来どおり高々一回である。
7. 遅いLLMの間に前景の判断が進み、無関係な参加者への処理・Body・発話が待たされない。Fenceの競合を長時間の非同期待機へ変換しない。

本節は設計案と現行競合の再現記録であり、Fence実装・修正後試験の成功証拠ではない。#632の設計・実装・具体所有者への機械的参加の採用が終わるまで、#630はBlockedを維持する。#630の未コミット試作を本設計へ移送せず、#361・#329・#610の製品実装には着手しない。


## Speech Presentation局所watchdog（#659）

START_WAIT/TERMINAL_WAITのwatchdogはcandidate/generationとPresentation laneに局所化する。
Owner lockでは短い期限・report・lifecycle判定だけを行い、Adapter I/O、deadline await、cancel/reap/closeをlock内に置かない。
期限待ちをCore global waitへ昇格させず、Speech Bのpreparationや認知を停止しない。
timeout/cancel/shutdownの局所cleanupもunrelated workへ取消を伝播させない。
reportとtimeoutのexact-boundary規則、固定policy generation、task回収は`speech_runtime_presentation_contracts.md`を正本とする。


### #659の別プロセス境界

Presentation AdapterのSDK・外部I/Oは1 Presentationごとのworkerへ隔離する。親Runtimeがdeadlineとterminal claimを所有し、Domain外Supervisorがserializable IPCとbounded grace/terminate/kill/reapを所有する。
親Task取消時も対象workerの回収とpipe closeを完了してから戻る。子の非協調状態をCoreのasyncio取消協調へ依存させず、同一process fallbackを設けない。
canonicalの詳細は`speech_runtime_presentation_contracts.md`を正とし、Speech Bの準備や認知をglobalに待たせない。

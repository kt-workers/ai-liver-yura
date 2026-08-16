# Attention / Autonomy / Turn 型付き契約

Status: Issue #333 implementation canonical
Parent:
- `brain_architecture.md`
- `concurrency_architecture.md`
- `goal_commitment_architecture.md`
Adjacent:
- `speech_pipeline_architecture.md` (#348)
- Runtime Kernel #322

## 1. 目的と正本順位

この文書はIssue #333の詳細実装正本である。`Attention / Autonomy / Turn` はcurrent Focus、Turn、response obligation、bounded source monitoring、Executive trigger eligibility、interrupt scheduling、fairnessを所有する。

親canonicalのAuthority invariantを変更しない。親文書の概念例と本書の詳細型・所有境界が曖昧な場合、#333の実装詳細については本書を優先する。

意味、Goal、Speech内容、Speech candidate lifecycle、Activity execution lifecycle、Body gesture、Internal Stateは決定・所有しない。

## 2. Authority境界

- Input Meaning #326: 外部自然言語の意味Authority。
- Appraisal #327: salience / relevance等の主観評価候補とInternal State Authority。
- Executive #328: conscious Goal / Action / deliberate focus shiftの唯一のAuthority。
- Goal / Commitment #366: current Goal / Commitment stateのAuthority。
- Activity Execution #329: execution lifecycle / Actual FactのAuthority。
- Speech Pipeline #348: `PreparedSpeechCandidate`、queue、stale / cancelled / superseded / presenting lifecycleのAuthority。
- Attention #333: Focus / Turn / response obligation、source admission、priority policy、fairness、interrupt eligibility、Executive trigger claimのAuthority。
- Body #337/#340: `AttentionFocusView`を視線・姿勢へ投影できるがFocusを書き戻さない。
- Runtime Kernel #322: lane / queue / cancellation primitiveを提供するがAttentionの意味・priority policyを決めない。

#333は他ModuleのStoreを直接mutationしない。他ModuleのDomain型へ逆依存して意味を再解釈しない。

## 3. PolicyとStateを分離する

`interruption_thresholds`、`source_priority_policy`、source budget、fairness上限はcurrent Focusそのものではなく、#333が所有するimmutable `AttentionSchedulingPolicy` とする。

```text
AttentionSchedulingPolicy
- policy_id
- policy_revision
- attention_budget
- source_kind_budgets{}
- source_priority_rules{}
- interruption_thresholds{}
- max_same_source_burst
- max_priority_burst
- cooldown_claims
```

PolicyはStore生成時に注入する。raw text、Prompt、Provider object、Character出力から動的に生成しない。

Policyを変更する場合は新しい`policy_revision`として明示し、current scheduling stateを同一atomic boundaryでrevalidateする。silent mutationは禁止する。

### 3.1 初期production policy

初期値は次とし、将来の調整はpolicy revisionとして行う。

- `attention_budget = 8`
- `max_same_source_burst = 2`
- `max_priority_burst = 4`
- `cooldown_claims = 1`

source kind budget:

| kind | max active entries |
|---|---:|
| user_interaction | 4 |
| goal | 2 |
| commitment | 2 |
| activity | 2 |
| appraisal | 2 |
| streaming | 2 |
| game | 2 |
| reflection | 1 |
| autonomous | 1 |

全kind budgetの和はglobal budgetと一致する必要はない。各kind capとglobal capの両方を満たす。

### 3.2 Source priority rule

`AttentionPriority`:

```text
BACKGROUND < NORMAL < FOREGROUND < DIRECT_USER
```

source projectorはtyped factからbounded `requested_priority` を提示できるが、#333 policyが許可範囲を検証してeffective priorityを確定する。範囲外の昇格はsilent clampせずrejectする。

初期許可範囲:

| kind | default | max |
|---|---|---|
| user_interaction | DIRECT_USER | DIRECT_USER |
| goal | NORMAL | FOREGROUND |
| commitment | NORMAL | FOREGROUND |
| activity | NORMAL | FOREGROUND |
| appraisal | NORMAL | FOREGROUND |
| streaming | BACKGROUND | FOREGROUND |
| game | NORMAL | FOREGROUND |
| reflection | BACKGROUND | BACKGROUND |
| autonomous | BACKGROUND | BACKGROUND |

`DIRECT_USER`はtrusted Input Gateway由来のuser interactionだけが使用できる。Streaming/Game/Appraisal等がDIRECT_USERへ自己昇格することを禁止する。

## 4. Ingress contractと変換責務

Source Moduleは#333の内部Stateを直接触らない。#333はsource-neutral `AttentionIngressSignal` を受ける。

```text
AttentionIngressSignal
- signal_id
- operation: offer | refresh | resolve
- source_ref
- source_kind
- source_context_revision
- source_revision?
- requested_priority?
- occurred_at
- expires_at?
```

`source_revision`はsource ownerが独立revisionを持つ場合だけ使う。Goal/Commitmentならgoal generation、その他は必要な場合のみ設定する。Foundation `RevisionVector`へ全source固有revisionを押し込まない。

### 4.1 Formal Port

Application境界に次を置く。

```text
AttentionIngressPort.offer(signal)
AttentionIngressPort.resolve(signal)
AttentionTriggerPort.claim_next(current_goal_revision, now)
```

Domain Storeは短い同期mutationだけを行い、Port callback、LLM、Repository I/O、Runtime enqueueをlock内で行わない。

### 4.2 Projector ownership

Source Module自身に#333 importを要求しない。typed source factから`AttentionIngressSignal`への変換は#333側Application/Usecase layerのstateless projectorが所有する。

```text
Input Gateway accepted user event
  → UserInteractionAttentionProjector
  → USER_INTERACTION / DIRECT_USER

AppraisalCandidate / committed appraisal signal
  → AppraisalAttentionProjector
  → APPRAISAL

Goal / Commitment typed state/event
  → GoalAttentionProjector
  → GOAL / COMMITMENT

ExecutionResult / execution event
  → ActivityAttentionProjector
  → ACTIVITY

Streaming aggregated typed event
  → StreamingAttentionProjector
  → STREAMING

Game aggregated/salient typed event
  → GameAttentionProjector
  → GAME
```

重要:

- user direct interactionはMeaning LLM完了を待たず、Input Gatewayのaccepted typed eventからAttentionへ届いてよい。内容の意味は解釈しない。
- Appraisal projectorはraw textを見ず、typed salience/relevanceだけを使う。
- Goal/Commitment projectorはcurrent StoreをAttention側からpollしない。Goal側のtyped change/due factを受ける。
- Activity projectorはIntent/PlanでなくActual Execution Factを使う。
- Streaming comment全件、Game frame全件をprojectしない。Subsystem側のaggregation/salient factのみ受ける。
- 将来Sourceが増えてもAttention DomainへProvider/Subsystem固有SDKを入れない。

## 5. Attention source state

accepted signalはbounded `AttentionSource`へ変換する。

```text
AttentionSource
- source_ref
- kind
- effective_priority
- source_context_revision
- source_revision?
- occurred_at
- last_refreshed_at
- expires_at?
- coalesced_count
```

source entryは意味本文、Goal本文、Speech本文、Provider payloadを持たない。

同一`source_ref`の`refresh`はcoalesceし、priorityは新signalをpolicy検証した結果へ更新できる。古いsource revision / 古いsource contextへの巻き戻しはrejectする。

`resolve`はsourceをeligible集合から除外する。foreground/turn/response obligationが同一sourceへ結び付いている場合は、trusted runtime factとして関連する無効参照をatomicにclearする。これは新しいconscious focusを選ぶ処理ではない。

## 6. AttentionFocusState

`AttentionFocusState`はimmutableなcurrent scheduling stateである。

```text
AttentionFocusState
- revision
- source_context_revision
- policy_id
- policy_revision
- foreground_focus_ref?
- active_focus_intent_ref?
- secondary_monitor_refs[]
- current_turn_owner?
- response_obligation?
- sources[]
- selection_epoch
- last_selected_source_ref?
- same_source_burst
- last_selected_priority?
- priority_burst
- cooldowns[]
- updated_at
```

`cooldowns`はcurrent bounded source集合に対する`source_ref / eligible_after_epoch`だけを持ち、source resolve時に除去する。履歴全件を保持しない。

`AttentionFocusView`はExecutive/Body向けbounded read modelであり、fairness内部カウンタを必要以上に露出しない。最低限Focus、monitor、Turn、obligation、policy revision、attention revisionを公開する。

### 6.1 active_focus_intent_ref

`active_focus_intent_ref`はcurrent foregroundを最後に確立したExecutive `attention_intent`のIDである。

- `acquire_foreground`成功時: `intent_id`を設定。
- foreground shift: 新しい`intent_id`へ置換。
- `release_foreground`: `foreground_focus_ref`と共にclear。
- runtime source resolveでforeground自体が無効になった場合もclear。
- Body gazeやAppraisal candidateから設定しない。

これにより「Focus target」と「それを意識的に選んだExecutive intent」のprovenanceを分離する。

## 7. Transitionとrevision

`AttentionTransition`:

```text
- transition_id
- operation
- expected_attention_revision
- expected_source_context_revision
- occurred_at
- target_ref?
- value?
- source_intent_ref?
```

合法operation:

```text
acquire_foreground / release_foreground
add_monitor / remove_monitor
assign_turn / release_turn
set_response_obligation / clear_response_obligation
```

規則:

- Executive由来transitionはtyped `AttentionIntentPayload`だけから射影する。
- `acquire_foreground` targetはcurrent bounded sourceとして既知でなければならない。
- `expected_attention_revision`不一致はbatch全体をreject。
- `expected_source_context_revision`不一致はbatch全体をreject。
- Storeへ渡すcurrent `source_context_revision`はmonotonicでなければならず、current stateより小さい値をrejectする。
- source offer/refreshも同様にglobal `source_context_revision`を巻き戻せない。
- batchはcopy上でvalidateし、成功時だけrevisionを一回増やしてatomic replaceする。
- duplicate transition IDはreject。
- release系operationはpayload targetを新しいState値として使用しない。

`attention_revision`が進んでも`source_context_revision`を巻き戻してはならない。

## 8. Eligibility / claim / fairness

read-only sortだけではfairnessを成立させられないため、diagnostic evaluationと実際のExecutive dispatch claimを分離する。

### 8.1 peek_eligibility

`peek_eligibility()`はcurrent snapshotから候補を見るpure operationである。fairness stateを進めない。UI/diagnostic/test inspection用であり、「選出済み」の事実にはしない。

### 8.2 claim_next

`claim_next()`だけがExecutiveへ渡す1件のtriggerをatomicにclaimし、次を同時更新する。

- `selection_epoch += 1`
- `last_selected_source_ref`
- `same_source_burst`
- `last_selected_priority`
- `priority_burst`
- 必要なcooldown entry
- `attention revision += 1`

返す`ExecutiveTriggerEligibility.attention_revision`はclaim後のrevisionである。

`trigger_id`は`selection_epoch + source_ref`を含む一意identityとし、同じStateを何度peekしても新しいtriggerを捏造しない。

### 8.3 bounded fairness

通常時:

1. effective priority順。
2. 同priority内はoldest eligible sourceを優先。
3. 同一sourceが`max_same_source_burst=2`回連続claimされたら、そのsourceを`cooldown_claims=1` claim分だけsoft cooldownする。
4. highest priorityが`max_priority_burst=4`回連続claimされたら、待機中の次に低いpriorityから最古sourceを1件claimする。
5. cooldown対象しかeligible sourceが存在しない場合はdeadlockを避けるためsoft cooldownを無視できる。

### 8.4 direct user protection

Direct user優先とanti-starvationは次で両立する。

- active `current_turn_owner`または`response_obligation`がdirect user interactionへ結び付いている間、BACKGROUND sourceへfairnessを譲るためだけにuser turnを破らない。
- このprotected intervalではlower priority sourceはmonitor可能だがinterrupt claim対象外。
- 複数DIRECT_USER source同士はsame-source burst/cooldownで公平に扱う。
- turn/obligation解消後、通常のpriority burst fairnessへ戻る。

fairnessは「ユーザーへの返答義務を無視してReflectionを開始する」ための仕組みではない。

## 9. Interruption threshold

Interruptionは「現在Activityを強制停止するAuthority」ではない。#333が決めるのは、challenger sourceを**current foreground/turnへ割り込み得るExecutive triggerとしてclaim可能か**までである。

実際のGoal変更はExecutive、Activity cancelは#329、Speech stop/cancelは#348が各Authorityで検証する。

初期threshold:

| current foreground priority | minimum challenger priority |
|---|---|
| none | BACKGROUND |
| BACKGROUND | NORMAL |
| NORMAL | FOREGROUND |
| FOREGROUND | DIRECT_USER |
| DIRECT_USER | DIRECT_USER |

追加規則:

- active response obligation中のBACKGROUNDはinterrupt不可。
- DIRECT_USERはprovider/Subsystem sourceから生成不可。
- threshold未満のsourceはsecondary monitoring/future eligibilityには残せる。
- threshold判定はraw event本文を見ない。

## 10. Speech Pipeline #348との境界

#333は`PreparedSpeechCandidate`のlifecycle Authorityを持たない。

#348が所有する:

```text
preparing → prepared → queued → revalidating → ready_to_present
→ presenting → completed
or cancelled / superseded / stale / rejected / failed
```

#333は#348からbounded `SpeechSchedulingView`を読む。

```text
SpeechSchedulingView
- speech_revision
- presenting_candidate?
- queued_candidates[]

SpeechCandidateSchedulingFact
- candidate_ref
- phase
- priority
- interruptibility
- source_context_revision
- attention_revision?
```

#333はこのViewをFocus/Turn/interrupt判断の入力に使うだけで、candidate statusを書き換えない。

必要な場合、#333は#348へtyped `SpeechSchedulingDirective`を発行する。

```text
SpeechSchedulingDirective
- directive_id
- operation: revalidate | supersede_queued | request_soft_finish | request_interrupt
- candidate_ref
- source_trigger_ref
- expected_speech_revision
- attention_revision
- reason_kind
- occurred_at
```

#348だけが自分のcurrent candidate lifecycle/revisionを再検証してdirectiveを適用し、最終的に`stale / cancelled / superseded`等へ遷移させる。

したがって:

- user inputでqueued autonomous speechを「無効候補にするべき」と判断するScheduling Authorityは#333。
- 実際にcandidateをsuperseded/cancelledへ遷移させるAuthorityは#348。
- current playbackを停止する外部副作用も#348 Presentation側が所有する。
- #333はSpeech text/TTS/Character内容を見ない。

## 11. Runtime / async lane境界

Domain Storeは同期・短時間のatomic state transitionだけを持つ。

Application側`AttentionCoordinator`は#322 Runtime Kernel上で次のように接続する。

```text
Input / source lane
  → typed source fact
  → Attention projector
  → attention lane: offer/resolve
  → claim_next
  → executive laneへRuntimeWorkItemをenqueue
```

重要:

- attention laneはExecutive LLM完了をawaitしない。
- claim後のExecutive work enqueueまでを行い、Executive resultは別Eventとして戻る。
- cancellation / supersede requestは#322 cancellation primitive又は各ownerのtyped directiveへ発行し、完了を待ってattention lockを保持しない。
- Speech presentation lane、Body realtime lane、Game/Streaming laneをattention処理で停止しない。
- Domain内部で`asyncio.sleep`、wall-clock polling、global schedulerを作らない。

### 11.1 slow preparation中のuser input

必須経路:

```text
slow autonomous Speech/LLM preparation task running
while
  user input accepted
  → USER_INTERACTION signal admitted
  → attention claim
  → foreground Executive work enqueue
  → lower-priority autonomous workへcancel/supersede request
```

slow taskの完了を待ってuser interaction処理を開始してはならない。

### 11.2 Speech再生中の次候補評価

必須経路:

```text
Speech A presenting on presentation lane
while
  typed Event / Goal / Appraisal source arrives
  → Attention eligibility/claim
  → Executive decision
  → Speech B preparation may start
```

Speech A playback completeをAttention/Executive/Speech B preparation開始条件にしない。

## 12. Bounded source lifecycle

- global `attention_budget`とper-kind budgetを同時に守る。
- foreground、turn owner、response obligationへ参照されるsourceはbudget eviction対象にしない。
- full時はunprotectedな最弱priority sourceを候補にし、incomingがstrictly strongerな場合だけreplaceする。
- 同priority overflowはsilent replaceせずrejectし、source owner側aggregation/coalescingへ戻す。
- `expires_at`を持つsourceのexpiry判定にはcaller-provided aware `now`を使い、Domainがwall clockを直接読まない。
- expired/resolved sourceはclaim不可。

## 13. 受入条件

### State / Authority

- immutable / strict JSON serializable snapshot
- `active_focus_intent_ref` provenance
- policyとcurrent stateの分離
- source/global revision rewind拒否
- stale/duplicate/invalid transitionのatomic reject
- Body/Character/Source ModuleがFocus Stateを直接mutationしない

### Source / budget

- User/Appraisal/Goal/Commitment/Activity typed fact projector
- future Streaming/Game aggregated projector contract
- DIRECT_USER偽装拒否
- global + per-kind bounded budget
- coalescing / refresh / resolve / expiry

### Fairness / interruption

- same sourceを複数回claimして永久独占しない
- priority burst後にlower eligible sourceがboundedに進む
- direct user response obligation中はbackground fairnessでturnを破らない
-複数direct user source間はstarvationしない
- interruption threshold未満のsourceはinterrupt claimされない

### Speech boundary

- stale/cancelled/superseded candidate lifecycleは#348のみが書く
- #333→#348はtyped scheduling directive
- #348→#333はbounded scheduling view
- candidate本文/TTS payloadをAttentionへ渡さない

### Concurrency / Adjacent

- slow autonomous preparation中にuser input→Attention→Executive enqueueが先に進む
- Speech A playback中にAttention evaluationとSpeech B preparation開始が可能
- Streaming/Game burstでAttention budgetを超えずExecutive/Body/Gameがstarveしない
- lock区間にawait / callback / I/Oなし
- Core global lock / single blocking cognitive loopなし

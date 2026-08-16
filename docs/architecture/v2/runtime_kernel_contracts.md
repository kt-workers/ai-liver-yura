# V2 Runtime Coordination Kernel Contracts

Status: Implementation Contract / Issue #322

Parent architecture:
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/foundation_contracts.md`
- `docs/architecture/v2/llm_role_contracts.md`

Implementation package: `app/runtime/kernel/`

## 1. Purpose

Domain意味判断を持たず、typed workをbounded concurrent laneとして調整するRuntime Kernelを定義する。

KernelはModuleが付与したpriority、queue policy、cancellation/stale policyを執行する。Eventの意味、Goal、Attention、Speech、Body、Memory importanceを判断しない。

## 2. Work envelope

`RuntimeWorkItem[T]`:

- `work_id`
- `lane_id`
- `payload`: Module所有のtyped value
- `priority`: critical / foreground / normal / background
- `queue_key?`: coalesce / replace用identity
- `revisions`: #321 `RevisionVector`
- `created_at`
- `deadline_at?`
- `interruptible`

Kernelはpayload内容を解釈しない。work/lane/key identityとaware datetimeを検証し、immutable envelopeとして運ぶ。

## 3. Clock

`RuntimeClock`:

- `now() -> datetime`
- `sleep(delay_seconds) -> awaitable`

Production clockとdeterministic fake clockを同じPortで扱う。Kernel内部で直接wall clockやblocking sleepを呼ばない。

## 4. Bounded queue policies

`BoundedWorkQueue`はcapacityを必須とし、unbounded modeを持たない。

policy:

- `REJECT_NEW`: fullなら新規拒否
- `DROP_OLDEST`: 最古を明示dropし新規受付
- `LATEST_WINS`: 同じqueue keyの旧itemを置換。keyなしは拒否
- `COALESCE`: 同じkeyの既存itemとModule提供coalescerで結合
- `REPLACE_SAME_KEY`: 同じkeyがあれば置換、なければcapacity判定

各enqueueはtyped `QueueAdmission`を返す:

- accepted / rejected / replaced / coalesced / dropped_oldest
- admitted work id
- displaced work ids

重要factをsilent dropしない。callerはadmission resultを観測・記録できる。

## 5. Priority and anti-starvation

priority順:

```text
critical > foreground > normal > background
```

strict priorityだけではbackgroundが永久starveするため、schedulerはbounded burst fairnessを持つ。

- `max_priority_burst`: 同一または高priorityを連続選択できる上限
- burst上限到達時、待機中の次に低いpriorityから最古itemを1件選ぶ
- critical safety/shutdown controlはfairness override可能
- 同priority内はFIFO

Kernelは何がforegroundかを決めず、Moduleが付与したclassを執行する。

## 6. Lane and concurrency limits

`RuntimeLanePolicy`:

- `lane_id`
- `max_in_flight`
- queue capacity/policy
- error isolation
- cancellation grace

RuntimeCoordinatorはlaneごとのworker taskを所有し、Role数・Provider数・Body frame source等を固定しない。

- 1 laneのawaitは他laneを停止しない
- lane内max-in-flightを超えない
- handler exceptionはtyped failure/diagnosticへ変換し、他lane workerをcancelしない
- Provider単位追加limitは後続Adapter/registrationで同primitiveを利用可能

## 7. Cancellation

`CancellationRegistry`は少なくともwork_id単位のtokenを所有する。

- cancel requestはidempotent
- hard cancel可能なhandler taskへcancelを伝播
- hard cancel非対応でもtokenをcancelledにし、late resultをcommit対象外にする
- reason / requested_atを保持
- completed workのcancelは状態を書き換えずno-op結果

decision/candidate/activity/goal/presentation単位のgroup cancellationは、group keyからwork_id集合を登録することで拡張する。

## 8. Stale and deadline infrastructure

Kernelはrevision意味を判断しない。Moduleが渡すcurrent revision predicateまたはvalidatorで、dispatch前・result publish前に確認する。

`WorkDisposition`:

- completed
- failed
- cancelled
- timed_out
- stale
- superseded
- rejected

deadlineはUTC absolute instantで判定する。deadline前に開始しても完了時に超過した場合はModule policyに従いtimed_out/revalidateとし、Kernelが成功へ書き換えない。

## 9. Runtime coordinator lifecycle

```text
created → running → stopping → stopped
```

- startはidempotentではなく重複startを拒否
- stopping後は通常workを受理しない
- shutdown controlは受理可能
- shutdown controlの受付phaseはworker drain前にatomicに閉じる。受付終了後とresource close中は拒否する
- stop:
  1. new normal/background admission停止
  2. queued itemをpolicyに従いcancel/reject
  3. running interruptible taskへcancel通知
  4. owned worker/task完了をawait
  5. resource close
  6. pending owned task 0をassert
- stopは繰り返し呼べるidempotent operation

## 10. Diagnostics and health

`RuntimeDiagnosticsSnapshot`:

- coordinator state
- lane別queue depth / in-flight / completed / failed / cancelled / stale / rejected
- oldest queued age
- priority別queued count
- total owned task count
- last error summary（secret/payload本文なし）

Health:

- healthy: runningかつworker正常
- degraded: 一部lane error/backpressure継続
- stopping
- stopped

metricsはpayload自然言語、Prompt、secretを含めない。

## 11. Error isolation

- handler exceptionをworker task消失へ直結させない
- failureを該当work/laneへ限定
- diagnostic counterとtyped dispositionを発行
- fail-fastが必要なcritical laneだけ明示policyでcoordinator stopを要求可能
- fail-fastが生成するstop taskはcoordinatorが所有し、呼び出し側が停止完了をawaitできる
- optional lane failureでCore global shutdownしない

## 12. Explicit non-goals

- Eventの意味・salience・priority決定
- Attention/Focus state (#333)
- Executive / Goal / Activity Authority
- LLM Role schema/policy定義 (#323)
- concrete Provider invocation
- Speech/Body/Game/Streaming固有loop
- persistence transaction
- distributed queue/process orchestration

## 13. Unit acceptance

- deterministic fake clockでdeadline/ageを検証
- bounded capacityと全queue policy
- admissionがdrop/replaceをsilentにしない
- priority ordering / same-priority FIFO
- bounded anti-starvation
- lane max-in-flight
- slow lane中にunrelated laneが進行
- slow Reflection相当lane中にforeground相当lane開始
- cancellation idempotency / hard and soft cancellation
- stale result publish拒否
- handler exception isolation
- shutdown後pending owned task 0
- stop idempotency / post-stop admission拒否
- diagnostics snapshot
- payloadを解釈するDomain判断なし
- Provider/SDK importなし

## 14. Typed fairness override — Issue #415

bounded anti-starvationは全priority classの通常workへ適用する。`WorkPriority.CRITICAL`であること自体はfairness override Authorityではない。

### 14.1 fairness budgetの意味

`max_priority_burst`は「同じpriorityを何回選んだか」ではなく、**lower-priority waiterが存在する間にstrict-priority selectionでそのwaiterを何回連続して追い越したか**の上限として扱う。

したがって、CRITICALとFOREGROUNDが交互に選択される等、strict-priority側のclassが途中で変化してもfairness debtをリセットしない。

正規選択は次の順序とする。

1. 現在待機中の最上位priorityのqueue headをstrict-priority candidateとする。
2. そのcandidateより低いpriorityに待機itemがなければ通常どおりcandidateをdispatchし、fairness debtを0とする。
3. lower waiterが存在し、fairness debtが`max_priority_burst`未満ならstrict-priority candidateをdispatchし、debtを1増やす。
4. lower waiterが存在し、debtが上限以上なら、fairness override資格がない限り、lower-priority各queueのheadから`created_at`が最古のitemを1件dispatchし、debtを0へ戻す。
5. 同priority queue内では常にFIFOを維持し、override対象を探すためにheadを飛び越えない。

このため、通常CRITICALが継続供給されても、CRITICAL/FOREGROUND/NORMALが混在して高優先度側のclassが変化しても、lower-priority waiterを永久starveさせない。

### 14.2 fairness override Authority

Issue #415で既存実装が持つoverride資格は、typed control-plane marker `RuntimeWorkItem.shutdown_control == True` **だけ**とする。payload本文、lane名、work id、priority名、文字列、例外内容等からshutdown/safety意味を推測してはならない。

`shutdown_control=True`は通常Domain workが自由に意味付けするflagではなく、Runtime control-planeが付与済みのtyped metadataとして扱う。少なくとも次を契約とする。

- `shutdown_control=True`のitemは`WorkPriority.CRITICAL`でなければならない。非CRITICAL shutdown controlはinvalidとしてfail-closedする。
- queueは`shutdown_control`のprovenanceをpayload解釈で再判定しない。Coordinator / composition境界は、このmarkerをtrusted control-plane用途だけに付与する責務を持つ。
- 通常CRITICAL (`shutdown_control=False`) は必ずbounded fairnessに従う。
- 将来shutdown以外のsafety controlへoverrideを拡張する場合は、明示typed contract / policyを追加してから行う。CRITICAL class全体を再び例外化してはならない。

### 14.3 override時のfairness debt

lower waiterが存在する状態でshutdown controlをdispatchする場合、control-plane安全性のためfairnessをoverrideしてよい。ただしoverride dispatchはfairness debtを帳消しにしない。

- override dispatchでlower waiterを追い越した場合、debtは少なくとも`max_priority_burst`へsaturateした状態を維持する。
- shutdown controlがなくなった次の非override strict-priority candidateは、lower waiterが残っていればfairness dispatchへ譲る。
- shutdown controlが連続する間は必要なcontrolを先にdispatchできる。

これによりshutdown sequenceを優先しつつ、control完了後に通常CRITICALへさらに無制限の追い越し権を与えない。

### 14.4 shutdown lifecycleとの整合

`RuntimeCoordinator.stop()`の既存契約を維持する。

- STOPPING移行時、queued non-shutdown workはcancel/reject対象。
- `_shutdown_control_open`中だけlate shutdown controlを受理できる。
- control受付phase終了後やresource close中はshutdown controlも拒否する。
- fairness修正のためにshutdown admission gate、cancellation grace、worker drain順序を変更しない。

### 14.5 必須Regression

- non-shutdown CRITICALを連続投入しBACKGROUNDが待機 → `max_priority_burst`後にBACKGROUNDが進む
- CRITICAL / FOREGROUND等のstrict-priority classが切り替わりながら連続負荷 → lower waiterが永久starveしない
- 通常CRITICALとshutdown controlを明確に区別する
- `shutdown_control=True`かつ非CRITICALをfail-closedで拒否する
- trusted CRITICAL shutdown controlはlower waiterがいてもfairnessをoverrideできる
- shutdown control連続後、lower waiterが残る場合は次の通常strict-priority workより先にfairness dispatchされる
- same-priority FIFOを維持し、shutdown controlを探すためにqueue headを飛び越えない
- 既存bounded queue policy、cancellation、shutdown admission、shutdown drain、post-stop rejectionを維持する

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

# V2 Runtime Operational / Numerical Contracts

Owners: #322 / #350
Related: `runtime_kernel_contracts.md`, `runtime_lifecycle_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

Runtime KernelとLifecycleが要求するbounded queue、concurrency、fairness、cancellation grace、retry/backoff、diagnostic rate limit、shutdown graceについて、単位・値域・計算式・missing時挙動を固定する。

本書はDomain priorityやProvider failure分類を決めない。#322は実行調整primitive、#350はdependency lifecycleを所有する。

## 2. Kernel policy schema

### 2.1 Lane policy

```text
RuntimeLanePolicy
- lane_id: non-empty stable identity
- queue_capacity: int >= 1
- queue_policy: REJECT_NEW | DROP_OLDEST | LATEST_WINS | COALESCE | REPLACE_SAME_KEY
- max_in_flight: int >= 1
- cancellation_grace_seconds: finite float >= 0
- error_isolation: ISOLATE | FAIL_FAST_CONTROLLED
```

Rules:

- boolをinteger/numberとして受理しない。
- `COALESCE`はModule supplied coalescer必須。
- `LATEST_WINS` / `REPLACE_SAME_KEY`はkeyなしitemを暗黙key化しない。
- `FAIL_FAST_CONTROLLED`はtyped control-plane stop requestだけを生成でき、handler exceptionから直接event loop/global processをterminateしない。
- lane policy missing/invalid時、そのlaneをhidden defaultで起動せずconfiguration failureとしてadmissionを閉じる。他laneは独立して起動可能。

### 2.2 Scheduler policy

```text
RuntimeSchedulerPolicy
- policy_id
- policy_revision: non-negative int
- max_priority_burst: int >= 1
```

`max_priority_burst`の意味・fairness debt計算は`runtime_kernel_contracts.md` Section 14を正本とする。policy revision変更時に既存fairness debtを旧policyから任意変換せず、新policy適用境界でscheduler stateを明示再初期化しdiagnosticへ記録する。

## 3. Cancellation grace

`cancellation_grace_seconds`はcancel request発行後、interruptible handlerがcooperative cleanupを完了するためにRuntimeCoordinatorが待てる**最大実時間秒**である。

- `0`はgrace待機なしを意味する。
- grace超過後もlate resultをsuccessへcommitしない。
- Python task hard-cancel等を行ってもexternal effectが既に起きた可能性はowner reconciliationへ残す。
- grace timeoutはDomain failureを捏造せずRuntime disposition/diagnosticへ記録する。
- grace超過後に別のhidden cleanup timeoutを追加せず、停止を成功扱いしない。

## 4. Dependency retry policy

#350 dependency lifecycleはdependencyごとにimmutable/versioned policyを持つ。

```text
DependencyRetryPolicy
- policy_id
- policy_revision: non-negative int
- dependency_id
- retry_enabled: bool
- max_retry_attempts: int >= 0
- initial_backoff_seconds: finite float > 0
- backoff_multiplier: finite float >= 1
- max_backoff_seconds: finite float >= initial_backoff_seconds
- diagnostic_min_interval_seconds: finite float >= 0
```

`max_retry_attempts`は**initial attempt失敗後に追加で行えるretry回数**である。`0`はretryなし。

retry番号`n`を1始まりとし、jitterなしのcanonical delayは次とする。

```text
retry_delay_seconds(n) =
  min(max_backoff_seconds,
      initial_backoff_seconds * backoff_multiplier ** (n - 1))
```

Rules:

- retryable/non-retryable分類はdependency owner/Provider contractからtypedに受け取り、例外message substringで決めない。
- retry waitは#322 `RuntimeClock.sleep()`相当のinjectable clockを使用し、Domain/library内部でblocking sleepしない。
- shutdown開始、dependency generation supersede、permission/credential permanent failure、policy limit到達で新規retryを開始しない。
- hidden random jitterを入れない。将来jitterが必要ならseed/sourceを含む明示versioned policyを別途追加する。
- policy missing/invalid時はretryを推測せず`retry_enabled=false`相当のfail-closed operationとし、dependencyをavailableへ捏造しない。

## 5. Diagnostic rate limit

同一failure fingerprintについて、前回emitから`diagnostic_min_interval_seconds`未満では新しいfull diagnostic eventをemitしない。

- suppressed countは集計してよい。
- interval到達後の次eventにsuppressed countを付与してよい。
- fingerprintはsecret/payload/Prompt/raw provider bodyを含まないstable sanitized fieldsだけから作る。
- rate limitingはfailure state自体を隠さず、availability snapshot/metrics counterは更新可能。

## 6. Shutdown policy

```text
RuntimeShutdownPolicy
- policy_id
- policy_revision: non-negative int
- in_flight_settle_grace_seconds: finite float >= 0
- final_persistence_grace_seconds: finite float >= 0
- resource_close_grace_seconds: finite float >= 0
- owned_task_join_grace_seconds: finite float >= 0
```

各値は最大待機秒。

正規順序は`runtime_lifecycle_contracts.md` Section 4を維持する。

- in-flight settle graceを超えたlate resultはcurrent runtimeへ新規commitしない。
- final persistence grace超過はdurability degradationとして記録し、Persistence close後にwriteを再開しない。
- 1 resource closeのtimeout/failureで後続resource closeを省略しない。
- owned task join graceを超えても`stopped`を成功状態として捏造しない。typed shutdown failure/degraded terminal diagnosticを残し、event loop close可否はComposition Rootが明示判断する。
- shutdown policy missing/invalidは安全なshutdownをhidden constantで実行せずconfiguration failureとする。ただし既にrunningなprocessで緊急停止要求を受けた場合、new admissionを即時閉じ、無期限waitを禁止し、取得可能なpolicy範囲でbest-effort closeを行いconfiguration failureを必ず記録する。

## 7. Policy generation / freshness

Runtime policy snapshotは起動generationへbindする。

- lane/scheduler policy変更はnew runtime generationまたは明示reconfiguration boundaryで適用する。
- retry policy変更は新しいretry cycleから適用し、既にsleep中の旧cycleを新revisionへ付け替えない。必要なら旧cycleをcancel/supersedeしてnew generationを開始する。
- shutdown開始後にpolicy revisionを切り替えてgraceを延長し続けることを禁止する。shutdown開始時snapshotをそのshutdown generationのAuthorityとする。

## 8. Required tests

- queue capacity/max-in-flight/countでbool/0/negativeを拒否
- cancellation grace 0 / positive / timeout
- retry `n=1`でinitial delay、指数増加、max cap
- max_retry_attempts=0でretryなし
- non-retryable failureでretryなし
- shutdown中retry開始なし
- hidden jitterなし / fake clock deterministic
- diagnostic interval境界（未満suppress / 等値以降emit可）
- resource close timeoutでも後続close実行
- persistence grace後にwrite再開なし
- policy revision supersedeで旧cycle resultをnew generationへcommitしない
- policy missing/invalid時にhidden defaultを使わない

## 9. Production implementation mapping

工程110 / #322のD10 owner amendmentは次へ対応する。

- `app/runtime/kernel/contracts.py`
  - explicit `RuntimeLanePolicy`
  - versioned `RuntimeSchedulerPolicy`
  - strict count / finite grace validation
  - `FAIL_FAST_CONTROLLED`
- `app/runtime/kernel/queue.py`
  - `max_priority_burst`を必須入力としhidden `8`を持たない。
- `app/runtime/kernel/coordinator.py`
  - scheduler policyをruntime generationへ明示bindする。
  - laneのqueue/concurrency/cancellation graceを全てexplicit policyから取得する。
  - cancellation grace超過後に別のhidden実時間waitを追加しない。
- Runtime Kernel既存Unit/Adjacent testでは、シナリオ用数値をtest fixture/helperで明示し、test値をproduction defaultとして再利用しない。

Section 4–7の#350 dependency retry / diagnostic / shutdown policyは工程340のowner amendmentで実装する。

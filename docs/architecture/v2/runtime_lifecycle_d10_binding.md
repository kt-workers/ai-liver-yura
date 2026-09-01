# V2 Runtime Lifecycle D10 binding

Owner: #350
Canonical authority: `runtime_lifecycle_contracts.md`, `runtime_operational_numeric_contracts.md`
Related: #322, #359, #445
Status: implementation binding

## 1. 目的

既存Runtime Lifecycleのavailability / reconnect / close境界を維持しつつ、D10で固定されたdependency retry、diagnostic rate limit、shutdown graceを明示的なversioned policyへ接続する。

Provider固有の例外本文、retry可否の意味、Domain State、Persistence snapshot内容は#350で推測しない。

## 2. DependencyRetryPolicy

各dependencyは次を明示注入する。

```text
DependencyRetryPolicy
- policy_id
- policy_revision
- dependency_id
- retry_enabled
- max_retry_attempts
- initial_backoff_seconds
- backoff_multiplier
- max_backoff_seconds
- diagnostic_min_interval_seconds
```

規則:

- count/revisionはconcrete int。boolを拒否する。
- seconds/multiplierはfinite number。bool / NaN / ±Infinityを拒否する。
- `max_retry_attempts`はinitial attempt失敗後の追加retry回数。0はretryなし。
- retry `n`は1始まりで `min(max, initial * multiplier ** (n - 1))`。
- hidden jitterを入れない。
- policy missing/invalidでretryを推測しない。

## 3. Typed dependency failure

Lifecycleへ渡すfailureはprovider/ownerが既に分類したtyped factとする。

```text
DependencyFailure
- failure_code: sanitized stable identifier
- retryable: bool
```

- Exception message substringからretry可否を決めない。
- raw exception本文、credential、Prompt、SDK responseをfingerprintへ入れない。
- diagnostic fingerprintは`dependency_id + failure_code`からLifecycleが作る。
- reconnect callbackがtyped failureを返さず予期しない例外を送出した場合、Lifecycleは例外classをprovider分類として採用せず、固定されたsanitizedな非retryable failureへ閉じる。

## 4. Retry cycle generation

Dependencyごとにcurrent retry policy generationを保持する。

- `schedule_reconnect()`開始時のPolicy snapshotをそのcycleへbindする。
- sleep中 / reconnect await中にPolicy generationが変わった旧cycle resultをcurrent dependency stateへcommitしない。
- Policy更新時にactive old cycleはcancel/supersedeし、取消完了までretired taskとして追跡する。
- 同一`policy_id/revision`で内容だけ変更することを禁止する。
- 同一generation同値再設定はidempotent。
- shutdown開始後は新規retryを開始しない。
- non-retryable failure、retry disabled、retry上限到達ではUNAVAILABLEへ閉じる。

## 5. Diagnostic rate limit

`allow_diagnostic(dependency_id, failure_code)`はcurrent dependency retry policyの`diagnostic_min_interval_seconds`を使用する。

- fingerprintごとに前回emit時刻を保持する。
- interval未満はsuppress、等値以降はemit可能。
- failure state/snapshot更新自体はrate limitしない。
- suppressed countは補助観測値であり、availability/failure Authorityにはしない。

## 6. RuntimeShutdownPolicy

```text
RuntimeShutdownPolicy
- policy_id
- policy_revision
- in_flight_settle_grace_seconds
- final_persistence_grace_seconds
- resource_close_grace_seconds
- owned_task_join_grace_seconds
```

全secondsはfinite number >= 0。shutdown開始時にsnapshotし、そのshutdown中に新Policyへ付け替えない。

## 7. RuntimeCoordinator shutdown binding

`RuntimeCoordinator`へ`RuntimeShutdownPolicy`をconstructorで必須注入する。hidden shutdown constantを持たない。

正規順序:

1. normal admission close
2. queued/future work cancel
3. running workへcancelを伝播
4. `in_flight_settle_grace_seconds`内でsettle
5. high-frequency/event producer stop hookを停止し、新しいframe/event/comment等を発生させない
6. final persistence hookをPersistenceがopenな間に`final_persistence_grace_seconds`内で実行
7. close hooksをreverse orderで実行
8. producer stop / 各close hookはresource停止操作として`resource_close_grace_seconds`でboundし、1件のtimeout/failureでも後続hookを必ず試す
9. runtime-owned worker taskを`owned_task_join_grace_seconds`内でjoin
10. pending owned workが0で、かつowned task join graceを超過していないときだけSTOPPEDへ遷移

producer stop hookはPersistence flushより前に実行する。これによりfinal snapshot capture中に新しいframe/eventが流入し続ける状態を作らない。

final persistence hookはowner-declared restart-safe stateを外から注入する。#350がEmotion/Attention/Speech/Activityをgeneric snapshotしない。

## 8. Shutdown failure convergence

Shutdown stage failureはsanitized typed diagnosticへ集約する。

```text
RuntimeShutdownFailure
- stage
- error_class
```

- raw exception本文を保存しない。
- producer stop failure/timeoutでもfinal persistenceとresource closeを続行する。
- final persistence failure/timeoutでもresource closeを続行する。
- resource close failure/timeoutでも後続closeを続行する。
- owned task join timeout / pending owned workが残る場合、STOPPED成功を捏造しない。
- terminal shutdown failure後の`stop()`二重要求は同じshutdown generationの同じfailureへ収束し、producer/persistence/close hookを再実行しない。

## 9. RuntimeLifecycle dependency close

`RuntimeLifecycle`も同じ`RuntimeShutdownPolicy`を明示受領する。

- dependency closeはreverse registration order。
- 各dependency closeを`resource_close_grace_seconds`でboundする。
- 1 dependency closeのtimeout/failureでも後続dependencyをcloseする。
- retry taskはshutdown開始時にcancelし、new retryを開始しない。
- policy切替でretireしたretry taskも取消完了まで追跡し、shutdown時に未回収taskを残さない。
- stop/closeはidempotent。

## 10. Compatibility

維持する:

- optional dependency failureで無関係laneを停止しない
- availability typed snapshot
- RuntimeClockによるretry sleep
- RuntimeCoordinatorのqueue/cancellation ownership
- #359だけがPersistence repository/transaction semanticsを所有
- Provider adapterだけがconcrete connection/callを所有

変更しない:

- Domain Goal / Internal State / Execution Fact
- retryable分類のprovider-specific意味
- restart-safe snapshotのDomain内容

## 11. Required tests

- retry policy bool / NaN / ±Infinity / negative reject
- max_retry_attempts=0でretryなし
- retry n=1 initial delay / multiplier / max cap
- non-retryable failureでretryなし
- fake clock deterministic / hidden jitterなし
- diagnostic interval `<` suppress / `==` emit
- same generation content mutation reject
- policy revision変更中のold sleep / reconnect result非commit
- policy revision変更でcancelしたold taskをshutdownが回収する
- shutdown開始後retry開始なし
- shutdown policy strict numeric
- producer stopはfinal persistenceより前
- producer stop failure後もpersistence/close継続
- final persistenceはresource close前
- final persistence timeout/failure後もclose継続
- resource close timeout/failure後も後続close実行
- owned task join grace超過でSTOPPEDを捏造しない
- terminal failure後のdouble stopでhook再実行なし
- successful double stop idempotent
- policy missing時hidden defaultなし

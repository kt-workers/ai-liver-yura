# V2 Streaming / Game Realtime Operational Numerical Contracts

Owners: #347 / #365
Related: `streaming_subsystem_contracts.md`, `game_skill_runtime_contracts.md`, `runtime_operational_numeric_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

Streaming comment burst処理とGame realtime loopについて、`bounded`、`configured delay`、`game-specific cadence`だけでは実装者判断になるqueue capacity、batch/window、tick/deadline、no-catch-up規則をversioned policyとして固定する。

Core Attention/Executive Authorityは変更しない。

## 2. Common strict numeric rule

count/revisionはconcrete int、seconds/rate/ratioはfinite numberを要求し、bool、NaN、±Infinityを拒否する。

## 3. StreamingOperationalPolicy

```text
StreamingOperationalPolicy
- policy_id
- policy_revision: non-negative int
- comment_ingress_capacity: int >= 1
- max_comment_codepoints: int >= 1
- aggregation_window_seconds: finite float > 0
- max_comments_per_window: int >= 1
- max_representative_signals_per_window: int >= 1
- max_moderation_in_flight: int >= 1
- observation_freshness_seconds: finite float >= 0
- overflow_policy: DROP_OLDEST_WITH_FACT | REJECT_NEW_WITH_FACT
- reconnect_policy_ref
```

`reconnect_policy_ref`は`runtime_operational_numeric_contracts.md`のversioned `DependencyRetryPolicy`を参照する。

## 4. Streaming comment admission

- comment text lengthはUnicode code point数で測る。
- `max_comment_codepoints`超過はsilent truncateして同じ意味のcommentとみなさない。typed `COMMENT_TOO_LARGE`としてrejectするか、provider normalization層が**truncated=true**の別evidence objectを明示生成する。
- queue overflowは必ずdropped/rejected countとsource event identityをbounded telemetryへ残す。silent lossをしない。
- raw provider arrival orderは`observed_at` → provider sequence（存在時）→ event_idでstable orderingする。

## 5. Streaming aggregation window

Windowはevent countではなくmonotonic/absolute timeで切る。

```text
window_start = first admitted event observed_at
window_end = window_start + aggregation_window_seconds
```

- `[window_start, window_end)`を同一windowとし、ちょうど`window_end`のeventは次window。
- `max_comments_per_window`を超える入力はoverflow policyに従い、全件をLLM/moderatorへ渡さない。
- output `representative signals`は最大`max_representative_signals_per_window`。
- aggregation model/providerが上限より多く返した場合、先頭Nをsilent採用せずpolicy/schema violation。
- grouping/representative selectionがopen-ended AIの場合も、outputは同じbounded typed schemaへ通す。

## 6. Streaming observation freshness

provider observation age:

```text
age_seconds = now_absolute - observed_at_absolute
```

- future observation timestampはinvalid diagnostic。
- `age > observation_freshness_seconds`はcurrent-state reconciliationへ使用せずhistorical/stale observationとして扱う。
- 等値はfresh範囲内。
- observationを捨てることとprovenance historyを消すことを混同しない。

## 7. Streaming reconnect

- exact retry count/backoff formulaは`DependencyRetryPolicy`を使用する。
- reconnect loopが独自sleep/jitterを持たない。
- final retry failure後に余分なbackoff sleepを行わない。
- credential/permanent policy failureはretryableへ昇格しない。
- reconnect generation変更後のold observation/resultをcurrent generationへ適用しない。

## 8. GameRealtimePolicy

Game implementationごとにimmutable/versioned policyを必須とする。

```text
GameRealtimePolicy
- policy_id
- policy_revision: non-negative int
- target_tick_rate_hz: finite float > 0
- tick_work_budget_ratio: finite float in (0,1]
- default_action_deadline_ratio: finite float > 0
- telemetry_queue_capacity: int >= 1
- observation_summary_interval_seconds: finite float > 0
- max_observations_per_summary: int >= 1
- max_tactical_in_flight: int >= 1
- max_consecutive_deadline_misses_before_degraded: int >= 1
- safe_fallback_strategy_ref?: stable typed ref
```

Derived:

```text
tick_period_seconds = 1 / target_tick_rate_hz
work_budget_seconds = tick_period_seconds * tick_work_budget_ratio
default_action_deadline_seconds = tick_period_seconds * default_action_deadline_ratio
```

No hard-coded 60fps assumption in generic #365.

## 9. Game tick scheduling / no catch-up explosion

Use monotonic clock for scheduler deadlines.

At loop start:

```text
next_tick = monotonic_now
```

For each tick:

1. tick deadline=`next_tick`.
2. execute mandatory perception/control bounded by `work_budget_seconds`.
3. optional tactical/model work that cannot meet current budget is skipped/deferred/cancelled according to typed result; it does not extend the frame indefinitely.
4. normal next tick=`next_tick + tick_period_seconds`.
5. if work completes after one or more tick deadlines, **do not replay missed ticks**. Set next tick to `monotonic_now + tick_period_seconds` and increment deadline-miss metrics.

This prevents catch-up loops.

## 10. Game action deadline

If `GameFrameAction.deadline` is absent, runtime derives:

```text
deadline = intended_at_absolute + default_action_deadline_seconds
```

- explicit action deadline must be timezone-aware/monotonic-correlated according to adapter clock contract and later than intended_at.
- dispatch開始時またはapply report前にdeadline超過なら成功を捏造しない。
- effect発生可能性があるtimeoutはambiguous/applied effect evidenceを保持する。

## 11. Tactical work freshness

Long-running tactical/model request binds:

- session_id
- game_state_revision
- strategy_revision
- policy_id/revision
- request deadline

completion時にcurrent revisionsを再読し、いずれか不一致ならstale。old resultをnew strategy/game stateへrebaseしない。

`max_tactical_in_flight`超過時、foreground frame controlを待たせずnew optional workをreject/coalesceする。coalesce keyはexact session+strategy+task identityであり、free text/AI similarityを使わない。

## 12. Game telemetry aggregation

Telemetry queueは`telemetry_queue_capacity`でbounded。

Summary windowは`[window_start, window_start + observation_summary_interval_seconds)`。

- same semantic/state identityのlatest-state telemetryだけ明示policyでcoalesce可能。
- Actual applied action/result/history evidenceをlatest-winsで消さない。
- output `GameObservationEvent`は1 summaryあたり最大`max_observations_per_summary`。
- output超過はsilent first-Nでなくpolicy violation。

## 13. Deadline degradation / fallback

consecutive deadline miss countが`max_consecutive_deadline_misses_before_degraded`以上になった時点でGame Skill availabilityをtyped DEGRADEDへ投影できる。

- counterはdeadlineを満たしたtickで0へresetする。
- fallback strategyを使う場合、`safe_fallback_strategy_ref`がcurrent accepted high-level Goal/strategy policyで許可されたtyped local strategyにexactly resolveできる場合だけ使用する。
- missing fallback時に「安全そうな動き」を実装者が作らない。controlをskip/hold/typed degradeする。
- fallbackはCore Goal/participant/session identityを変更しない。

## 14. Policy freshness

Streaming aggregation/reconnect jobsとGame tactical tasksはpolicy identity/revisionへbindする。

policy revision変更時:

- in-flight resultをnew revisionへ付け替えない。
- new window/tactical generationからnew policyを使う。
- running Game frame loopのpolicy hot-swapはatomic generation boundaryで行い、tick period変更時にold deadline debtを新periodへcarryしない。

## 15. Required tests

### Streaming
- queue overflow両policy / no silent loss
- codepoint length boundary
- aggregation window end equality
- representative count bound
- stale observation `>` / `==` boundary
- reconnect exact backoff / final failure no extra sleep

### Game
- 30/60/120等policyでderived tick period deterministic
- work budget ratio validation
- tick miss後catch-up replayなし
- default action deadline
- stale state/strategy/policy tactical result reject
- telemetry queue/batch bounds
- deadline miss thresholdでdegraded、successful tickでcounter reset
- missing safe fallbackでnew Core Goal/actionを捏造しない
- slow Core/Speech/Streaming中もframe loop継続

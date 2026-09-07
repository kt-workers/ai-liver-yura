# V2 Body Trajectory Timing / Time-scaling Contracts

Owner: #339
Upstream: #336 / #337 / #338
Related: `body_motion_planning_contracts.md`, `body_solver_controller_contracts.md`, `body_physical_numeric_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

`BodyMotionPhase.relative_duration_weight`とcurrent pose/velocity、dynamic limits、`movement_tempo`からactual phase durationを決めるAuthorityを固定する。

LLMが秒数を決めず、実装者が「自然そうな速度」を任意に選ばず、同じinput/model/policyから同じphase durationを得る。

## 2. TrajectoryTimingPolicy

```text
TrajectoryTimingPolicy
- policy_id
- policy_revision: non-negative int
- reference_phase_seconds: finite float > 0
- minimum_phase_seconds: finite float > 0
- maximum_phase_seconds: finite float >= minimum
- tempo_octaves: finite float >= 0
- duration_search_growth: finite float > 1
- duration_search_max_expand_steps: int >= 1
- duration_binary_search_iterations: int >= 1
- duration_tolerance_seconds: finite float > 0
- terminal_velocity_policy: ZERO_UNLESS_CONTINUATION | PRESERVE_MATCHING_TRAJECTORY
```

Initial V2 baseline:

```text
reference_phase_seconds = 0.45
minimum_phase_seconds = 1/60
maximum_phase_seconds = 10.0
tempo_octaves = 0.5
duration_search_growth = 2.0
duration_search_max_expand_steps = 12
duration_binary_search_iterations = 24
duration_tolerance_seconds = 1e-4
terminal_velocity_policy = ZERO_UNLESS_CONTINUATION
```

bool、NaN、±Infinityは禁止。

## 3. Relative weight normalization

PlanにN phaseがあり、各weight `w_i > 0`。

```text
mean_weight = sum(w_i) / N
normalized_weight_i = w_i / mean_weight
```

N=0はinvalid Plan。

これにより全weightを同じ定数倍してもduration resultは変わらない。

## 4. Expression tempo scale

#337 `movement_tempo ∈ [-1,1]`。

```text
tempo_scale = 2 ** (-movement_tempo * tempo_octaves)
```

- +1側はduration短縮、-1側はduration延長。
- input range外をclampせずreject。
- style scaleはhard dynamic limitsを緩和しない。

Aesthetic duration floor:

```text
T_aesthetic_i =
  max(minimum_phase_seconds,
      reference_phase_seconds
      * normalized_weight_i
      * tempo_scale)
```

## 5. Boundary state

各phaseのtrajectory generationはcurrent/previous phase terminal stateから開始する。

Per scalar DOF/root component:

```text
q0, v0, a0
q1, v1, a1
```

- `q0/v0/a0`はprevious committed/current trajectory state。
- target `q1`はcompiled task solution。
- `ZERO_UNLESS_CONTINUATION`では、明示continuous follow-through goalがないcomponentの`v1=a1=0`。
- `PRESERVE_MATCHING_TRAJECTORY`を使う場合、next phaseが同じ task-space/DOF directionのcontinuous goalとしてcompilerにexactly linkedされているcomponentだけnext phase boundary velocity/accelerationを共有できる。
- velocityをID名やmotion名から推測しない。

## 6. Canonical per-component interpolation family

position scalar `q(t)`はphase interval `[0,T]`で5次polynomialを使用し、6 boundary conditions:

```text
q(0)=q0
q'(0)=v0
q''(0)=a0
q(T)=q1
q'(T)=v1
q''(T)=a1
```

をexactに満たすquintic polynomialをcanonical initial implementationとする。

Coefficient solveはclosed linear systemであり、同一input/Tから同一coefficientsを得る。

Orientation taskはscalar canonical DOF spaceでsolveした各DOF trajectoryからderived quaternionへprojectし、quaternionを直接5次補間してjoint-limit Authorityにしない。

Root world translation/rotationも各canonical scalar componentで同じboundary polynomialを使う。

## 7. Continuous extrema validation

候補duration `T`がfeasibleかは、tick samplingだけで決めない。

各scalar polynomialについてinterval `[0,T]`内の:

- `|q'(t)|` velocity
- `|q''(t)|` acceleration
- `|q'''(t)|` jerk
- positional hard limit

のcontinuous extremaを評価する。

Required method:

- velocity extrema候補: endpoints + `q''(t)=0`の実根。
- acceleration extrema候補: endpoints + `q'''(t)=0`の実根。
- jerk extrema候補: endpoints + `q''''(t)=0`の実根。
- positional extrema候補: endpoints + `q'(t)=0`の実根。
- 実根は`0 <= t <= T`だけ評価。

polynomial root solverはfinite result / residualを検証し、root resolution failureを`NUMERICAL_FAILURE`としてfail-closedする。sample-only PASSは禁止。

Task-space residual/contact/balanceは別#339 physical acceptanceも同じcandidate trajectoryに対して満たす必要がある。

## 8. Deterministic duration search

For each phase:

1. `T_low = T_aesthetic_i`。
2. `T_low`がhard physical validation PASSなら、それをinitial feasible upper `T_high=T_low`とする。
3. FAILなら、`T = T_low * duration_search_growth^k`を`k=1..max_expand_steps`で評価し、最初のPASSを`T_high`とする。
4. `T > maximum_phase_seconds`ならそれ以上評価せずINFEASIBLE。
5. feasible `T_high`を得て、直前FAIL durationを`T_fail`とする。最初の`T_low`がPASSならbinary search不要。
6. `[T_fail, T_high]`を固定回数binary searchし、mid PASSならupper、FAILならlower。
7. `upper-lower <= duration_tolerance_seconds`になったら早期終了可。
8. final duration=`upper`。

Rules:

- PASS/FAIL validationが同一input/Tでdeterministicであること。
- timeout/CPU負荷を理由にsearch iterationを暗黙削減しない。
- maximum durationを超えてまで動作を遅くしてsuccessにしない。
- physical infeasibilityとnumerical failureを区別する。

## 9. Multi-component / multi-goal phase

phaseは全active scalar component/taskを**同じT**で実行する。

候補Tは全componentのdynamic limits、task-space target residual、support/contact/balance constraintsを同時にPASSして初めてfeasible。

一部jointだけ別の短いTで終了してstatic holdへ入ることは、solverが同じphase内でそのcomponent targetを早期達成してholdするclosed trajectoryを明示生成する場合のみ許可する。phase duration Authorityは1つ。

## 10. Interruption / supersede timing

new Planへのblend segmentも本書と同じboundary state + duration searchを使う。

- current q/v/aをstart boundary。
- new trajectory entry q/v/aをtarget boundary。
- hard/continuity constraintsを満たす最短feasible durationをsearch。
- safety emergency policyだけが別hard interruptを許可し、そのpolicy ID/revisionをtraceする。

Home/Neutralへ一旦戻す時間を挿入しない。

## 11. Completion time

Trajectory planned `end_offset_s`到達だけでCOMPLETEDにしない。

completionは#339のcurrent observed stateが:

- completion position/orientation tolerance
- required contact/balance
- terminal velocity/acceleration policy

を満たしたactual controller evidenceで確定する。

planned duration超過時はtrajectory/controller policyによりcontinue/recover/failし、時刻だけでsuccessを捏造しない。

## 12. Policy/model freshness

`ExecutableBodyTrajectory`は:

- body model ID/revision/fingerprint
- `BodySolverPolicy.policy_revision`
- `TrajectoryTimingPolicy.policy_id/revision`
- start BodyState revision
- expression revision used for tempo scale

をbindする。

rebase時はcurrent q/v/aとcurrent allowed expressionから**new trajectory identity + new timing calculation**を行う。old absolute offsetsをcurrent poseへそのまま貼らない。

## 13. Required tests

- weight全体scale invariance
- tempo -1/0/+1 exact scale
- moving start velocity continuity
- quintic boundary q/v/a exactness
- continuous extrema catches sample間peak
- expansion first feasible + binary search deterministic
- minimum/maximum duration bounds
- multi-joint slowest constraintがphase durationを支配
- hard balance/contact failはduration延長だけで無理にsuccessにしない
- supersede blend current q/v/aから開始
- repeated identical input produces identical timing
- planned end timeだけでCOMPLETEDにしない

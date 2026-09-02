# #339 Post-Completion Baseline Continuation Binding

Owner: #339
Discovered by: #341 / #346 Human Verification preparation
Base: `rebuild/v2-foundation@8d39b4bcb84b809e4ac23d161ff32d5530e2473b`
Canonical:
- `body_solver_controller_contracts.md`
- `body_solver_d10_controller_completion.md`
- `body_integration_contracts.md`

Status: implementation binding

## 1. 問題

現行`BodyContinuousController`はactive trajectoryが`COMPLETED`になった後、次tickを`INVALID_PLAN`で拒否する。

これはold trajectoryをterminal後に再実行しないというexecution contract自体には適合するが、#339 canonical Section 2 / 22の:

- base trajectory continuation
- `when no new trajectory is ready, current trajectory continues or stable expression baseline/realtime layers continue`
- previous committed BodyStateからのcontinuation
- no Home reset

を満たさない。

#341ではdeliberate motion完了後も#340 gaze/blink/breath/viseme/subtle channelsをBodyPoseFrameへcommitし続ける必要がある。

## 2. Authority分離

`COMPLETED`の`BodyMotionExecutionReport`はterminal evidenceとして不変にする。

baseline continuationはterminal trajectoryを再開することではない。

```text
COMPLETED execution report (immutable evidence)
         +
current committed BodyState / velocity / acceleration
         +
latest realtime overlay
         ↓
#339 baseline continuation tick
         ↓
next BodyState / BodyPoseFrame
```

baseline frameにはactive plan / active trajectoryを設定しない。

`INTERRUPTED`は従来契約どおり明示interrupt後の追加frameを禁止する。今回の修正scopeへ混ぜない。

## 3. Baseline tick admission

通常`tick()`のactive trajectory pathは従来どおり:

```text
PLANNED | STARTED | OBSERVABLE
```

を処理する。

trackerが`COMPLETED`の場合だけbaseline continuation pathへ入る。

`INTERRUPTED`は従来どおりrejectする。

`SUPERSEDED`は`supersede_trajectory()`が同Controller内で即座にnew trackerへ置換するためbaseline対象ではない。

その他terminal failureを暗黙baseline成功へ読み替えない。

## 4. Baseline physical target

baselineはHome / Neutral / fixed presetを持たない。

各tickでprevious committed stateを基準に:

- joint target position = そのtick開始時のcurrent scalar DOF position
- root position target = none
- root orientation target = none
- root impulse target = none
- balance mode = `STABLE_SUPPORT_REQUIRED`

とする。

これによりexisting dynamic limiterが:

- non-zero joint velocity/accelerationをjerk→acceleration→velocity bound内で0へsettle
- non-zero root linear/angular velocityをroot dynamic limit内で0へsettle
- current poseからのみ連続進行

させる。

baseline自体が新しいsemantic postureを発明しない。

## 5. Overlay composition

baseline tickも通常tickと同じ#340 channel composition gateを使用する。

- latest `RealtimeOverlayBundle`
- based-on BodyState revision freshness
- deterministic channel conflict resolution
- applied/degraded refs

をそのまま`BodyPoseFrame`へ保持する。

現行#340はchannel-onlyなのでscalar DOFを直接変更しない。将来joint-affecting overlay導入時は通常physical validation pathと同じhard/dynamic/balance再検証を必須とする。

## 6. Commit / report truth

baseline tick:

- `BodyStateAuthority`だけがrevisionを進める。
- `BodyPoseFrame.active_plan_id = None`
- `BodyPoseFrame.active_trajectory_id = None`
- old `COMPLETED` reportは内容・timestamp・residualを変更しない。
- baseline frame生成をold motionのPROGRESSED/COMPLETED再発火として扱わない。

`BodyControllerTickResult.execution_report`はread-only terminal snapshotを返してよい。これは新しいexecution eventではなく、Controller current report snapshotである。

## 7. New trajectory activation after completion

baseline continuation中にnew accepted trajectoryが届いた場合、同じ`BodyContinuousController` instanceでactivateする。

新API:

```text
activate_trajectory(
  trajectory,
  observed_at,
  started_monotonic_s,
) -> previous BodyMotionExecutionReport
```

status別:

- current `STARTED | OBSERVABLE`: old trackerを`SUPERSEDED`へ終端してnew trackerへ切替。
- current `COMPLETED`: old terminal reportはそのまま保持したsnapshotとして返し、new trackerへ切替。old statusを書き換えない。
- current `PLANNED`: actual未開始trajectoryを暗黙supersedeしない。従来どおりreject。
- `INTERRUPTED`その他terminal failure: reject。

従来`supersede_trajectory()`は互換APIとして`STARTED | OBSERVABLE`だけを許可し、内部共通activation helperを使用する。

## 8. Continuity state

new trajectory activation時は従来supersedeと同じく:

- `BodyStateAuthority.current`
- scalar DOF position / velocity / acceleration
- root `RootDynamicsState`
- `_last_monotonic_s`

を保持する。

resetするのは:

- active trajectory identity
- trajectory phase-relative origin
- phase target snapshot
- phase root base velocity
- execution tracker

だけである。

Home/Neutral reset、Controller再construct、zero velocity injectionは禁止する。

## 9. Failure atomicity

baseline tickでも通常tick同様:

- `last_monotonic_s`
- root acceleration state

はvalidated frame commit成功後だけ進める。

balance/support/commit failure時にcandidate stateを持ち越さない。

new trajectory activationもmodel/policy/start revision/monotonic validationをold tracker mutationより先に行う。

## 10. Required tests

最低限:

1. final motion tickがCOMPLETEDになった次tickもBodyState revisionが進む。
2. baseline frameのactive plan/trajectoryはNone。
3. old COMPLETED reportのstatus/timestamp/residualはbaseline tick後も不変。
4. baseline中もfresh #340 overlay channelが適用される。
5. stale overlayはdegradedとなる。
6. baselineでjoint/root velocity/acceleration/jerk limitを破らずsettleする。
7. baselineはHome/Neutralへsnapしない。
8. baseline balance failureはBodyState/internal control timeを進めない。
9. COMPLETED後のnew trajectoryをsame Controllerへactivateできる。
10. COMPLETED old reportをSUPERSEDEDへ書き換えない。
11. existing INTERRUPTED frame-block semanticsは維持する。
12. STARTED/OBSERVABLEからのexisting supersede semanticsは維持する。
13. PLANNEDから`activate_trajectory`はactual supersedeを発明せずrejectする。

#341 Adjacent testでは、deliberate motion completion後も複数frameとrealtime overlayが継続し、その後new planning resultをsame Controllerへactivateできることを固定する。

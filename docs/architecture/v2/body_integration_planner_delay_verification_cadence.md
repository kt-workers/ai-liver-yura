# #341 Planner Delay Verification Cadence

Owner: #341
Related: #339 / #546
Canonical parent:
- `docs/architecture/v2/body_integration_contracts.md`
- `docs/architecture/v2/body_integration_post_solver_runtime_binding.md`
- `docs/architecture/v2/body_solver_controller_contracts.md`
Status: Integration Verification Binding

## 1. Purpose

#341のplanner-delay acceptanceは、Body Motion Plannerが5秒/20秒待機している間にも#339 physical controlと#340 realtimeが通常cadenceで継続することを証明する。

Planner latencyは**physical tick間隔を5秒/20秒へ拡大すること**を意味しない。

## 2. Canonical time model

Planner laneとphysical laneは独立している。

```text
planner wall time:  0s ------------------------------ 20s
                    [          pending               ]

physical control:   | | | | | | | | | | | | | | | | ...
                    canonical target_control_rate_hz
```

D10 baseline `BodySolverPolicy.target_control_rate_hz` は60 Hzであり、テストは同policyの `target_control_interval_seconds` を使用する。

5秒/20秒の待機は、それぞれ通常control intervalの反復tickとして表現する。巨大な単発`dt`でwall timeを飛ばしてはならない。

## 3. Why sparse multi-second dt is invalid for this acceptance

旧Integration testは待機時間を:

```text
0.1s → delay/2 → delay
```

の3 physical ticksだけで表現していた。

これは5秒時に約2.4秒、20秒時に約9.9秒の単発`dt`をControllerへ入力することになり、検証対象を「plannerが遅くてもphysical loopが継続する」から「physical scheduler自体が数秒停止する」へ変えてしまう。

#546でjoint dynamicsをtarget-aware brakingへ厳密化した結果、この非現実的な巨大`dt`がhard-limit conflictとして顕在化した。これは#546のhard safetyを緩める理由にしない。

## 4. Required test behavior

planner gateがclosedの間:

1. `control_interval = BodySolverPolicy.target_control_interval_seconds` を使う。
2. 5秒/20秒相当まで同intervalでphysical tickを繰り返す。
3. 各tickでcurrent trajectoryのframeが生成される。
4. planner sessionは`PLANNING`のまま。
5. BodyState revisionはtick数だけ単調増加する。
6. planner gateをopenした後も、次の通常control intervalでnew planをconsume/activateする。
7. same `BodyContinuousController` identityを維持する。

テストは実時間で5秒/20秒sleepする必要はない。monotonic simulationを通常control cadenceで進めればよい。

## 5. Safety boundary

- #341 testの都合で#339/#546 velocity・acceleration・jerk・hard-limit gateを緩めない。
- giant `dt` resilienceが必要なら、scheduler/runtime timing policyとして独立Issueで設計・検証する。
- 本acceptanceはplanner latencyとphysical loop non-blocking性の検証に限定する。

# #339 D10 Physical Controller Completion Binding

Owner: #339
Base lineage:
- PR #497: initial plan compiler（merge済み）
- PR #501: frame/state/report/FK/execution/publication基盤（merge済み）
Canonical:
- `body_solver_controller_contracts.md`
- `body_physical_numeric_contracts.md`
- `body_motion_planning_contracts.md`
Status: implementation binding

## 1. 目的

既存PR #497/#501を再実装せず、D10で#339へ明示された未完了physical controller責務だけを補完する。

保持する既存成果:
- `compile_body_motion_plan`
- `ExecutableBodyTrajectory` / `BodyTrajectoryPhase` / `BodySolveTask`
- `BodyPoseFrame` / `BodyMotionExecutionReport`
- deterministic `forward_kinematics`
- `BodyStateAuthority`
- `BodyMotionExecutionTracker`
- `LatestBodyFrameBuffer` / frame compatibility gate

新規責務は次だけとする。
- versioned numerical `BodySolverPolicy`
- trusted spatial target geometry boundary
- model / policy generation binding
- scalar DOFをAuthorityとするbounded IK
- dynamic CoM / support polygon / contact validation
- velocity / acceleration / jerk boundを持つcontinuous control tick
- #340 overlay適用後のhard/dynamic/balance再検証

## 2. Policy

`BodySolverPolicy`はD10正本Section 10の値を明示的に保持する。

```text
BodySolverPolicy
- policy_revision
- target_control_rate_hz
- numeric_epsilon
- max_ik_iterations
- position_residual_tolerance_ratio
- orientation_residual_tolerance_radians
- completion_position_tolerance_ratio
- completion_orientation_tolerance_radians
- minimum_support_margin_ratio
- max_per_iteration_dof_step_radians
```

Production constructorにhidden defaultは置かない。

正本のInitial V2 baseline値を採用する場合も、composition/test側で明示して構成する。

全floatはfiniteかつ意味上positive、`max_ik_iterations`はboolを拒否する1以上のint、revisionはnon-negative intとする。

## 3. Trajectory provenance

既存`ExecutableBodyTrajectory`へ次を追加する。

```text
- body_model_revision
- body_model_fingerprint
- solver_policy_revision
```

既存の`body_model_id`だけではD10のmodel generation bindingを満たさない。

compilerは:
- Planのmodel ID/revision/fingerprintとcurrent modelをexact照合
- `model.require_physical_control_contract()`
- 明示`BodySolverPolicy`
を要求し、trajectoryへAuthority値を付与する。

ordinary BodyState revision前進は従来どおりrebaseableで、model generation driftだけをhard staleとする。

## 4. Trusted spatial target boundary

`target_ref`文字列をgeometryとして解釈しない。

```text
BodySpatialTargetSnapshot
- target_ref
- position?
- orientation?
- linear_velocity?
- source_owner
- source_ref
- source_revision
- generation
- observed_at

BodySpatialTargetResolverPort
- resolve(target_ref) -> BodySpatialTargetSnapshot | None
```

初期#339補完は`SNAPSHOT_AT_ADMISSION`を実装する。
`TRACK_LATEST`は型として保持し、同identity/generationだけを再利用可能とする。generation変化はtyped failureへ閉じる。

## 5. Target metric

D10 Section 9をexactに使用する。

- TARGET_REF position: current→resolved target linear interpolation by `extent`
- TARGET_REF orientation: shortest-arc slerp by `extent`
- CONTACT: `extent == 1.0`以外をreject
- DIRECTION + ORIENT: current forward→directionのshortest-arc slerp fraction
- DIRECTION + TRANSLATE for chain: `sum(normalized_length) * reference_height * extent`
- root translate/impulse: `RootDynamicLimit`の明示budget
- regionだけでreach budgetを一意に決められないtranslateはUNSUPPORTED

root target resolutionはpositionとorientationを同一の一時変数へ格納しない。positionは`Vector3`、orientationは`Quaternion`として別々のtyped localへ保持し、静的型境界と数値意味を混同しない。

### 5.1 BodySolveTask binding

`BodySolveTask.joint_ids`は少なくとも1件のcanonical joint IDを持つ。一方、`chain_ids`は**0件以上**とする。

- chain/end-effectorへ一意に束縛されたtaskは`chain_ids`を保持する。
- root translation / orientation / impulseはroot jointへ束縛し、`chain_ids=()`を許可する。
- region/joint selectorからcompileされたが一意なchainを持たないtaskも`chain_ids=()`を許可する。そのtaskがchain geometryを必要とする処理へ到達した場合は、距離やend-effectorを推測せず`UNSUPPORTED_CAPABILITY`へ閉じる。
- `chain_ids`が空であること自体をschema invalidとはしない。可否はtask kindと必要geometryの組合せで判定する。

これによりroot budget ruleと「regionだけでreach budgetを発明しない」ruleを同一typed task契約で表現できる。

## 6. Deterministic scalar IK

Canonical solver pathはrandomnessを使わない。

実装方式はbounded deterministic scalar coordinate descentとする。

1. current `JointDofState`を開始点にする。
2. taskがbindするchainのDOFをcanonical joint順・X→Y→Z順で固定列挙する。
3. end-effector position/orientation residualを計算する。
4. 初期search stepは`max_per_iteration_dof_step_radians`とする。各iterationで各DOFについて `±current_step` の候補をhard limit内で評価する。
5. residualを`numeric_epsilon`より大きく減少させる候補のうち最良だけを採用する。equal within `numeric_epsilon` はstable `(joint_id, axis, signed_step)`順で決定する。
6. 現在のstepで改善候補が無いがtolerance未達の場合、`current_step /= 2`として同じcurrent iterateから探索を継続する。これによりpolicy値を「固定格子間隔」と誤解せず、名称どおり1 iterationの**最大**DOF stepとして扱う。
7. `current_step <= numeric_epsilon`、または`max_ik_iterations`までにtoleranceへ入れない場合は、last iterateをcommitせずtyped infeasible/numerical resultへ閉じる。明らかなstagnationを検出した場合は64回を必ず消費する必要はないが、iteration countは常に`max_ik_iterations`以下で決定論的でなければならない。
8. tolerance内ならsuccessとする。

この方式は最速解を目的にせず、D10のdeterminism / bounded iteration / hard-limit / residual contractを優先する。特に`max_per_iteration_dof_step_radians`を固定量としてのみ使用し、到達可能なtargetがstep gridの間にあるだけでINFEASIBLEへ落ちる実装は禁止する。

## 7. FK / end-effector frame

既存`forward_kinematics`を保持する。

追加helperはCanonical `EndEffectorDefinition.local_position/local_forward_axis/local_up_axis`をworldへ投影し、joint centerをend-effector位置とみなさない。

hard-limit判定はscalar DOFに対して行い、quaternion逆分解を使用しない。

## 8. Balance / contact

Dynamic CoM:
- 各segmentのproximal/distal world位置
- explicit `center_of_mass_fraction_from_proximal`
- `mass_fraction`
からD10式をexact計算する。

Grounded balance:
- 明示active support contactだけを使用する。
- contact local_positionをFKでworldへ投影する。
- XZ plane上でconvex hullを作る。
- 非共線3点未満は`INSUFFICIENT_SUPPORT_GEOMETRY`。
- CoM projectionがpolygon外又はminimum support margin未満なら`BALANCE_INFEASIBLE`。

`TEMPORARY_FLIGHT_ALLOWED`ではgrounded polygon requirementを解除するが、`RECOVER_STABLE_SUPPORT`では再度supportを要求する。

## 9. Continuous tick / dynamic bounds

ControllerはNeutral/Homeではなくprevious committed physical `BodyState`から開始する。

per tick:
1. active phase/taskをmonotonic elapsed timeから選択
2. IK/target solveでdesired scalar DOFを得る
3. previous position/velocity/accelerationからjoint dynamic limitを適用
4. jerk → acceleration → velocity → positionの順でbound
5. scalar hard limitを再検証
6. scalar DOF→derived BodyPose
7. FK / target residual
8. balance/contact
9. realtime overlayをcanonical channelとしてcompose
10. overlay後hard/dynamic/balance再検証
11. `BodyStateAuthority`へatomic commit
12. `BodyPoseFrame`とexecution evidenceを生成

solver/tick失敗時は未検証candidateをcommitしない。さらにcontrol tickの`last_monotonic`とroot acceleration stateもcandidateとして扱い、validated frame commit成功後だけ進める。失敗tickの時間・加速度を次tickへ持ち越してはならない。

## 10. Execution lifecycle / supersede

accepted Plan / compiled trajectoryだけではactual executionを開始しない。`BodyMotionExecutionReport`はControllerがvalidated frameをcommitした後だけ`PLANNED`から`STARTED` / `OBSERVABLE`へ進む。

`INTERRUPTED` / `SUPERSEDED`はactual motionを開始済みの`STARTED` / `OBSERVABLE`からだけ遷移可能とする。未実行の`PLANNED` trajectoryを入れ替えることをactual interruptionとして報告しない。

既存report schemaの`completed_at`はactual executionのterminal timestampとして`COMPLETED`だけでなく`INTERRUPTED` / `SUPERSEDED`でも必須とし、終端時点のachieved targetとresidualを保持する。terminal reportから再度progress/complete/terminal遷移しない。

supersedeはController instanceを破棄して新規作成する方式をcanonical pathにしない。同一`BodyContinuousController`内で:

1. new trajectoryのmodel generation / solver policy bindingとactivation monotonic timeを先に検証する。
2. old trackerを`SUPERSEDED`へ終端する。
3. `BodyStateAuthority.current`、previous committed scalar DOF position/velocity/acceleration、root dynamic acceleration state、last control monotonic timeを保持する。
4. phase target snapshotとphase-relative originだけをnew trajectory用にresetする。
5. new trackerは`PLANNED`から開始し、次のvalidated frame commit後にのみactualへ昇格する。
6. new desired targetは通常のjerk → acceleration → velocity → position limiterを通すため、暗黙Home/Neutral resetや無制限stepを作らない。

interrupt後はControllerから追加frameをcommitできない。supersede後は旧trajectoryでは追加frameをcommitできず、新trajectoryだけが継続する。

## 11. Overlay boundary

#340はBodyState writerではない。#339が最終commit Authorityを維持する。

現行#340 overlayはcanonical realtime channel値であり、joint DOF直接値ではないため:
- channel値は`BodyPoseFrame.channel_values`へ記録する。
- scalar joint stateを変更しないchannelはhard joint limitを迂回しない。
- 将来joint-affecting overlayが導入された場合は、同tick validation pathを必須とする。

applied/degraded refsはframe evidenceへ保持する。

## 12. Failure追加

`BodySolverFailureCode`へD10で区別された次を追加する。

- MODEL_REVISION_MISMATCH
- MODEL_FINGERPRINT_MISMATCH
- INVALID_DOF_STATE
- INVALID_SOLVER_POLICY
- TARGET_GEOMETRY_UNAVAILABLE
- TARGET_GENERATION_CHANGED
- INSUFFICIENT_SUPPORT_GEOMETRY
- DYNAMIC_LIMIT_CONFLICT

generic FAILEDへ潰さない。

## 13. 実装順

Stage 1 — Policy / provenance / geometry contracts
Stage 2 — FK end-effector + CoM/support utilities
Stage 3 — bounded scalar IK
Stage 4 — continuous dynamic-bound controller tick
Stage 5 — execution/frame integration + D10 tests

各Stageは同じbranchで継続し、新しい#339実装lineageを作らない。

## 14. Required verification

最低限:
- model ID/revision/fingerprint mismatch
- policy validation/revision binding
- end-effector local offset FK
- target snapshot position/orientation / unavailable
- extent 0 / 0.5 / 1
- CONTACT extent != 1 reject
- root / region-only taskが`chain_ids=()`で型として表現可能
- chain geometry必須処理でchain未束縛ならUNSUPPORTED
- scalar hard limit exact boundary
- bounded/adaptive IK iteration / repeated determinism / unreachable typed failure
- fixed-step grid間targetもtolerance内へ収束
- dynamic velocity/acceleration/jerk bound
- root dynamic velocity/acceleration/jerk bound
- dynamic CoM explicit fraction
- support polygon inside/outside/margin / insufficient geometry
- airborne release / support recovery
- current pose start / no Home reset
- overlay後もscalar hard limit unchanged
- accepted Planだけではactual completionにならない
- failed tick does not commit BodyState or internal control time/dynamics
- interruption / supersedeはactual start後だけterminal化し、terminal timestamp / residualを保持する
- supersede後もposition / velocity / acceleration continuityをprevious committed stateから維持する
- terminal old trajectoryから追加frameをcommitしない

full repository GateはRuff / strict Mypy / full pytest / compileall / diff-check / base freshnessを使用する。

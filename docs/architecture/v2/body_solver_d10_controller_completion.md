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

## 6. Deterministic scalar IK

Canonical solver pathはrandomnessを使わない。

実装方式はbounded deterministic scalar coordinate descentとする。

1. current `JointDofState`を開始点にする。
2. taskがbindするchainのDOFをcanonical joint順・X→Y→Z順で固定列挙する。
3. end-effector position/orientation residualを計算する。
4. 各iterationで各DOFについて `±max_per_iteration_dof_step_radians` の候補をhard limit内で評価する。
5. residualを最も減少させる候補だけを採用する。equal within `numeric_epsilon` はstable `(joint_id, axis, signed_step)`順で決定する。
6. tolerance内ならsuccess、`max_ik_iterations`到達時はlast iterateをcommitせずtyped infeasible/numerical resultへ閉じる。

この方式は最速解を目的にせず、D10のdeterminism / bounded iteration / hard-limit / residual contractを優先する。

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

solver/tick失敗時は未検証candidateをcommitしない。

## 10. Overlay boundary

#340はBodyState writerではない。#339が最終commit Authorityを維持する。

現行#340 overlayはcanonical realtime channel値であり、joint DOF直接値ではないため:
- channel値は`BodyPoseFrame.channel_values`へ記録する。
- scalar joint stateを変更しないchannelはhard joint limitを迂回しない。
- 将来joint-affecting overlayが導入された場合は、同tick validation pathを必須とする。

applied/degraded refsはframe evidenceへ保持する。

## 11. Failure追加

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

## 12. 実装順

Stage 1 — Policy / provenance / geometry contracts
Stage 2 — FK end-effector + CoM/support utilities
Stage 3 — bounded scalar IK
Stage 4 — continuous dynamic-bound controller tick
Stage 5 — execution/frame integration + D10 tests

各Stageは同じbranchで継続し、新しい#339実装lineageを作らない。

## 13. Required verification

最低限:
- model ID/revision/fingerprint mismatch
- policy validation/revision binding
- end-effector local offset FK
- target snapshot position/orientation / unavailable
- extent 0 / 0.5 / 1
- CONTACT extent != 1 reject
- scalar hard limit exact boundary
- bounded IK iteration / repeated determinism / unreachable typed failure
- dynamic velocity/acceleration/jerk bound
- dynamic CoM explicit fraction
- support polygon inside/outside/margin / insufficient geometry
- airborne release / support recovery
- current pose start / no Home reset
- overlay後もscalar hard limit unchanged
- accepted Planだけではactual completionにならない
- failed tick does not commit BodyState

full repository GateはRuff / strict Mypy / full pytest / compileall / diff-check / base freshnessを使用する。

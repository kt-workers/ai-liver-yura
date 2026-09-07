# V2 Body Physical / Numerical Contracts

Owners: #336 / #338 / #339
Parent: #335
Design gate: #445
Status: Canonical Supplement / implementation-decidability correction

Related:
- `body_architecture.md`
- `body_motion_planning_contracts.md`
- `body_solver_controller_contracts.md`
- `body_realtime_layers_contracts.md`
- `avatar_presentation_contracts.md`

## 1. 目的

Canonical Body Model、BodyMotionPlan、Solver / Continuous Controllerの間で、実装者が数学表現・target geometry・物理量変換・balance/contact・数値許容値を発明しなくてよいように、V2 Bodyのphysical / numerical Authorityを固定する。

本書は既存の意味・責務境界を変更せず、#336/#338/#339の不足していた数値契約を補完する。

## 2. Canonical joint coordinate Authority

### 2.1 Scalar DOFがphysical Authority

各回転jointのphysical configurationは、quaternionを逆分解して得る値ではなく、宣言済みDOFごとのscalar coordinateを正本とする。

```text
JointDofState
- joint_id
- coordinates[]

JointDofCoordinate
- axis: X | Y | Z
- position_radians
- velocity_radians_per_second
- acceleration_radians_per_second2
```

Rules:

- coordinateは`JointDefinition`で宣言されたaxisだけを持つ。
- 各axisはexactly one。
- hard/comfortable/relaxed limitはこの`position_radians`へ直接適用する。
- solverはscalar DOF空間を更新する。
- quaternionからEuler角等へ逆分解してhard limitを判定してはならない。
- external renderer quaternionをCanonical joint coordinateへ逆変換してBodyStateを書き換えてはならない。

### 2.2 Local transformへの一意なprojection

列vectorを用いるrotation matrix表記で、joint local rotationは次を正本とする。

```text
R_local = R_rest · R_X(theta_x) · R_Y(theta_y) · R_Z(theta_z)
```

- `theta_x/y/z`は存在するDOFだけを使用する。
- composition orderは常にX→Y→Zで固定する。
- axisはjointの**rest-local coordinate frame**のcanonical axisである。
- quaternionは上記rotation matrixから得るderived representationでありphysical coordinate Authorityではない。
- quaternion signの`q`と`-q`は同一rotationとして扱う。

この定義により、複数DOF jointでもlimit判定のためのquaternion decompositionを不要にする。

### 2.3 BodyPose / BodyState

Canonical BodyStateは少なくとも:

```text
BodyState
- body_model_id
- body_model_revision
- body_model_fingerprint
- revision
- observed_at
- joint_dof_states[]       # physical Authority
- root world state
- derived BodyPose         # renderer/FK等へ渡せるprojection
- bounded history
```

を持つ。

既存`BodyPose.joint_local_transforms`はderived pose projectionとして維持可能だが、scalar DOF stateなしに#339がphysical BodyStateをcommitすることを正規経路にしない。

## 3. Model revision / fingerprint

`CanonicalBodyModel`は:

```text
- body_model_id
- body_model_revision: non-negative int
- body_model_fingerprint: stable digest
```

を持つ。

fingerprint対象:

- skeleton hierarchy
- rest transforms
- DOF axes / hard / comfortable / relaxed limits
- dynamic limits
- segment geometry / mass
- end-effector definitions
- contact/support geometry
- reference height

serialization orderやcache等、意味を持たないderived情報はfingerprint対象外。

Rule:

- 上記意味情報が変わる場合revisionを進めfingerprintも変える。
- #338 Planと#339 SolveContextはID/revision/fingerprintを全てbindする。
- ID一致だけで別generation modelを受理しない。

## 4. Joint / root dynamic limits

### 4.1 Joint dynamic limit

各DOFはhard positional rangeに加えて:

```text
JointDynamicLimit
- axis
- max_velocity_radians_per_second > 0
- max_acceleration_radians_per_second2 > 0
- max_jerk_radians_per_second3 > 0
```

を持つ。

値はmodel/control profileで明示し、axis名やjoint名から推測しない。

### 4.2 Root dynamic limit

```text
RootDynamicLimit
- max_linear_velocity_mps
- max_linear_acceleration_mps2
- max_linear_jerk_mps3
- max_angular_velocity_radps
- max_angular_acceleration_radps2
- max_angular_jerk_radps3
- directional_translation_budget_m
- impulse_budget_mps
```

全値はfinite / positive。missingのままroot translation/impulseを実行可能扱いしない。

## 5. Segment mass / dynamic center of mass

`SegmentDefinition`は既存の`mass_fraction`に加えて:

```text
- center_of_mass_fraction_from_proximal: [0,1]
```

を持つ。

dynamic segment CoM:

```text
segment_com_world =
  proximal_world_position
  + fraction * (distal_world_position - proximal_world_position)
```

body CoM:

```text
body_com_world = sum(segment_com_world * mass_fraction) / sum(mass_fraction)
```

Rules:

- 全segmentのmass fraction合計は`1.0 ± 1e-6`を要求する。
- fractionを指定せずmidpoint=0.5と推測してはならない。
- existing static `CenterOfMassReference`はrest/reference validationに利用可能だが、dynamic balance Authorityを代替しない。

## 6. End effector geometry

単なるjoint IDではなく、task-space targetの幾何を一意にする。

```text
EndEffectorDefinition
- end_effector_id
- joint_id
- local_position: Vector3
- local_forward_axis: unit Vector3
- local_up_axis: unit Vector3
```

Rules:

- forward/upはfinite、unit、互いに平行ではない。
- position/orientation taskはjoint centerではなくこのframeを利用する。
- chainは`end_effector_id`へbindする。
- hand/foot/head等の語をID名から意味推測しない。

## 7. Contact / support geometry

```text
ContactPointDefinition
- contact_id
- joint_id
- local_position: Vector3
- support_capable: bool
```

active support contactはFKでworld位置へ投影する。

grounded phaseでbalanceを必須とする場合:

1. activeな`support_capable=true` contactを取得する。
2. ground/support planeへ投影する。
3. convex hullをsupport polygonとする。
4. dynamic body CoMのplane projectionがpolygon内かつ`minimum_support_margin_m`以上内側にあることを要求する。

Rules:

- support polygonを要求するphaseで3点未満、または非共線3点を作れない場合は`BALANCE_INFEASIBLE`。
- contact geometryをfoot joint center等から暗黙生成しない。
- airborne宣言phaseはgrounded support polygon requirementを解除できるが、takeoff/landing transitionを省略しない。

## 8. Spatial target geometry boundary

### 8.1 Target refはidentityでありgeometryではない

`BodySpatialTarget(kind=TARGET_REF)`の`target_ref`文字列から位置・方向を推測してはならない。

#339へ渡すtrusted geometryはread-only boundaryから取得する。

```text
BodySpatialTargetSnapshot
- target_ref
- coordinate_space: WORLD
- position?: Vector3
- orientation?: Quaternion
- linear_velocity?: Vector3
- source_owner
- source_ref
- source_revision
- generation
- observed_at
```

```text
BodySpatialTargetResolverPort
- resolve(target_ref) -> BodySpatialTargetSnapshot | typed unavailable
```

Authority:

- Resolverはsemantic targetを決めない。
- #338がcommit済みtarget identityを選ぶ。
- Resolverはそのidentityに対するgeometry/provenanceだけを返す。
- #339はtarget ID/revision/generationを記録する。

Unavailable / missing required component:

- geometryを捏造しない。
- `TARGET_GEOMETRY_UNAVAILABLE`またはtask-specific `UNSUPPORTED` / `INFEASIBLE`へ閉じる。

### 8.2 Tracking mode

初期canonical:

```text
TargetTrackingMode
- SNAPSHOT_AT_ADMISSION
- TRACK_LATEST
```

- deliberate fixed reach/contactは原則`SNAPSHOT_AT_ADMISSION`。
- moving target追従が明示されたPlanだけ`TRACK_LATEST`。
- `TRACK_LATEST`ではsame target identity/generationのfresh geometryだけを各tickで利用し、generation変更時はrevalidation/replanする。
- low-latency gaze micro trackingは#340責務であり、#339の全taskを自動TRACK_LATESTにしない。

## 9. `extent`のdeterministic metric化

`extent ∈ [0,1]`はそのままmeter/radianではない。effectごとに次のclosed ruleでtask-space targetへ変換する。

### 9.1 TARGET_REF

`TRANSLATE` / `ORIENT`:

- extent=0: current task poseを維持。
- extent=1: resolved target poseへ到達するgoal。
- 0<extent<1: current task poseからresolved target poseへのfractional interpolation。
- positionはlinear interpolation。
- orientationはshortest-arc quaternion slerp。

`CONTACT`:

- actual contact goalなのでextentは`1.0`を要求する。
- 1.0未満を接触成功へ読み替えない。

### 9.2 DIRECTION + ORIENT

- selector/end-effectorのcurrent forward axisをworldへ投影する。
- specified unit directionへfull-alignするorientationを求める。
- extentをcurrent→full-align orientationのshortest-arc slerp fractionとする。

したがってangle scaleを任意定数で発明しない。

### 9.3 DIRECTION + TRANSLATE

end-effector/chain:

```text
reach_budget_m = sum(chain segment normalized_length) * reference_height
translation_distance_m = extent * reach_budget_m
```

root:

```text
translation_distance_m = extent * RootDynamicLimit.directional_translation_budget_m
```

region selectorだけで一意なchain/reach budgetが得られない場合は、明示chain/end-effector bindingなしに距離を推測せず`UNSUPPORTED`。

### 9.4 DIRECTION + IMPULSE

root impulse:

```text
requested_delta_velocity = direction * extent * RootDynamicLimit.impulse_budget_mps
```

chain/joint impulseは明示されたcapability/policyがある場合だけ許可し、root ruleを流用しない。

## 10. Numerical Solver Policy

#339はversioned immutable policyを入力として持つ。

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

Initial V2 baseline:

```text
target_control_rate_hz = 60
numeric_epsilon = 1e-9
max_ik_iterations = 64
position_residual_tolerance_ratio = 0.01        # reference height比
orientation_residual_tolerance_radians = 0.017453292519943295  # 1 degree
completion_position_tolerance_ratio = 0.015
completion_orientation_tolerance_radians = 0.03490658503988659 # 2 degrees
minimum_support_margin_ratio = 0.01
max_per_iteration_dof_step_radians = 0.08726646259971647        # 5 degrees
```

meter値へ変換するratioは`reference_height`を掛ける。

Rules:

- policy revisionをtrajectory/provenanceへbindする。
- runtime負荷に応じてiteration/toleranceを暗黙変更しない。
- policy変更は明示revisionとして扱う。
- random seed / random perturbationをcanonical solver pathに使わない。
- numerical failure時にlast iterateをcommitしない。

solverの内部手法はanalytic/Jacobian/optimization/hybridから選択可能だが、同一input/model/policyでdeterministicであり、本書と#339 acceptanceを満たさなければならない。

## 11. Hard-limit / frame commit order

各control tickは少なくとも:

```text
latest scalar DOF state
+ active trajectory task targets
+ latest allowed realtime overlays
→ solve scalar DOF candidate
→ scalar hard-limit validation/clamp policy
→ FK / end-effector residual
→ contact/support + dynamic CoM validation
→ velocity / acceleration / jerk validation
→ derived local/world transforms + quaternion projection
→ BodyPoseFrame validation
→ atomic BodyState revision commit
```

- hard constraint failure frameはcommitしない。
- overlay適用後にも同じhard checksを再実行する。
- derived quaternionだけを見てhard limit PASSにしない。

## 12. Failure additions

#339 closed failureへ少なくとも追加する。

```text
MODEL_REVISION_MISMATCH
MODEL_FINGERPRINT_MISMATCH
INVALID_DOF_STATE
INVALID_SOLVER_POLICY
TARGET_GEOMETRY_UNAVAILABLE
TARGET_GENERATION_CHANGED
INSUFFICIENT_SUPPORT_GEOMETRY
DYNAMIC_LIMIT_CONFLICT
```

既存failureと意味が重なる場合は最終schemaで統合してよいが、異なるfailure classをgeneric `FAILED`だけへ潰さない。

## 13. Required tests追加

### Joint coordinate
- multi-DOF scalar coordinates→derived quaternionの固定X→Y→Z順
- quaternion sign同値
- scalar hard-limit exact boundary
- quaternion逆分解を使わずlimit enforcement
- undeclared axis reject

### Model generation
- model revision mismatch
- fingerprint mismatch
- model geometry変更でfingerprint変更

### Geometry
- end-effector local offsetを含むFK
- TARGET_REF snapshot position/orientation
- missing target geometry fail closed
- TRACK_LATEST same generation update
- target generation replacement reject/replan

### Extent
- TARGET_REF 0/0.5/1 interpolation
- CONTACT extent != 1 reject
- DIRECTION ORIENT slerp fraction
- chain reach based TRANSLATE
- root budget based TRANSLATE/IMPULSE
- ambiguous region translation unsupported

### Balance
- segment mass fraction total validation
- explicit segment CoM fraction
- support polygon inside/outside/margin
- insufficient support geometry reject
- airborne release + landing regain

### Dynamics
- per-DOF velocity/acceleration/jerk bound
- root dynamic bound
- overlay後のdynamic/hard-limit再検証

### Numerical policy
- exact policy revision binding
- fixed iteration budget
- tolerance boundary
- repeated identical input produces identical result

## 14. Issue / implementation impact

この設計補修は新しい独立Body機能を追加するのではなく、既存責務の未完了部分を明示する。

- #336: model revision/fingerprint、scalar DOF state、dynamic limits、segment CoM、end-effector/contact geometryを実装・検証する必要がある。
- #338: target tracking modeとextentのclosed semanticsをPlan contractへ反映する必要がある。
- #339: resolver boundary、metric compilation、scalar solver、balance/contact/dynamics/numerical policyを実装する必要がある。

したがって既存Issueをまず再評価し、これらの責務が未実装なら新規重複Issueを作るのではなく各owner Workを再開する。

新しい独立Spatial Target provider実装が将来必要になった場合は、そのProvider/Subsystemのownerが存在しないことを確認してから別Workとして工程へ挿入する。Core #339はtarget geometryを捏造することでその欠落を隠さない。

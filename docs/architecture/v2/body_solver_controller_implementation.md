# #339 Body Solver / Continuous Controller 実装対応

Owner Issue: #339
Canonical: `docs/architecture/v2/body_solver_controller_contracts.md`
Base: `rebuild/v2-foundation@eef98e4bc873efda94a33b8f5f84d720a2cfb71d`

## 目的

#339の正本設計と現行実装を照合し、PR #497で完了した初回compile段階と、未実装のphysical controller段階を分離して完成させる。

この文書は正本設計を置換しない。実装の対応関係と進捗だけを記録する。

## 現在の実装済み範囲

PR #497で次が実装済み。

- `BodyMotionPlan` / `CanonicalBodyModel` / latest `BodyState` の整合検証
- canonical selector / chain / end-effector解決
- phase相対時間から具体区間への変換
- goalからtyped `BodySolveTask`へのcompile
- latest BodyState revisionへのrebase
- `ExecutableBodyTrajectory`生成

これは正本 Section 4.1 の初回実装境界に一致する。

## 未実装で今回完成させる範囲

正本 Sections 6–24 を実装対象とする。

1. Canonical frame / execution result
   - immutable `BodyPoseFrame`
   - `BodyMotionExecutionReport`
   - frame identity、BodyState revision、active plan/trajectory、canonical realtime channel、overlay適用証拠

2. Kinematics / safety
   - deterministic FK
   - bounded IK
   - DOF / hard joint limit enforcement
   - residualとtyped feasibility
   - finite-value validation

3. Balance / contact
   - support contactの明示
   - center-of-mass / support marginの検査
   - grounded / temporary flight / recovery phaseの区別
   - infeasible時に未検証poseをcommitしない

4. Continuous Controller
   - previous committed `BodyState`からnext frameを生成
   - Home/Neutral reset禁止
   - velocity / acceleration / jerk bound
   - trajectory continuation
   - supersede時のposition/velocity continuity
   - #340 overlayの最終合成後にhard constraint再検証

5. Single-writer state authority
   - #339だけがBodyState revisionをcommit
   - stale expected revisionを拒否
   - renderer失敗でBodyStateをrollbackしない

6. Physical observation
   - accepted Planとactual motionを分離
   - STARTED / OBSERVABLE / COMPLETEDをcontroller evidenceからのみ生成
   - INTERRUPTED / SUPERSEDED / INFEASIBLE / FAILEDをtyped化

7. Deterministic tests
   - arm reach / bilateral / look allocation
   - hard limit / unreachable target
   - current pose start / no Home reset
   - supersede continuity
   - overlay再検証
   - grounded balance / jump phase family
   - repeated solve determinism
   - accepted Plan != actual completion

## 実装順

安全境界を先に固定する。

### Stage A — Frame / State / Report contract

`BodyPoseFrame`、execution report、single-writer commit契約を追加する。後続solverが未検証状態をcommitできない形を先に作る。

### Stage B — FK / hard limit / deterministic local solver

Canonical skeletonとDOFだけを使用し、rendererやsemantic情報を入力にしない。bounded iterationとresidualを必須にする。

### Stage C — trajectory / continuity / supersede

現pose・velocityを開始点としてframeを進める。固定Home resetを作らない。

### Stage D — balance / contact / realtime overlay composition

support/CoM、airborne/landing、#340 overlay適用後の安全再検証を追加する。

### Stage E — runtime / integration evidence

Planner遅延中もcurrent trajectoryを継続し、renderer遅延をCore frame loopへ伝播させない。#341と#346へ渡せるcanonical `BodyPoseFrame`を確定する。

## 完了判定

PR #497のcompile成功だけでは#339をDoneにしない。

正本 Section 24の必須試験を満たし、実際に`BodyPoseFrame`を生成・commitでき、accepted Planとphysical execution evidenceを分離できた時点で#339を完了候補とする。

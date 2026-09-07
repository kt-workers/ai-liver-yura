# #336 D10 Physical Body Model 実装対応

Owner: #336
Canonical: `body_physical_numeric_contracts.md`
Related: `body_architecture.md`, `body_solver_controller_contracts.md`
Status: Implementation mapping

## 1. 目的

D10で#336へ追加されたphysical / numerical Authorityを、既存のCanonical Body APIを再実装せず補完する。

既存`BodyPose` / `BodyVelocity`はrenderer/FK等へ渡せるderived representationとして維持する。一方、#339のphysical control経路ではscalar DOF state、model generation、dynamic limit、geometryを明示的なAuthorityとし、必要情報が欠けるmodel/stateをfail-closedにする。

## 2. 実装するAuthority

### Scalar DOF

- `JointDofCoordinate`
- `JointDofState`
- declared axis exactly-once validation
- hard positional limitをscalar coordinateへ直接適用
- `R_rest · R_X · R_Y · R_Z`の固定順でderived quaternionへ投影
- quaternion `q` / `-q`を同一rotationとして比較可能

hard limit判定のためにderived quaternionをEuler等へ逆分解しない。

### Model generation

`CanonicalBodyModel`へ次を追加する。

- `body_model_revision`
- semantic SHA-256 `body_model_fingerprint`

fingerprintはcoordinate system、reference height、skeleton/rest transform、DOF limit/dynamic limit、segment geometry/mass/CoM fraction、end-effector、chain binding、contact、CoM reference、root dynamic limitから決定論的に生成する。revision値とfingerprint自身はdigest入力に含めない。

D10以前のテストやread-only比較でstale generationを表現できるよう、constructor自体はcaller supplied fingerprintを保持できる。ただしcurrent semanticsから再計算したfingerprintと一致しないmodelは`physical_control_contract_complete=False`となり、`require_physical_control_contract()`で必ずfail-closedする。#339のphysical pathがstale fingerprintを受理することはない。

### Dynamic / geometry contract

- `JointDynamicLimit`
- `RootDynamicLimit`
- `SegmentDefinition.center_of_mass_fraction_from_proximal`
- `EndEffectorDefinition`
- `ContactPointDefinition`
- `KinematicChain.end_effector_id`

segment mass fraction合計`1.0 ± 1e-6`はphysical-control completenessの必須条件とする。legacy/derived modelのconstructorでは既存表現を保持できるが、合計不整合のmodelを#339のphysical pathへ昇格できない。segment CoM fractionを未指定時に0.5へ推測しない。

End Effectorのforward/upは明示unit vectorで、平行を禁止する。contact/support位置をjoint名から推測しない。

## 3. Compatibility / fail-closed boundary

D10以前のUnit/Adjacentや非physical consumerを一度に破壊しないため、追加fieldは既存constructor後方へ配置し、legacy/derived表現は構築可能なまま維持する。

physical controlとして使用する場合は:

```text
CanonicalBodyModel.require_physical_control_contract()
BodyState.validate_physical_for(model)
```

を必須境界とする。

`require_physical_control_contract()`は少なくとも:

- fingerprintがcurrent model semanticsとexact一致
- segment mass fraction合計が`1.0 ± 1e-6`
- 全declared DOFにdynamic limitあり
- 全segmentにexplicit CoM fractionあり
- explicit EndEffectorDefinitionあり
- chainがend_effector_idへbind
- RootDynamicLimitあり

を要求する。

`validate_physical_for()`はさらに:

- model ID/revision/fingerprint exact一致
- DOFを持つ全jointのscalar `JointDofState`
- scalar hard limit
- derived pose/velocity skeleton整合

を要求する。

既存compatibility pathでfield欠落やstale比較fixtureを構築可能にすることは、#339がそれをphysical factとして受理してよいことを意味しない。

## 4. #339への接続

#339は本実装のstrict physical boundaryを利用し、次の後続責務を実装する。

- bounded IK
- task-space residual / feasibility
- dynamic CoM / support polygon
- velocity / acceleration / jerk validation
- trajectory timing / continuous extrema
- continuous controller / supersede continuity
- #340 overlay後のhard safety再検証
- atomic physical BodyState commit

#336ではsolver algorithm、trajectory、BodyExpression意味、renderer mappingを実装しない。

## 5. Verification

Unitで以下を固定する。

- X→Y→Z scalar DOF projection
- q/-q rotation equivalence
- hard-limit exact boundary / undeclared axis reject
- semantic fingerprint determinism / physical semantics変更時のdigest変更
- stale supplied fingerprintのphysical gate reject
- incomplete physical model fail-closed
- segment mass totalのphysical gate reject
- End Effector unit/nonparallel axis
- BodyState generation/scalar authority binding
- model generation mismatch / missing scalar state reject

full suiteではD10以前のlegacy/derived model constructionを維持しつつ、strict physical gateだけが新Authorityを要求することも回帰確認する。

## 6. 工程

本補修は新しい独立機能ではなく#336のD10 owner amendmentである。

```text
#336 D10補修
→ #337 D10 Body Expression policy補修
→ #338 D10 Motion Planning physical binding補修
→ #339 Solver / Continuous Controller残責務
```

各工程を通常mergeしてから次へ進む。

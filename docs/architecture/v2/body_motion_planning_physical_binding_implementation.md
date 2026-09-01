# #338 D10 Body Motion Planning Model Generation Binding 実装対応

Owner: #338
Canonical:
- `body_motion_planning_contracts.md`
- `body_physical_numeric_contracts.md`
Related: #336 / #337 / #339
Status: Implementation mapping

## 1. 目的

既存PR #422で実装済みのBody Motion Plannerを作り直さず、D10で#336へ追加されたCanonical Body Model generationを#338のcommitted `BodyMotionPlan`へ明示的にbindする。

#338はhigh-level motion compositionを所有する。model generationの同一性を保持するが、IK/FK・task-space geometry解決・trajectory timing・physical feasibilityは#339へ残す。

## 2. Model generation binding

Authorityが`BodyMotionPlan`をcommitするとき、captured `CanonicalBodyModel`から次をexact copyする。

```text
body_model_id
body_model_revision
body_model_fingerprint
```

Candidateは既存schemaの`body_model_id`によるmodel identity groundingを維持する。revision/fingerprintはLLM候補に決めさせず、trusted snapshotからAuthorityがPlan provenanceへ付与する。

## 3. Freshness boundary

commit時のcurrent modelがcaptured modelと異なる場合はhard staleとしてrejectする。これには少なくとも次を含む。

- body model ID変更
- body model revision変更
- semantic fingerprint変更
- fingerprint対象physical semantics変更

一方、次は既存契約どおりrebase可能であり、#338のhard staleにはしない。

- ordinary `BodyState.revision` advance
- `BodyExpressionContext.revision` advance

Planはcaptured model generationを保持したまま、#339がlatest BodyStateへrebaseして新しいtrajectory identityを生成する。

## 4. Authority境界

本補修では次を変更しない。

- Executive BODY intent binding
- selector / goal / phase / coordination schema
- deterministic path / conditional LLM path
- raw user textを意味Authorityにしない境界
- BodyExpressionをactual joint valueとしてfreezeしない境界

また次は#339責務として実装しない。

- `TARGET_REF` geometry resolver
- extentのmeter/radian metric化
- bounded IK/FK
- hard limit / balance / contact acceptance
- trajectory timing / continuous extrema
- continuous controller / BodyState commit

## 5. Verification

Unitで次を固定する。

- committed Planがexact model ID/revision/fingerprintを保持する
- same IDでもrevision変更をrejectする
- same ID/revisionでもfingerprint変更をrejectする
- BodyState / BodyExpression revision advanceは許可する
- rebaseable revision advanceでPlanのmodel generation bindingが変化しない

## 6. 工程

本補修は#338のD10 owner amendmentであり、既存#422成果の再実装ではない。

```text
#336 D10 physical model
→ #337 D10 expression policy
→ #338 model generation binding
→ #339 physical solver / continuous controller残責務
```

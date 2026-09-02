# #341 Post-Completion Activation Reconciliation

Owner: #341
Upstream change: #339 / PR #543
Revalidated base: `rebuild/v2-foundation@6add58a9290cc97e87d8983658ec71065c42dde9`
Related:
- `body_integration_post_solver_runtime_binding.md`
- `body_solver_post_completion_continuation.md`
- `body_solver_controller_contracts.md`

Status: implementation binding

## 1. 背景

#341の初回Integration runtimeは、new planning resultのphysical admissionを#339 `supersede_trajectory()`へ委譲していた。

その後#339 / PR #543で、正常`COMPLETED`後もcurrent BodyStateからbaseline/realtime frameを継続し、同じControllerへnew trajectoryを`activate_trajectory()`できる契約が追加された。

#341はこの新しい#339 Authorityを利用し、COMPLETED後のactivation semanticsを自身で再実装しない。

## 2. Admission API

accepted planning resultをcompileした後の唯一の#341 admission callは:

```text
BodyContinuousController.activate_trajectory(...)
```

とする。

#341はcurrent execution statusに応じたphysical意味を決めない。

- STARTED / OBSERVABLE: #339がold executionをSUPERSEDEDへ終端する。
- COMPLETED: #339がold COMPLETED reportを不変のterminal evidenceとして保持しnew trackerへ切り替える。
- PLANNED / INTERRUPTED / unsupported terminal state: #339がtyped rejectする。

#341は`BodySolverError`を既存のtrajectory admission rejectionへ投影するだけである。

## 3. Planning-result consume timing

physical tick前にcompleted planning resultをconsume可能なController statusを:

```text
STARTED
OBSERVABLE
COMPLETED
```

とする。

理由:
- STARTED / OBSERVABLEでは従来どおりcontinuous supersedeが必要。
- COMPLETEDではbaseline continuationが可能だが、new planが既にreadyならbaselineを余分に1frame生成せずnew trajectoryをsame Controllerへactivateする。
- PLANNEDはcurrent trajectoryがまだactual開始していないため、既存のtick-first truth境界を維持する。初回validated tick後にplanning resultをconsumeする既存挙動は変更しない。
- INTERRUPTEDは明示interrupt後の追加frame禁止という#339契約を維持し、#341が暗黙復帰させない。

## 4. Session truth

old controller reportが:

- SUPERSEDED: current active sessionを`SUPERSEDED`へ更新する。
- COMPLETED: old sessionは既に`COMPLETED`であり、そのterminal status/timestampを変更しない。

new planning submissionは通常どおり:

```text
PLANNING
→ PLAN_READY
→ first validated new trajectory frame
→ EXECUTING / COMPLETED
```

へ進む。

COMPLETED old executionをSUPERSEDEDへ書き換えない。

## 5. Baseline / overlay continuity

planning resultがpending又は失敗している場合、#341は#339 `tick()`を通常どおり呼ぶ。

current reportがCOMPLETEDなら#339 baseline pathが:
- active plan/trajectoryなし
- current pose/velocityからのphysical settling
- #340 realtime overlay
- BodyState revision continuation

を所有する。

#341はbaseline poseやHome/Neutralを生成しない。

## 6. Failure atomicity

- compile failure: current Controller / BodyStateは変更しない。
- `activate_trajectory()` rejection: current Controller / BodyStateは変更しない。
- COMPLETED baseline中のplanning failure: baseline realtimeを継続する。
- late retired plan:従来どおりadmitしない。

## 7. Required Adjacent verification

最低限:

1. initial trajectoryがCOMPLETEDした後もplanning pending中はbaseline BodyState revisionが進む。
2. COMPLETED baseline中もfresh #340 overlayがframeへ適用される。
3. COMPLETED後にnew planning resultがreadyなら、次physical tickでsame Controllerへnew trajectoryをactivateする。
4. old COMPLETED session/reportをSUPERSEDEDへ変更しない。
5. new sessionはPlan readyだけでEXECUTINGにならず、validated new frame後だけactualへ進む。
6. Controller object identityはCOMPLETED→new trajectoryで不変。
7. planning/trajectory admission failure時はCOMPLETED baseline realtimeが継続する。
8. existing STARTED/OBSERVABLE supersede、INTERRUPTED frame-block、late-result suppressionを回帰維持する。

Human Verificationはこのmachine Adjacent Gateと#346 Stick Presentation surface成立後にユーザーへ依頼する。

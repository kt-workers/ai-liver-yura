# #341 Post-#339 Body Integration Runtime Binding

Owner: #341
Base lineage: `loop/work-341`
Revalidated base: `rebuild/v2-foundation@8d39b4bcb84b809e4ac23d161ff32d5530e2473b`
Canonical:
- `body_integration_contracts.md`
- `body_solver_controller_contracts.md`
- `body_realtime_layers_contracts.md`
- `body_motion_planning_contracts.md`
- `concurrency_architecture.md`
Status: implementation binding

## 1. 再開理由

#341は2026-08-30にcompleted扱いされたが、その時点のproductionは`BodyIntegrationTrace` / `BodyExecutionSession`のread modelだけだった。

その後#339はD10 physical controller未完了として再openされ、PR #540で2026-09-01に完成した。したがって#341は、完成した#338 / #339 / #340を実際に非停止で接続するIntegration責務を再検証する。

旧`loop/work-341@db17792e600a8dfcb9c330ca86e0661a7d63260e`はread modelとUnitだけで、現行baseが完全に祖先として含む。新lineageは作らず同branchをfast-forwardして再利用する。

## 2. Authority境界

#341は次を新しく決めない。

- BODY intentの意味、priority、interruptibility: #328
- BodyMotionPlanのfreshness / commit: #338
- IK/FK、physical feasibility、trajectory continuity、BodyState mutation: #339
- gaze/blink/breath/viseme/subtle overlay値: #340
- Actual Execution Fact: #329
- renderer projection: #346

#341が所有するのは、既存Authority間のtask lifecycle、identity、cancellation、late-result suppression、read model、non-blocking publicationだけである。

## 3. Runtime lane分離

`BodyIntegrationRuntime`は1本のserial await chainを作らない。

```text
planning task (#338, async / slow)
        │
        └── completed accepted plan
                ↓
        compile_body_motion_plan (#339)
                ↓
        BodyContinuousController.supersede_trajectory (#339)

#340 BodyRealtimeRuntime (independent async lane)
        ↓
latest RealtimeOverlayBundle
        ↓
physical tick (#339, synchronous / no external await)
        ↓
BodyStateAuthority commit
        ↓
LatestBodyFrameBuffer publish
```

Planner待機中にもphysical tickと#340 laneは継続する。

## 4. Planning Port

#341は具体的LLM実装を知らず、既存#338 plannerと同じstructural contractだけを使う。

```text
BodyMotionPlanningPort.plan(
  snapshot,
  candidate_id,
  plan_id,
  created_at,
) -> await BodyMotionPlan
```

`BodyMotionPlanner` / `DeterministicBodyMotionPlanner`のどちらもこのPortへ適合する。

#341はplan candidateを生成・修正・commitしない。

## 5. Submission contract

planning submissionは最低限を明示する。

```text
BodyPlanningSubmission
- session_id
- command_id
- snapshot: BodyMotionPlanningContextSnapshot
- candidate_id
- plan_id
- trajectory_id
- trajectory_duration_s
- created_at
```

`decision_id` / `intent_id` / revisions / body_model_id / trace_idはsnapshotのtrusted値をそのまま`BodyIntegrationTrace`へ投影する。

`RevisionVector`の`goal_revision` / `attention_revision`はupstream契約どおりoptionalであり、#341 traceも`None`を真正な「そのrevision provenanceなし」として保持する。0等の架空revisionを補完してはならない。`source_context_revision`は常に必須とする。

`command_id`はSystemCommand identityとして上流から明示的に渡し、#341が捏造しない。

## 6. Supersede admission boundary

#341はpriority比較表を持たない。

新しいsubmissionを現在のplanning/trajectoryへ割り込ませるかは、上流のtrusted routingで決定済みでなければならない。Runtime APIはその事実を明示する`supersede_allowed`を受ける。

- current planner resultがpending又は未consumeであり`supersede_allowed=False`ならrejectする。
- `supersede_allowed=True`ならold owned planner taskをcancel可能ならcancelし、未consume completed taskを含めretired generationへ移して新generationへ進む。
- old plannerがcancelを無視してlate returnしてもretired generationのresultは#339へadmitしない。
- #338自身のcommit freshness gateもそのまま通る。
- accepted new planのphysical transitionは#339 `supersede_trajectory`へ委譲し、#341がjoint/velocity/accelerationを変更しない。

`supersede_allowed`は#341の判断結果ではなく、上流Authority判断の入力である。

## 7. Plan activation truth

#338がPlanを返しただけではactual executionとしない。

1. Planをcurrent `BodyStateAuthority.current`に対して#339 compilerへ渡す。
2. trajectory generation / model / policy bindingを#339に検証させる。
3. current controllerへ`supersede_trajectory`する。
4. new `BodyExecutionSession`は`PLAN_READY`とする。
5. 次のvalidated physical tickで#339 execution reportがSTARTED/OBSERVABLEになって初めてsessionを`EXECUTING`へ進める。
6. COMPLETED / INTERRUPTED / SUPERSEDED等のactual evidenceは#339 reportからのみ投影する。

Intent/Planだけをactual factへ昇格しない。

## 8. Overlay handoff

#340のpublication callbackは`publish_overlay(bundle)`へlatest値を置くだけで、physical tickやplannerをawaitしない。

physical tickはその時点のlatest bundleをsnapshotして#339 `tick(... overlay_bundle=...)`へ渡す。

- overlay未生成なら`None`を渡す。
- speech timing degradationは#340 bundle内のtyped stateを保持し、#341が架空visemeを補完しない。
- #341はoverlay channel conflictを解かない。#339 final composition gateへ渡す。

## 9. Frame publication / slow output

physical tick成功後のframeは既存`LatestBodyFrameBuffer.publish()`へ同期的に最新値だけを置く。

#341はrenderer callbackをphysical tick内でawaitしない。

slow outputは別consumerが`take_latest()`する責務とし、過去frameはbufferがcoalesceする。renderer slowdown / unavailableでCanonical BodyState commitを停止しない。

## 10. Session read model

Runtimeは既存immutable `BodyExecutionSession`をreplaceして保持する。

- submission accepted: `PLANNING`, active_plan_id=None
- #338 plan + #339 trajectory admission: `PLAN_READY`, active_plan_id=plan_id
- first validated new-controller frame: `EXECUTING`, started_at=#339 report.started_at
- actual completion: `COMPLETED`, completed_at=#339 report.completed_at
- owned planning cancellation by newer admitted submission: old session `SUPERSEDED`
- explicit shutdown before actual start: `CANCELLED`
- planner/solver/controller failure: `FAILED` / `REJECTED` with typed upstream reason text only

started/completed時刻を#341独自clockから発明しない。actual motion時刻は#339 reportを正とする。

## 11. Task ownership / shutdown

#341が所有するasync taskはplanning taskだけとする。#340 runtimeをconstructorで受けた場合はstart/close lifecycleも#341が束ねる。

`close()`:
- new submissionを禁止
- owned pending plannerをcancelしてawait
- #340 runtimeをcloseしてawait
- owned pending task countを0にする
- current already-committed BodyStateをrollbackしない

controller physical stateをshutdownでHome/Neutralへresetしない。

## 12. Failure atomicity

- planner失敗: current controller/realtimeを停止しない。
- compile/supersede失敗: current controllerとBodyStateを変更しない（#339 atomic boundaryを利用）。
- physical tick失敗: #339がBodyState / internal control timeを進めない。
- frame publication失敗: committed BodyStateをrollbackしない。

#341は他Authorityのfailureを成功へ読み替えない。

## 13. Required automated verification

最低限:

1. existing current controllerはplanner pending中もframe revisionを進める。
2. fake plannerの5s/20s相当pending中も複数physical tickが継続する。
3. #340 overlay publicationはplanner pendingと独立し、次physical tickへ渡る。
4. accepted planだけではsessionはEXECUTINGにならない。
5. first validated new trajectory frame後だけEXECUTINGになる。
6. supersede_allowed=Trueでold plannerをcancelし、old sessionをSUPERSEDEDへ終端する。
7. late old-generation planは#339へadmitされない。
8. supersede transitionはsame #339 Controllerを使用し、BodyState continuityを保持する。
9. planner failure中もcurrent physical tickは継続する。
10. `LatestBodyFrameBuffer`でslow consumer中のframeがcoalesceされ、producerをawaitしない。
11. shutdown後owned planning + realtime pending taskが0。
12. no Home/Neutral reset。
13. optional goal/attention revisionを捏造せずtraceへ保持する。

full GateはV2 Deterministic CIのRuff / strict Mypy / full pytest / compileall / diff-check / base freshnessを使用する。

## 14. Human Verification boundary

fake Integration PASS後、実Motion LLM + Stick/Live2Dでdirection / full-body coordination / continuity / realtime overlays / interruptionをHuman Verificationする。

このHuman Verification前に、見た目の良否を理由にCanonical 3D contractを弱めない。

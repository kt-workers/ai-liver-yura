# V2 Body Integration Contracts

Owner Issue: #341
Parent: #335
Related: #328 / #336 / #337 / #338 / #339 / #340 / #346 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

本書は、Executiveが確定した`BodyIntent`から、Body Expression、Motion Planning、deterministic Solver / Continuous Controller、Realtime Layerを経て、連続した`BodyPoseFrame`が生成されるまでの**結合契約**を定義する。

#341は新しい身体意味・物理・Attention・Execution Fact Authorityを作らない。各ownerの責務を接続し、identity / revision / cancellation / degraded / trace / acceptanceを統合する。

```text
Committed Executive BODY intent
        │
        ├──────────────→ #338 Body Motion Planning ─→ BodyMotionPlan ─┐
        │                                                             │
#327/#333/#355 ─→ #337 BodyExpressionContext ─────────────────────────┤
                                                                      ↓
                                                       #339 Solver / Controller
                                                                      │
#333 Focus / blink-breath policy / #348+#358 speech timing ─→ #340 ──┤
                                                                      ↓
                                                                 BodyState
                                                                      ↓
                                                               BodyPoseFrame
                                                                      ↓
                                                            #346 Avatar outputs
```

この図はdata/authority dependencyであり、毎frame全段をserial awaitする意味ではない。

---

## 2. Authority map

### #328 Executive

- BODY actionを選ぶ唯一のconscious Action Authority。
- priority / interruptibility / preconditions / required capabilitiesを確定する。
- final joint angle / trajectory / realtime overlayを決めない。

### #336 Canonical Body Model / Body State

- skeleton / DOF / anatomical side / limit / chain / current body stateのcanonical authority。
- renderer制約を受けない。

### #337 Body Expression

- current Internal State / Focus / Character Body Styleからhigh-level expression biasへ投影する。
- Pose / motion preset / joint angleを生成しない。

### #338 Motion Planner

- accepted BODY intentをsolver可能なhigh-level `BodyMotionPlan`へ変換する。
- feasibility / final physical trajectory / BodyState mutationを所有しない。

### #339 Solver / Continuous Controller

- physical feasibility、IK/FK、joint limits、balance、trajectory、continuity、BodyState mutationのAuthority。
- current trajectory continuationを所有する。

### #340 Realtime Layers

- gaze tracking、blink、breath、viseme、subtle motion等のbounded realtime overlay candidateを生成する。
- BodyStateへ直接書き込まず、#339 composition gateを通る。

### #333 Attention

- cognitive Focus / TurnのAuthority。
- Body gazeはFocusの身体表現であり、BodyからAttention stateを逆生成しない。

### #348 / #358 Speech

- Presentation commit/startとactual TTS timingを所有する。
- 未commit speechやspeculative audioでvisemeを開始しない。

### #329 Actual Execution Fact

- BODY intent / plan / pose frameだけをactual factとしない。
- #339 execution observation / #346 output observation等のtrusted evidenceを受けてActual Execution Factへ正規化する。

#341はこれらのAuthorityを上書きしない。

---

## 3. Integration identity

Body executionの関連物は最低限次でtrace可能にする。

```text
BodyIntegrationTrace
- trace_id
- decision_id
- intent_id
- command_id
- motion_plan_id?
- body_model_id
- source_context_revision
- goal_revision
- attention_revision
- body_state_revision_start
- expression_revision_start
- created_at
```

identity rule:

- BODY intent / SystemCommand / BodyMotionPlanは同じdecision/intent lineageへbindする。
- BodyModel ID mismatchはfail closed。
- planが存在しないrealtime-only updateはBODY intent lineageを捏造しない。
- Speech viseme overlayはspeech presentation identityを別に保持し、BODY intent identityへ無理に統合しない。
- renderer/output IDをCanonical Body identityにしない。

---

## 4. Integration lanes

### 4.1 Deliberate motion lane

```text
Committed BODY intent
→ #338 planning request
→ BodyMotionPlan
→ #339 plan admission / solve / controller
→ BodyState revision advance
```

Planner待機中も#339 current trajectory continuationと#340 realtime layersは動き続ける。

### 4.2 Expression lane

```text
Internal State / Attention / Character Body Style
→ #337 BodyExpressionContext
→ #339 / #340 read-only shaping input
```

Expression revisionが進んでもcurrent motionを停止しない。必要ならlatest expressionへrebindする。

### 4.3 Realtime lane

```text
Focus / low-level timing / speech timing
→ #340 RealtimeOverlayBundle
→ #339 composition gate
→ next BodyState / BodyPoseFrame
```

Realtime layerはPlanner completionを待たない。

### 4.4 Presentation lane

```text
BodyPoseFrame
→ #346 Avatar adapter(s)
```

Avatar unavailable / renderer slow / model capability不足でもCanonical BodyState更新を停止しない。

---

## 5. Body execution session

Integrationで追跡するruntime envelopeを定義する。

```text
BodyExecutionSession
- session_id
- trace: BodyIntegrationTrace
- status
- active_plan_id?
- current_body_state_revision
- started_at?
- completed_at?
- terminal_reason?
```

status:

```text
ADMITTED
PLANNING
PLAN_READY
EXECUTING
INTERRUPTING
COMPLETED
CANCELLED
SUPERSEDED
REJECTED
FAILED
```

これは新しいBodyState Authorityではなくorchestration read modelである。

`PLANNING`中にもBody realtimeは継続する。

---

## 6. Admission and freshness

BODY intentをintegrationへadmitする前に:

- committed Executive decision / BODY intent / SystemCommand identity一致
- required capability availability
- preconditions current
- source / goal / attention revision policy一致
- current BodyModelとの互換

を確認する。

#338のlong-running planning結果到着時は#338 Authorityがhard staleを検査する。

#339 plan admission時はさらに:

- current BodyModel
- plan compatibility
- constraints / capability
- plan supersede/cancel state

を確認する。

BodyState revisionはrealtimeで進み続けるため、単純な`current revision == planning revision`をhard stale条件にしない。#339がlatest current stateへsafe rebaseできる場合はrebaseする。

---

## 7. Supersede / interruption

新しいBODY intent到着時、integration coordinatorは意味判断せず、trusted priority / interruptibilityと#339 compatibility resultに従う。

可能な結果:

```text
CONTINUE_CURRENT
BLEND_NEW_PLAN
SOFT_INTERRUPT
HARD_INTERRUPT_IF_SAFE
QUEUE_BOUNDED
REJECT_NEW
```

ただし最終的なphysical transition / velocity continuityは#339が所有する。

- old in-flight plannerはcancel/supersede可能。
- late old planはcommit/admission不可。
- already-started physical effectは「なかったこと」にしない。
- interruption後Home/Neutralへ強制resetしない。
- safe recoveryはcurrent pose / velocity / expressionから#339が生成する。

---

## 8. Simultaneous composition

同時に存在し得るもの:

```text
base/current trajectory
+ deliberate arm/body motion
+ gaze
+ blink
+ breath
+ viseme
+ subtle posture correction
+ balance correction
```

#341は`one action slot = one motion`を導入しない。

composition ownership:

- semantic/body-region intention: #338 plan
- realtime overlay candidate: #340
- physical region conflict / DOF / continuity / limits: #339

同一regionにexclusive conflictがあれば#339がtyped conflict/degradationを返す。#341がfixed priority tableで特定gestureを選ばない。

---

## 9. Speech / viseme integration

Viseme admissionには最低限:

```text
speech_presentation_id
presentation_status = STARTED | PRESENTING
actual_audio_start
SpeechTimingTrack?
```

が必要。

禁止:

- CharacterUtterance生成だけで口を動かす
- PreparedSpeechCandidateだけで口を動かす
- speculative TTS artifactだけで口を動かす
- Verifier未accept candidateで口を動かす

Speech timing unavailable時:

- exact viseme timingを捏造しない
- typed degraded lip-sync modeを許可できるが、そのdegradationをtraceする
- speech以外のgaze/blink/breath/body motionを停止しない

Speech interrupted/completed時はcorresponding speech overlayを終了し、他のBody motionを継続する。

---

## 10. BodyPoseFrame publication

#339がaccepted BodyState revisionからimmutable `BodyPoseFrame`をpublicationする。

最低限:

```text
BodyPoseFrame
- frame_id
- body_model_id
- body_state_revision
- timestamp
- root_transform
- canonical_joint_pose
- canonical gaze/face/mouth channels
- active_motion_refs[]
- speech_sync_ref?
- degraded_channels[]
```

- renderer固有bone/parameterを含めない。
- frame publication失敗でBodyStateをrollbackしない。
- slow subscriberがBody frame producerを無制限blockしない。
- subscriberごとのbounded latest-frame/coalescing policyを使える。

---

## 11. Avatar / output degradation

#346等のoutputが:

- unavailable
- slow
- partially capable
- disconnected

でもBody Coreは継続する。

Canonical能力をoutput capabilityへ合わせて縮小しない。

Output側は表現不能channelをdegraded projectionとして報告できるが、BodyModel/BodyStateを変更しない。

---

## 12. Execution observation / Actual Fact boundary

`BodyIntent`、`BodyMotionPlan`、`PLAN_READY`は実行済みFactではない。

#339は実際のcontroller適用についてtyped observationを生成できる。

```text
BodyExecutionObservation
- observation_id
- decision_id / intent_id?
- motion_plan_id?
- body_state_revision
- phase: STARTED | PROGRESSED | COMPLETED | INTERRUPTED | FAILED
- applied_goal_refs[]
- observed_at
- failure_reason?
```

これは#339のphysical execution evidenceであり、#341は内容を発明しない。

#329は必要なCapability/Activity contractへ対応する場合、trusted observationをActual Execution Factへ正規化する。

Avatar表示成功はCore physical executionそのものと同義ではない。逆にAvatar切断でもCanonical BodyState上でmotionが進んでいる場合、その差をprovenanceで区別する。

---

## 13. Error / degraded categories

Integration-level closed status例:

```text
INTENT_STALE
CAPABILITY_UNAVAILABLE
PRECONDITION_FAILED
PLANNING_REJECTED
PLANNING_CANCELLED
PLAN_SUPERSEDED
SOLVER_REJECTED
CONTROLLER_FAILED
REALTIME_DEGRADED
SPEECH_TIMING_UNAVAILABLE
OUTPUT_UNAVAILABLE
OUTPUT_DEGRADED
SHUTDOWN_CANCELLED
```

Integrationはerrorを別Authorityの成功へ読み替えない。

- Planner failure → fixed motion preset fallback禁止。
- Avatar failure → Body failureへ無条件昇格しない。
- speech timing failure → full Body停止禁止。

---

## 14. Concurrency / scheduling

必須:

- Motion Planner 5s/20s delay中も#339 current trajectoryと#340 realtimeが継続。
- Character generation完了をBody planning開始条件にしない。
- Body planning完了をSpeech preparation開始条件にしない。
- TTS/Verifier delayでspeech以外Body realtime停止なし。
- renderer slowdownでCore Body loop停止なし。
- high-frequency body frameをExecutiveへ毎frame投入しない。
- background Body planningでforeground BODY intentをstarveしない。
- cancellation/shutdown後にowned pending taskを残さない。

---

## 15. Observability

最低限trace:

```text
body_intent_admitted
body_planning_queued/started/completed/cancelled/stale
body_plan_admitted/rejected/superseded
solver_started/completed/rejected
controller_motion_started/progressed/completed/interrupted
expression_revision_changed
realtime_overlay_generated/degraded
speech_viseme_started/completed/degraded
body_state_revision_committed
body_frame_published
avatar_projection_started/completed/degraded
```

metric:

- planning queue/provider latency
- plan→motion start latency
- body frame interval / jitter p50/p95/p99
- realtime overlay lateness
- interruption latency
- stale/supersede counts
- output drop/coalesce count

raw user text / Prompt / secretをtraceへ含めない。

---

## 16. Integration test topology

Fake components:

- fake Executive committed BODY intent
- fake/slow #338 Planner
- deterministic #339 Solver/Controller reference
- fake #337 expression source
- fake #333 focus source
- fake #348/#358 speech timing
- fake #346 output sink
- fake clock

必須scenario:

1. right / left / up / down / front / back / diagonal 3D orientation。
2. small angleでeyes/head主体、大角度でneck/torso contribution可能。
3. unilateral arm reach。
4. bilateral coordinated motion。
5. small/large jumpでhip/knee/ankle/root/arms協調。
6. expression + deliberate motion + gaze + breath + viseme simultaneous。
7. Planner 5s/20s delay中frame継続。
8. Character LLM delayとBody planning独立。
9. new high-priority BODY intentでold planner cancel/supersede。
10. late stale plan非適用。
11. current pose違いでtrajectoryが変わる。
12. motion終了後Home resetなし。
13. TTS timing unavailableでspeech layerだけdegraded。
14. Avatar unavailableでもBodyState継続。
15. output slowでもframe producer bounded。
16. cancellation/shutdown後pending task 0。

---

## 17. Human Verification boundary

Unit/Integration fake PASS後、実Motion LLM + Stick/Live2D等でHuman Verificationする。

Human確認はrenderer見た目だけでなく:

- direction
- full-body coordination
- continuity
- no Home reset
- spontaneous micro-motion
- gaze / blink / breath
- speech viseme
- interruption / transition

を確認する。

2D validation modelの表現限界をCanonical 3D capabilityの失敗とはみなさず、Core failureかAdapter degradationかを切り分ける。

---

## 18. #445 Design Gate

本設計が完成してもproduction implementationへ進まない。

#445全体のD1〜D9完了、cross-design audit、ユーザー確認後にのみ#341実装/Integrationを開始する。

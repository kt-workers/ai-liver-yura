# AI Liver ゆら V2 Body Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Parent Issue: #335
Root management: #317

## 1. 目的

Bodyは、ゆら自身の身体状態・身体表現・運動実現を所有するCore領域である。

BodyはLive2D、Stick Figure、3D Model等の表示機構そのものではない。

またBodyを、固定Pose/Motion Presetの再生器や「LLMが返るまで停止する身体」にしない。

目標:

- current poseから連続して動く
- 明示指示と自発表現を同じ身体へ合成する
- 360度の3D方向を扱う
- 全身関節を協調させる
- 非指示時も呼吸・瞬き・視線・微動等で生き続ける
- Speech / Game / Activityと同時並行して動く
- LLM latencyやAvatar不在でBody realtimeを停止しない

---

## 2. BodyはCoreである

BodyがCoreかどうかは「AvatarがなくてもSystemがtextで動けるか」で決めない。

Bodyは以下のCore固有責務を所有するためCoreである。

- canonical physical representation
- current body state
- embodiment / body expression semantics
- motion planning contract
- movement safety / continuity
- realtime bodily processes

Avatar / Live2D / Stick / 3D rendererはBodyPoseFrameを表示する外側Adapter / Subsystemである。

---

## 3. Bodyの構造

```text
Executive BodyIntent ───────────────┐
                                    │
Internal State / Interaction ─→ Body Expression Projection
Character Body Style ───────────────┘
                                    ↓
                           BodyExpressionContext
                                    │
Current Body State ─────────────────┼────────┐
Canonical Body Model ───────────────┘        │
                                             ↓
                                  Body Motion Planning
                                  (LLM when appropriate)
                                             ↓
                                      BodyMotionPlan
                                             ↓
                         Deterministic Motion Compiler / Solver
                         - IK / FK / Kinematics
                         - joint limits
                         - balance / CoM
                         - trajectory / timing
                         - continuity
                                             ↓
                                    Continuous Controller
                                             ↓
                              Base / Goal Motion State
                                             │
            ┌────────────────────────────────┼───────────────────┐
            ↓                                ↓                   ↓
      gaze / attention                 breath / blink       speech / viseme
            └────────────────────────────────┼───────────────────┘
                                             ↓
                                      BodyPoseFrame
                                             ↓
                                Presentation Adapter(s)
```

この図は責務依存であり、毎frame全段を直列実行する意味ではない。

---

## 4. D01 Canonical Body Model

Issue: #336

Renderer非依存の身体正本。

最低限:

```text
CanonicalBodyModel
- body_model_id
- coordinate_system
- root
- joints[]
- segment definitions[]
- normalized proportions
- end_effectors[]
- kinematic_chains[]
- center_of_mass references
- capabilities
```

### Joint

```text
CanonicalJoint
- joint_id
- parent_joint_id?
- anatomical_region
- anatomical_side: left / right / center
- local_axes
- degrees_of_freedom[]
- hard_limits
- preferred / comfortable range
- relaxed reference
```

### 原則

- anatomical left/rightを正本とする
- screen mirrorはAdapter責務
- Live2D parameter / VRM bone / Stick node名をCanonicalへ入れない
- 2Dモデルの表現限界をCanonical Body能力上限にしない
- Neutral / relaxed referenceは存在してよいが、毎Motion終了後の強制帰還Poseにはしない

---

## 5. D02 Body State

Issue: #336

現在の身体状態はBody自身が所有する。

```text
BodyState
- revision
- observed_at
- root transform
- joint pose
- joint velocities
- body velocity
- center_of_mass state
- active_motion_refs[]
- active_expression_state
- attention / gaze state
- breath state
- blink state
- speech_sync state
- current capability/degraded state
```

Body StateをCharacter / GUI / Avatarが直接書き換えない。

Rendererから観測値をfeedbackする場合もtyped feedback contractを通す。

---

## 6. D03 Body Expression Projection

Issue: #337

質問:

> 現在のゆらの状態・関係・注意・Character Styleを、身体表現としてどのような傾向にするか。

入力例:

- Emotion
- Desire / Drive / Motivation
- Energy / Arousal
- Interaction state
- Attention
- Current Activity
- Character Body Expression Style

出力はfixed poseではなく高レベル傾向。

```text
BodyExpressionContext
- posture tendency
- movement energy
- softness / sharpness
- compactness / expansiveness
- movement tempo
- gaze freedom
- head / torso expressiveness
- symmetry tendency
- coordination tendency
- breathing tendency
- idle variation tendency
- gesture density
```

禁止:

```text
joy -> HAPPY_POSE_3
anger -> ANGRY_MOTION_2
female -> GIRL_POSE
processing -> THINKING_GESTURE
```

Character固有らしさはstyle / cost / tendencyへ作用し、固定Motion選択へしない。

---

## 7. D04 Body Motion Planning

Issue: #338

質問:

> ExecutiveのBodyIntentを、現在の身体からどのような運動計画として実現するか。

open-endedな全身motion compositionにはLLMを利用可能。

ただしBody Motionを固定番号のLLM RoleとしてSystemへ縛らない。

入力:

```text
BodyMotionPlanningRequest
- body_intent
- current_body_state snapshot
- canonical_body_model view
- BodyExpressionContext
- Character Body Style
- activity / environment constraints
- priority / interruptibility
- source_context_revision
```

出力:

```text
BodyMotionPlan
- plan_id
- source_decision_id
- source_context_revision
- goals[]
- involved_chains[]
- end_effector_targets[]
- spatial targets
- movement phases[]
- relative timing
- coordination constraints
- balance requirement
- expression overlays
- priority
- interruptibility
- preconditions
- completion conditions
```

### LLMへ出させないもの

- raw user textの再解釈
- Live2D parameter
- renderer-specific bone names
- unchecked final joint angles
- every-frame pose stream
- physical success fact

LLM outputはplan candidateであり実行事実ではない。

---

## 8. Motion Intent examples

### 8.1 右手を高く上げる

```text
BodyIntent
- target = anatomical right hand
- spatial relation = above shoulder/head region
- magnitude = high
```

Planner/Solverはcurrent poseからshoulder / elbow / wrist / scapular/torso contributionを協調させる。

`right_arm_raise`という完成Pose名を正規入力にしない。

### 8.2 右を見る

方向Goalをeyes→head→neck→torsoへcomfortable rangeに応じて分配する。

小さい角度ではeyes主体、大きければhead / torsoまで使える。

### 8.3 両腕を振る

left/right chainを同時に対象化し、shoulder / elbow / wristを協調させる。

movement energy / styleによって振幅・速度・柔らかさが変わる。

### 8.4 Jump

```text
prepare
→ compression
→ extension
→ airborne
→ landing
→ continuous recovery
```

hip / knee / ankle / root / arms / torsoを協調。

大小ジャンプでpreparation depthやarm contributionが変わる。

固定Jump preset一種類にしない。

---

## 9. D05 Deterministic Motion Compiler / Solver

Issue: #339

LLMの創造的motion compositionと身体制約Authorityを分離する。

```text
BodyMotionPlan
→ structural validation
→ capability validation
→ kinematic target compilation
→ IK / FK
→ joint limit enforcement
→ balance / center of mass validation
→ trajectory generation
→ smoothing / continuity
→ executable trajectory
```

### Authority

deterministic layerが最終的に守るもの:

- joint limits
- required DOF
- kinematic feasibility
- body capability
- continuity
- balance constraints
- velocity / acceleration constraints as modeled
- invalid / unsupported motion rejection

LLMが「できる」と言ってもsolverが不成立ならExecution Factは成功にならない。

---

## 10. D06 Continuous Controller

Issue: #339

BodyはMotion Planを1回再生してNeutralへ戻るのではなく、現在状態から次状態へ連続的に合流する。

```text
current trajectory
+ new accepted plan
+ expression baseline
+ realtime overlays
→ continuous next pose
```

必要:

- transition blending
- velocity continuity
- interruption handling
- plan replacement / supersede
- partial completion
- safe recovery
- expression baselineへの滑らかな復帰

「復帰」は固定Home Poseへ戻ることではない。

---

## 11. D07 Realtime Layers

Issue: #340

LLMを待たず高頻度で更新する身体プロセス。

- gaze tracking / attention micro adjustment
- blink
- breathing
- viseme / mouth
- subtle sway / balance micro-motion
- small posture correction
- current trajectory continuation

### 不変条件

Body Motion LLMが5秒・20秒遅れてもRealtime Layerは継続する。

Bodyは「次のmotion planが来るまで完全静止」しない。

ただしrandom noiseを生物らしさとみなさない。current state / attention / activity / body dynamicsに整合した微動にする。

---

## 12. Speech / Viseme

実際にPresentation commitされたSpeechだけがviseme timelineへ入る。

```text
Committed speech
+ actual audio start
+ pronunciation / viseme timeline
→ Body speech realtime layer
```

理想:

- phoneme / mora / viseme timing
- A/I/U/E/O等のshape variation
- lip closure
- silence / pause
- interpolation

TTS timing unavailable時のみ安全なfallbackへ縮退する。

Speech preparation中の未commit candidateでは口を動かさない。

---

## 13. Executive / Character / Body relationship

```text
                 ExecutiveDecision
                   /           \
          SpeechIntent        BodyIntent
              ↓                  ↓
        Speech pipeline      Body planning
```

CharacterとBodyは兄弟Realizer。

禁止:

```text
Character text
→ Bodyがその日本語を読んでgesture決定
```

```text
Body pose
→ Characterがそのposeから発言意味を再決定
```

同じExecutive contextから並行して動ける。

---

## 14. Non-blocking Body runtime

Body realtimeは独立lane。

```text
Motion LLM running
while
  current body trajectory continues
  gaze continues
  blink continues
  breath continues
  viseme continues if speech is presenting
  new body feedback may arrive
```

Character/TTS/DB/Game AIもBody frame loopのblocking prerequisiteにしない。

### Slow Motion LLM

新しいIntentがMotion LLM処理中に届いた場合:

- higher priorityでold requestをcancel
- compatibleならcurrent request継続
- result arrival時にsource_context_revision / preconditionsを確認
- staleならdiscard

---

## 15. Multiple simultaneous motions

Bodyは「1 action slot = 1 preset」にしない。

同時に存在し得る例:

```text
base posture / locomotion
+ attention gaze
+ arm gesture
+ facial expression
+ breathing
+ viseme
+ small balance correction
```

競合はpriority / body region ownership / additive-vs-exclusive / kinematic constraints等で解決する。

具体composition policyは#339/#340で型付きに定義する。

---

## 16. Execution facts

Body execution lifecycle:

```text
requested
→ accepted
→ planned
→ started
→ observable/applied
→ completed

or
rejected / unsupported / failed / cancelled / timed_out / superseded
```

Characterが「右手上げたよ」と言える根拠は`BodyIntent`や`BodyMotionPlan`ではなく、必要なExecution Factである。

---

## 17. Avatar / Renderer boundary

Bodyのpublic output:

```text
BodyPoseFrame
- frame_id
- body_state_revision
- timestamp
- root transform
- canonical joint pose
- gaze / attention channels
- face / mouth expression channels as canonical signals
- speech sync markers
- active motion refs
```

Adapter側:

```text
BodyPoseFrame
→ Stick projection
→ Live2D projection
→ 3D / VRM projection
```

Renderer制約でCanonical Body contractを縮小しない。

利用不能parameterはAdapterでbest-effort projection / degraded mappingを行う。

---

## 18. Capability / degraded state

Body Capabilityはtypedに扱う。

例:

- has_leg_chain
- supports_root_translation
- supports_face_channels
- supports_gaze
- supports_viseme
- renderer/output available

Canonical BodyとPresentation capabilityを区別する。

Avatar不在でもBody State / motion execution semanticsを破壊しない。

---

## 19. Input boundary

Bodyへ直接入れてよいもの:

- Executive BodyIntent
- Internal State-derived expression context
- attention target
- actual speech synchronization event
- typed contact / touch percept
- body feedback / renderer capability

Bodyへ直接入れないもの:

- raw user natural language
- raw YouTube comment
- Character final textをgesture authorityとして利用
- GUI-specific commands without typed authority contract

将来Touchでは、click/drag eventとactual avatar/body hitを区別し、body regionをtyped perceptとして扱う。

---

## 20. V1から継承する教訓

維持する:

- Skeleton / DOF / Joint Limits
- current poseからのGenerative Motion
- IK / Kinematics
- anatomical left/right
- multi-joint full-body coordination
- 360度3D
- jump / bilateral / diagonal motion
- Character Body Style
- viseme同期
- no Home reset
- Stick modelを検証Adapterとして使う

改善する:

- fixed Pose axisへ縮退しない
- raw text→motion preset mappingを作らない
- Motion LLMを毎frame controlへ使わない
- Motion LLM latencyで身体を停止しない
- Character→Bodyの直列意味経路にしない
- renderer unavailableをCore failureにしない

---

## 21. Unit Acceptance

### Canonical Model

- hierarchy validation
- DOF / limit validation
- anatomical left/right
- chain / end-effector lookup
- invalid model reject

### Planner

- direction 3D
- unilateral / bilateral reach
- jump phases
- composite motion
- current pose dependent result
- unsupported capability
- stale plan

### Solver / Controller

- limit enforcement
- feasible / infeasible target
- continuity
- interruption
- supersede
- no forced Home reset

### Realtime

- slow Motion LLM中もframe継続
- blink / breath / gaze継続
- speech viseme overlay
- no uncontrolled high-frequency jitter

---

## 22. Adjacent / Integration Acceptance

Issue #341で最低限:

1. Executive BodyIntent→BodyMotionPlan→continuous BodyPoseFrame。
2. CharacterとBody planningを並列開始可能。
3. slow Motion LLM 5s/20sでもBody realtime停止なし。
4. new high-priority BodyIntentでold planningをcancel/supersede。
5. stale BodyMotionPlanを適用しない。
6. right/left/up/down/front/back/diagonalを表現。
7. eyes/head/neck/torsoの段階協調。
8. one/both arms。
9. large/small jump。
10. simultaneous expression + motion + gaze + speech viseme。
11. user-directed motion後もHome resetしない。
12. Avatar unavailableでもBody State維持。

実Motion LLM + Stick/AvatarはVerification。

---

## 23. Observability

最低限:

- body_state_revision
- motion_request_id / plan_id
- plan queued / started / completed latency
- source_context_revision
- cancel / stale / superseded
- solver rejection reason
- frame interval / jitter
- dropped frame / output failure
- realtime overlay state

実LLM latencyとBody frame stabilityを同一timelineで観測できるようにする。

---

## 24. Design Gate

- [ ] #335 parentが本書をcanonicalとして参照
- [ ] #336〜#341が本書と一致
- [ ] BodyをPluginと誤定義していない
- [ ] Motion LLMに固定Role番号を与えていない
- [ ] CharacterとBodyを兄弟Realizerとして定義
- [ ] Body realtimeがLLM待ちから独立
- [ ] current pose / continuous control / no Home resetを維持
- [ ] Canonical 3D能力を2D mockで弱めない
- [ ] slow Motion LLM acceptanceをIntegrationへ含める

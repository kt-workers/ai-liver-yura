# AI Liver ゆら V2 Body Architecture

Status: Draft / V2 Design Gate
Parent architecture: `docs/architecture/v2/system_architecture.md`
Cognitive / LLM: `docs/architecture/v2/cognitive_llm_architecture.md`
Concurrency: `docs/architecture/v2/concurrency_architecture.md`
Attention / Focus: #333
Parent Issue: #335
Root management: #317

## 1. 目的

Bodyは、ゆら自身の身体状態・身体表現・運動実現を所有するCore領域である。

BodyはLive2D、Stick Figure、3D Model等のrendererそのものではなく、固定Pose/Motion Preset再生器でもない。

目標:

- current poseから連続して動く
- 明示BodyIntentと自発表現を同じ身体へ合成
- 360度の3D方向
- 全身関節協調
- 非指示時も呼吸・瞬き・視線・微動等で生き続ける
- Speech / Game / Activityと同時並行
- Motion Planner/LLM latencyやAvatar不在でrealtime停止なし

---

## 2. BodyはCore

Body membershipを「AvatarがなくてもTextで動けるか」で決めない。

BodyはCore固有の:

- canonical physical representation
- current body state
- embodiment / expression semantics
- motion planning contract
- physical safety / continuity
- realtime bodily processes

を所有する。

Avatar / Live2D / Stick / 3D rendererは外側Presentation Subsystem/Adapter #346。

---

## 3. 構造

```text
Executive BodyIntent ───────────────┐
Internal State / Activity ─→ Body Expression Projection
#333 Attention / Focus ──────────────┤
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
                         Deterministic Compiler / Solver
                         - IK / FK / Kinematics
                         - limits / balance / CoM
                         - trajectory / timing / continuity
                                             ↓
                                    Continuous Controller
                                             │
           ┌─────────────────────────────────┼───────────────────┐
           ↓                                 ↓                   ↓
     gaze / attention                 breath / blink       speech / viseme
           └─────────────────────────────────┼───────────────────┘
                                             ↓
                                      BodyPoseFrame
                                             ↓
                                  Avatar / Renderer(s)
```

責務依存図であり毎frame全段を直列実行する意味ではない。

---

## 4. D01 Canonical Body Model — #336

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

原則:

- anatomical left/rightが正本
- screen mirrorはAdapter責務
- Live2D/VRM/Stick固有名をCanonicalへ入れない
- 2Dモデルの限界をCanonical能力上限にしない
- relaxed/neutral referenceは存在できるが強制帰還Poseにしない

---

## 5. D02 Body State — #336

```text
BodyState
- revision
- observed_at
- root transform
- joint pose / velocities
- body velocity
- center_of_mass state
- active_motion_refs[]
- active_expression_state
- attention / gaze state
- breath / blink state
- speech_sync state
- capability / degraded state
```

Body Stateの書込みAuthorityはBody。
Character / GUI / Avatarが直接mutationしない。

### 5.1 #336 の詳細契約

`CanonicalBodyModel` と `BodyState` はrenderer非依存の不変値である。各値は
JSON互換の辞書へ直列化でき、生成後に内部の配列又は対応表を書き換えてはならない。
Body以外の領域はsnapshotを読めるが、書込みは新しいrevisionを持つ
`BodyState` をBodyが生成することでのみ行う。

#### 座標、姿勢及び責務

- Canonical座標系は右手系の3次元座標である。`+X` は解剖学的右、`+Y` は上方、
  `+Z` は前方とする。単位はmeter、body modelの長さはreference heightを`1.0`とした
  正規化長で表す。
- 向きは単位quaternionの`(x, y, z, w)`で表す。位置、quaternion、速度、質量割合及び
  制限値へNaN又は無限大を入れてはならない。
- root transformだけがworld座標であり、root以外のjoint transform及びrest offsetは
  親jointに対するlocal座標である。world transformの合成、FK、IK及びrenderer座標への
  投影は後続のSolver又はAdapterの責務であり、Canonical Modelは所有しない。
- `BodyPose` はroot world transformと、全jointを一意に含むlocal transformから成る。
  `BodyVelocity` はrootのworld線形・角速度と、全jointのlocal線形・角速度を同じ識別子で
  保持する。過去poseはimmutableな時系列snapshotとしてのみ保存する。

#### Skeleton、可動域及び検証

- jointは一意なIDと、rootを一つだけ持つ親子木で構成する。自己親、存在しない親、cycle、
  複数rootはrejectする。解剖学的left/right/centerはCanonicalでありscreen mirrorではない。
- segmentは直接の親子jointを結び、正の正規化長及び質量割合を持つ。end effectorは既知の
  jointを参照し、kinematic chainはroot側から末端側へ連続する既知joint列である。
- 各DOFは`X`、`Y`又は`Z`軸を一度だけ指定する。hard rangeはmin ≤ max、comfortable
  rangeはhard range内、relaxed referenceはcomfortable range内とする。DOFのないjointは
  rotationを持たない固定jointである。
- `BodyState` は既知のbody model ID、非負revision、timezone-aware観測時刻を持つ。pose、
  velocity、historyは同じskeletonの全joint集合を持ち、historyの時刻はcurrent snapshotを
  超えてはならない。不正な入力はProvider、renderer又はsolverを呼ぶ前にrejectする。

この契約はDomainの身体同一性を固定するが、Motion Planner、Solver、Continuous Controller及び
Avatar Adapterの実装又は実行責務を先取りしない。特にrenderer bone名、画面座標、Live2D又は
Stick固有の制約を含めない。

---

## 6. D03 Body Expression Projection — #337

質問:

> 現在の内部状態・関係・活動・注意・Character Styleを身体表現の傾向へどう投影するか。

入力例:

- Emotion / Desire / Drive / Motivation
- Energy / Arousal
- Interaction / Activity
- #333 Focus / Attention
- Character Body Style #355

出力:

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
processing -> THINKING_GESTURE
```

Character textをBody expression authorityにしない。

---

## 7. D04 Body Motion Planning — #338

質問:

> Executive BodyIntentをcurrent bodyからどう運動計画として実現するか。

open-ended全身motion compositionではLLMを利用可能だが、固定Role番号・常時LLM必須にはしない。

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
- priority / interruptibility
- preconditions
- completion conditions
```

Planner/LLMへ出させない:

- raw user textの再解釈
- renderer parameter / bone名
- unchecked final joint angles
- every-frame pose stream
- physical success fact

BodyMotionPlanはcandidate/planでありActual Factではない。

---

## 8. Motion examples

### Right hand up

anatomical right hand + spatial targetを指定し、current poseからshoulder/elbow/wrist/torso contributionをSolverが協調。

`RIGHT_ARM_RAISE_PRESET`を正規契約にしない。

### Look direction

eyes→head→neck→torsoへcomfortable rangeに応じて分配。small angleではeyes主体、大きければtorsoまで利用可能。

### Bilateral gesture

left/right chainsを同時対象化し、style/energyに応じて振幅・速度・柔らかさを変える。

### Jump

```text
prepare → compression → extension → airborne → landing → recovery
```

hip/knee/ankle/root/arms/torsoを協調し、大小jumpで深さ・arm contribution等が変化する。

---

## 9. D05 Deterministic Compiler / Solver — #339

Planner implementationがLLM/軽量Planner/将来方式のどれでも、physical Authorityはdeterministic layerが所有する。

```text
BodyMotionPlan
→ structural / capability validation
→ kinematic target compilation
→ IK / FK
→ joint limits
→ balance / center of mass
→ trajectory / smoothing / continuity
→ executable trajectory
```

最終的に守る:

- joint limits / DOF
- feasibility
- body capability
- continuity
- balance
- modeled velocity/acceleration
- unsupported motion rejection

Planner/LLM出力角を無検証で適用しない。

---

## 10. D06 Continuous Controller — #339

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
- interruption
- plan replacement / supersede
- partial completion
- safe recovery
- expression baselineへの滑らかな合流

「復帰」をHome/Neutral resetと同義にしない。

Planner応答待ちでもcurrent trajectory continuationを行える。

---

## 11. D07 Realtime Layers — #340

Body Planning/LLM更新周期に依存しない高頻度process。

- gaze tracking / attention micro-adjustment
- blink
- breathing
- viseme / mouth
- subtle sway / balance micro-motion
- small posture correction
- current trajectory continuation

Motion Plannerを5s/20s遅延させてもRealtime Layerは継続する。

random noiseを生物らしさとみなさず、Body State / #333 Focus / Activity / dynamicsへ整合させる。

---

## 12. Speech / Viseme

実際にPresentation commitされたSpeechだけをvisemeへ入れる。

```text
Committed Speech
+ actual audio start
+ pronunciation / viseme timeline
→ Body speech realtime layer
```

TTS timing unavailableならtyped degradation/fallback。
未commit prepared speechでは口を動かさない。

Speech/TTS/Verifier待ちでspeech以外のBody realtimeを止めない。

---

## 13. Attention / Focus

Cognitive Focus Stateの正本は#333。

```text
#333 AttentionFocusState
→ Body Expression / gaze target projection
→ Body realtime gaze
```

Bodyの視線はFocusの身体表現であり、Bodyが「何に注意すべきか」をconsciousに決めるAuthorityではない。

視覚tracking等の低レベルrealtime adjustmentはBody側で行える。

---

## 14. Executive / Character / Body

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
Character text → Bodyが日本語を読みgesture semanticを決定
Body pose → Characterが発話意味を再決定
```

SpeechとBody planningを並列開始可能。

---

## 15. Non-blocking Body runtime

```text
Motion Planner running
while
  current trajectory continues
  gaze / blink / breath continue
  viseme continues if presenting
  balance/subtle correction continues
  new feedback may arrive
```

Character/TTS/DB/Game AIをBody frame loopのblocking prerequisiteにしない。

new BodyIntent到着時:

- priority/compatibilityに応じold planning cancel/supersede
- result到着時source_context_revision / preconditions確認
- staleならdiscard

---

## 16. Multiple simultaneous motions

```text
base posture / locomotion
+ attention gaze
+ arm gesture
+ facial expression
+ breathing
+ viseme
+ balance correction
```

競合はpriority / body region ownership / additive-vs-exclusive / kinematic constraints等で解決。

1 action slot = 1 presetにはしない。

---

## 17. Execution facts

```text
requested → accepted → planned → started → observable/applied → completed
or rejected / unsupported / failed / cancelled / timed_out / superseded
```

Characterが「右手を上げた」とclaimする根拠はBodyIntent/Planではなく必要なExecution Fact。

---

## 18. Avatar / Renderer boundary

```text
BodyPoseFrame
- frame_id
- body_state_revision
- timestamp
- root transform
- canonical joint pose
- gaze / attention channels
- face / mouth canonical signals
- speech sync markers
- active motion refs
```

```text
BodyPoseFrame
→ Stick / Live2D / 3D projection
```

renderer制約でCanonical Body contractを縮小しない。利用不能parameterはAdapterでdegraded projection。

Avatar unavailableでもBody State / semantics維持。

---

## 19. Input boundary

Bodyへ入れてよい:

- Executive BodyIntent
- Internal State-derived expression context
- #333 typed attention/focus
- actual speech sync event
- typed contact/touch percept
- body feedback / renderer capability

直接入れない:

- raw user NL / raw YouTube comment
- Character final textをgesture authorityとして使用
- GUI-specific untyped command

Touchはclick/drag情報とactual avatar/body hit、body regionを分離する。

---

## 20. V1から継承する教訓

維持:

- Skeleton / DOF / limits
- current poseからGenerative Motion
- IK/Kinematics
- anatomical L/R
- full-body coordination
- true 3D direction
- jump / bilateral / diagonal motion
- Character Body Style
- viseme
- no Home reset
- Stick model as validation adapter

改善:

- finite Pose/Motion preset axisへ縮退しない
- raw text→motion preset mappingを作らない
- Motion LLMを毎frame controllerにしない
- Planner latencyで身体停止しない
- Character→Body直列意味経路にしない
- renderer unavailableをCore failureにしない

---

## 21. Acceptance

### Unit

Canonical:
- hierarchy / DOF / limit / side / chain

Planner:
- 3D direction
- unilateral / bilateral
- jump phases
- composite motion
- current-pose dependence
- stale / unsupported

Solver/Controller:
- feasibility / limits / balance
- continuity
- interruption / supersede
- no Home reset

Realtime:
- slow Planner中frame継続
- gaze/blink/breath継続
- viseme overlay
- no uncontrolled jitter

### Integration #341

1. Executive BodyIntent→BodyMotionPlan→continuous BodyPoseFrame
2. CharacterとBody planning並列開始
3. Planner 5s/20s delayでもrealtime継続
4. high-priority new BodyIntentでold planning cancel/supersede
5. stale plan非適用
6. right/left/up/down/front/back/diagonal
7. eye/head/neck/torso協調
8. one/both arms
9. large/small jump
10. expression + motion + gaze + viseme simultaneous
11. no Home reset
12. Avatar unavailableでもBody State維持

実Motion LLM / Stick / AvatarはVerification。

---

## 22. Observability

- body_state_revision
- motion_request_id / plan_id
- plan queue/provider/planning latency
- source_context_revision
- cancel / stale / supersede
- solver reject reason
- frame interval / jitter
- output failure
- realtime overlay / focus ref

LLM/Planner latencyとBody frame stabilityを同一timelineで確認可能にする。

---

## 23. Design Reconciliation Status

- [x] #335 parentが本書をcanonicalとして参照
- [x] #336〜#341が本書と一致
- [x] BodyをPluginと誤定義していない
- [x] Motion LLMに固定Role番号を与えていない
- [x] Planner implementationとdeterministic physical Authorityを分離
- [x] CharacterとBodyを兄弟Realizerとして定義
- [x] #333 Focus/AttentionとBody gaze Authorityを分離
- [x] Body realtimeがPlanner/LLM待ちから独立
- [x] current pose / continuous control / no Home reset維持
- [x] Canonical 3D能力を2D mockで弱めない
- [x] slow Planner acceptanceを#340/#341へ含める

残るのは#317全体Design Gate確認と実装後Verificationである。

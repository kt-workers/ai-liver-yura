# Body Generative Motion 再統合設計 v1.0.0

## 対象

Issue #211。

Bodyを固定Pose/Preset再生器ではなく、Internal Directiveで決定された身体行動意図を、現在姿勢・Skeleton・関節自由度・IK/Kinematics・重心・連続制御から全身Motionへ実現する汎用Body Realizerへ移行する。

本設計はLive2D専用ではない。棒人間、Live2D、将来の3D Avatarは同じ `BodyPoseFrame` を各Adapterで投影する。

## #207共通完成目標との整合

本設計はIssue #207の「Issue間の完成目標整合ルール」に従う。

#211だけがPresetを廃止しても、別Issueが状態名→固定MotionやEmotion→固定Gestureを導入すれば完成形として矛盾する。そのためBody関連Issue全体を次の共通経路へ収束させる。

```text
Perception / Input / Memory / Internal State
→ Meaning / Appraisal
→ Emotion / Desire / Drive / Motivation
→ Interaction Intention / Internal Directive
→ Activity / Expression Intention
→ Body Realizer
   + current pose / motion history
   + Skeleton / DOF / Joint Limits
   + Character Body Expression Style
   + Attention / Speech realtime signals
→ continuous BodyPoseFrame
→ Live2D / 3D / Stick Figure Adapter
```

#211が所有するのはこのうち **Body Realizerの汎用運動能力** であり、上位意思決定、Character固有Style、TTS Viseme、GUI表示判断を重複して所有しない。

## 上位因果契約

```text
Input / Memory / Internal State
→ Appraisal
→ Internal Directive LLM
   body action intention
→ high-level BodyMotionGoal
→ Body Motion Planner
   + current pose / velocity
   + Skeleton Profile
   + Joint DOF / Limits
   + Kinematic Chains
   + balance / center of mass
   + Emotion / Activity baseline
→ BodyMotionPlan
→ IK / Kinematic / Trajectory Solver
→ Continuous Controller
→ BodyPoseFrame
→ Stick figure / Live2D / 3D Adapter
```

ユーザー入力はBodyの主意思ではない。入力意味解析は要求内容を構造化するだけで、実際に動くかどうかはInternal Directiveが決める。

## リアルタイム責務境界

Generative Motionは「毎Frame LLMへ姿勢を聞く」方式ではない。

```text
Internal Directive / Activity / Expression
  → 高レベル身体意図・BodyMotionGoal
       低頻度 / event-driven
  → Body Motion Planner
       goal受理・再計画時
  → IK / Kinematics / Trajectory Solver
       決定論的・数理的
  → Continuous Controller
       30〜60fpsの高頻度・非LLM
  → BodyPoseFrame
```

### LLMが所有するもの

- ゆらが何をする／しないかという高レベル意思
- 必要な場合の意味的な身体行動意図

### LLMが所有しないもの

- Joint角
- 毎Frame Pose
- IK反復
- 物理積分
- Balance補正
- 固定Gesture/Pose名の選択
- Avatar固有Parameter

これにより、既存の「Bodyは常時動作するリアルタイムSubsystem」という設計を維持したままPreset方式だけを置換する。

## 主従関係

現行は `BodyTrackingPose` の有限補助軸から3D `joints/root_transform/gaze_vector`を再構築している。

#211では主従を次へ変更する。

```text
Canonical 3D joint/root/gaze state = 主契約
BodyTrackingPose                  = 互換投影
```

Emotion/Activity由来の既存連続Body、呼吸、瞬き、表情、Speech layerは維持し、Generative Motionを3D関節レイヤとして合成する。

旧`BodyExternalConstraint`や`right_arm_raise`等は移行Compatibilityとして既存回帰を維持してよいが、新しい身体能力をそこへ追加しない。

## 非目標

- `right_arm_raise` 等を完成Motion/Pose名として増やす
- 入力文言ごとの `if/elif` を増やす
- CharacterLLM / Internal Directive LLMから関節角を直接出す
- 高頻度Body TickでLLMを呼ぶ
- Raw User TextをMotion Solverへ渡す
- 毎回Neutral/Home Poseへ戻ってから動く
- Emotion/Activity由来の連続表現を明示指示で置き換える
- Live2D固有Bone/ParameterをCore契約へ持ち込む
- Character固有の女の子らしい/男性らしい仕草を本Issueへ混在させる（#214）
- 発音同期口形を本Issueへ混在させる（#213）
- Body Pose Lab UI簡素化を本Issueへ混在させる（#215）
- #184のInternal Directive/Character整合性判定を作り直す
- #186 Awakeningや#189会話ProcessのAppraisalをBody内部で再実装する

## Canonical Skeleton Profile

Bodyはモデル非依存の身体知識を所有する。

### Canonical joints

```text
hips
spine
chest
neck
head
left/right_clavicle
left/right_upper_arm
left/right_lower_arm
left/right_hand
left/right_upper_leg
left/right_lower_leg
left/right_foot
```

### Joint Profile

各Jointは次を持つ。

- parent joint
- normalized local offset / segment length
- DOF（pitch / yaw / roll）
- 軸ごとのmin/max angle
- preferred / relaxed angle
- comfort weight

### Kinematic chain

最低限次を解決できる。

- left/right hand → clavicle / upper arm / lower arm / hand
- left/right foot → hips / upper leg / lower leg / foot
- head → spine / chest / neck / head
- gaze → gaze vector + head / neck / chest / spine / hips / root
- root / center of mass → root transform / hips / legs

`left/right`はゆら自身の解剖学的左右を正本とする。鏡像表示はRenderer/Avatar Adapterの責務。

## BodyMotionGoal

完成Motion名ではなく、Bodyが満たす意味目標を表す。

Goal種別:

- end-effector position
- look direction
- joint orientation
- root translation
- crouch / center-of-mass lowering
- jump / vertical displacement
- oscillation
- composite

Goalは次を保持できる。

```text
goal id
target end-effector / joint
position or direction vector
orientation
magnitude / intensity
duration
weight
components
```

### 座標系

Motion GoalはBody契約と同じright-handed / Y-upのモデル非依存3D座標系を使う。

- `direction`: 正規化された向き
- `position`: Task-spaceまたはroot translationとして意味が明示された3D位置/変位
- Avatar固有Canvas座標やLive2D Parameter値を入れない

### 任意方向

左右・上下を独立した完成軸へ落とさず、方向は3Dベクトルで扱う。

```text
up          -> (0, +1, 0)
left-up     -> normalized(-1, +1, 0)
forward-up  -> normalized(0, +1, +1)
back-right  -> normalized(+1, 0, -1)
look target -> normalized(target - head_position)
```

これにより斜め・上下・前後を含む360度方向を同じ経路で扱う。

## Motion Planning

PlannerはGoalとSkeletonから、使用するchain、phase、duration、coordinationを決める。

同じGoalでも開始Pose、現在速度、movement energy、Joint Limit、balanceにより結果が変わる。

### 腕

`右手を上へ`は `right_arm_raise=1` ではなく、right handのTask-space位置目標。

Solverは肩・肘・手首・必要なら肩帯/胸郭へ必要量を分配する。

### 視線と360度方向転換

任意3D directionを快適域に応じて段階的に分配する。

```text
small angle:
gaze → head

medium angle:
gaze → head → neck → chest

large / rear angle:
gaze → head → neck → chest → spine → hips → root yaw
```

後方を見る要求を首のJoint Limitだけで無理に満たさない。上半身の快適域を越える場合、Body全体が向きを変えることで360度の対象を視認可能にする。

視線Ray自体は全方向を向けられるが、身体姿勢はJoint Limit・Balanceを守って協調する。

### 首・腰

head / neck / chest / spine / hipsはyaw/pitch/rollを使用できる。首傾げ・腰の左右傾きも固定Poseなしで生成する。

### 脚・しゃがみ

しゃがみは単なる`body_height`変更ではなく、

- root/COM低下
- hip flexion
- knee flexion
- ankle compensation
- torso balance

を協調する。

### ジャンプ

ジャンプはアルゴリズムで次のphaseを生成する。

```text
prepare
→ propel
→ airborne
→ land
→ settle
```

小ジャンプ:

- 浅いhip/knee/ankle屈曲
- 脚主体のpropulsion
- 小さいCOM上昇
- 腕協調は小さい

大ジャンプ:

- 深いhip/knee/ankle屈曲
- 上体・腕の振りを協調
- 大きいCOM上昇
- landingで脚・腰を使い衝撃吸収

固定のjump Poseライブラリは作らない。強度、現在姿勢、movement energy、Character Style（#214で後続）等から軌道と協調量が変わる。

### 個別関節と全身協調

高レベルGoalは必要に応じて特定Joint orientationも指定できる。

- elbowだけ曲げる
- wristだけ曲げる
- neck roll
- torso roll
- knee flexion

ただしTask-space Goalでは、目的達成に必要な複数JointをSolverが自動協調させる。

## Continuous Controller

```text
Emotion/Activity baseline
+
active BodyMotionPlan(s)
+
realtime gaze / speech / blink
→ continuous BodyPoseFrame
```

Motionは現在Poseから始め、終了後にNeutralへsnap-backせずEmotion/Activity baselineへ連続合流する。

複合Goalは競合しない範囲で同時合成する。

例:

- 左上を見る + 右手を上げる
- しゃがみながら手を動かす
- 首を傾けながら腰を反対方向へ傾ける
- ジャンプ中の腕振り + 視線維持

競合するGoalはpriority/weight、Joint ownership、Balance、安全なJoint Limitを基準に調停する。後から来たGoalで全身を無条件上書きしない。

## #184 / PR #202との境界

実行事実境界は維持する。

```text
accepted
planned
started
observable/applied
completed
rejected / unsupported
```

#211ではBody側へ `BodyMotionGoal` を受付・計画・実行できる契約を追加する。PR #202統合後、明示Body ActionのMOVEが固定Pose軸ではなくこのGoalを投入するよう接続する。

#211の基盤実装自体は最新developから独立して進め、PR #202未マージ差分を直接前提にしない。

## 他Issueとの境界

- #167/#172/#178: Emotion/Interaction Intention/Body因果入力・連続Runtimeは完成済み。再実装しない
- #184/PR #202: Internal Directiveと各Realizerの意味整合性・実行事実
- #186/#196〜#199: Awakening Appraisal/Lifecycle/Expression
- #189〜#194: Conversation Process/Discourse/Expression Appraisal
- #213: 発音/Viseme同期口形
- #214: Character Profile由来のBody Expression Style
- #215: Body Pose Lab表示・検証UI

各Issueは責務を分けるが、#207の共通完成目標とPreset非依存方針を共有する。

## 実装順序

1. Canonical Skeleton全身化
2. Skeleton Profile / DOF / Limits / chain
3. BodyMotionGoal / BodyMotionPlan
4. Planner
5. IK / Kinematic / Trajectory Solver
6. Generative Motion Controller
7. StateDrivenBodyControllerへ3D関節レイヤとして合成
8. Body SubsystemへMotion Goal受付契約を追加
9. HTTP/SSEでfull joint/root/gazeが出力されることを検証
10. 全体pytest
11. 実画面Verification（表示側詳細は#215）

## 完了条件

- fixed Motion/Pose名を正規Motion生成経路に持たない
- 高頻度Body TickでLLMを呼ばない
- Skeleton ProfileがHierarchy / DOF / Limit / relaxed pose / chainを持つ
- current poseからMotionPlanを生成する
- shoulder/elbow/wristを個別・協調で動かせる
- hip/knee/ankleを個別・協調で動かせる
- head/neck/chest/spine/hipsのyaw/pitch/rollを協調できる
- gazeを3D任意方向へ向けられる
- 後方方向では必要に応じてhips/rootまで回して360度方向転換できる
- 上下・斜め・前後を同じvector goalで扱える
- crouchをCOM低下+脚関節屈曲として生成できる
- jumpをprepare→propel→airborne→landとして生成できる
- 小/大ジャンプで軌道/屈曲/腕協調量が変わる
- composite goalを同時実行できる
- 競合Goalをpriority/weight/Joint Limit/Balanceで調停できる
- Joint Limitを越えない
- 開始Poseに応じて軌道が連続する
- 固定Homeへsnap-backしない
- Emotion/Activity baselineへ連続合流する
- BodyPoseFrameの3D joint/root/gazeが正本として更新される
- Compatibility Pose軸に新能力を追加しない
- 全体pytest成功
- ユーザー実画面確認までDraft・未マージ

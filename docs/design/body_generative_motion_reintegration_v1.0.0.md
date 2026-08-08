# Body Generative Motion 再統合設計 v1.0.0

## 対象

Issue #211。

Bodyを固定Pose/Preset再生器ではなく、Internal Directiveで決定された身体行動意図を、現在姿勢・Skeleton・関節自由度・IK/Kinematics・重心・連続制御から全身Motionへ実現する汎用Body Realizerへ移行する。

本設計はLive2D専用ではない。棒人間、Live2D、将来の3D Avatarは同じ `BodyPoseFrame` を各Adapterで投影する。

## 上位因果契約

```text
Input / Memory / Internal State
→ Appraisal
→ Internal Directive LLM
   body action intention
→ Body Realizer
   + current pose / velocity
   + Skeleton Profile
   + Joint DOF / Limits
   + Kinematic Chains
   + balance / center of mass
   + Emotion / Activity baseline
→ BodyMotionGoal
→ BodyMotionPlan
→ IK / Kinematic Solver
→ Continuous Controller
→ BodyPoseFrame
→ Stick figure / Live2D / 3D Adapter
```

ユーザー入力はBodyの主意思ではない。入力意味解析は要求内容を構造化するだけで、実際に動くかどうかはInternal Directiveが決める。

## 主従関係

現行は `BodyTrackingPose` の有限補助軸から3D `joints/root_transform/gaze_vector`を再構築している。

#211では主従を次へ変更する。

```text
Canonical 3D joint/root/gaze state = 主契約
BodyTrackingPose                  = 互換投影
```

Emotion/Activity由来の既存連続Body、呼吸、瞬き、表情、Speech layerは維持し、Generative Motionを3D関節レイヤとして合成する。

## 非目標

- `right_arm_raise` 等を完成Motion/Pose名として増やす
- 入力文言ごとの `if/elif` を増やす
- CharacterLLMから関節角を直接出す
- Raw User TextをMotion Solverへ渡す
- 毎回Neutral/Home Poseへ戻ってから動く
- Emotion/Activity由来の連続表現を明示指示で置き換える
- Live2D固有Bone/ParameterをCore契約へ持ち込む
- Character固有の女の子らしい/男性らしい仕草を本Issueへ混在させる（#214）
- 発音同期口形を本Issueへ混在させる（#213）
- Body Pose Lab UI簡素化を本Issueへ混在させる（#215）

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
- gaze → gaze vector + head / neck / chest
- root / center of mass → root transform / hips

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

### 任意方向

左右・上下を独立した完成軸へ落とさず、方向は3Dベクトルで扱う。

```text
up          -> (0, +1, 0)
left-up     -> normalized(-1, +1, 0)
forward-up  -> normalized(0, +1, +1)
look target -> normalized(target - head_position)
```

これにより斜め・360度方向を同じ経路で扱う。

## Motion Planning

PlannerはGoalとSkeletonから、使用するchain、phase、duration、coordinationを決める。

同じGoalでも開始Pose、現在速度、movement energy、Joint Limit、balanceにより結果が変わる。

### 腕

`右手を上へ`は `right_arm_raise=1` ではなく、right handのTask-space位置目標。

Solverは肩・肘・手首・必要なら肩帯/胸郭へ必要量を分配する。

### 視線

任意3D directionを快適域に応じて

```text
gaze
→ head
→ neck
→ chest / torso
```

へ分配する。小さい角度差では視線中心、大きい角度差では首・胸まで使う。

### 首・腰

head / neck / torsoはyaw/pitch/rollを使用できる。首傾げ・腰の左右傾きも固定Poseなしで生成する。

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

小ジャンプは浅い屈曲+脚主体。大ジャンプは深い屈曲+腕等の協調余地+大きいCOM上昇。固定のjump Poseライブラリは作らない。

## Continuous Controller

```text
Emotion/Activity baseline
+
active BodyMotionPlan
+
realtime gaze / speech / blink
→ continuous BodyPoseFrame
```

Motionは現在Poseから始め、終了後にNeutralへsnap-backせずEmotion/Activity baselineへ連続合流する。

複合Goalは競合しない範囲で同時合成する。

例:

- 左上を見る + 右手を上げる
- しゃがみながら手を動かす
- 視線 + 全身姿勢

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

## 実装順序

1. Canonical Skeleton全身化
2. Skeleton Profile / DOF / Limits / chain
3. BodyMotionGoal / BodyMotionPlan
4. Planner
5. IK / Kinematic Solver
6. Generative Motion Controller
7. StateDrivenBodyControllerへ3D関節レイヤとして合成
8. Body SubsystemへMotion Goal受付契約を追加
9. HTTP/SSEでfull joint/root/gazeが出力されることを検証
10. 全体pytest
11. 実画面Verification（表示側詳細は#215）

## 完了条件

- fixed Motion/Pose名を正規Motion生成経路に持たない
- Skeleton ProfileがHierarchy / DOF / Limit / relaxed pose / chainを持つ
- current poseからMotionPlanを生成する
- shoulder/elbow/wristを個別・協調で動かせる
- hip/knee/ankleを個別・協調で動かせる
- head/neck/torsoのyaw/pitch/rollを協調できる
- gazeを3D任意方向へ向けられる
- 上下・斜め・任意方向を同じvector goalで扱える
- crouchをCOM低下+脚関節屈曲として生成できる
- jumpをprepare→propel→airborne→landとして生成できる
- 小/大ジャンプで軌道/屈曲量が変わる
- composite goalを同時実行できる
- Joint Limitを越えない
- 開始Poseに応じて軌道が連続する
- 固定Homeへsnap-backしない
- Emotion/Activity baselineへ連続合流する
- BodyPoseFrameの3D joint/root/gazeが正本として更新される
- 全体pytest成功
- ユーザー実画面確認までDraft・未マージ

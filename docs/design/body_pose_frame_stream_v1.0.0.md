# BodyPoseFrame Stream 設計 v1.0.0

## 1. 目的

Body Subsystemが、完成済みの待機モーションを一定間隔で再生するのではなく、内的状態・Activity・知覚候補・明示制約から連続した身体姿勢を生成する。

出力は人間のモーショントラッキングと同様に一定周期の`BodyPoseFrame`とし、棒人間、Live2D、3Dモデルで共通利用する。

## 2. 制御階層

```text
感情・欲求・緊張・関心・Activity
            +
Perceptionからの注意候補
            +
明示的な身体制約
            ↓
Procedural Body Controller
  - 現在姿勢
  - 目標姿勢
  - 速度
  - 相関した微細揺らぎ
  - Attention選択と滞在時間
            ↓
Generative Body Motion Controller
  - reach / translate / rotate
  - oscillate / circle
  - sequence / parallel / repeat
  - hold / release
  - Canonical joint IK
            ↓ 30〜60fps
BodyPoseFrame + BodyKinematicPose
            ↓
Avatar Adapter
  - Stick Model
  - Live2D
  - VRM / 3D Skeleton
```

Character LLM、Activity、ActionPlanGroupは毎フレームの値を決めない。低速の意味・制約をBodyへ渡し、Bodyが連続状態へ展開する。

完成動作名を追加するのではなく、明示的な身体要求は`BodyMotionRequest`の運動プリミティブへ変換し、Procedural Bodyが生成した現在姿勢へ重ねる。詳細は`docs/design/generative_body_motion_v1.0.0.md`を参照する。

## 3. BodyPoseFrameの汎用契約

`BodyPoseFrame`は3D対応を主契約とする。

- `coordinate_space`: 右手系・Y-up
- `root_transform`: 位置、Quaternion、Scale
- `joints`: Canonical jointごとのローカルQuaternionと任意位置
- `blend_shapes`: 目・口・表情の正規化値
- `gaze_vector`: 3D空間上の視線Ray
- `velocity`: 補助軸の毎秒変化量
- `inner_state`: フレーム生成時の内的状態Snapshot
- `attention_target_id`／`attention_dwell_ms`

棒人間とLive2D向けに、次の正規化補助投影も同じEnvelopeへ含める。

- 頭yaw／pitch／roll
- 視線X／Y
- 左右の目の開き
- 口の開き・口形
- 胴体yaw／pitch／roll・高さ
- 左右腕の上げ・内寄せ

補助投影は3D骨格の代替ではない。

Generative Motion経路では既存`BodyPoseFrame`を破壊せず、`GenerativeBodyPoseFrame`が次を追加する。

- `motion_schema_version`
- `kinematic_pose`
- `active_motion_ids`
- `held_targets`

`kinematic_pose`はモデル非依存のCanonical関節位置であり、棒人間、Live2D、3D Adapterが共通利用する。

## 4. Canonical joint

初期版の`BodyPoseFrame.joints`は上半身中心の次を提供する。

- `hips`
- `spine`
- `chest`
- `neck`
- `head`
- `left_upper_arm`
- `right_upper_arm`
- `left_lower_arm`
- `right_lower_arm`

Generative Motionの`BodyKinematicPose`は、end effectorとIKを扱うため次の位置関節を提供する。

- `pelvis`
- `spine`
- `chest`
- `neck`
- `head`
- `left_shoulder`／`right_shoulder`
- `left_elbow`／`right_elbow`
- `left_hand`／`right_hand`
- `left_hip`／`right_hip`
- `left_knee`／`right_knee`
- `left_ankle`／`right_ankle`

脚、手首、指、肩、足などは契約を壊さず追加できる。Avatar AdapterはCanonical jointを対象モデルの骨へマッピングする。

```text
Body joint_id: left_upper_arm
  ↓ VRM Adapter
J_Bip_L_UpperArm

Body joint_id: head
  ↓ 独自3D Adapter
Armature/Spine/Neck/Head
```

モデル固有の骨名をCoreやBodyへ持ち込まない。

## 5. BlendShape

初期Canonical名：

- `eye_blink_left`
- `eye_blink_right`
- `jaw_open`
- `mouth_smile`
- `mouth_frown`

3D AdapterはMorph Target／BlendShapeへ、Live2D Adapterは対応Parameterへ変換する。

## 6. 連続運動生成

### 6.1 Attention

Bodyは候補ごとに次を受ける。

- 画面正規化位置
- 顕著性
- 新規性
- 脅威度
- 現Activityとの関連度
- 安定性

候補選択は内的状態で変化する。

- 好奇心が高い：新規性の寄与を上げる
- 緊張が高い：脅威度の寄与を上げる
- 関与が高い：関連対象を長く見る
- 回避が高い：関連対象への直視を弱める

視線、頭、胴体は異なる応答速度で追従する。

### 6.2 微細動作

毎フレームの独立乱数は使用しない。前フレームと連続する平均回帰型の揺らぎを生成し、視線、首、重心、腕へ小さく投影する。

### 6.3 物理応答

各軸は現在値と速度を保持し、ばね・減衰モデルで目標へ近づく。新しい命令が来てもneutralへ戻さず、現在値を初期条件として継続する。

### 6.4 明示的な運動要求

`BodyMotionRequest`は、対象、軌道、回転、時間、順序、同時性を運動プリミティブとして表す。

- `reach`: end effectorをBodyローカル絶対位置へ近づける
- `translate`: 対象subtreeを平行移動する
- `rotate`: pivot周辺で対象subtreeを回転する
- `oscillate`: 指定vectorを振幅として往復する
- `circle`: pivot周辺の円軌道を生成する
- `sequence`: 子要求を順番に実行する
- `parallel`: 子要求を同じローカル時間で実行する
- `repeat`: 1個の子要求を反復する
- `hold`／`release`: 現在位置の保持と解除

上肢・下肢のend effector移動後は2-bone IKで肘・膝を再計算し、Frame間を平滑化する。

## 7. Avatar別Adapter

### 棒人間

通常の連続姿勢は正規化補助投影をCanvas関節へ適用する。Generative Motionを含むFrameでは`kinematic_pose`のCanonical関節位置を直接描画する。

### Live2D

補助投影とBlendShapeをLive2D Parameterへ変換する。

```text
head_yaw      -> ParamAngleX
gaze_x        -> ParamEyeBallX
eye_blink_*   -> ParamEyeLOpen / ParamEyeROpen
jaw_open      -> ParamMouthOpenY
body_height   -> ParamBodyY または独自Parameter
```

`kinematic_pose`は、モデルプロファイルが持つ可動部・Parameter組み合わせへ投影する。Live2D固有の制約や近似はAdapter側の責務とする。

### 3D / VRM

`root_transform`、`joints`、`blend_shapes`、`gaze_vector`に加え、必要に応じて`kinematic_pose`を使用する。Quaternionをモデル骨のRest Poseと座標系へ変換して適用する。

## 8. Transport

本番では`BodyPoseFrameOutputPort`の実装として、WebSocketまたは同等の双方向ストリームを使用する。

- 最新Frame優先
- 送信待ちでBody Tickを停止しない
- 遅延した中間Frameは破棄可能
- sequenceとtimestampで欠落・遅延を検出
- Avatar Runtime側で短い補間Bufferを持つ

HTTPによる`AvatarPerformancePlan`は意味的な演技要求・互換経路として残し、30〜60fpsのPose Frame送信には使用しない。

## 9. Render最小検証モジュール

`gui/yura-body-pose-lab`はCore、LLM、TTS、DBを必要としない。

```text
心境スライダー・注意候補
         ↓ HTTP設定更新
Procedural Body Controller
         +
任意BodyMotionRequest JSON
         ↓ 30fps
GenerativeBodyPoseFrame
         ↓ SSE
ブラウザ棒人間
```

確認対象：

- 心境変更による動き方の差
- 注意候補の選択と滞在
- 視線→頭→胴体の追従差
- 瞬き、呼吸、姿勢揺らぎ
- Frame間の連続性
- 3D joint／Quaternion／BlendShape payload
- reach／rotate／circle等の任意運動要求
- sequence／parallel／repeat
- hold／release
- `kinematic_pose`による関節描画

Renderサービス名は`yura-body-pose-lab`とする。

## 10. 現在の境界

実装済み：

- 汎用`BodyPoseFrame` Domain契約
- Canonical 3D骨格への投影
- 心境・注意候補駆動の連続Controller
- モデル非依存`BodyMotionRequest`／`BodyMotionPlan`
- reach／translate／rotate／oscillate／circle
- sequence／parallel／repeat
- hold／release／hold_final
- 上肢・下肢の2-bone IK
- `GenerativeBodyPoseFrame`と`BodyKinematicPose`
- Render単体ラボのMotion APIとCanonical関節描画
- `BodyPoseFrameOutputPort`

未実装：

- StructuredInputMeaningから`BodyMotionRequest`への変換
- Core本番LifecycleへのGenerative Motion Controller統合
- Motion priority／blend／authority
- WebSocket Transport
- Live2D Parameter Adapter
- VRM／3Dモデル固有Skeleton Adapter
- カメラ・マイク由来の実Perception候補
- 発話音素と口形のFrame統合
- 完全な3D IK、関節可動域、接地、衝突判定

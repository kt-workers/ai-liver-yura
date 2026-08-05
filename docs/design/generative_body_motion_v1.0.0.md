# Generative Body Motion 設計 v1.0.0

## 1. 目的

Bodyを、`右手を上げる`、`手を振る`、`ジャンプする`といった完成済みモーション名の再生装置として実装しない。

Brain／入力意味解析から受け取った対象、軌道、回転、時間、反復、順序、並行関係をモデル非依存の運動要求として表し、Bodyが現在姿勢を初期条件に毎Tickの関節位置を生成する。

この設計の目的は次のとおり。

- 名前付きプリセットを追加し続けなくても新しい動作を表現できる
- 動作の前後でホーム姿勢へ戻らず、現在姿勢から連続して遷移する
- 左右の手、脚、頭、胴体などを順次または同時に制御できる
- 棒人間、Live2D、VRM／3Dで同じ運動要求とCanonical姿勢を共有する
- Character LLMに関節角度やモデル固有Parameterを直接生成させない

## 2. 対象範囲

本設計で扱う範囲：

- `BodyMotionRequest`によるモデル非依存の運動要求
- `BodyMotionPlanner`による能力検証と実行計画化
- `GenerativeBodyMotionController`による毎Tickの関節位置生成
- `BodyKinematicPose`によるCanonical関節位置契約
- sequence／parallel／repeatによる運動合成
- hold／releaseによる姿勢保持
- 上肢・下肢の2-bone IK
- Body Pose Labからの任意JSON入力と棒人間描画

本設計の対象外：

- 日本語入力から`BodyMotionRequest`を生成する意味解析Prompt
- Internal Directive／Character応答から通常Core起動へ接続する配線
- Live2Dモデル固有Parameterへの変換
- VRM／独自3Dモデル固有Skeletonへの変換
- 衝突判定、重力、接地、関節可動域を含む完全な物理シミュレーション

## 3. 全体構成

```text
Brain / Input Meaning Interpreter
       │
       │ 対象・方向・軌道・時間・合成規則
       ▼
BodyMotionRequest
  ├─ reach / translate / rotate
  ├─ oscillate / circle
  ├─ hold / release
  └─ sequence / parallel / repeat
       ▼
BodyMotionPlanner
  - Operation形状検証
  - Canonical target／pivot検証
  - duration／targets算出
       ▼
BodyMotionPlan
       ▼
GenerativeBodyMotionController
  - Procedural Bodyの基礎姿勢
  - 複数Motionの時間評価
  - subtree変換
  - 2-bone IK
  - hold反映
  - Frame間平滑化
       ▼
GenerativeBodyPoseFrame
  ├─ 既存BodyPoseFrame
  ├─ BodyKinematicPose
  ├─ active_motion_ids
  └─ held_targets
       ▼
Stick Model / Live2D Adapter / 3D Adapter
```

`ProceduralBodyController`が生成する呼吸、視線、内的状態由来の基礎姿勢を消さず、その上に運動要求を合成する。

## 4. 座標系

運動要求とCanonical関節位置はBodyローカル正規化座標を使用する。

- `x`: 右が正
- `y`: 上が正
- `z`: 前が正
- 単位: モデル固有のメートルやピクセルではなく、体格で正規化した相対値
- `coordinate_space`: `body_local_normalized`

Avatar Adapterは、この座標を対象モデルのRest Pose、Canvas座標、Live2D Parameter、3D Skeletonへ変換する。

Core／Bodyの契約へモデル固有の骨名やParameter名を持ち込まない。

## 5. BodyMotionRequest

### 5.1 基本フィールド

| フィールド | 内容 |
|---|---|
| `operation` | 運動プリミティブまたは合成操作 |
| `target` | 操作対象となるCanonical joint／end effector |
| `vector` | 到達位置または移動量。Bodyローカル座標 |
| `pivot` | 回転・円運動の中心。省略時はPlannerの既定値を使用 |
| `axis` | `x`、`y`、`z` |
| `amount` | 回転量。ラジアン |
| `radius` | 円運動半径 |
| `direction` | `1`または`-1` |
| `timing` | 継続時間、遅延、反復、補間、終了保持 |
| `children` | sequence／parallel／repeatの子要求 |
| `motion_id` | 呼出側が指定可能な識別子 |
| `metadata` | 実行ロジックに依存しない補助情報 |

### 5.2 Operation

#### `reach`

対象end effectorをBodyローカルの絶対位置へ近づける。

主用途：

- 手を任意位置へ伸ばす
- 足先を任意位置へ動かす
- 頭を位置として移動する

`vector`は移動量ではなく到達先である。

#### `translate`

対象とその子孫関節を`vector`分だけ平行移動する。

主用途：

- 胴体を左右・上下・前後へ移動する
- 腕全体を位置関係を保ったまま移動する
- rootを移動する

#### `rotate`

`pivot`を中心に対象subtreeを指定軸で回転する。

- `amount`: ラジアン
- `direction`: 回転方向
- `axis`: `x`、`y`、`z`

`pivot`省略時は、手→肩、足首→股関節、頭→首などの既定pivotを使用する。

#### `oscillate`

`vector`を振幅として対象subtreeを往復移動する。

`timing.repetitions`は継続時間内の振動回数として扱う。

#### `circle`

対象をpivot周辺の円軌道へ移動する。

- `radius`は0より大きい必要がある
- `axis`は円の法線軸を表す
- `direction`で周回方向を切り替える
- `timing.repetitions`で周回数を指定する

#### `hold`

現在の対象位置を保持する。要求受理時点の最新Canonical姿勢から位置を取得する。

#### `release`

対象に設定された保持を解除する。

#### `sequence`

子要求を記述順に実行する。全体時間は子要求時間の合計と親の遅延で算出する。

#### `parallel`

すべての子要求を同じローカル時間で評価する。全体時間は最長の子要求時間と親の遅延で算出する。

#### `repeat`

1個の子要求を`timing.repetitions`回繰り返す。

### 5.3 Timing

| フィールド | 範囲・意味 |
|---|---|
| `duration_seconds` | 0.05〜120秒 |
| `delay_seconds` | 0〜120秒 |
| `repetitions` | 1〜64 |
| `easing` | `linear`、`smoothstep`、`ease_in_out` |
| `hold_final` | 終了位置を保持するか |

単純な運動プリミティブで`hold_final=false`の場合、Controllerは開始時に立ち上がり、中央区間で効果を維持し、終了時に下層姿勢へ戻るパルス形状を使用する。

`hold_final=true`の場合は開始姿勢から終了姿勢へ補間し、完了時の対象位置をhold状態へ保存する。

`oscillate`と`circle`は開始・終了部に窓関数を適用し、軌道が突然出現・消失しないようにする。

## 6. Planner

`BodyMotionPlanner`は完成モーション名を解決しない。

責務：

- `BodyMotionRequest`の構造検証
- 対応Canonical target／pivotの検証
- rotate／circleに必要なpivotの解決可否確認
- sequence／parallel／repeatを含む総実行時間の算出
- 参照されるtarget一覧の抽出
- `motion_id`未指定時のplan ID発行

初期対応target：

- root、pelvis、spine、chest、neck、head
- left/right shoulder、elbow、hand
- left/right hip、knee、ankle

Plannerは入力文の意味解釈、自然言語の左右判定、Avatarモデル能力への変換を担当しない。

## 7. Canonical Kinematic Pose

`BodyKinematicPose`はRendererやAvatar形式に依存しない関節位置である。

```text
BodyKinematicPose
  ├─ coordinate_space
  ├─ root_position
  └─ joints[]
       ├─ joint_id
       ├─ position {x, y, z}
       └─ confidence
```

初期骨格：

- pelvis、spine、chest、neck、head
- left/right shoulder、elbow、hand
- left/right hip、knee、ankle

`BodyKinematicProjector`は既存`BodyTrackingPose`を基礎Canonical姿勢へ投影する。これにより、内的状態、視線、呼吸、会話由来の連続姿勢とGenerative Motionを同じ関節空間で合成できる。

`GenerativeBodyPoseFrame`は既存`BodyPoseFrame`を破壊せず、次を追加する互換Envelopeである。

- `motion_schema_version`
- `kinematic_pose`
- `active_motion_ids`
- `held_targets`

## 8. Tick処理

毎Tickの処理順序：

1. `ProceduralBodyController.tick()`で基礎`BodyPoseFrame`を生成する
2. 基礎姿勢を`BodyKinematicPose`へ投影する
3. hold中の対象位置を適用する
4. 実行中Motionを開始順に評価する
5. sequence／parallel／repeatをローカル時間へ展開する
6. reach／translate／rotate／oscillate／circleを関節位置へ適用する
7. 上肢・下肢の中間関節を2-bone IKで再計算する
8. 完了Motionの`hold_final`対象を保持する
9. 指数平滑化で前Frameから連続化する
10. `GenerativeBodyPoseFrame`を出力する

`dt_seconds`は1/240秒〜0.1秒に制限し、極端な停止や時計飛びで姿勢が一度に大きく変化することを防ぐ。

## 9. IK

初期版は次の4本の2-bone chainを解く。

- left shoulder → left elbow → left hand
- right shoulder → right elbow → right hand
- left hip → left knee → left ankle
- right hip → right knee → right ankle

基礎姿勢から上側・下側ボーン長を取得し、end effector位置に対して中間関節を再計算する。

現在のIKはx-y平面で屈曲位置を求め、zはchain上の比率で補間する。完全な3次元IK、関節可動域、捻り、Pole Vector制御は後続範囲とする。

## 10. 複数Motionと競合

異なるtargetのMotionは同時に実行できる。

同一または親子関係にあるtargetへ複数Motionが重なる場合、初期版は実行中Motionを登録順に適用し、後から適用された変換がその時点の関節位置へ合成される。

初期版では次を持たない。

- Motion priority
- target単位の排他ロック
- 重み付きblend
- 意味的な競合解決

これらが必要になった段階で、`BodyMotionPlan`へpriority／blend mode／authorityを追加する。入力意味解析側で完成モーションへ戻すことはしない。

## 11. Body Pose Lab API

Body Pose LabはCore、LLM、TTS、DBなしで運動生成を検証できる。

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/motion` | 任意の`BodyMotionRequest`を送信 |
| `POST` | `/api/motion/cancel` | plan IDを指定して中断 |
| `POST` | `/api/motion/clear` | 実行中Motionを全消去 |
| `GET` | `/api/motions` | active motion／hold状態取得 |
| `GET` | `/api/frames` | SSEでPose Frameを受信 |

ブラウザは`kinematic_pose`のCanonical関節位置を直接描画する。名前付きアニメーションをブラウザ側で再生しない。

## 12. 入力意味解析との将来接続

自然言語からは、完成モーション名ではなく、実行に必要な空間関係へ分解する。

例：

```text
入力: 「右手を頭の横まで上げて、左手を前に伸ばして」

parallel
  ├─ reach target=right_hand vector=(頭右側の座標)
  └─ reach target=left_hand  vector=(前方座標)
```

```text
入力: 「右手で円を2回描いてから、その位置で止めて」

sequence
  ├─ circle target=right_hand repetitions=2
  └─ hold target=right_hand
```

入力意味解析は、左右、対象、相対位置、回数、順序、同時性、保持意図を構造化する。Bodyは発話文の解釈をやり直さない。

## 13. エラーと安全境界

- NaN／InfinityはDomain生成時に拒否する
- duration、delay、repetitions、radiusを上限付きで検証する
- 未対応target／pivotはPlannerで拒否する
- composite operationのchildren形状を厳格に検証する
- 不正MotionがBodyの基礎Tickを停止させないよう、API境界で検証エラーとして返す
- motion payloadへ会話本文、音声データ、モデル固有秘密情報を含めない

## 14. テスト方針

最低限、次を回帰対象とする。

- 任意座標へのreach
- 手のreach後の肘IK
- 円軌道の連続生成
- x／y／z軸rotate
- 左右手のparallel
- 左右脚のsequence
- repeatの時間展開
- hold／release／hold_final
- cancel／clear
- Frame間平滑化
- 既存BodyPoseFrameとの互換
- Body Pose Lab API
- `kinematic_pose`を使った棒人間描画
- Render entrypointと`server.py`直接起動

## 15. 後続課題

- StructuredInputMeaningから`BodyMotionRequest`への変換
- Internal Directive／通常Core Runtimeへの接続
- Motion priority／blend／authority
- 3D IK、Pole Vector、関節可動域、接地
- 指、手首、足先、肩甲骨などCanonical jointの拡張
- Perception座標とBodyローカル座標の変換
- Live2D Parameter Adapter
- VRM／3D Skeleton Adapter
- Viseme／音素同期との合成
- Avatar Runtimeからの完了・失敗・中断通知

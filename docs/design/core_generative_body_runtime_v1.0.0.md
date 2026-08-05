# Core Generative Body Runtime 設計 v1.0.0

## 1. 目的

身体動作の解釈、軌道生成、IK、毎フレーム姿勢計算をCore機能として実装する。

棒人形、Live2D、3DモデルはCoreが生成したPose Frameの表示・投影だけを担当する。表示側へ`右手を上げる`、`手を振る`などの完成モーション名や運動ロジックを持たせない。

## 2. 責務境界

```text
ユーザー入力
    ↓
Input Meaning Interpreter
    ↓ StructuredInputMeaning
Body Motion Meaning Normalizer（Core）
    ↓ BodyMotionRequest
Action Planner / ExecuteActionUsecase（Core）
    ↓ BodySubsystemPort.request_motion()
CoreGenerativeBodyRuntime（Core）
    ├─ Procedural Body基礎姿勢
    ├─ BodyMotionPlanner
    ├─ sequence / parallel / repeat
    ├─ reach / translate / rotate
    ├─ oscillate / circle
    ├─ hold / release
    ├─ 2-bone IK
    └─ Frame間平滑化
    ↓ GenerativeBodyPoseFrame 30〜60fps
BodyPoseFrameOutputPort
    ↓
Stick Mock / Live2D Adapter / 3D Adapter
```

### Core

Coreが所有するもの：

- 自然言語・構造化意味から運動要求への変換
- BodyMotionRequestとBodyMotionPlan
- 現在姿勢、実行中Motion、保持状態
- 時間評価とMotion合成
- IK
- Pose Frame生成
- 出力遅延からBody Tickを隔離する制御

### 棒人形モック

棒人形が所有するもの：

- `/api/body-pose-frame`でFrameを受信する
- 最新Frameを保持する
- `kinematic_pose`の関節をCanvasへ描画する
- sequence、Frame age、active motion IDを表示する

棒人形が所有しないもの：

- BodyMotionRequestの生成
- Motion名の解決
- 軌道生成
- IK
- easing、repeat、hold
- 関節位置の補正

## 3. 入力意味からMotionRequestへの変換

`normalize_body_motion_meaning()`は、身体指示を`avatar_body_action=right_hand_raise`のような完成動作IDへ変換しない。

次の情報へ分解する。

- 対象: right_hand、left_hand、head、chest、root等
- operation: reach、translate、rotate、oscillate、circle
- vector／pivot／axis／amount／radius
- duration、repetitions、easing、hold_final
- sequence／parallel

正規化後の`StructuredInputMeaning`：

```json
{
  "target": {
    "type": "body_motion",
    "id": "reach"
  },
  "entities": [
    {
      "type": "body_motion_request",
      "payload": {
        "operation": "reach",
        "target": "right_hand",
        "vector": {"x": 0.62, "y": 1.25, "z": 0.0},
        "timing": {
          "duration_seconds": 1.5,
          "repetitions": 1,
          "easing": "smoothstep",
          "hold_final": true
        }
      }
    }
  ]
}
```

入力意味LLMが完全なpayloadを生成した場合はそれを優先する。payloadがない場合は、Coreの意味正規化処理が対象、方向、時間、回数、順序を運動プリミティブへ変換する。

## 4. Action実行境界

`AvatarBodyCommandActionPlanner`は互換上の名称を維持するが、`body_actions`を生成しない。

最初のActionPlanへ`body_motion_request`を付与する。`MotionAwareExecuteActionUsecase`はAction種別に依存せずMotionRequestを先にCore Bodyへ配送し、その後、発話、表情、字幕等の通常Actionを継続する。

同じ`motion_id`はUseCase境界で重複配送しない。

## 5. Runtime

`CoreGenerativeBodyRuntime`は`LivingBodyRuntime`のActivity、内的状態、発話、表情文脈を受け取りつつ、`GenerativeBodyMotionController`を所有する。

毎Tick：

1. Activity／表情由来の内的状態を更新
2. Procedural Bodyの呼吸、視線、姿勢を生成
3. 実行中BodyMotionRequestを現在時刻で評価
4. subtree移動・回転を合成
5. 上肢・下肢の2-bone IKを計算
6. hold状態を適用
7. 関節位置を平滑化
8. GenerativeBodyPoseFrameを出力

## 6. 出力

`HttpBodyPoseFrameOutput`はQueueを1件に制限する。

- 新Frame到着時、古い未送信Frameを破棄可能
- HTTP送信待ちでCore Tickを止めない
- 表示側停止をCore会話・Body計算の停止へ昇格しない
- Frameには会話本文や音声データを含めない

## 7. 通常起動

`YURA_BODY_POSE_OUTPUT_URL`が設定される場合、Composition Rootは`CoreGenerativeBodyRuntime`を選択する。

```bash
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_POSE_OUTPUT_URL=http://127.0.0.1:8010 \
python -m app
```

Avatar Output PluginがなくてもPose Frame出力だけでCore Bodyを起動できる。

## 8. Body Pose Labの位置付け

`gui/yura-body-pose-lab`は、Domain／Controller単体検証の補助環境として残す。

本番の所有関係、通常起動、入力意味からの配送を検証する基準は`CoreGenerativeBodyRuntime`と`gui/yura-core-stick-mock`の結合経路である。

Lab内でMotionRequestを直接送れることは、Motionの所有者がLabであることを意味しない。

## 9. 現在の制約

- 自然言語Fallbackは対象・方向・時間・回数・順序の基本表現を扱う
- 完全な空間参照解決は入力意味LLMの明示payloadを優先する
- IKは初期版2-boneで、完全3D Pole Vectorや関節可動域は未実装
- Motion priority、authority、重み付きblendは未実装
- Live2D／VRM固有投影はAdapter側の後続範囲

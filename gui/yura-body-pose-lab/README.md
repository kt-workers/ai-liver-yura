# Yura Body Pose Lab

Core、LLM、TTS、DBを起動せず、`GenerativeBodyMotionController`と`BodyPoseFrame`を単体確認する補助モジュールです。

**本番のBody機能や通常起動の所有者ではありません。**

通常の開発・結合確認では、CoreがMotionRequest、軌道、IK、Pose Frameを生成し、`gui/yura-core-stick-mock`は受信したFrameを描画するだけの構成を使用します。

```text
python -m app
  ↓ GenerativeBodyPoseFrame
gui/yura-core-stick-mock
```

本Labは、Core配線から切り離してController単体の挙動や任意JSONを調べる場合だけ使用します。

## 単体起動

リポジトリルートから実行します。

```bash
python gui/yura-body-pose-lab/render_server.py
```

ブラウザ：

```text
http://127.0.0.1:8000
```

ポートを変更する場合：

```bash
PORT=8010 python gui/yura-body-pose-lab/render_server.py
```

## 単体確認内容

- 心境Presetまたは各スライダーによる運動変化
- 会話相手、左の光、右の物音からの注視対象選択
- 目が先行し、頭、胴体が異なる速度で追従すること
- 呼吸、瞬き、視線微動、姿勢変化が連続していること
- 新しい対象へ移る際にホーム姿勢へ戻らないこと
- 任意`BodyMotionRequest`のoperation、sequence、parallel、repeat、hold
- Payloadに`kinematic_pose`、`active_motion_ids`、`held_targets`が存在すること

## API

### Health

```text
GET /health
```

### 最新Frame

```text
GET /api/snapshot
```

### 連続Frame

```text
GET /api/frames
Content-Type: text/event-stream
Event: body-pose-frame
```

### Motion単体入力

```text
POST /api/motion
Content-Type: application/json
```

このAPIはControllerの単体試験用です。通常Coreでは、入力意味解析とAction Plannerを通して`BodySubsystemPort.request_motion()`へ配送します。

## Render

`render.yaml`の`yura-body-pose-lab`は単体デモ用途です。

- Build: `python -m compileall app gui/yura-body-pose-lab`
- Start: `python gui/yura-body-pose-lab/render_server.py`
- Health: `/health`
- Core用APIキー、LLM、TTS、PostgreSQLは不要

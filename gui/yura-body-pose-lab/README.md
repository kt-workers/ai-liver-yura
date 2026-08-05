# Yura Body Pose Lab

Core、LLM、TTS、DBを起動せず、心境と注意候補だけから連続`BodyPoseFrame`を生成する最小検証モジュールです。

## ローカル起動

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

## 確認内容

- 心境Presetまたは各スライダーによる運動変化
- 会話相手、左の光、右の物音からの注視対象選択
- 目が先行し、頭、胴体が異なる速度で追従すること
- 呼吸、瞬き、視線微動、姿勢変化が連続していること
- 新しい対象へ移る際にホーム姿勢へ戻らないこと
- Payloadに3D用の`root_transform`、`joints`、`blend_shapes`、`gaze_vector`が存在すること

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

### 内的状態更新

```text
POST /api/state
Content-Type: application/json
```

```json
{
  "arousal": 0.6,
  "tension": 0.2,
  "curiosity": 0.9,
  "confidence": 0.6,
  "engagement": 0.8,
  "avoidance": 0.0,
  "movement_energy": 0.6
}
```

### 注意候補更新

```text
POST /api/candidates
Content-Type: application/json
```

```json
[
  {
    "candidate_id": "viewer",
    "x": 0.0,
    "y": 0.0,
    "salience": 0.8,
    "novelty": 0.1,
    "threat": 0.0,
    "relevance": 1.0,
    "stability": 0.9
  }
]
```

## Render

`render.yaml`に`yura-body-pose-lab`を追加しています。

- Build: `python -m compileall app gui/yura-body-pose-lab`
- Start: `python gui/yura-body-pose-lab/render_server.py`
- Health: `/health`
- Core用APIキー、LLM、TTS、PostgreSQLは不要

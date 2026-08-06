# からだの水鏡 — Body Pose Lab

Emotion因果設計から生成される`BodyPoseFrame`を、モデル非依存の棒人形と診断値で確認する検証画面です。

## ローカル単体起動

```bash
python gui/yura-body-pose-lab/server.py
```

既定URL:

```text
http://127.0.0.1:8768
```

単体起動ではLab内の`StateDrivenBodyController`が30HzでFrameを生成します。

## Coreから送信して確認

Body Pose Lab側のローカル生成を停止して起動します。

```bash
YURA_BODY_POSE_LAB_LOCAL_SIMULATION=0 \
python gui/yura-body-pose-lab/server.py
```

Core側へ送信先を設定します。

```bash
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_POSE_OUTPUT_URL=http://127.0.0.1:8768 \
python -m app
```

CoreのHTTP Outputは次のEndpointへ`BodyPoseFrame`を送信します。

```text
POST /api/body-pose-frame
```

## Render起動

```bash
python gui/yura-body-pose-lab/render_server.py
```

`PORT`が設定されている場合はその値を使用し、Hostは既定で`0.0.0.0`です。

## 設定

| 環境変数 | 既定値 | 用途 |
| --- | ---: | --- |
| `YURA_BODY_POSE_LAB_HOST` | `127.0.0.1` | bind Host |
| `YURA_BODY_POSE_LAB_PORT` | `8768` | bind Port。未指定時は`PORT`も参照 |
| `YURA_BODY_POSE_LAB_TICK_HZ` | `30` | ローカルControllerのTick周波数 |
| `YURA_BODY_POSE_LAB_RANDOM_SEED` | `23` | 再現可能な微動・注意選択Seed |
| `YURA_BODY_POSE_LAB_LOCAL_SIMULATION` | `1` | Lab内Controllerを動かすか |
| `YURA_BODY_POSE_LAB_MAX_SUBSCRIBERS` | `32` | SSE同時接続上限 |
| `YURA_BODY_POSE_LAB_MAX_JSON_BYTES` | `524288` | JSON Request上限 |

## API

- `GET /health`
- `GET /api/snapshot`
- `GET /api/frames` — SSE
- `POST /api/body-pose-frame`
- `POST /api/emotion`
- `POST /api/activity-context`
- `POST /api/attention-candidates`
- `POST /api/external-constraint`
- `DELETE /api/external-constraint`
- `POST /api/speech`
- `POST /api/blink`

## 責務境界

Python Server:

```text
Frame Hub
Application Service
Payload Decoder
API Controller
SSE Stream
Static Files
HTTP Server
Composition Root
Tick Loop
```

Browser:

```text
State / Presets
API Client
Frame Stream
Candidate Controls
Stick Figure Renderer
Metrics / Payload
Main Composition
```

旧実装の巨大`server.py`・`app.js`やController monkeypatchは使用していません。

## 注意

- Labは検証用Adapter／GUIです。Emotion、Motivation、Activity選択を決定しません。
- 身体操作は固定Motion名ではなく、正規化Pose軸への一時制約として入力します。
- SSEは遅いクライアントに対してlatest-frame-winsで配信します。
- ユーザー発話本文、Character Prompt、Memoryは診断Snapshotへ保存しません。

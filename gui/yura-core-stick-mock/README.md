# Yura Core Stick Mock

Coreが生成した`BodyPoseFrame`を受信し、Live2Dの代わりに棒人間へ反映する開発用モックです。

このモック自身は心境、注意、身体動作を生成しません。表示内容はCoreから受信したFrameだけです。

## 構成

```text
Core Activity / Character / Internal State
                 ↓
        CoreBodyPoseRuntime
                 ↓ 30fps / latest-frame-wins
        BodyPoseFrame HTTP Output
                 ↓
       Yura Core Stick Mock
                 ↓ SSE
             Browser Canvas
```

## 起動

### 1. 棒人間モック

リポジトリルートで実行します。

```bash
python gui/yura-core-stick-mock/server.py
```

ブラウザ:

```text
http://127.0.0.1:8010
```

### 2. Core

別ターミナルで起動します。

```bash
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_POSE_OUTPUT_URL=http://127.0.0.1:8010 \
python -m app
```

既存Avatar Runtimeも同時利用する場合は、通常のAvatar Output設定も併用できます。Avatar Outputがなくても`YURA_BODY_POSE_OUTPUT_URL`が設定されていればBody Runtimeは起動します。

## 環境変数

| 変数 | 既定値 | 説明 |
|---|---:|---|
| `YURA_BODY_POSE_OUTPUT_URL` | 未設定 | CoreがBodyPoseFrameを送るモックURL |
| `YURA_BODY_POSE_OUTPUT_TIMEOUT_SECONDS` | `1.0` | 1回のHTTP送信タイムアウト |
| `YURA_BODY_TICK_HZ` | `30.0` | Body Controller更新頻度 |
| `HOST` | `127.0.0.1` | モックサーバーの待受Host |
| `PORT` | `8010` | モックサーバーの待受Port |

## API

- `POST /api/body-pose-frame`: Coreから最新Frameを受信
- `GET /api/frames`: ブラウザ向けSSE
- `GET /api/snapshot`: 最新Frame
- `GET /health`: 接続状態とFrame age

## 通信方針

Core側の送信Queueは1件です。ネットワーク送信が遅れた場合、古い未送信Frameを破棄して最新Frameを優先します。Bodyの30fps Tick LoopをHTTP待ちで停止させません。

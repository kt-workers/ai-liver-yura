# Yura Core Stick Mock

Coreが生成した`BodyPoseFrame`を描画するだけの検証用モックです。

## 責務

描画するもの:

- 表情BlendShape
- 目・瞬き
- 視線
- 口形
- 頭・胴体・腕・脚
- 呼吸と姿勢変化

実行しないもの:

- 自然言語の解釈
- 感情や表情の決定
- Activity判断
- Motion計画
- IK
- プリセット選択

## 起動

ターミナル1:

```bash
.venv/bin/python gui/yura-core-stick-mock/server.py
```

ブラウザ:

```text
http://127.0.0.1:8010
```

ターミナル2:

```bash
YURA_WEB_CONVERSATION_ENABLED=0 \
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_POSE_OUTPUT_URL=http://127.0.0.1:8010 \
YURA_BODY_TICK_HZ=30 \
.venv/bin/python -m app
```

通常の会話入力を行い、Character応答に応じた表情、視線、姿勢、腕の動き、発話口形が
同じ棒人形へ重なって現れることを確認します。「手を上げて」等の身体命令は本検証の主目的
ではありません。

## API

- `GET /health`
- `GET /api/state`
- `GET /api/events`
- `POST /api/body-pose-frame`

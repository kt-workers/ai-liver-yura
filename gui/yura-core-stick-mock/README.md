# Yura Core Stick Mock

Coreが生成した`GenerativeBodyPoseFrame`を表示するだけの検証用モックです。

このモジュールは次を行いません。

- 自然言語の解釈
- MotionRequestの生成
- 軌道、sequence、parallel、repeatの処理
- IK
- 関節位置の平滑化
- 名前付きモーションの再生

これらはすべてCoreの`CoreGenerativeBodyRuntime`が担当します。

## 起動

### 1. 棒人形モック

リポジトリルートで実行します。

```bash
.venv/bin/python gui/yura-core-stick-mock/server.py
```

ブラウザ：

```text
http://127.0.0.1:8010
```

### 2. Core

別ターミナルで実行します。

```bash
YURA_WEB_CONVERSATION_ENABLED=0 \
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_POSE_OUTPUT_URL=http://127.0.0.1:8010 \
.venv/bin/python -m app
```

Avatar Output Pluginは必須ではありません。`YURA_BODY_POSE_OUTPUT_URL`が設定されていれば、Core Body Runtimeだけを起動できます。

## 確認例

Coreの入力へ次のような指示を送ります。

```text
右手を上に1.5秒かけて伸ばして、そのまま止めて
右手を円を描くように2回動かして
両手を左右に振って
右手を前に伸ばしてから、左手を上げて
```

入力意味解析後、Core内では次の経路で処理されます。

```text
StructuredInputMeaning
        ↓
BodyMotionRequest
        ↓
BodyMotionPlanner
        ↓
CoreGenerativeBodyRuntime
        ↓ 30fps
GenerativeBodyPoseFrame
        ↓ HTTP
Stick Mock
```

## ポート変更

```bash
PORT=8020 .venv/bin/python gui/yura-core-stick-mock/server.py
```

Core側も同じURLへ変更します。

```bash
YURA_BODY_POSE_OUTPUT_URL=http://127.0.0.1:8020
```

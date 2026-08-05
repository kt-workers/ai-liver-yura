# Core Generative Body ローカル確認

## 1. ブランチ

```bash
git fetch origin
git switch feature/core-generative-body-motion
git pull
```

## 2. 棒人形モック

```bash
.venv/bin/python gui/yura-core-stick-mock/server.py
```

```text
http://127.0.0.1:8010
```

このプロセスはPose Frameを描画するだけです。

## 3. Core

別ターミナルで実行します。

```bash
YURA_WEB_CONVERSATION_ENABLED=0 \
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_POSE_OUTPUT_URL=http://127.0.0.1:8010 \
YURA_BODY_TICK_HZ=30 \
.venv/bin/python -m app
```

## 4. 入力例

```text
右手を上に1.5秒かけて伸ばして、そのまま止めて
左手を左右に3回振って
右手を円を描くように2回動かして
両手を上に伸ばして
右手を前に伸ばしてから、左手を上に伸ばして
胴体を35度ひねって
```

## 5. 確認ポイント

- 入力意味のtarget.typeが`body_motion`になる
- entitiesへ`body_motion_request`が追加される
- Coreログに`body_motion_submitted`が記録される
- 棒人形へ`GenerativeBodyPoseFrame`が届く
- `active_motion_ids`が実行中だけ表示される
- `hold_final`では`held_targets`へ対象が残る
- 棒人形を停止してもCore会話・Body Tickが継続する

## 6. Body Pose Labとの違い

`gui/yura-body-pose-lab`はController単体確認用です。通常起動と入力意味からの結合確認には使用しません。

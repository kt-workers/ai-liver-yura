# Body Runtime・棒人間 ローカル結合確認

## 目的

通常のCore起動経路から、常駐Body Runtimeが生成した重複Track型
`AvatarPerformancePlan`を、検証専用の棒人間Web Runtimeへ送って確認する。

検証用`test/*`ブランチはdevelopへ取り込まず、Coreと棒人間を別worktreeで起動する。

## 実行時の構成

```text
外界入力
  ├─ テキスト / STT結果 ───────────────→ 意味解析・内部指令
  ├─ カメラ / 音声の意味的観測 ───────→ 意味解析・内部指令
  └─ 対象位置 / 音源方向など低遅延観測 → Body Perception（後続実装）

意味解析・内部指令
  ↓ Activityの作成・更新
Activity / ActionPlanGroup
  ├─ Character LLM（必要時）
  ├─ TTS生成Action
  ├─ BodyActivityContext
  └─ BodyExpressionRequest
          ↓
Body Runtime（既定30fps）
  ├─ Activity基礎姿勢
  ├─ 表情・注意・首・胴体・左右腕
  ├─ breathing
  └─ micro_sway
          ↓
AvatarPerformancePlan
          ↓ HTTP
棒人間Web Runtime
          ↓ requestAnimationFrame
Canvas描画
```

ActivityはLLMと同列の変換器ではない。継続目的とTurnごとのActionを束ねる既存の
ドメイン概念・実行管理単位として維持する。

Character LLMはTTSへ直接送信しない。Character応答からActionPlannerがSPEAK Actionを
作り、Action実行層がTTSを呼ぶ。生成済み音声の長さと発話情報はBodyの再生時計へ登録する。

## 1. 検証用worktreeを作る

リポジトリの親ディレクトリで実行する。

```bash
git fetch origin

git worktree add --detach ../ai-liver-yura-body \
  origin/feature/avatar-performance-plan

git worktree add --detach ../ai-liver-yura-stick \
  origin/test/avatar-runtime-render-stick-model
```

既に同名ディレクトリがある場合は、別の空ディレクトリ名を指定する。

## 2. 棒人間Web Runtimeを起動する

ターミナルA：

```bash
cd ../ai-liver-yura-stick
python gui/yura-avatar-runtime-lab/server.py
```

ブラウザで次を開く。

```text
http://127.0.0.1:8000
```

別ポートを使う場合：

```bash
PORT=8780 python gui/yura-avatar-runtime-lab/server.py
```

## 3. CoreとBody Runtimeを起動する

ターミナルB：

```bash
cd ../ai-liver-yura-body

YURA_WEB_CONVERSATION_ENABLED=0 \
YURA_AVATAR_OUTPUT_ENABLED=1 \
YURA_AVATAR_RUNTIME_URL=http://127.0.0.1:8000 \
YURA_AVATAR_OUTPUT_TIMEOUT_SECONDS=3.0 \
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_TICK_HZ=30 \
python -m app
```

棒人間を8780番で起動した場合は、URLも`http://127.0.0.1:8780`へ変更する。

## 4. 確認項目

### 起動直後

Character LLMやユーザー入力がなくても、Body Runtimeから次が定期的に届く。

- `breathing`
- `micro_sway`

棒人間画面の受信履歴に`body-autonomous`由来のPerformanceが表示される。

### 会話時

Coreのコンソールへ通常どおり文章を入力する。

```text
それは嫌？
```

応答内容に応じて、Bodyへ次が流れる。

- Activity由来の注意対象・姿勢傾向
- Character応答由来の表情
- 肯定／否定、接近／後退、緊張、開放性などの意味軸
- 発話中の強調情報

Bodyは意味軸を、表情・注意・首・胴体・左右腕の重複Trackへ展開する。

### 障害時

棒人間Web Runtimeを停止しても、Core会話とActivityは継続する。Body Runtimeは送信失敗を
診断状態へ記録し、次のTickを止めない。

## 5. 確認用設定

| 環境変数 | 既定値 | 用途 |
|---|---:|---|
| `YURA_BODY_RUNTIME_ENABLED` | Avatar有効時に有効 | Body Runtimeの起動 |
| `YURA_BODY_TICK_HZ` | `30` | Body状態更新周期 |
| `YURA_BODY_AUTONOMOUS_INTERVAL_MS` | `2400` | 自律Track送信間隔 |
| `YURA_BODY_BASELINE_REFRESH_MS` | `30000` | Activity基礎姿勢の再送間隔 |
| `YURA_BODY_EXPRESSION_QUEUE_LIMIT` | `32` | 表現要求Queue上限 |
| `YURA_BODY_MAX_EXPRESSIONS_PER_TICK` | `4` | 1 Tickの表現処理上限 |

## 現在の検証範囲

確認できるもの：

- 通常Application lifecycleでのBody開始・停止
- Activity Contextの配送
- Character表現Intentの配送
- TTS準備済み音声時間のBody登録
- 自律動作
- 重複TrackのHTTP送信
- 棒人間での連続合成

まだ対象外のもの：

- カメラ・マイクのPerception実装
- 音源方向と対象位置のBodyへの低遅延入力
- 実音声再生をBodyが所有する共通時計
- 音素・Visemeによる口同期
- Live2D / VTube Studio固有Parameter変換
- Body Runtimeの独立プロセス化

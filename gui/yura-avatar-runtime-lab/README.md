# Yura Avatar Runtime Lab

Live2DモデルおよびVTube Studioへ接続する前に、Coreから出力された高レベルな表情・ジェスチャー・視線命令をWeb上で確認するための最小検証Runtimeです。

Canvas 2Dの棒人間を使用するため、Live2D SDK、画像素材、GPUは不要です。

## 構成

```text
Character LLM
  ↓ CharacterResponse / ReactionPlan
ActionPlanner
  ↓ change_expression / move
Avatar Output Plugin
  ↓ HTTP POST /api/avatar/actions
Avatar Runtime Lab
  ↓ SSE /api/avatar/events
Browser Canvas stick model
```

## ローカル起動

```bash
python gui/yura-avatar-runtime-lab/server.py
```

既定URL：

```text
http://127.0.0.1:8780
```

ポートを変更する場合：

```bash
PORT=8781 python gui/yura-avatar-runtime-lab/server.py
```

## Coreから接続

別ターミナルでCoreを次の環境変数付きで起動します。

```bash
YURA_AVATAR_OUTPUT_ENABLED=1 \
YURA_AVATAR_RUNTIME_URL=http://127.0.0.1:8780 \
YURA_AVATAR_OUTPUT_TIMEOUT_SECONDS=3.0 \
python -m app
```

Character LLMが返した `expression` は `change_expression` Actionとして、`gesture` は `move` ActionとしてLabへ送信されます。

## モバイルでの手動操作

画面幅が1040px以下の場合、Manual Probeの先頭に小型のLive Previewを表示します。

- 操作パネルをスクロールしている間、プレビューは画面上端へ追従します。
- メインCanvasの描画済みフレームを転写するため、表情・視線・ジェスチャーの表示差は発生しません。
- 現在の演技名と受信シーケンスも同時に表示します。
- 大きなメインCanvasと状態一覧は従来どおり残します。

これにより、スマートフォンで表情・ジェスチャー・視線ボタンを操作しながら、動作結果を同時に確認できます。

## 手動疎通確認

表情：

```bash
curl -X POST http://127.0.0.1:8780/api/avatar/actions \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 1,
    "type": "avatar.action",
    "action": "expression",
    "name": "happy",
    "intensity": 1.0
  }'
```

ジェスチャー：

```bash
curl -X POST http://127.0.0.1:8780/api/avatar/actions \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 1,
    "type": "avatar.action",
    "action": "gesture",
    "name": "wave",
    "intensity": 1.0
  }'
```

視線：

```bash
curl -X POST http://127.0.0.1:8780/api/avatar/actions \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 1,
    "type": "avatar.action",
    "action": "gaze",
    "target": "right",
    "behavior": "maintain",
    "intensity": 0.8
  }'
```

## API

| Method | Path | 用途 |
|---|---|---|
| GET | `/health` | Renderヘルスチェック |
| GET | `/api/avatar/state` | 現在状態と履歴 |
| GET | `/api/avatar/events` | ブラウザ向けSSE |
| POST | `/api/avatar/actions` | Avatar Action受信 |

## Render

`render.yaml` に `yura-avatar-runtime-lab` を追加しています。

- Branch: `test/avatar-runtime-render-stick-model`
- Build: `python -m compileall app gui/yura-avatar-runtime-lab`
- Start: `python gui/yura-avatar-runtime-lab/server.py`
- Health: `/health`

Renderへデプロイ後、ローカルCore側の `YURA_AVATAR_RUNTIME_URL` に発行されたHTTPS URLを設定します。

```bash
YURA_AVATAR_OUTPUT_ENABLED=1 \
YURA_AVATAR_RUNTIME_URL=https://<render-service>.onrender.com \
python -m app
```

## 対応値

### 表情

- `neutral`
- `happy`
- `sad`
- `surprised`
- `angry`
- `curious`

未知の名前も契約上は受信できますが、描画はneutral相当になります。

### ジェスチャー

- `small_nod`
- `head_tilt`
- `wave`
- `lean_forward`
- `bounce`

未知の名前も履歴には残りますが、固有アニメーションは実行されません。

### 視線

代表値：

- `viewer`
- `left`
- `right`
- `up`
- `down`
- `away`
- `neutral`

## MVP上の制約

- 通信は暫定HTTPであり、完了通知・割込み・双方向状態同期は未実装です。
- Renderの公開Action APIには認証がありません。これは動作検証専用です。
- Render無料サービスがスリープしている場合、初回Actionがタイムアウトすることがあります。
- Pluginは失敗時にUnavailableへ縮退し、Core処理は継続します。自動再接続は次段階です。
- 棒人間Runtimeは検証ブランチ専用であり、本番Live2D Backendへ統合しません。

## 次段階

1. Foundationを正式なRuntime Plugin Setupへ統合する
2. AvatarPerformancePlanを導入する
3. HTTPからWebSocketへ移行する
4. 完了・中断・失敗通知と再接続を実装する
5. VTube Studio Backendとモデルプロファイルを追加する
6. サンプルLive2Dモデルで表情・視線・モーションを検証する

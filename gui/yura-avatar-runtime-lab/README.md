# Yura Avatar Runtime Lab

Live2DモデルおよびVTube Studioへ接続する前に、Coreから出力された高レベルな表情・ジェスチャー・視線命令と `AvatarPerformancePlan` をWeb上で確認するための検証Runtimeです。

Canvas 2Dの棒人間を使用するため、Live2D SDK、画像素材、GPUは不要です。このコードは `test/avatar-runtime-render-stick-model` ブランチだけで管理し、developへは取り込みません。

## 構成

```text
Character LLM
  ↓ CharacterResponse / ReactionPlan
AvatarPerformancePlanner
  ↓ AvatarPerformancePlan
Avatar Output Plugin
  ↓ POST /api/avatar/performances
Avatar Runtime Lab
  ↓ SSE /api/avatar/events
Browser Canvas stick model
```

個別Actionの後方互換経路も維持します。

```text
Avatar Output Plugin
  ↓ POST /api/avatar/actions
expression / gesture / gaze
```

## 対応API

| Method | Path | 用途 |
|---|---|---|
| GET | `/health` | Renderヘルスチェック |
| GET | `/api/avatar/state` | 現在状態、最終Action、最終Performance、履歴 |
| GET | `/api/avatar/events` | ブラウザ向けSSE |
| POST | `/api/avatar/actions` | 後方互換の個別Avatar Action受信 |
| POST | `/api/avatar/performances` | 時間軸付きAvatar Performance受信 |

`/health` の `performance_api` が `true` の場合、Performance受信APIを利用できます。

## Performance契約

`POST /api/avatar/performances` は次のDTOを受信します。

```json
{
  "schema_version": 1,
  "type": "avatar.performance.submit",
  "performance_id": "performance-1",
  "source_activity_id": "activity-1",
  "output_unit_id": "output-1",
  "priority": 500,
  "interrupt_policy": "replace_lower_priority",
  "return_behavior": "neutral",
  "segments": [
    {
      "expression": {"name": "curious", "intensity": 0.65},
      "gesture": {"name": "head_tilt", "intensity": 0.55},
      "gaze": {
        "target": "viewer",
        "behavior": "maintain",
        "intensity": 0.8
      },
      "duration_ms": 1200,
      "fade_in_ms": 180,
      "fade_out_ms": 220
    },
    {
      "expression": {"name": "happy", "intensity": 0.9},
      "gesture": {"name": "wave", "intensity": 0.9},
      "gaze": null,
      "duration_ms": 1800,
      "fade_in_ms": 180,
      "fade_out_ms": 300
    }
  ]
}
```

検証Runtimeでの制約は次のとおりです。

- `priority`: 0〜1000
- `segments`: 1〜8区間
- `duration_ms`: 100〜30000
- `fade_in_ms` / `fade_out_ms`: 0〜5000かつ区間時間以下
- 表情・Gesture・視線の強度: 0.0〜1.0

### 割込み方針

- `replace_lower_priority`: 実行中と同等以上のPriorityなら置換
- `queue`: 実行中Performanceの後ろへ追加
- `ignore_if_busy`: 実行中なら新しいPerformanceを無視

### 終了後の復帰

- `neutral`: neutral / idle / neutralへ戻す
- `hold`: 最終表情と視線を維持し、Gestureだけ終了
- `previous`: Performance開始前の表情・Gesture・視線へ戻す

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

`feature/avatar-performance-plan` のCoreを別ターミナルで、次の環境変数付きで起動します。

```bash
YURA_AVATAR_OUTPUT_ENABLED=1 \
YURA_AVATAR_RUNTIME_URL=http://127.0.0.1:8780 \
YURA_AVATAR_OUTPUT_TIMEOUT_SECONDS=3.0 \
python -m app
```

Performance対応経路では、Output Unitごとに `/api/avatar/performances` へ一度だけ送信されます。RuntimeがPerformanceを拒否した場合は、Plugin側で既存の `/api/avatar/actions` へ縮退します。

## ブラウザでの手動確認

Manual Probeの `3区間演技` ボタンを押すと、次の順番でPerformanceを送信します。

1. curious / head_tilt / viewer
2. surprised / lean_forward / right
3. happy / wave / viewer
4. neutralへ復帰

各区間の表情・Gesture・視線、強度、現在区間番号、最終Payloadを画面で確認できます。

既存の表情・Gesture・視線ボタンとランダム送信は、個別Actionの後方互換確認に使用します。

## curl疎通確認

Performance：

```bash
curl -X POST http://127.0.0.1:8780/api/avatar/performances \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 1,
    "type": "avatar.performance.submit",
    "performance_id": "curl-performance-1",
    "source_activity_id": "curl-activity",
    "output_unit_id": "curl-output",
    "priority": 500,
    "interrupt_policy": "replace_lower_priority",
    "return_behavior": "neutral",
    "segments": [
      {
        "expression": {"name": "curious", "intensity": 0.7},
        "gesture": {"name": "head_tilt", "intensity": 0.6},
        "gaze": {"target": "viewer", "behavior": "maintain", "intensity": 0.8},
        "duration_ms": 1200,
        "fade_in_ms": 150,
        "fade_out_ms": 200
      },
      {
        "expression": {"name": "happy", "intensity": 0.9},
        "gesture": {"name": "wave", "intensity": 0.9},
        "gaze": null,
        "duration_ms": 1800,
        "fade_in_ms": 180,
        "fade_out_ms": 300
      }
    ]
  }'
```

個別表情：

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

## モバイルでの手動操作

画面幅が1040px以下の場合、Manual Probeの先頭に小型のLive Previewを表示します。

- 操作パネルをスクロールしている間、プレビューは画面上端へ追従します。
- メインCanvasの描画済みフレームを転写します。
- Performanceの現在区間と受信シーケンスを同時に確認できます。
- iPhoneのSafe Areaを考慮します。

## Render

`render.yaml` の `yura-avatar-runtime-lab` を使用します。

- Branch: `test/avatar-runtime-render-stick-model`
- Build: `python -m compileall app gui/yura-avatar-runtime-lab`
- Start: `python gui/yura-avatar-runtime-lab/server.py`
- Health: `/health`

Renderへデプロイ後、Core側の `YURA_AVATAR_RUNTIME_URL` に発行されたHTTPS URLを設定します。

```bash
YURA_AVATAR_OUTPUT_ENABLED=1 \
YURA_AVATAR_RUNTIME_URL=https://<render-service>.onrender.com \
python -m app
```

## 自動テスト

```bash
pytest tests/test_avatar_runtime_lab.py
```

次を回帰テストで確認します。

- 個別Action Payloadの正常系・異常系
- Performance Payloadと複数Segmentの正常系・異常系
- StateHubがPerformanceを一度の受信イベントとして保持すること
- 履歴上限
- `queue` / `ignore_if_busy` / Priority置換処理の存在
- `neutral` / `hold` / `previous` 復帰処理
- モバイル追従プレビュー

## 対応値

### 表情

- `neutral`
- `happy`
- `sad`
- `surprised`
- `angry`
- `curious`

### Gesture

- `small_nod`
- `head_tilt`
- `wave`
- `lean_forward`
- `bounce`

### 視線

- `viewer`
- `left`
- `right`
- `up`
- `down`
- `away`
- `neutral`

未知の名前も契約上は受信できますが、棒人間固有の描画がない場合はneutralまたはidle相当になります。

## 検証Runtime上の制約

- 通信は暫定HTTP/SSEです。
- `fade_in_ms` と `fade_out_ms` は契約として保持しますが、棒人間では完全な補間表現ではなく区間切替確認を主目的とします。
- 公開Action APIとPerformance APIに認証はありません。検証専用です。
- Render無料サービスがスリープしている場合、初回送信がタイムアウトすることがあります。
- 完了・中断・失敗通知をCoreへ返す双方向契約は未実装です。
- VTube StudioやLive2Dモデル固有Parameterは扱いません。
- この検証ブランチはdevelopへマージしません。

## 次段階

1. Render上でPerformance APIと3区間再生を確認する
2. `feature/avatar-performance-plan` のCoreからRenderへ実送信する
3. 完了・中断・失敗通知の契約を設計する
4. HTTP/SSEからWebSocketへ移行する
5. VTube Studio Backendとモデルプロファイルを追加する
6. サンプルLive2Dモデルで表情・視線・モーションを検証する

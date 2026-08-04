# Yura Avatar Runtime Lab

Live2DモデルやVTube Studioへ接続する前に、ゆらが選んだ注意・表情・首・体・腕のIntentを、Canvas 2Dの棒人間で確認する検証Runtimeです。

このRuntimeはモーションキャプチャではありません。カメラやカーソルは外界の対象位置を提供し、誰をどのように見るか、首を振るか、体を傾けるか、手を上げるかはゆら側が決めます。

本コードは `test/avatar-runtime-render-stick-model` ブランチだけで管理し、developへは取り込みません。

## 構成

```text
Activity / ActionPlanGroup
  ├─ Speech / Subtitle
  └─ Avatar Performanceを1回送信
       ↓
AvatarPerformancePlan
  ├─ Expression Track
  ├─ Attention Track
  ├─ Head Track
  ├─ Torso Track
  ├─ Left Arm Track
  └─ Right Arm Track
       ↓
Avatar Runtime Lab
  ↓ 毎フレーム合成
Browser Canvas stick model
```

ActionPlanGroupはActivity Turn由来の出力を束ねます。部位別の動作をActionSchedulerへ細切れに渡さず、Avatar Runtimeが複数Trackを同時に合成します。

## 生物的な連続動作

- 呼吸は明示Actionがない間も継続します。
- 視線、首、体は異なる速度で対象へ向きます。
- Attention Trackを維持したまま、首振りやうなずきを加算できます。
- 上体を傾けながら、左右の腕を別々に動かせます。
- 一時的なTrackが終わっても、継続中の表情や注意対象はneutralへ戻りません。
- 新しいPerformanceは、その瞬間の姿勢から短く補間して開始します。
- カーソル追従では小さな位置変化をデッドゾーンで無視します。

## API

| Method | Path | 用途 |
|---|---|---|
| GET | `/health` | CapabilityとPerformance Schema確認 |
| GET | `/api/avatar/state` | 現在状態、最終Action、最終Performance、履歴 |
| GET | `/api/avatar/events` | ブラウザ向けSSE |
| POST | `/api/avatar/actions` | 後方互換の個別Avatar Action |
| POST | `/api/avatar/performances` | 重複Track型Avatar Performance |

`/health` では次のCapabilityを返します。

```json
{
  "status": "ok",
  "service": "avatar-runtime-lab",
  "performance_api": true,
  "performance_schema_version": 2,
  "overlapping_tracks": true
}
```

## Performance Schema v2

```json
{
  "schema_version": 2,
  "type": "avatar.performance.submit",
  "performance_id": "reject-1",
  "source_activity_id": "conversation-1",
  "output_unit_id": "output-1",
  "priority": 500,
  "interrupt_policy": "replace_lower_priority",
  "return_behavior": "hold",
  "duration_ms": 3000,
  "tracks": [
    {
      "track_id": "look-away",
      "channel": "attention",
      "start_offset_ms": 620,
      "duration_ms": 2380,
      "fade_in_ms": 160,
      "fade_out_ms": 260,
      "blend_mode": "override",
      "continuity": "current",
      "hold": true,
      "layer_priority": 120,
      "intent": {
        "type": "attention",
        "target": "away",
        "behavior": "avoid",
        "intensity": 0.85,
        "eye_follow": 1.0,
        "head_follow": 0.48,
        "body_follow": 0.18
      }
    },
    {
      "track_id": "head-shake",
      "channel": "head",
      "start_offset_ms": 180,
      "duration_ms": 1450,
      "fade_in_ms": 120,
      "fade_out_ms": 240,
      "blend_mode": "additive",
      "continuity": "current",
      "hold": false,
      "layer_priority": 240,
      "intent": {
        "type": "motion",
        "name": "head_shake",
        "intensity": 1.0,
        "amplitude": 1.0,
        "tempo": 1.35,
        "repetitions": 4,
        "body_participation": 0.7,
        "direction": "horizontal"
      }
    }
  ],
  "segments": []
}
```

### Track共通項目

- `channel`: `expression` / `attention` / `head` / `torso` / `left_arm` / `right_arm` / `autonomous`
- `start_offset_ms`: Performance開始からTrackが始まるまでの時間
- `duration_ms`: Track継続時間
- `fade_in_ms` / `fade_out_ms`: Trackの影響が入る・抜ける時間
- `blend_mode`: `override` または `additive`
- `continuity`: `current` または `neutral`
- `hold`: 終了後もIntentを維持するか
- `layer_priority`: 同じ部位で競合したときの優先度

Schema v1の直列`segments`も移行期間の後方互換として受信できますが、正規の検証対象はSchema v2の`tracks`です。

## 手動確認

画面には次の3つの複合演技ボタンがあります。

### 強く嫌がる

- 嫌そうな表情
- 最初は相手を見て、その後に視線をそらす
- 上体を後ろへ傾ける
- 首を大きく複数回横へ振る
- 両腕を胸元へ引く
- すべてを時間的に重ねる

### 強く肯定する

- 嬉しい表情
- 相手を見る状態を維持
- 大きく複数回うなずく
- 上体を前へ傾ける
- 右手を上げる

### カーソルを見る

- カーソルを注意対象として維持
- 目が先に動き、首が遅れて、体がさらに遅れて追う
- 小さな位置変化は無視する

旧表情・Gesture・視線ボタンは、個別Actionの後方互換確認用です。

## ローカル起動

```bash
python gui/yura-avatar-runtime-lab/server.py
```

既定URL：

```text
http://127.0.0.1:8000
```

ポートを変更する場合：

```bash
PORT=8780 python gui/yura-avatar-runtime-lab/server.py
```

## Coreから接続

`feature/avatar-performance-plan` のCoreを別ターミナルで起動します。

```bash
YURA_AVATAR_OUTPUT_ENABLED=1 \
YURA_AVATAR_RUNTIME_URL=http://127.0.0.1:8000 \
YURA_AVATAR_OUTPUT_TIMEOUT_SECONDS=3.0 \
python -m app
```

Output Unitごとに `/api/avatar/performances` へ1回送信されます。Performance APIだけが未対応の場合は、Plugin側で既存の個別Actionへ縮退します。

## curl疎通確認

```bash
curl -X POST http://127.0.0.1:8000/api/avatar/performances \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 2,
    "type": "avatar.performance.submit",
    "performance_id": "curl-nod-1",
    "source_activity_id": "curl-activity",
    "output_unit_id": "curl-output",
    "priority": 500,
    "interrupt_policy": "replace_lower_priority",
    "return_behavior": "hold",
    "duration_ms": 2200,
    "tracks": [
      {
        "track_id": "look-viewer",
        "channel": "attention",
        "start_offset_ms": 0,
        "duration_ms": 2200,
        "fade_in_ms": 120,
        "fade_out_ms": 200,
        "blend_mode": "override",
        "continuity": "current",
        "hold": true,
        "layer_priority": 100,
        "intent": {
          "type": "attention",
          "target": "viewer",
          "behavior": "maintain",
          "intensity": 1.0,
          "eye_follow": 1.0,
          "head_follow": 0.6,
          "body_follow": 0.15
        }
      },
      {
        "track_id": "nod",
        "channel": "head",
        "start_offset_ms": 180,
        "duration_ms": 1400,
        "fade_in_ms": 100,
        "fade_out_ms": 220,
        "blend_mode": "additive",
        "continuity": "current",
        "hold": false,
        "layer_priority": 220,
        "intent": {
          "type": "motion",
          "name": "nod",
          "intensity": 0.9,
          "amplitude": 0.85,
          "tempo": 1.15,
          "repetitions": 3,
          "body_participation": 0.4,
          "direction": "vertical"
        }
      }
    ],
    "segments": []
  }'
```

## モバイル操作

画面幅が1040px以下の場合、操作パネルの先頭に小型Live Previewを表示します。

- 操作中も画面上端へ追従します。
- メインCanvasの描画フレームを転写します。
- 現在の複合演技と受信シーケンスを確認できます。
- iPhoneのSafe Areaを考慮します。

## Render

`render.yaml` の `yura-avatar-runtime-lab` を使用します。

- Branch: `test/avatar-runtime-render-stick-model`
- Build: `python -m compileall app gui/yura-avatar-runtime-lab`
- Start: `python gui/yura-avatar-runtime-lab/server.py`
- Health: `/health`

Renderへデプロイ後、Core側の `YURA_AVATAR_RUNTIME_URL` に発行されたHTTPS URLを設定します。

## 自動テスト

```bash
pytest tests/test_avatar_runtime_lab.py
```

回帰テストでは次を確認します。

- Schema v2 Track Payloadの正常系・異常系
- Trackの時間的重複
- AttentionとMotionの同時保持
- 部位、合成方式、連続性、保持、優先度
- StateHubがPerformanceを1イベントとして保持すること
- Segment直列再生処理が残っていないこと
- カーソル注意とデッドゾーン
- 首振り、うなずき、体傾き、左右腕動作
- モバイル追従プレビュー
- 既存個別Actionの後方互換

## 制約

- カメラ映像からの人物・物体認識は未実装です。
- ゆら自身が注意対象を選ぶ判断ロジックはCore側の後続工程です。
- 通信は暫定HTTP/SSEです。
- 公開APIに認証はありません。検証専用です。
- Render無料サービスがスリープ中の場合、初回接続に時間がかかることがあります。
- 完了・中断・失敗通知をCoreへ返す双方向契約は未実装です。
- VTube StudioやLive2D固有Parameterは扱いません。
- この検証ブランチはdevelopへマージしません。

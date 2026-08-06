# Body Pose Lab 責務分離設計 v1.0.0

## 1. 目的

`BodyPoseFrame`、連続Pose Controller、Runtime、Transportを、棒人形表示と診断情報によって実動作確認する。

Labは検証用Adapter／GUIであり、Emotion因果、Interaction Intention、Body表現判断、Activity選択を所有しない。Coreが生成した`BodyPoseFrame`を受信・保存・配信・描画し、検証入力は型付きApplication Serviceを通じて既存Controller契約へ渡す。

## 2. 旧実装を直接移植しない理由

旧`server.py`は次を1ファイルで担当していた。

- Frame保存
- Controller生成とTick Thread
- 内的状態更新
- 注意候補更新
- Body command処理
- HTTP API
- SSE
- 静的ファイル配信
- JSON変換
- 起動処理

旧`app.js`もDOM参照、Preset、状態更新、API、SSE、Candidate Drag、Metrics、Payload、Canvas描画を集中していた。

これらは変更理由と検証方法が異なるため、そのまま移植しない。

## 3. Server責務

```text
BodyPoseFrame
    ↓
BodyPoseLabFrameHub
    ├─ snapshot
    └─ subscriber queues

HTTP Request
    ↓
BodyPoseLabHttpRouter
    ├─ BodyPoseLabApiController
    │      ↓
    │  BodyPoseLabApplicationService
    ├─ BodyPoseLabSseStream
    └─ BodyPoseLabStaticFiles
```

### 3.1 Frame Hub

- 最新Frameを保持
- Frame sequenceを検証
- SSE subscriberごとの1件Queueへ最新Frameを配信
- 遅いsubscriberでは古い未送信Frameを破棄
- HTTP、Controller、JSON、Threadを知らない

### 3.2 Application Service

- Labで許可する検証入力を型付き契約へ変換
- Emotion Snapshot更新
- Activity Context更新
- 注意候補更新
- 正規化外部制約の適用
- 発話Presentationの開始
- Snapshot取得

Body Motion名やCharacter発言を生成しない。

### 3.3 API Controller

- HTTP payloadの構文検証
- Application Service呼び出し
- レスポンスDTO生成

### 3.4 SSE Stream

- Hub subscribe／unsubscribe
- Event framing
- keep-alive

### 3.5 Static Files

- 許可された`web/`配下だけを配信
- パストラバーサルを拒否
- MIME解決

### 3.6 Composition

- `StateDrivenBodyController`を明示生成
- monkeypatchしない
- Tick Loop、Hub、Application、HTTP Serverを構築
- 起動／停止順だけを管理

## 4. Client責務

```text
main.js
 ├─ lab-state.js
 ├─ presets.js
 ├─ api-client.js
 ├─ frame-stream.js
 ├─ candidate-controls.js
 ├─ metrics-view.js
 ├─ payload-view.js
 └─ stick-figure-renderer.js
```

- `main.js`: 部品のCompositionとイベント配線のみ
- `lab-state.js`: 画面状態
- `presets.js`: 検証Preset定義
- `api-client.js`: REST通信
- `frame-stream.js`: SSE再接続
- `candidate-controls.js`: 注意候補の編集・Drag
- `metrics-view.js`: 数値表示
- `payload-view.js`: Raw payload表示
- `stick-figure-renderer.js`: Frameから棒人形を描画

## 5. 検証入力境界

### Emotion

Coreの`EmotionState`と同じ型・範囲を使用する。Lab独自のDriveをBody主原因として追加しない。

### Activity Context

- engagement
- movement_energy
- gaze_freedom
- posture_tendency
- attention target
- Interaction Intention

### Attention Candidates

`BodyAttentionCandidate`として位置、salience、novelty、threat、relevance、stabilityを渡す。

### External Constraint

Body command名ではなく、`BodyExternalConstraint`の正規化軸目標として渡す。

例:

```json
{
  "constraint_id": "raise-right-arm",
  "duration_ms": 1800,
  "targets": [
    {"axis": "right_arm_raise", "value": 0.85, "weight": 1.0}
  ]
}
```

### Speech

本文や音声データではなく、`SpeechPresentationRequest`のID、duration、audio referenceを渡す。

## 6. API

- `GET /health`
- `GET /api/snapshot`
- `POST /api/emotion`
- `POST /api/activity-context`
- `POST /api/attention-candidates`
- `POST /api/external-constraint`
- `DELETE /api/external-constraint`
- `POST /api/speech`
- `GET /api/frames` (SSE)

Core RuntimeのHTTP Outputは`POST /api/body-pose-frame`へFrameを送信できる。

## 7. セキュリティ・診断

- 受信Body Frame、診断値、IDだけを保持する
- ユーザー発話本文、Character生成文、Prompt、Memoryを保存しない
- Payload上限を設ける
- 非有限値を拒否する
- SSE subscriber数を制限する
- エラー本文へ内部例外・ファイルパスを露出しない
- Labは既定でloopbackへbindする

## 8. テスト境界

- Frame Hub: latest-frame-wins、subscribe、unsubscribe
- Application Service: 各入力の型変換とController呼び出し
- API Controller: 正常系、型不正、範囲外、サイズ上限
- Static Files: traversal拒否、MIME
- SSE: Frame、keep-alive、slow consumer
- Composition: 起動・停止、Tick、外部HTTP Frame受信
- Browser資産: 純粋変換関数を可能な範囲で分離

## 9. Stacked PR

本工程は`feature/body-causal-reintegration`をBaseとする別Draft PRで実装する。PR #180へGUI・Server資産を継ぎ足さない。明示承認なしではマージしない。

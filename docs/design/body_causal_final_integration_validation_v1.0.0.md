# Body因果再統合 最終検証設計 v1.0.0

## 1. 目的

工程1〜7で分離・再構築したBody因果経路を、実際のHTTP Server、Core側HTTP Output、SSE、ローカルTick Loopを通して統合検証する。

この工程では新しいBody表現機能を追加しない。検証用コード、契約上の不整合修正、旧PR整理だけを行う。

## 2. 検証対象

```text
Core確定Emotion
  → BodyExpressionInput
  → StateDrivenBodyController
  → BodyPoseFrame
  → HttpBodyPoseFrameOutput
  → Body Pose Lab POST /api/body-pose-frame
  → BodyPoseLabFrameHub
  → GET /api/snapshot
  → GET /api/frames (SSE)
  → Stick Figure Client
```

## 3. 内部段階

### 8-1 実HTTP Server

- loopbackの空きPortでServerを起動
- `GET /health`
- `GET /api/snapshot`
- `GET /`
- JavaScript／CSS資産
- 不正JSON、Payload上限、未定義Route
- shutdown／close

### 8-2 Core HTTP Output→Lab

- `BodyPoseFrame`をCore側Encoder／Sender／Outputから送信
- Labがsourceとsequenceを保持
- Snapshotで受信を確認
- 同一sourceのstale sequenceを拒否
- 新Frameでlatestを更新

### 8-3 SSE／local simulation

- SSE接続後の最初の`body-pose-frame` Event
- slow subscriberのlatest-frame-wins
- local simulation Tick Loopのstart／stop
- stop後にTickが増加しない

### 8-4 因果・安全境界

- Payloadにユーザー発話本文、Character Prompt、Memoryを含めない
- EmotionとActivity Contextは型付き境界を通す
- Body command名をController主入力にしない
- External Constraintは正規化Pose軸だけを使用
- Runtime→Bootstrap逆依存がないことを確認
- 主要ファイル・関数の責務再監査

### 8-5 最終CI・旧PR整理

- 全体pytest
- PR #180／#181／本PRのStack状態を確認
- 旧PR #159／#160／#163は再利用・置換内容を記録してclose
- 検証PR #130は目的と現状を確認し、不要ならclose
- `develop`へは明示承認なしでマージしない

## 4. テスト構造

実HTTP統合テストでも責務を分ける。

- Server lifecycle fixture
- HTTP JSON client helper
- SSE first-event reader
- Core Output integration test
- local simulation lifecycle test
- architectural boundary test

1つの巨大テスト関数へ起動・送信・SSE・終了・旧PR確認を混在させない。

## 5. 合格条件

- 実Socket経由でCore FrameがLabへ届く
- health／snapshot／static assetが正常
- SSEでFrameを受信できる
- local Tick Loopが安全に停止する
- HTTP障害やslow subscriberがCore Tickを停止しない
- 診断Payloadが有限・型付き・本文非保持
- 全体CI成功
- 旧PRの扱いが明文化される

## 6. 非目標

- Live2D／VRM Adapter実装
- モデル固有Bone／Parameter mapping
- WebSocket／gRPC等の正規Transport決定
- Body表現アルゴリズムの追加調整
- `develop`へのマージ

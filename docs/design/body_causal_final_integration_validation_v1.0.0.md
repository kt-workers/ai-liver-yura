# Body因果再統合 最終検証設計 v1.0.0

## 後続設計による位置付け更新（2026-08-08）

本書はIssue #178 / PR #180〜#182で完了したBody因果再統合の**当時の検証設計と結果境界**を記録する。Runtime/Transport/SSE/安全境界の検証方針は引き続き有効である。

ただし、当時の検証条件である「External Constraintは正規化Pose軸だけを使用」は、Issue #211以前のCompatibility境界を確認したもの。これを将来Body Motionの正規設計として拡張しない。

後続の正規完成形は次へ更新される。

```text
high-level body intention / BodyMotionGoal
→ current pose + Skeleton + DOF / Joint Limits
→ Motion Planning / IK / Kinematics / trajectory
→ Continuous Controller
→ BodyPoseFrame
→ HTTP / SSE / Avatar or Lab Adapter
```

したがって本書の歴史的テストを削除・改変して過去結果を作り替えるのではなく、旧normalized Pose-axis経路はCompatibility回帰として保持し、新しい身体能力は#211のGenerative Motion経路で検証する。

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

#211以降もこのTransport経路自体は維持し、Controller内部で生成されるCanonical joints/root/gazeの自由度を拡張する。

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
- 当時のCompatibility External Constraintは正規化Pose軸だけを使用
- Runtime→Bootstrap逆依存がないことを確認
- 主要ファイル・関数の責務再監査

後続#211では、明示Body Motionの正規入力をfixed Pose axisへ増築せず、型付き`BodyMotionGoal`とSkeleton/IK/Kinematicsへ移行する。

### 8-5 最終CI・旧PR整理

- 全体pytest
- PR #180／#181／本PRのStack状態を確認
- 旧PR #159／#160／#163は再利用・置換内容を記録してclose
- 検証PR #130は目的と現状を確認し、不要ならclose
- `develop`へは明示承認なしでマージしない

## 4. テスト構造

実HTTP統合テストでも責務を分ける。

### Support

- `tests/support/body_pose_lab_http_harness.py`
  - 実Server lifecycle
  - HTTP JSON／bytes request
  - SSE first-event reader
  - bounded polling
- `tests/support/body_pose_frame_factory.py`
  - 最小BodyPoseFrame生成

### 実HTTP・表示資産

- `tests/test_body_pose_lab_http_integration.py`
  - health
  - snapshot
  - index／JavaScript／CSS
  - 未定義Route／traversal
- `tests/test_body_pose_lab_http_safety.py`
  - 不正JSON
  - Payload上限

### Core Transport

- `tests/test_body_core_to_lab_http_integration.py`
  - `HttpBodyPoseFrameOutput`から実Socketへ送信
  - source／sequence
  - stale拒否
  - latest更新

### SSE／Lifecycle

- `tests/test_body_pose_lab_sse_lifecycle.py`
  - 最初のSSE Frame Event
  - subscriber解放
  - local Tick start／stop
  - stop後のTick停止

### 因果・安全境界

- `tests/test_body_causal_architecture_boundaries.py`
  - Runtime→Bootstrap逆依存なし
  - 固定Body command名非依存
  - Compatibility正規化Pose軸の境界確認
  - Speech本文・Prompt・Memory非保持

#211ではこれに加え、fixed Motion/Pose名を正規経路に持たないこと、Canonical Skeleton/DOF/Joint Limit、任意3D direction、IK、連続性を別テストで検証する。

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

## 7. 後続Issueとの整合

- #211: Generative Motion基盤。旧Pose軸Compatibilityを新規能力へ拡張しない
- #213: TTS発音/Viseme同期口形
- #214: Character Profile由来のBody表現Style
- #215: Body Pose Lab表示簡素化

各Issueは#207の共通Body完成目標へ収束し、本書の歴史的Compatibility検証を異なる最終設計として再利用しない。

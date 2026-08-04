# Avatar Output Plugin / Avatar Runtime Subsystem 設計検討レポート

## 1. 目的

AI Liver「ゆら」のリアクション、発話、感情、ジェスチャー、視線などをLive2Dアバターへ反映するため、次の範囲を整理する。

- 既存の `app/plugins/avatar_output` の活用方針
- Core、Plugin、Subsystemの責務境界
- 視線制御の位置付け
- VTube StudioとサンプルLive2Dモデルを用いた検証構成
- 将来の独自Live2Dモデルおよび別描画方式への拡張性
- 段階的な実装計画

本レポートは、`ai-liver-yura` リポジトリの `develop` ブランチに存在する実装と、今回の設計検討を基にまとめたものである。

---

## 2. 結論

推奨構成は次の通りである。

```text
AI Liver Core
    ↓
app/plugins/avatar_output
    ↓ WebSocket
Avatar Runtime Subsystem
    ↓ WebSocket
VTube Studio
    ↓
VTube StudioサンプルLive2Dモデル
```

分類としては、次の二重構造が適切である。

- Coreから見たアバター出力機能：交換可能なPlugin
- Live2Dの描画・継続制御・モデル管理を行う実行系：独立したSubsystem

VTube Studioは最終的なアーキテクチャそのものではなく、Avatar Runtime Subsystemから利用する最初のBackendと位置付ける。

```text
Avatar Runtime Subsystem
├── Performance Scheduler
├── Expression Controller
├── Gesture Controller
├── Gaze Controller
├── State / Priority / Interruption Manager
└── Backend
    ├── VTubeStudioBackend       # 初期検証
    └── CubismWebBackend         # 将来候補
```

---

## 3. 既存実装の確認結果

### 3.1 `app/plugins/avatar_output`

既存の `AvatarOutputPlugin` は、Live2Dや3D Adapterを任意CapabilityとしてCoreから隔離するためのPluginとして実装されている。

現在公開しているCapabilityは次の2つである。

```text
output.avatar.expression
output.avatar.gesture
```

現在の主な処理は以下である。

- Adapterの有無によるAvailability判定
- Plugin初期化・終了
- Capabilityの公開
- 表情変更の委譲
- ジェスチャー再生の委譲
- Adapter実行失敗時のUnavailable移行
- Capability Reporterへの状態通知

### 3.2 `AvatarOutputPort`

現在のPortは次の2操作だけを定義している。

```python
async def set_expression(expression: str) -> None
async def play_gesture(gesture: str) -> None
```

Live2Dに依存しない高レベル契約としての方向性は適切だが、実際のアバター制御に必要な次の契約が不足している。

- 視線
- 頭部姿勢
- 身体姿勢
- 表現強度
- 時間軸付きの演出
- 実行キャンセル
- 状態取得
- 実行完了・失敗通知

### 3.3 Runtime登録

現在のRuntime Plugin登録処理では、LLM Provider、Memory、Voice Outputなどは登録されているが、`avatar_output` はComposition Rootへ接続されていない。

したがって、現状は次の状態と判断できる。

> PluginとPortの骨格は存在するが、実Adapter、設定、Runtime登録、Action実行経路、Subsystem接続は未実装または未接続である。

---

## 4. 既存の意味決定・表現計画との関係

Live2D対応のために、新しい「意味決定層」を追加する必要はない。

現在のCoreには、すでに次の構造が存在する。

```text
Event
  ↓
Activity選択・実行
  ↓
ResponseContext
  ↓
CharacterResponse
  ↓
ReactionPlan
  ↓
ActionPlanGroup
```

`CharacterResponse` および `ReactionPlan` には、次の高レベル表現情報が含まれる。

- 発話本文
- 表情
- ジェスチャー
- 音声意図
- 発話後の間
- 発話内で表現が変化する区間

そのため、新規に必要なのは意味の再決定ではなく、既存の高レベル表現をアバター演出へ変換する中間層である。

```text
ReactionPlan
    ↓
AvatarPerformancePlan
    ↓
Avatar Output Plugin
    ↓
Avatar Runtime Subsystem
```

---

## 5. Plugin部分の責務

`app/plugins/avatar_output` は、CoreとAvatar Runtime Subsystemの境界として扱う。

### 5.1 担当する責務

- Coreの抽象的な表現命令を受け取る
- Subsystem用通信DTOへ変換する
- WebSocketまたはHTTPでSubsystemへ送信する
- CapabilityをCoreへ公開する
- 接続状態とSubsystem状態を監視する
- 接続不能時にUnavailableまたはDegradedへ移行する
- アバター機能停止時もCore本体を継続動作させる
- 実行完了・中断・失敗をCoreへ返す
- Activity ID、Output Unit ID、Performance IDなどの相関IDを維持する

### 5.2 担当しない責務

- VTube Studio API認証
- VTube StudioのParameter名
- Live2Dモデル固有マッピング
- 毎フレームのParameter送信
- 表情・視線・ジェスチャーの補間
- モーション合成
- 呼吸、瞬き、Idle制御
- Live2D描画
- OBSへの描画出力

これらはSubsystem側に置く。

---

## 6. Subsystem部分の責務

新規のSubsystemは `Live2D Subsystem` ではなく、より抽象的な `Avatar Runtime Subsystem` とする。

### 6.1 名称を抽象化する理由

Live2D固有名をSubsystem名に含めると、将来の次の変更で境界が不自然になる。

- VTube Studioから独自Cubism Runtimeへの移行
- VRMアバターへの対応
- 2D・3Dアバターの切り替え
- 別PCまたは別プロセスへの描画移行

SubsystemをAvatar Runtimeとしておけば、Backendだけを差し替えられる。

### 6.2 主な責務

- AvatarPerformancePlanの受信
- 表情状態の管理
- ジェスチャーのスケジューリング
- 視線の連続制御
- 頭部と身体の追従制御
- 表現の優先度管理
- 割込みと復帰
- Fade-in / Fade-out
- 補間
- Idle、呼吸、瞬き
- 発話状態との同期
- Backend Capabilityの検出
- モデル固有プロファイルの適用
- VTube Studioとの認証・再接続
- 現在状態と実行結果の通知

### 6.3 内部構成案

```text
subsystems/avatar_runtime/
├── api/
│   ├── websocket_server.py
│   └── dto.py
├── application/
│   ├── performance_service.py
│   ├── performance_scheduler.py
│   ├── capability_service.py
│   └── connection_service.py
├── domain/
│   ├── avatar_state.py
│   ├── performance_plan.py
│   ├── expression_state.py
│   ├── gesture_state.py
│   ├── gaze_state.py
│   └── priority.py
├── infrastructure/
│   └── backends/
│       └── vtube_studio/
│           ├── client.py
│           ├── authentication.py
│           ├── parameter_injector.py
│           ├── hotkey_controller.py
│           └── model_profile.py
└── config/
    └── model_profiles/
```

---

## 7. 視線制御

### 7.1 独立チャネルとして扱う

視線はGestureに含めず、独立した制御チャネルとする。

理由は、各表現の時間特性が異なるためである。

|制御|特性|
|---|---|
|表情|数百msから数秒維持|
|ジェスチャー|開始と終了を持つ短時間動作|
|視線|継続的に更新される状態|
|口パク|音声に合わせた高速更新|
|瞬き|独立周期|
|呼吸|常時動作|

視線を単発Actionとして扱うだけでは、自然な追従や注視を実現しにくい。

### 7.2 Capability

初期実装では、少なくとも次を公開する。

```text
output.avatar.expression
output.avatar.gesture
output.avatar.gaze
```

将来的には以下も検討する。

```text
output.avatar.pose
output.avatar.lipsync
output.avatar.blink
```

### 7.3 高レベル視線Intent

CoreはLive2D Parameter値ではなく、意味的な視線Intentを出力する。

```python
AvatarGazeIntent(
    target="viewer",
    behavior="maintain",
    intensity=0.8,
)
```

想定値：

```text
viewer   視聴者を見る
speaker  発話者を見る
object   対象物を見る
down     考え込んで下を見る
away     気まずそうに逸らす
wander   自然に漂わせる
neutral  正面へ戻す
```

Subsystem側で連続座標へ変換する。

### 7.4 自然な視線演出

自然な視線は、単に目のParameterを設定するだけでは不十分である。

推奨する挙動：

1. 目が先に対象へ移動する
2. 少し遅れて頭が追従する
3. 一定時間注視する
4. 小さなランダム揺らぎを加える
5. 必要に応じて正面または次の対象へ戻る

この演出処理はCoreではなくSubsystemで行う。

---

## 8. Port拡張方針

### 8.1 最小拡張

既存契約を活かして段階的に進める場合は、視線操作を追加する。

```python
class AvatarOutputPort(Protocol):
    async def set_expression(self, expression: str) -> None:
        ...

    async def play_gesture(self, gesture: str) -> None:
        ...

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        ...
```

### 8.2 推奨する中期形

個別操作が増えるため、最終的にはPerformance単位の契約へ寄せる。

```python
class AvatarOutputPort(Protocol):
    async def submit_performance(
        self,
        performance: AvatarPerformanceCommand,
    ) -> None:
        ...

    async def cancel_performance(
        self,
        performance_id: str,
    ) -> None:
        ...

    async def get_status(self) -> AvatarOutputStatus:
        ...
```

既存の `set_expression()` と `play_gesture()` は互換用Facadeとして残し、内部で `submit_performance()` に変換できる。

---

## 9. AvatarPerformancePlan

`ReactionPlan` と実際のアバター制御の間に、エンジン非依存の演出計画を追加する。

```python
AvatarPerformanceSegment(
    expression="curious",
    expression_intensity=0.7,
    gesture="small_head_tilt",
    gesture_intensity=0.4,
    gaze_target="viewer",
    gaze_behavior="maintain",
    gaze_intensity=0.8,
    duration_ms=1800,
    fade_in_ms=200,
    fade_out_ms=300,
)
```

この層の目的は意味を再決定することではなく、既存の表現意図をアバター向けに詳細化することである。

### 9.1 含める情報

- Performance ID
- Activity ID
- Output Unit ID
- Priority
- Expression
- Expression intensity
- Gesture
- Gesture intensity
- Gaze target
- Gaze behavior
- Head pose
- Body pose
- Duration
- Fade-in / Fade-out
- Interrupt policy
- Return behavior

---

## 10. VTube Studioを用いた初期検証

### 10.1 位置付け

VTube StudioをLive2D描画・モデル実行Backendとして利用する。

検証時点では、ゆら専用Live2Dモデルが未完成のため、VTube Studio付属または利用可能なサンプルモデルを使用する。

### 10.2 検証する機能

初期段階では次を確認する。

- VTube Studio APIへの接続
- Plugin認証
- 現在モデル取得
- 利用可能Parameter取得
- Hotkey一覧取得
- 表情切替
- ジェスチャーまたはモーション実行
- 左右・上下の視線移動
- 正面復帰
- 頭部追従
- 接続断・再接続
- モデル差異によるCapability判定

### 10.3 表情

表情は、初期検証ではVTube StudioのHotkeyまたはExpression切替を利用する。

```text
happy      → Happy Hotkey
sad        → Sad Hotkey
surprised  → Surprised Hotkey
neutral    → Neutral Hotkey
```

### 10.4 ジェスチャー

サンプルモデルに利用可能なモーションまたはHotkeyがある場合はそれを利用する。

存在しない場合は、頭部・身体Parameterを時間変化させ、簡易ジェスチャーを作る。

例：

```text
small_nod
head_tilt
look_away
lean_forward
```

### 10.5 視線

視線はHotkeyではなくParameter Injectionで制御する。

Subsystem内に20〜30Hz程度の更新ループを持ち、Coreからは高レベルIntentだけを受け取る。

```text
Gaze Intent
    ↓
Gaze Controller
    ↓
Interpolation
    ↓ 20〜30Hz
VTube Studio Parameter Injection
```

---

## 11. モデルプロファイル

サンプルモデルや将来のゆらモデルごとの差異をコードへ埋め込まず、モデルプロファイルで管理する。

```yaml
backend: vtube_studio
model_id: sample-model-id

expressions:
  neutral:
    hotkey: Neutral
  happy:
    hotkey: Happy
  sad:
    hotkey: Sad
  surprised:
    hotkey: Surprised

gestures:
  small_nod:
    type: parameter_sequence
    duration_ms: 700
    parameters:
      head_y: [0.0, -0.2, 0.15, 0.0]

gaze:
  horizontal_input: EyeHorizontal
  vertical_input: EyeVertical
  head_horizontal_input: FaceAngleX
  head_vertical_input: FaceAngleY
```

起動時にVTube Studioから取得したParameter一覧・Hotkey一覧と照合し、利用可能なCapabilityを動的に判定する。

---

## 12. PluginとSubsystemの通信契約

### 12.1 通信方式

WebSocketを推奨する。

理由：

- 双方向通信が必要
- 接続状態を継続監視する
- 完了・中断・失敗通知がある
- 視線や発話状態などの継続制御がある
- 将来的なリアルタイム同期に適する

### 12.2 Performance送信例

```json
{
  "type": "avatar.performance.submit",
  "performance_id": "perf-001",
  "source_activity_id": "activity-001",
  "output_unit_id": "output-001",
  "priority": 100,
  "segments": [
    {
      "expression": {
        "name": "curious",
        "intensity": 0.7
      },
      "gesture": {
        "name": "small_head_tilt",
        "intensity": 0.4
      },
      "gaze": {
        "target": "viewer",
        "behavior": "maintain",
        "intensity": 0.8
      },
      "duration_ms": 1800
    }
  ]
}
```

### 12.3 Capability通知例

```json
{
  "type": "avatar.capabilities.changed",
  "backend": "vtube_studio",
  "connected": true,
  "model_loaded": true,
  "capabilities": [
    "expression",
    "gesture",
    "gaze",
    "head_pose"
  ]
}
```

### 12.4 実行結果通知例

```json
{
  "type": "avatar.performance.status",
  "performance_id": "perf-001",
  "status": "completed"
}
```

---

## 13. エラー・劣化動作

Avatar Runtime SubsystemまたはVTube Studioが利用できない場合でも、Core本体は継続動作する。

想定状態：

```text
available
degraded
unavailable
reconnecting
```

Capability単位で状態を管理する。

例：

```text
expression = available
gesture    = degraded
gaze       = unavailable
```

モデルに必要なParameterが存在しない場合も、Plugin全体を停止せず、該当Capabilityだけを利用不可にする。

---

## 14. 実装段階

### 第1段階：現状監査と接続基盤

Plugin側：

- `avatar_output` のRuntime登録
- 設定追加
- Subsystem Client Adapter
- Capability追加
- 接続状態監視

Subsystem側：

- WebSocket API
- VTube Studio接続
- 認証
- モデル情報取得
- Parameter・Hotkey一覧取得
- 状態確認用API

検証：

- 表情切替
- 左右上下の視線
- 正面復帰

### 第2段階：Core Action連携

- `CHANGE_EXPRESSION` からPlugin呼び出し
- `MOVE` からPlugin呼び出し
- 視線ActionまたはGaze Intent連携
- Action ID、Activity ID、Output Unit IDの相関
- 失敗時のCore継続

### 第3段階：AvatarPerformancePlan

- `ReactionPlan` からの変換
- 複数Segment
- 表情強度
- 視線対象
- Gesture強度
- Duration
- Fade
- Priority
- Interrupt policy

### 第4段階：自然な連続動作

- 視線の目先行・頭追従
- 視線の微小揺らぎ
- Idle
- 呼吸
- 瞬き
- 発話との同期
- 口パク
- 割込みと復帰

### 第5段階：ゆら専用モデルへの移行

- ゆらモデル用プロファイル
- Parameter対応確認
- Expression・Motion調整
- 感情強度の調整
- OBS表示との統合
- サンプルモデルとの差分検証

---

## 15. 推奨する最初の実装範囲

最初から全演出を作らず、次の縦断経路を完成させる。

```text
Core CHANGE_EXPRESSION
    ↓
AvatarOutputPlugin
    ↓
Subsystem Client
    ↓
Avatar Runtime Subsystem
    ↓
VTubeStudioBackend
    ↓
サンプルモデルの表情変更
```

次に視線経路を追加する。

```text
Core Gaze Intent
    ↓
AvatarOutputPlugin
    ↓
Avatar Runtime Subsystem
    ↓
Gaze Controller
    ↓
VTube Studio Parameter Injection
    ↓
サンプルモデルの視線移動
```

この2経路が成立すれば、Plugin境界、Subsystem境界、VTube Studio Backend、Capability管理、接続監視の基本構造を検証できる。

---

## 16. 最終判断

- 既存の `app/plugins/avatar_output` は活用する
- 現在のPluginは骨格段階であり、実接続は未完成
- Live2D描画・連続制御はCore Plugin内へ入れない
- 新規に `Avatar Runtime Subsystem` を設ける
- VTube StudioはSubsystem内部の初期Backendとする
- ゆらモデル完成前はVTube Studioのサンプルモデルで検証する
- 視線はGestureとは別の独立Capability・独立制御チャネルとする
- `ReactionPlan` と実アバター制御の間に `AvatarPerformancePlan` を置く
- CoreはLive2D Parameter名やVTube Studio APIを知らない
- モデル差異はモデルプロファイルで吸収する
- Avatar機能停止時もCoreはdegraded状態で単独動作する

以上の構成により、現在のCore・Plugin分離方針を維持しながら、Live2Dアバターへの表情、ジェスチャー、視線、発話同期を段階的に追加できる。

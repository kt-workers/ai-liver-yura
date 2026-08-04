# AvatarPerformancePlan 導入設計 v1.0.0

## 1. 目的

Character LLMが生成した `ReactionPlan` を、Live2DやVTube Studioなどの描画方式に依存しないアバター演技計画へ変換する。

```text
CharacterResponse
  ↓
ReactionPlan
  ↓ 決定論的変換
AvatarPerformancePlan
  ↓
AvatarOutputPort
  ↓
Avatar Runtime
```

本層は意味や行動を再決定しない。確定済みの表情・ジェスチャー・視線意図を、アバター実行に必要な相関ID、強度、時間、割込み方針へ詳細化する。

## 2. 責務境界

### ReactionPlan

- 発話本文
- 表情名
- ジェスチャー名
- 高レベル視線Intent
- 声の意図
- 表現が変わる区間
- 発話後の間

### AvatarPerformancePlan

- Performance ID
- Activity ID
- Output Unit ID
- Priority
- 表情・ジェスチャー・視線の強度
- Segment継続時間
- Fade-in / Fade-out
- Interrupt policy
- 終了後のReturn behavior

### Avatar Runtime

- Live2D ParameterやVTube Studio Hotkeyへのマッピング
- 補間、毎フレーム更新、視線の目先行・頭追従
- Idle、呼吸、瞬き
- Performanceのスケジューリング、割込み、復帰

Coreはモデル固有Parameter、Hotkey、座標、フレームレートを知らない。

## 3. ドメイン契約

`app/domain/avatar_performance.py` に次を置く。

- `AvatarExpressionIntent`
- `AvatarGestureIntent`
- `AvatarGazeIntent`
- `AvatarPerformanceSegment`
- `AvatarPerformancePlan`
- `AvatarInterruptPolicy`
- `AvatarReturnBehavior`

`AvatarGazeIntent` は描画方式に依存しないためPort実装詳細ではなくドメイン契約とし、既存import互換のため `app.ports.avatar_output` から再公開する。

## 4. 変換規則

`AvatarPerformancePlanner` は `ReactionPlan` を決定論的に変換する。

- 表情・ジェスチャー・視線の意味名は変更しない
- 未指定強度は `1.0`
- Priorityは既存 `ActionPlanner` の出力優先度を利用する
- Performance IDはCoreで発行する
- Activity IDとOutput Unit IDを引き継ぐ
- Durationは発話文字数、発話後の間から暫定推定する
- FadeはCore共通の安全な既定値を補完する
- Segment数はReactionPlanと一致させる

LLMにPerformance ID、Priority、割込み方針、Live2D Parameterを生成させない。

## 5. 既存Actionとの互換性

既存の次のActionは維持する。

```text
CHANGE_EXPRESSION
MOVE
```

Action metadataへPerformanceを付与し、Avatar-aware UseCaseがOutput Unitごとに一度だけ `submit_performance()` を呼び出す。

Performance送信に成功した場合、同じPerformanceに属する個別表情・ジェスチャー送信を抑止する。Performance APIを持たない互換Adapter、またはPerformance送信に失敗した場合は、既存の個別操作へ縮退する。

これにより、既存Action Scheduler、字幕、音声、Topic Memoryの経路を変更せずに移行できる。

## 6. PortとCapability

`AvatarOutputPort` に次を追加する。

```python
async def submit_performance(performance: AvatarPerformancePlan) -> None:
    ...
```

既存Facadeは残す。

```python
async def set_expression(expression: str) -> None: ...
async def play_gesture(gesture: str) -> None: ...
async def set_gaze(gaze: AvatarGazeIntent) -> None: ...
```

Pluginは次のCapabilityを追加する。

```text
output.avatar.performance
```

### 6.1 段階移行中の互換境界

型契約上は `submit_performance()` を推奨するが、Plugin Factoryは移行前Adapterへこのメソッドを必須にしない。

- 既存Adapterが個別表情・Gesture・視線だけを実装している場合も登録可能
- `submit_performance()` がない場合は `output.avatar.performance` だけをUnavailableとする
- Performance Endpointの404・通信失敗時もPerformance CapabilityだけをUnavailableとする
- `expression / gesture / gaze` Capabilityは維持し、Avatar-aware UseCaseが個別Actionへ縮退する
- 個別Action側も失敗した場合に限り、Avatar Plugin全体をUnavailableとする

この境界により、CoreとAdapterを同時更新できない環境でも段階的に移行できる。

## 7. HTTP Web MVP契約

暫定HTTP Adapterは次へ送信する。

```text
POST /api/avatar/performances
```

```json
{
  "schema_version": 1,
  "type": "avatar.performance.submit",
  "performance_id": "perf-001",
  "source_activity_id": "activity-001",
  "output_unit_id": "output-001",
  "priority": 100,
  "interrupt_policy": "replace_lower_priority",
  "return_behavior": "neutral",
  "segments": [
    {
      "expression": {"name": "curious", "intensity": 0.7},
      "gesture": {"name": "head_tilt", "intensity": 0.4},
      "gaze": {"target": "viewer", "behavior": "maintain", "intensity": 0.8},
      "duration_ms": 1800,
      "fade_in_ms": 200,
      "fade_out_ms": 300
    }
  ]
}
```

HTTPはWeb MVP用の暫定Transportであり、完了通知、取消、双方向状態通知は後続のWebSocket段階で追加する。

## 8. 障害時動作

- Avatar Runtime停止時もCore、会話、字幕、音声を継続する
- Performance API非対応時は個別Actionへ縮退する
- Performance送信失敗だけで発話を失敗扱いにしない
- Performance送信失敗だけで個別Avatar Capabilityを停止しない
- Delivery-aware UseCaseの発話確定境界を維持する
- 送信済みPerformance IDの保持数を制限し、常駐Runtimeで無制限に増加させない

## 9. 今回の実装範囲

- ドメイン契約
- ReactionPlanからの決定論的変換
- Character LLMの高レベル強度・視線Schema
- Action metadataによるPerformance搬送
- Port / Plugin / HTTP AdapterのPerformance送信
- Performance Capability単独の劣化管理
- 旧Adapterおよび個別Actionへの後方互換Fallback
- 単体・統合回帰テスト

対象外：

- `test/*` 検証ブランチのdevelop取り込み
- Render棒人間Runtime側のPerformance API実装
- WebSocket
- Cancel / Status取得
- VTube Studio Backend
- Live2Dモデル固有マッピング

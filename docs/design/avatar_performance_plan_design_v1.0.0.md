# AvatarPerformancePlan 導入設計 v1.0.0

## 1. 目的

`AvatarPerformancePlan`を、Character LLMが選んだポーズを再生する仕組みではなく、Body Subsystemが生成した複数の身体TrackをAvatar Runtimeへ渡す実行契約として定義する。

```text
Activity Context ─────────┐
Internal State ───────────┤
Characterの表現意図 ──────┤
Perception ───────────────┤
Speech Presentation ──────┘
             ↓
       Body Subsystem
             ↓ compile
  AvatarPerformancePlan
             ↓
       Avatar Runtime
             ↓
       Live2D / 3D
```

Body Subsystem全体の責務は`body_subsystem_architecture_v1.0.0.md`で定義する。本契約はその出力の一つであり、呼吸、瞬き、注意選択、音声再生などBodyの全機能を表すものではない。

## 2. 責務境界

### Activity

- 継続する目的
- 主な注意対象
- 関与度
- 姿勢傾向
- 動きの活発さ
- 視線の自由度

毎フレームの角度や身体部位を指定しない。

### Character LLM

- 発話本文
- 声の意図
- 表情の意味
- 必要な場合だけ高レベルな身体表現Intent
- 必要な場合だけ意味上の注意対象
- 発話中の意味的な強調点

首、胴体、腕などの身体部位、モーション名、回数、振幅、速度、時刻、Live2D Parameterは指定しない。

### Body Subsystem

- Activity Contextと現在の身体状態を統合する
- 高レベル表現Intentを身体部位別プリミティブへ展開する
- 複数Trackの重なり、優先度、継続性を決定する
- 現在姿勢から開始する計画を作る
- 発話同期用の意味的強調を時間軸へ投影する
- AvatarPerformancePlanを生成する

### AvatarPerformancePlan

- Performance ID
- Activity ID
- Output Unit ID
- Priority
- 複数の重複可能なTrack
- Trackごとの開始オフセット、継続時間、Fade
- 加算または上書き
- 部位内優先度
- 現在姿勢からの連続性
- Track終了後の保持方針
- Performance全体の割込み方針

### Avatar Runtime

- Live2D Parameterや3D Boneへのマッピング
- 毎フレームのTrack合成
- 補間、可動範囲、安全制限
- 目、首、体の遅延追従
- Performanceの割込みと復帰
- Bodyの常駐レイヤーとの合成

Coreはモデル固有Parameter、Hotkey、座標、フレームレートを知らない。

## 3. 正規表現

正規の演技表現は、直列Segmentではなく重複可能なTrackである。

対象Channelは次とする。

- `expression`
- `attention`
- `head`
- `torso`
- `left_arm`
- `right_arm`
- `autonomous`

各Trackは次を保持する。

- `track_id`
- `channel`
- `start_offset_ms`
- `duration_ms`
- `fade_in_ms`
- `fade_out_ms`
- `blend_mode`: `override`または`additive`
- `continuity`: 現在姿勢から開始する方針
- `hold`
- `layer_priority`
- Channelに対応するIntent

一つのTrackが終了しても、他の継続中Trackをneutralへ戻さない。終了したTrackの寄与だけをFade-outする。

## 4. Body表現からの変換

`BodyExpressionPlanner`は、完成済み全身プリセットを選ばず、高レベルな意味軸から独立Trackを生成する。

現在の決定論的Fallbackでは、例として次の変換を行う。

- `agreement > 0`：うなずき方向のHead Track
- `agreement < 0`：首振り方向のHead Track
- `approach > 0`：前傾方向のTorso Track
- `approach < 0`：後退方向のTorso Track
- `surprise`：短い反射的Torso Track
- `openness`低下：左右腕を内側へ寄せるTrack
- `openness`、`warmth`、`approach`上昇：左右腕を開くTrack
- `assertiveness`上昇：姿勢を伸ばすTorso Track

これは実行プリミティブへの変換であり、Character LLMが`head_shake`や`lean_back`を直接選ぶものではない。

同じ「拒否」でも、agreement、approach、tension、openness、arousal、assertivenessなどの組合せにより、生成されるTrack、強度、重なり方が変わる。

## 5. Activity Contextとの合成

Character LLMが注意Intentを出さなくても、Activity ContextからBodyが基礎的な注意方針を作れる。

例：会話Activity

```json
{
  "attention_target": "conversation_partner",
  "engagement": 0.72,
  "posture_tendency": "open",
  "movement_energy": 0.38,
  "gaze_freedom": 0.25
}
```

明示的な首振りが終了しても、会話相手を注意対象とするActivity Contextは継続する。

## 6. ActionPlanGroupとの関係

ActionPlanGroupはActivity Turnから生じた発話、字幕、Avatar出力などを束ね、リソース競合と実行結果を管理する。

身体部位ごとのActionをActionSchedulerへ細切れに積まない。Output Unitごとに複合Performanceを一度だけ送信し、部位間の同時実行と連続性はBodyおよびAvatar Runtimeで扱う。

移行期間中は既存の`CHANGE_EXPRESSION`と`MOVE`を維持し、Action metadataへPerformanceを付与する。Performance送信に成功した場合は同じPerformanceに属する個別Avatar操作を抑止する。

## 7. 発話との関係

TTS生成はBodyの責務ではない。

```text
Character Text
  ↓
TTS Plugin
  ↓ 音声・実時間・音素/Viseme
SpeechPresentationRequest
  ↓
Body Subsystem
  ├─ 音声再生時計
  ├─ 口・Viseme同期
  └─ 強調語に同期する身体Track
```

現在の文字数によるDuration推定は、音声情報をBodyへ接続するまでの暫定Fallbackである。最終仕様では、生成済み音声の実時間を基準にする。

## 8. 互換契約

段階移行のため次を残す。

- `ReactionSegment.gesture`
- `ReactionSegment.gaze`
- `AvatarPerformanceSegment`
- `set_expression()`
- `play_gesture()`
- `set_gaze()`
- 旧Segment Payload

新しいCharacter応答では`gesture`と旧`gaze`を原則使用しない。

Performance APIがないAdapter、またはPerformance送信に失敗した環境では、既存の個別Avatar操作へ縮退する。Performance Endpointの障害だけでは、個別表情・Gesture・視線Capabilityを停止しない。

## 9. HTTP Web MVP契約

暫定HTTP Adapterは次へ送信する。

```text
POST /api/avatar/performances
```

Schema v2では`tracks`を正規表現とし、旧Runtime向けに`segments`も併送できる。

HTTPは検証用Transportである。Bodyの常時更新、完了通知、取消、状態返送、音声再生同期には後続の双方向Transportを使用する。

## 10. 障害時動作

- Avatar Runtime停止時もCore、会話、字幕を継続する
- Performance API非対応時は個別Avatar操作へ縮退する
- Performance送信失敗だけで発話を失敗扱いにしない
- Performance送信失敗だけで個別Avatar Capabilityを停止しない
- 送信済みPerformance IDの保持数を制限する
- Body出力の障害を意味判断やActivity実行の成功と混同しない

## 11. 今回の実装範囲

- 重複Track型AvatarPerformancePlan
- Bodyの高レベルドメイン契約
- ActivityからBodyActivityContextを作るBuilder
- 意味軸から部位別Trackを作る決定論的Fallback
- Character LLMの`embodied_expression`、`attention_intent`、`speech_emphasis`
- Character LLMから身体部位・モーション名を排除するPrompt
- Action metadataによるPerformance搬送
- Port、Plugin、HTTP AdapterのPerformance送信
- 旧Adapterおよび個別Actionへの後方互換Fallback
- 単体・統合回帰テスト

対象外：

- 独立プロセスとしてのBody Runtime
- Bodyの30〜60fps常時Tick
- カメラ人物・物体認識
- 外界対象の識別と選択
- TTS生成後の実音声再生時計
- Viseme同期
- WebSocketによる双方向状態通知
- VTube Studio Backend
- Live2Dモデル固有マッピング
- `test/*`検証ブランチのdevelop取り込み

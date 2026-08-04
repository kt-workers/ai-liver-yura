# Body Subsystem アーキテクチャ v1.0.0

## 1. 目的

ゆらの身体を、Character LLMが選ぶ固定ポーズ集ではなく、現在のActivity、内部状態、外界認識、発話、直前までの身体状態から連続的に動く独立Subsystemとして扱う。

Body Subsystemは「脳から命令が来たときだけ動く出力装置」ではない。LLMを待たずに常時稼働し、呼吸、瞬き、姿勢維持、視線、注意対象への追従、発話同期を担当する。

```text
Input
  ↓
Input Meaning Interpreter
  ↓
Internal Directive Planner
  ↓
Activity ────────────────┐
  ↓ 必要な場合            │ BodyActivityContext
Character LLM             │
  ↓ 発話・意味的表現意図   │
TTS生成                    │
  ↓ 音声・時間情報         │
                          ▼
                   Body Subsystem
                   ├─ Body State
Perception ──────────────→├─ Attention Controller
Camera / Cursor / Sound   ├─ Autonomous Motion
                   ├─ Expression Planner
                   ├─ Speech Presentation
                   ├─ Track Composer
                   └─ Motion Runtime
                          ├─ 音声再生
                          └─ Live2D / 3D
```

## 2. 基本原則

### 2.1 脳は身体を毎フレーム操作しない

脳側は「ユーザーと会話している」「強く拒否を表したい」「対象を見たい」のような目的と意味を渡す。首の角度、腕の角度、フレーム時刻、Live2D Parameterは指定しない。

### 2.2 BodyはLLMなしで動き続ける

次はBody内部の常駐制御で行う。

- 呼吸
- 瞬き
- 小さな眼球運動
- 姿勢の微調整
- 重心移動
- 長時間の完全静止を避ける動き
- 発話中の口の動き
- Activityで許された範囲の周辺確認
- 注意対象への目、首、体の遅延追従

### 2.3 Activityは継続文脈を渡す

Activityは毎フレームの動作命令を送らない。Bodyへ次のような継続状態を提示する。

```json
{
  "source_activity_id": "conversation-001",
  "attention_target": "conversation_partner",
  "engagement": 0.72,
  "posture_tendency": "open",
  "movement_energy": 0.38,
  "gaze_freedom": 0.25
}
```

この状態は、明示的な演技が終了してもActivityが続く間は保持される。

### 2.4 強い表現だけを要求する

驚き、拒否、喜び、怒りなど、人格的な意味を持つ身体表現が必要なときだけ`BodyExpressionRequest`を送る。

```json
{
  "expression": {
    "attitude": "firm_rejection",
    "intensity": 0.85,
    "valence": -0.7,
    "arousal": 0.65,
    "tension": 0.8,
    "openness": 0.2,
    "approach": -0.6,
    "agreement": -0.9,
    "surprise": 0.0,
    "assertiveness": 0.75,
    "warmth": 0.2
  },
  "attention": {
    "target": "conversation_partner",
    "behavior": "avoid",
    "engagement": 0.75,
    "avoidance": 0.65
  }
}
```

`head_shake`や`raise_hand`などの身体部位別モーション名は、Character LLMの標準出力にしない。

## 3. Body内部の責務

### 3.1 Body State

現在姿勢、注意対象、視線方向、表情、発話状態、継続中Track、直前動作を保持する。新しい動作はneutralではなく、現在状態から開始する。

### 3.2 Attention Controller

カメラ、カーソル、音などから得られた対象候補と、Activityおよび明示的な注意Intentを統合する。

Perceptionは「人物が右側にいる」と報告するだけであり、その人物を見るかどうかはBodyの注意方針と脳側の目的が決める。

微細な座標変化はデッドゾーンで無視し、目、首、体を異なる速度で追従させる。

### 3.3 Autonomous Motion Controller

呼吸、瞬き、Idle、姿勢変更を生成する。Character LLMを呼び出さない。

### 3.4 Expression Planner

意味軸を部位別プリミティブへ展開する。

例として、`agreement < 0`は首の横振り、`approach < 0`は上体の後退、`openness`の低下は左右腕を内側へ寄せる傾向へ個別に変換する。

これは「強く嫌がる」という完成済み全身プリセットを再生する処理ではない。複数の意味軸から独立Trackを生成し、現在状態へ重ねる。

### 3.5 Speech Presentation Controller

TTS生成はTTS Pluginが担当する。Bodyは生成済み音声、実時間、音素またはViseme、意味的な強調点を受け取る。

Bodyが共通の再生時計を開始し、次を同期する。

- 音声再生
- 口の開閉
- Viseme
- 発話中の表情
- 強調語に対応する首、視線、体の動き

音声データの生成責務をBodyへ移さない。最終再生と身体同期だけをBodyが統括する。

### 3.6 Track Composer

最終姿勢は次を毎フレーム合成する。

```text
最終姿勢
  = Activityの基礎姿勢
  + 内的状態の身体傾向
  + 注意対象への向き
  + 明示的な身体表現
  + 発話同期動作
  + 呼吸・瞬き・Idle
```

一時Trackが終了したときは、そのTrackの影響だけをFade-outする。他の継続TrackやActivity姿勢をneutralへ戻さない。

## 4. Character LLMの責務

Character LLMは主に発話を生成する。発話に密接な人格的表現が必要な場合だけ、次を追加できる。

- `embodied_expression`
- `attention_intent`
- `speech_emphasis`

Character LLMは次を出力しない。

- 身体部位
- モーション名
- ポーズ名
- 角度
- 回数
- 振幅
- 速度
- 開始時刻
- Performance ID
- Live2D Parameter
- VTube Studio Hotkey

Bodyが自律的に処理できる生理動作や周辺反応は、Character LLM出力を省略する。

## 5. AvatarPerformancePlanとの関係

`AvatarPerformancePlan`はBody Subsystemではない。Bodyが複数の身体表現をAvatar Runtimeへ渡すための実行契約である。

```text
Activity / Character / Internal State / Perception / Speech
                         ↓
                  Body Subsystem
                         ↓ compile
             AvatarPerformancePlan
                         ↓
                  Avatar Runtime
```

`AvatarPerformancePlan`は目、首、胴体、左右腕、表情などの重複Trackを持つ。Avatar RuntimeはTrackを毎フレーム補間し、Live2Dまたは3D固有Parameterへ変換する。

## 6. ActionPlanGroupとの関係

ActionPlanGroupはActivity Turnから生じた発話、字幕、Body要求などを束ね、リソース競合と実行結果を管理する。

身体部位ごとのActionをActionSchedulerへ大量に積まない。Bodyへの要求は1つの複合要求として渡し、部位間の同時実行と連続性はBody内部で扱う。

## 7. 優先順位

Body内部では概ね次の順で制約する。

1. モデル可動範囲、安全制限
2. 緊急の明示的表現要求
3. 発話同期の強調
4. Activityの注意・姿勢方針
5. 周辺対象への自律反応
6. 呼吸、瞬き、Idle

上位Trackは下位Trackを必ず完全停止するわけではない。例えば強い首振り中も呼吸と表情は継続する。

## 8. 更新周期

意味判断と身体更新の周期を分ける。

```text
脳・LLM                 数百ms〜数秒
Activity Context更新    Activity遷移時または意味のある変化時
Perception              センサーに応じた周期
Body制御                30〜60fps
Live2D / 3D描画         描画環境のフレーム周期
```

Bodyの30〜60fpsループでLLMを呼び出さない。

## 9. 現在の実装範囲

PR #158では次を実装する。

- `BodyActivityContext`
- `BodyExpressionRequest`
- `EmbodiedExpressionIntent`
- `BodyAttentionIntent`
- `SpeechEmphasis`
- `SpeechPresentationRequest`
- `BodySubsystemPort`
- Activityから身体文脈を作るBuilder
- 意味軸から部位別Trackを合成する決定論的Fallback
- Character LLMの高レベルIntent Schema
- 旧`gesture` / `gaze`経路の移行互換
- `AvatarPerformancePlan`による複合Track送信

現段階では次を実装しない。

- 独立プロセスとしてのBody Runtime
- カメラ人物・物体認識
- 外界対象の識別
- Bodyの常時Tick Loop
- TTS生成後の実音声再生時計
- Viseme同期
- WebSocketによる双方向状態通知
- Live2D / VTube Studio固有変換

## 10. 移行手順

1. Bodyのドメイン契約と高レベルIntentを導入する
2. `gesture`をCharacter LLMの標準出力から外す
3. Activity ContextとBody ExpressionをBodyへ送るGatewayを実装する
4. TTS生成結果を`SpeechPresentationRequest`としてBodyへ渡す
5. Bodyの常時Tick、Attention、Autonomous Motionを独立Runtimeへ実装する
6. AvatarPerformancePlanをBody内部のコンパイル結果に限定する
7. 旧個別Avatar Actionを削除可能になるまで互換経路を維持する

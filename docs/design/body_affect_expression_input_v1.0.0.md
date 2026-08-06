# 感情起点Body Expression入力設計 v1.0.0

## 1. 目的

確定済みEmotion Stateと採用済みInteraction Intentionを、Pose計算前の高レベルBody表現入力へ変換する。

Emotionをモーション名、関節角度、固定Gestureへ直接変換しない。感情基礎表現と対人的な一時表現を別レイヤーで保持し、後段の連続Pose Controllerが合成できるようにする。

## 2. 因果経路

```text
Emotion State
  → BodyAffectBaselineProjector
  → BodyAffectBaseline

Interaction Intention
  → InteractionExpressionProjector
  → InteractionExpressionProjection

BodyActivityContext
BodyAffectBaseline
InteractionExpressionProjection
  → BodyExpressionInputBuilder
  → BodyExpressionInput
```

`BodyExpressionInput`はPoseではなく、Pose生成の根拠となる意味的入力である。

## 3. 既存Body契約の責務分離

旧`app/domain/body.py`は次を同時に保持していた。

- 高レベル表現意図
- 注意意図
- Activity Body文脈
- 発話強調
- Body表現要求
- 音声提示要求

次へ分け、`body.py`は旧import互換の再公開Facadeへ縮小した。

```text
body_expression.py
  └─ EmbodiedExpressionIntent

body_attention_intent.py
  ├─ BodyAttentionBehavior
  └─ BodyAttentionIntent

body_activity_context.py
  ├─ BodyPostureTendency
  └─ BodyActivityContext

body_expression_request.py
  └─ BodyExpressionRequest

body_speech.py
  ├─ SpeechEmphasis
  └─ SpeechPresentationRequest

body.py
  └─ 互換再公開のみ
```

新規実装は責務別Moduleから直接importする。

## 4. Body Affect契約

### BodyAffectChannels

Emotion StateのReactive Emotionを変更せずSnapshotとして保持する。

- joy
- amusement
- anger
- sadness
- fear
- surprise
- discomfort
- emotional_pressure

### BodyAffectBaseline

Body表現の基礎となるモデル非依存軸。

- dominant_affect
- intensity
- valence
- arousal
- tension
- openness
- approach
- warmth
- surprise
- assertiveness
- expressiveness
- avoidance

この型は次を持たない。

- Motion名
- Gesture名
- Joint ID
- 角度
- 実行権限
- Transport情報

### BodyAffectBaselineProjector

確定済み`EmotionState`だけを入力とする純粋Projector。

- Emotionを更新しない
- Desire／Driveを更新しない
- Activityを選択しない
- Poseを生成しない
- Character本文を参照しない

Reactive Emotionと既存のvalence、arousal、talkativenessを有限な意味軸へ射影する。

## 5. 顔表現

### BodyFacialAffectTarget

モデル固有BlendShapeへ変換する前の意味的ターゲット。

- smile
- frown
- brow_raise
- brow_tension
- eye_widen
- eye_narrow
- mouth_tension

### BodyFacialAffectResolver

```text
BodyAffectBaseline
  + optional EmbodiedExpressionIntent overlay
  → BodyFacialAffectTarget
```

対人的Overlayが存在しても感情基礎表現を消さない。

例:

- sadnessが強い状態でcomfort意図を採用した場合、悲しみのfrownを維持しながらwarmth由来の穏やかさを少量重ねる
- fearが強い場合、eye_widenとbrow_tensionを基礎として保持する
- set_boundaryのassertivenessはeye_narrowやbrow_tensionへ重ねるが、Emotion自体を怒りへ書き換えない

## 6. 注意意図

### BodyAttentionIntentResolver

入力:

- `BodyActivityContext`
- `BodyAffectBaseline`
- optional `InteractionExpressionProjection`

優先順:

1. 明示Activity Contextのattention target
2. Interaction Expressionのtarget
3. targetがなければ`None`

Interaction Expressionのbehaviorを維持し、Activity Contextのengagementを採用する。感情のavoidanceは既存の対人的avoidanceを上書きせず、必要な場合だけ増加させる。

## 7. BodyExpressionInput

```text
BodyExpressionInput
├─ BodyActivityContext
├─ BodyAffectBaseline
├─ BodyFacialAffectTarget
├─ optional EmbodiedExpressionIntent overlay
└─ optional BodyAttentionIntent
```

基礎感情とInteraction Overlayを別フィールドに保持する。

Payloadは明示的に次を示す。

```text
grants_execution_authority = false
contains_pose = false
```

## 8. Interaction Expression Profile分離

旧`InteractionExpressionProjector.project()`は、全意図のProfile定数と射影処理を1つの大きな条件分岐で担当していた。

次へ分離した。

```text
interaction_expression_profiles.py
  ├─ InteractionExpressionProfile
  └─ finite intention setのProfile定義

interaction_expression_projector.py
  ├─ Profile選択
  ├─ target正規化
  └─ 型付きProjection生成
```

Profile集合は`InteractionIntentionType`の有限集合を完全に覆う。

## 9. 実行境界

Interaction Intentionが`act`でも、BodyExpressionInputは次を意味しない。

- Activity実行済み
- Body動作実行済み
- Capability確認済み
- Authority確認済み
- Safety確認済み

実行事実は既存のActivity Execution Result境界だけが決定する。

## 10. 工程5で行わないこと

- BodyPoseFrame生成
- 30〜60fps Tick
- ばね・減衰の時間積分
- 呼吸・瞬きScheduler
- Attention候補選択
- 一時身体制約の再生
- HTTP／WebSocket送信
- 棒人形描画
- Live2D／3D Adapter変換

これらは工程6以降で責務別に実装する。

## 11. テスト

- joyから正のvalence、warmth、approachを生成
- fearからtension、avoidanceを生成
- baselineがMotion／Jointを含まない
- sadness基礎表現をcomfort overlayが消さない
- 感情基礎とInteraction Overlayを別レイヤーで保持
- Interaction Intentionなしでも感情基礎表現を生成
- set_boundaryの注意回避を反映し、実行権限は付与しない
- 旧`app.domain.body` importの互換維持
- 非有限Emotion値の拒否
- Interaction Expression Profileが有限意図集合を完全に覆う
- ProfileにMotion／Gesture／Joint／Angle契約がない

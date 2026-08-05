# 状態駆動 Living Body Runtime 設計 v1.0.0

## 1. 目的

ゆらの身体を、ユーザーから受けた「右手を上げる」等の操作命令を実行する装置ではなく、
ゆら自身のEmotion、Drive、Desire、Activity、注意、人格的表現意図、発話状態、現在姿勢を
統合して常時動く身体として実装する。

本設計では表情をBodyの付属出力ではなく、視線、頭、胴体、腕、呼吸、瞬き、口形と同じ
連続身体状態の中心要素として扱う。

## 2. 関連設計との関係

本設計は次の既存設計を置き換えず、Coreの通常起動へ接続するための実装境界を具体化する。

- `body_subsystem_architecture_v1.0.0.md`
- `body_runtime_mvp_v1.0.0.md`
- `avatar_performance_plan_design_v1.0.0.md`
- `body_pose_frame_stream_v1.0.0.md`
- `character_response_content_plan_and_conversation_evaluation_design_v1.0.0.md`
- `internal_state_response_projection_audit_v1.0.0.md`

## 3. 制御フロー

```text
Agent State
├─ Emotion ───────────────┐
├─ Drive ─────────────────┤
├─ Desire / Motivation ───┤ Character表現方針にも投影
├─ Moral ─────────────────┤
├─ Relationship ──────────┤
└─ Target Interest ───────┘
        ↓ event_payload / Response Context
Activity Context
├─ attention target
├─ engagement
├─ posture tendency
├─ movement energy
├─ gaze freedom
└─ BodyAffectContext
   ├─ valence / arousal
   └─ joy / amusement / anger / sadness / fear / surprise / discomfort
        +
BodyExpressionRequest
├─ facial expression
├─ valence / arousal / tension
├─ openness / approach / agreement
├─ surprise / assertiveness / warmth
└─ attention intent
        +
SpeechPresentationRequest
├─ duration
├─ emphasis
└─ active speech clock
        ↓
StateDrivenBodyPoseRuntime
        ↓
StateDrivenBodyController
├─ Emotion基礎表情
├─ Procedural baseline
├─ Character表現Overlay
├─ Attention / gaze
├─ Head / torso / arms
├─ Breathing / blink / micro motion
└─ Speech mouth fallback
        ↓ 30〜60fps
BodyPoseFrame
├─ pose
├─ velocity
├─ joints
├─ blend_shapes
├─ gaze_vector
├─ inner_state
└─ attention_target_id
        ↓
Avatar Adapter
├─ 検証用棒人形
├─ Live2D
└─ 3D / VRM
```

## 4. 入力責務

### 4.1 Emotion／Drive

通常会話Eventへ確定済みの`emotion`と`drive`が格納されている場合、
`BodyActivityContextBuilder`が次へ一方向投影する。

```text
event_payload.emotion
  → BodyAffectContext
  → 基礎表情・覚醒度・緊張・回避・運動活性

event_payload.drive.engagement
  → BodyActivityContext.engagement

event_payload.drive.energy
  → BodyActivityContext.movement_energy

event_payload.drive.curiosity
  → BodyActivityContext.gaze_freedom
```

BodyはEmotionやDriveを再評価しない。Coreで確定したSnapshotだけを使用する。
Character LLMが表情Intentを省略しても、現在感情は弱い基礎表情と動き方として残る。

Desire、Motivation、Moralは既存のResponse Content PlanとCharacter表現意図を通じてBodyへ
影響する。これらをBodyが独自にActivity選択や価値判断へ使用しない。

### 4.2 Activity

Activityは身体部位や毎フレーム角度を指定しない。継続する注意、関与、姿勢傾向、動きの
活発さ、視線自由度をBodyへ渡す。

### 4.3 Character LLM

Character LLMはセリフと高レベルな表現意図を出す。関節座標、IK目標、振幅、速度、
反復回数、Live2D Parameter、完成モーション名は指定しない。

### 4.4 BodyExpressionRequest

BodyExpressionRequestは、喜び、共感、拒否、驚き、戸惑い等の人格的意味をBodyへ伝える。
Bodyは次の意味軸を顔と身体へ同時に展開する。

- valence: 微笑み／しかめ面
- arousal: 動きの活性
- tension: 目の狭まり、眉、身体の硬さ
- openness: 腕や姿勢の開閉
- approach: 前傾／後退
- agreement: うなずき／首振り
- surprise: 目、眉、口、反射姿勢
- assertiveness: 姿勢の伸び
- warmth: 微笑みと開いた姿勢

### 4.5 発話

発話中は、表情を消さずに口形を加算する。音素／Viseme未接続時は周期的なjaw_openを
暫定Fallbackとして使用する。音素情報が利用可能になった後は同じSpeech Presentation境界で
置き換える。

### 4.6 明示的な身体操作

ユーザーによる身体操作要求は正規の主入力ではない。将来対応する場合も、Bodyの現在状態へ
一時的な制約として重ねる。

```text
誤り:
StructuredInputMeaning -> BodyMotionRequest -> 身体

正規:
内部状態・Activity・表現意図 -> Living Body
                               + optional temporary constraint
```

一時制約中も、表情、視線、呼吸、瞬き、発話同期を停止しない。

## 5. 表情の正規契約

表情は`BodyPoseFrame.blend_shapes`へモデル非依存名で出力する。

初期Canonical BlendShape:

- `eye_blink_left`
- `eye_blink_right`
- `eye_squint_left`
- `eye_squint_right`
- `brow_raise`
- `brow_lower`
- `jaw_open`
- `mouth_smile`
- `mouth_frown`

Live2D Adapterはこれらを対象モデルのParameterへ、3D AdapterはBlendShape／Morph Targetへ
変換する。Coreはモデル固有名を知らない。

表情は二層で合成する。

```text
確定済みEmotionの基礎表情
  + Character／Internal Directive由来の一時的な人格表現
  + 発話口形
```

一時表現終了後もEmotion基礎表情は残る。

## 6. 連続性

- 新しい表現は現在姿勢を開始点とする
- 表情はattack／hold／release envelopeで出入りする
- 発話口形は表情へ加算する
- 呼吸、瞬き、注意、Activity姿勢、Emotion基礎表情は別レイヤーとして継続する
- 表現終了時はその寄与だけを除去する
- 毎回neutralまたはホーム姿勢へ戻らない

## 7. Runtime構成

`StateDrivenBodyPoseRuntime`は既存`LivingBodyRuntime`を拡張する。

- Activity Context Gatewayを維持
- Emotion／Drive SnapshotをBody Contextへ投影
- Body Expression Queueと旧AvatarPerformancePlanを互換維持
- Speech Presentation Gatewayを維持
- 同じ意味要求を`StateDrivenBodyController`へ渡す
- 毎TickのBodyPoseFrameを`BodyPoseFrameOutputPort`へ送る
- Pose出力障害でCore、会話、次Tickを止めない

`YURA_BODY_POSE_OUTPUT_URL`が設定された場合、Composition RootはこのRuntimeを選択する。
未設定でAvatar Outputだけがある場合は、従来のLivingBodyRuntimeへ縮退する。

## 8. Transport

検証段階では`HttpBodyPoseFrameOutput`を使用する。

- Queueサイズ1
- 最新Frame優先
- 古い未送信Frameを破棄
- HTTP待ちでBody Tickを停止しない
- 接続失敗を診断情報へ隔離

本番の正規TransportはWebSocket等の双方向ストリームへ置き換える。

## 9. 棒人形モック

`gui/yura-core-stick-mock`は表示専用である。

担当:

- BodyPoseFrame受信
- SSEによるブラウザ中継
- pose、blend_shapes、gazeの描画
- 接続状態とPayload表示

担当しない:

- 感情判断
- 表情選択
- Motion生成
- IK
- Activity判断
- 自然言語解釈

棒人形で表情が見えない場合は、Core FrameまたはAdapterの欠落として検出できる。

## 10. 現在の実装範囲

実装済み:

- StateDrivenBodyController
- 通常会話EventのEmotion／DriveからBodyActivityContextへの型付き投影
- CharacterがIntentを省略しても残るEmotion基礎表情
- 高レベル表現意図の顔・頭・胴体・腕への同時投影
- 表情BlendShape
- 表情を維持した発話口形Fallback
- Activityによる基礎姿勢と注意候補
- Canonical joints／gaze／blend_shapesを含むFrame
- 通常Composition Root接続
- 最新Frame優先HTTP出力
- 表情対応棒人形モック
- Controller／Runtime／状態搬送回帰テスト

後続:

- Desire／Motivation／MoralのBody固有意味軸への型付き投影
- Relationshipによる表情開放度の調整
- 音素／Viseme同期
- 眉・頬・瞳孔等のCanonical拡張
- Perception Adapterからの低遅延注意候補
- WebSocket Transport
- Live2D Parameter Adapter
- VRM／3Dモデル固有Adapter

## 11. 受け入れ条件

1. ユーザーが身体命令を出さなくてもBodyが動き続ける
2. Characterが表情Intentを省略しても、現在Emotionが弱い基礎表情へ現れる
3. Characterの喜び、悲しみ、怒り、驚き等が顔へ明確に現れる
4. 同じ表現要求が視線、姿勢、腕へも整合して現れる
5. 発話中も表情が消えない
6. Activityの注意対象と基礎姿勢が一時表現終了後も継続する
7. 出力先停止時もCore会話が継続する
8. 棒人形は受信Frameを描画するだけで判断しない

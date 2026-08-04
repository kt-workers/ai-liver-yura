# Body Subsystem アーキテクチャ v1.0.0

## 1. 目的

ゆらの身体を、Character LLMが選んだ固定ポーズを順番に再生する装置ではなく、
Activity、内部状態、外界認識、発話、現在姿勢を統合して常時動く独立Subsystemとして扱う。

BodyはLLMを待たずに稼働し、呼吸、姿勢維持、注意、視線、首、胴体、腕、表情、
発話同期を連続的に制御する。

## 2. システム上の位置

```text
外界入力
  ├─ テキスト入力
  ├─ マイク音声
  ├─ カメラ映像
  └─ マウス等の操作入力
          ↓
Perception / 入力Adapter
  ├─ 意味的観測 ───────────────→ 意味解析・内部指令
  └─ 空間・低遅延観測 ─────────→ Body Attention Controller

意味解析LLM
  ↓ StructuredInputMeaning
内部指令LLM
  ↓ InternalDirective
Activityの作成・更新
  ↓
Activity Manager / Action Planner / ActionPlanGroup
  ├─ Character LLM（必要時のみ）
  ├─ SPEAK / TTS生成
  ├─ Subtitle / Plugin Action
  ├─ BodyActivityContext
  └─ BodyExpressionRequest
          ↓
Body Runtime（非LLM・既定30fps）
  ├─ Body State
  ├─ Attention Controller
  ├─ Autonomous Motion
  ├─ Expression Planner
  ├─ Speech Presentation
  └─ Track Composer
          ↓
AvatarPerformancePlan
          ↓
Avatar Runtime
          ↓
Live2D / 3D / 検証用棒人間
```

## 3. Perceptionの二経路

カメラ、マイク、マウスはBodyだけの入力ではない。認識結果を用途別に分ける。

### 3.1 脳へ渡す意味的観測

- ユーザーが入室した
- 名前を呼ばれた
- 手を振った
- 物が落ちた
- 会話内容
- 操作対象が変わった

これらはEventまたはStructured Inputとして意味解析・内部指令へ渡し、Activityや判断に
利用する。

### 3.2 Bodyへ渡す低遅延観測

- 対象のおおよその画面位置
- 音源方向
- 対象が移動したか
- カーソル位置と速度
- 対象の検出信頼度

これらは視線や首の追従に使う。生映像・生音声を毎フレームLLMへ渡さない。

```text
人物が右側にいる
  → Bodyは必要なら目を先に右へ向けられる
  → 脳は「その人物を見る／無視する／確認する」を意味判断する
```

反射的な一瞥はBodyの許可範囲内で行えるが、誰を優先して見るかという人格的判断は
Activityと脳側の方針に従う。

## 4. Activityの位置付け

Activityは意味解析LLMやCharacter LLMと同列の変換コンポーネントではない。

既存どおり、ゆらが継続して行っている目的・状態と、TurnごとのActionを束ねる
ドメイン概念・実行管理単位である。

```text
内部指令
  ↓ Activityを作成・更新
Activity
  ├─ goal / context / lifecycle
  └─ TurnごとのActionPlanGroup
       ├─ Character生成
       ├─ SPEAK / TTS
       ├─ Subtitle
       ├─ Body Context更新
       ├─ Body Expression Request
       └─ その他Plugin Action
```

ActivityはBodyへ毎フレーム角度を送らない。注意対象、関与度、姿勢傾向、動きの活発さ、
視線自由度などを継続文脈として渡す。

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

一時的な首振りやうなずきが終わっても、このActivity文脈はActivityが続く間保持される。

## 5. Character LLMの責務

Character LLMはActivity実行中に必要な場合だけ呼ばれ、主に発話と人格的な表現意図を
生成する。

出力可能なもの：

- セリフ
- Voice Intent
- `embodied_expression`
- `attention_intent`
- `speech_emphasis`
- 顔表情の高レベル名

出力しないもの：

- 身体部位の角度
- Live2D Parameter
- モーション開始時刻
- 振幅、速度、反復回数
- 完成済み全身ポーズ
- VTube Studio Hotkey
- Performance ID

Character LLMを通さないもの：

- 呼吸
- 瞬き
- 微細な姿勢変更
- Activityで許された視線の一瞥
- 目、首、体の遅延追従
- 長時間の完全静止を避ける動き

## 6. Character・TTS・Bodyの経路

Character LLMからTTS Pluginへ直接出力する構成ではない。

```text
Character LLM
  ↓ CharacterResponse
Action Planner / ActionPlanGroup
  ├─ speech text + voice intent
  │       ↓
  │    SPEAK Action
  │       ↓
  │    TTS Plugin
  │       ↓ 生成音声・実時間
  │    Action実行Gateway
  │       ↓
  │    SpeechPresentationRequest
  │       ↓
  └────→ Body Runtime

CharacterResponseの表現意図
  ↓ BodyExpressionRequest
Body Runtime
```

TTS Pluginは音声生成を担当する。Bodyは生成済み音声のpresentation ID、実時間、強調点を
共通時計へ登録し、将来的に音声再生、口、Viseme、表情、身体強調を同期する。

現在の通常経路では、既存AudioPlayerによる再生を維持しながら、準備済みWAVの実時間または
推定時間をBodyへ登録する。実音声再生の所有権をBodyへ完全移行する工程は後続とする。

## 7. Bodyへの明示的表現要求

驚き、拒否、肯定、喜び、怒りなど、意味のある表現が必要な時だけ
`BodyExpressionRequest`を送る。

```json
{
  "facial_expression": "disgusted",
  "facial_intensity": 0.9,
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

Bodyはこれを完成済み「強く嫌がる」プリセットへ変換しない。意味軸から表情、注意、首、
胴体、左右腕の独立Trackを生成する。

## 8. Body内部の責務

### 8.1 Body State

現在Activity、姿勢、注意対象、表情、発話状態、要求Queue、直前のPerformance、診断状態を
保持する。新しい動作はneutralではなく現在状態から開始する。

### 8.2 Attention Controller

意味上の対象とPerceptionによる現在位置を結び付ける。微細な位置変更はデッドゾーンで
無視し、目、首、体を異なる速度で追従させる。

### 8.3 Autonomous Motion

LLMなしで呼吸、瞬き、微細な揺れ、Idle姿勢変更を生成する。

### 8.4 Expression Planner

意味軸を独立Trackへ展開する。

- `agreement > 0`：うなずき
- `agreement < 0`：首の横振り
- `approach > 0`：前傾
- `approach < 0`：後退
- `surprise`：反射的な後退
- `openness`低下：腕を内側へ寄せる
- `openness`・`warmth`上昇：腕を開く
- `assertiveness`上昇：姿勢を伸ばす

### 8.5 Speech Presentation

生成済み音声の実時間と発話状態を保持する。将来は共通再生時計、音素、Viseme、強調語の
実時間同期を所有する。

### 8.6 Track Composer

```text
最終姿勢
  = Activityの基礎姿勢
  + 内的状態の身体傾向
  + 注意対象への向き
  + 明示的な身体表現
  + 発話同期動作
  + 呼吸・瞬き・Idle
```

一時Track終了時は、そのTrackの影響だけをFade-outする。他の継続Trackをneutralへ戻さない。

## 9. ActionPlanGroupとの関係

ActionPlanGroupはActivity Turnから生じる発話、字幕、Body要求、Plugin Actionを束ね、
リソース競合、順序、キャンセル、実行結果を管理する。

身体部位ごとのActionをActionSchedulerへ細切れに積まない。ActionPlanGroupからBodyへは
高レベルな複合要求を渡し、部位間の同時実行と連続性はBody内部で扱う。

発話を含むSegmentは次の順に同期実行する。

```text
Subtitle
  → Body Context / Body Expression
  → 互換MOVE（Body成功時は省略）
  → SPEAK / TTS / Speech Presentation
```

複数SegmentはSegment番号順に進むため、後続Segmentの身体表現だけが先行しない。

## 10. AvatarPerformancePlan

`AvatarPerformancePlan`はBody Subsystemそのものではなく、BodyからAvatar Runtimeへ渡す
エンジン非依存の実行契約である。

独立チャネル：

- expression
- attention
- head
- torso
- left_arm
- right_arm
- autonomous

各Trackは開始オフセット、継続時間、Fade、加算／上書き、優先度、保持、現在姿勢からの
連続性を持つ。

## 11. Lifecycleと障害分離

通常の`python -m app`起動時：

1. Body対応Character ParserとAction PlannerをComposition Rootへ組み込む
2. Avatar Output Pluginを初期化する
3. Avatar Outputが利用可能ならBody Runtimeを生成・束縛する
4. Body RuntimeのTick Loopを開始する
5. Application終了時にBodyを先に停止する
6. Body束縛を解除してからAvatar Pluginを停止する

Avatar Runtimeが停止しても、Bodyの送信失敗はCore会話、Activity、字幕、次のTickを停止しない。

## 12. 更新周期

```text
脳・LLM                 数百ms〜数秒
Activity Context更新    Activity遷移時または意味のある変化時
Perception              センサーごとの周期
Body Runtime            既定30fps
Avatar描画               requestAnimationFrame / 描画環境周期
```

Body Tick内ではLLMを呼び出さない。

## 13. 現在の実装範囲

実装済み：

- Bodyドメイン契約とPort
- 通常Application lifecycleへのBody Runtime接続
- Activity Context Gateway
- Character表現Intent Gateway
- TTS準備済み音声時間のSpeech Presentation Gateway
- Body対応Character Schema・Parser・Prompt
- 意味軸から表情・注意・身体Trackを生成するPlanner
- 既定30fpsの常駐Body Runtime
- Activity基礎姿勢
- `breathing`と`micro_sway`
- 優先度付き表現Queue
- 重複Track型AvatarPerformancePlan
- HTTP Avatar Output
- 障害分離と診断Snapshot
- 旧Gesture・個別Avatar Actionへの互換Fallback
- 検証用棒人間Runtimeとのローカル接続

後続：

- カメラ・マイクのPerception Adapter
- 意味的観測を脳へ送るEvent経路
- 対象位置・音源方向をBodyへ送る低遅延経路
- 実音声再生をBodyが所有する共通時計
- 音素・Viseme同期
- 瞬き・眼球微動の詳細制御
- WebSocketによる低遅延状態通知
- Live2D / VTube Studio固有変換
- Body Runtimeの独立プロセス化
- Avatar Runtimeからの完了・中断・失敗通知

ローカル結合手順は
`docs/guides/body_runtime_stick_model_local_validation.md`を参照する。

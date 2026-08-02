# マルチモーダル入力意味解析アーキテクチャ v1.0.0

## 1. 目的

外部入力を文字列の表面規則で判定せず、入力媒体ごとの観測情報を文脈込みで意味構造へ変換し、Coreの後段処理が媒体差を意識せず利用できるようにする。

対象入力はテキストに限定しない。

- テキスト入力
- 音声入力
- カメラ映像
- 接触・ポインタ操作
- 将来追加されるセンサー・外部イベント

## 2. 基本方針

意味解析にはLLMまたはマルチモーダルモデルを使用する。

日本語の会話では、次の理由から疑問符、語尾、固定語句だけによる決定論的分類を正規経路にしない。

- 疑問符を省略する
- 語尾を崩す
- 名詞や断片語だけで直前質問へ回答する
- 「かな」を質問、推量、締めのいずれにも使う
- 音声では抑揚や間によって意味が変わる
- 映像や接触には文末記号が存在しない

決定論的処理は、意味そのものの推測ではなく次に限定する。

- JSON Schema検証
- enum・型・範囲の検証
- Activity Registryとの照合
- Authority・Capability・Safety・Constraintの検証
- 不正・低確信度時の安全なFallback

## 3. 全体フロー

```text
External Input
  ↓
Input Adapter / Perception Adapter
  ↓
Modality Observation
  ↓
Semantic Interpretation / Multimodal Fusion LLM
  ↓
Structured Input Meaning
  ↓
Situation Evaluator
  ↓
Behavior Planner
  ↓
Activity / Conversation Response Mode
  ↓
Character LLM
```

現行実装ではSituation Evaluatorが意味解析とActivity候補選択の両方を担っている。

今回の第一段階では、Situation EvaluatorのLLM出力を文脈的な意味構造へ拡張する。将来は次の二責務へ分離する。

```text
Input Meaning Interpreter
  入力媒体を統合して意味構造を生成

Situation Evaluator
  意味構造と現在状態からActivity候補・operationを評価
```

## 4. 入力Adapterの責務

Adapterは意味を最終決定せず、各媒体から観測可能な情報を構造化する。

### 4.1 テキスト

```json
{
  "modality": "text",
  "text": "しまなみ海道だよ",
  "source": "console",
  "timestamp": "..."
}
```

### 4.2 音声

音声入力は少なくとも次を分離する。

```json
{
  "modality": "speech",
  "transcript": "今日のところはこのくらいかな",
  "transcript_confidence": 0.94,
  "prosody": {
    "intonation": "falling",
    "energy": 0.42,
    "tempo": "slow",
    "pause_before_ms": 310
  },
  "speaker": "user"
}
```

STTは文字起こしを担当し、発話意図の最終判定は行わない。抑揚、速度、音量、間などは意味解析へ渡す観測情報である。

### 4.3 カメラ映像

映像AdapterまたはVision Modelは、生画像をCoreへ無制限に流さず、必要な観測へ縮約する。

```json
{
  "modality": "vision",
  "observations": [
    {
      "kind": "person_gesture",
      "label": "wave",
      "confidence": 0.88
    },
    {
      "kind": "gaze",
      "target": "avatar",
      "confidence": 0.72
    }
  ],
  "frame_window_ms": 1200
}
```

顔、視線、身振り、物体、場面変化などを観測候補とし、個人識別や断定は必要最小限にする。

### 4.4 接触・ポインタ操作

接触入力は既存のtouch featuresを観測として扱う。

- 対象へ接触したか
- 接触対象
- 部位
- click / drag / hover
- 軌跡
- 速度
- 継続時間
- リズム

快・不快、親密、攻撃などの意味はAdapterで固定せず、関係性・感情・継続文脈と合わせて意味解析する。

## 5. Structured Input Meaning

将来の正規契約は媒体に依存しない。

```json
{
  "source_modalities": ["speech", "vision"],
  "semantic_summary": "人間が会話を終える意向を穏やかに示した",
  "speech_act": "closing",
  "conversation_phase": "winding_down",
  "response_expectation": "acknowledge_and_close",
  "turn_relation": "continuation",
  "topics": ["current_conversation"],
  "entities": [],
  "affect_cues": {
    "valence": "neutral_positive",
    "arousal": "low"
  },
  "requested_activity": null,
  "negated": false,
  "hypothetical": false,
  "past_reference": false,
  "confidence": 0.93,
  "evidence_refs": ["speech:transcript", "speech:prosody"]
}
```

第一段階では既存契約との互換性を保つため、`speech_act`を次へ拡張する。

- `greeting`
- `statement`
- `question`
- `answer`
- `acknowledgement`
- `closing`
- `request`
- `proposal`
- `command`

## 6. speech_actの文脈契約

### question

人間がゆらから回答を得ようとしている。

疑問符は必須ではない。

### answer

直前のゆらの質問または確認に対する回答。

```text
ゆら: どこへ行ったの？
人間: しまなみ海道だよ
```

`しまなみ海道だよ`はstatementではなくanswerである。

### acknowledgement

相槌、同意、受領、短い反応。

入力の主目的が新しい情報提供や質問ではない。

### closing

会話を締める、区切る、離脱する意図。

```text
今日のところはこのくらいかな
```

表面上は推量にも見えるが、会話履歴を含めてclosingと判断する。

## 7. 応答モードとの接続

Conversation Response Modeは入力文字列を再解析しない。

```text
speech_act=question
  → answerを強く支持

speech_act=answer
  → 直後の再質問を抑え、listen/react/speakを支持

speech_act=acknowledgement
  → 通常はlisten/reactを支持
  → 強いcuriosity等があればaskも選択可能

speech_act=closing
  → listen/react/observeを支持
  → askと長いspeakを抑える
```

これは固定禁止ではなく、LLM意味解析結果と内的状態を合わせた重み付けである。

## 8. LLMと決定論的処理の境界

LLMが担当する。

- 曖昧な入力の意味解釈
- 会話履歴との関係
- 複数媒体の意味統合
- speech act
- conversation phase
- 応答期待
- 話題・参照対象
- confidenceと根拠参照

Coreが決定論的に担当する。

- 構造の検証
- 候補外Activityの拒否
- Activity Definitionとの照合
- Capability確認
- Authority確認
- Safety確認
- 実行結果の確定
- Character発話の事実整合性検証

LLMはActivityの実行成功、Providerの可用性、権限、安全性を確定しない。

## 9. Fallback

意味解析が失敗した場合は、表面文字列の疑問符や語尾から意味を断定しない。

```text
不正JSON
低confidence
未知enum
モデル障害
```

上記の場合は、次のいずれかへ安全に縮退する。

- `speech_act=statement`
- `conversation_phase=active`
- Activityを実行しない通常会話
- 必要な場合だけ確認応答

Fallbackは仮の意味であり、実行許可を与えない。

## 10. 今回の実装範囲

- Situation Evaluator Promptへ文脈的speech act定義を追加
- `answer`、`acknowledgement`、`closing`を契約へ追加
- 応答モード選択から入力文字列の表面判定を除外
- LLM意味解析結果を応答モードの重みとして使用
- 実プロセスログで確認された質問連続と終了局面の問題を回帰テスト化

## 11. 後続実装

1. `ModalityObservation`契約の追加
2. Text／Speech／Vision／Touch Adapterの共通入力Port
3. `StructuredInputMeaning`の独立ドメイン型
4. Input Meaning InterpreterとSituation Evaluatorの責務分離
5. 音声prosodyの入力
6. Vision observationの入力
7. 複数媒体の時間窓によるFusion
8. confidence・evidenceのTrace表示
9. 管理画面で意味解析結果を確認する診断UI

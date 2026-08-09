# Character Language Realizer Architecture v1.0.0

## 1. 目的

Character LLMの責務を、内部状態・状況・実行事実を解釈して「何を言うか」を決める役割から切り離し、**確定済みの発言意味をCharacter Profileどおりの言語表現へ実現するLanguage Realizer**へ限定する。

現在のCharacter経路は、`ResponseContext`全体、Emotion / Drive、Conversation Response Decision、Response Content Plan、Character Profileを同時に解釈し、さらにexpression / voice_intent / pause等まで生成している。この構造では、内部状態の意味解釈、談話判断、人物らしい言い回し、音声演技の決定が一つのLLMへ集まり、責務境界が曖昧になる。

本設計は、次の分離を正規方針とする。

```text
What to say
  ↓
Semantic Utterance
  ↓
How this character says it
  ↓
Character Utterance
  ↓
How it is performed in voice
  ↓
Speech Performance Plan
  ↓
TTS / Body / Avatar
```

固定文・固定言い換え辞書・Emotion名→台詞のPreset変換は採用しない。

---

## 2. 現状の責務混在

現行`CharacterPromptBuilder`は、少なくとも以下を一度に扱う。

- Character Profile
- ResponseContext全体
- Emotion / Drive
- Relationship / Situation / Memory
- Conversation Response Decision
- Response Content Plan
- question / new direction budget
- allowed / forbidden claims
- 内部感情を見せる・隠す判断
- expression / gesture
- voice_intent
- speed / pitch / intonation / volume / breathiness
- pause_after_seconds
- reaction_segments

また`CharacterResponse`も、発話本文とVoiceIntent、pause、表情、gesture、ReactionPlanを同じ出力契約に保持する。

その結果、例えば内部状態への直接質問で、

```text
joy = 0.0
curiosity = high
engagement = high
```

という入力をCharacter LLM自身が意味解釈し、curiosity / engagementをjoyの根拠として誤用する余地が生じる。

この種の問題はPromptを強くするだけでは根本解決しない。Character LLMへ「状態値から正しい意味を決める」責務そのものを持たせないことを正規方針とする。

---

## 3. 目標アーキテクチャ

```text
User Input / Autonomous Motivation
        ↓
Input Meaning Interpreter
        ↓
StructuredInputMeaning
        ↓
Internal Directive Planner
        ↓
Validated InternalDirective
        ↓
Response Semantics Planner
   + Emotion / Desire / Drive
   + Relationship Appraisal
   + Memory / Knowledge
   + Situation
   + Activity execution facts
   + Discourse Appraisal
        ↓
SemanticUtterancePlan
        ↓
Character Language Realizer (Character LLM)
   + CharacterProfile
   + Character-facing Interpersonal Context
   + Character-facing Discourse Context
   + high-level Expression Intent
        ↓
CharacterUtterance
        ↓
Speech Performance Planner
   + Character Voice Style
   + Expression Intent
   + linguistic phrasing hints
   + TTS capability
        ↓
SpeechPerformancePlan
        ↓
TTS Adapter
        ↓
Audio / Pronunciation Timeline

同時に:
Expression Intent + CharacterUtterance
        ↓
Body / Face / Gaze
```

CharacterとBodyは引き続き兄弟Realizerとし、互いの出力を意思決定の正本にはしない。

---

## 4. Response Semantics Planner

### 4.1 責務

Response Semantics Plannerは**何を伝えるか**を決める。

ここで初めて、内部数値や内部モデルを発言可能な意味へ変換する。

入力候補:

- `StructuredInputMeaning`
- `Validated InternalDirective`
- Emotion
- Desire
- Drive
- Relationship Appraisal
- Situation
- Activity execution facts
- Memory / Knowledge
- Discourse Appraisal
- Interaction Intention

出力は自然文ではなく、可能な限り型付きの意味契約とする。

例:

```json
{
  "speech_act": "direct_answer",
  "target": {"type": "internal_state", "id": "joy"},
  "propositions": [
    {
      "type": "self_state",
      "subject": "self",
      "predicate": "current_joy",
      "polarity": "negative",
      "certainty": "high"
    }
  ],
  "required_content": [],
  "optional_context": [],
  "forbidden_additions": [
    "unsupported_positive_emotion",
    "unsupported_relationship_claim"
  ],
  "response_length": "short",
  "question_budget": 0,
  "new_direction_budget": 0,
  "self_disclosure": "brief"
}
```

### 4.2 数値状態の扱い

raw値はこの層までで解釈する。

```text
joy = 0.0
↓
current_joy = absent / negative proposition
```

```text
curiosity = high
engagement = high
↓
interaction engagement / attentional orientation
```

これらをCharacter LLMへraw数値として渡さない。

target-specific evidenceはこの層の入力・検証材料であり、Character LLMの直接入力ではない。

### 4.3 Neutral Utteranceとの違い

完全な中立日本語文を必須成果物にしない。

NG:

```text
「現在、私は楽しいとは感じていません。」
→ Character LLMが表面言い換えするだけ
```

推奨:

```text
意味構造
+ 発話行為
+ 開示量
+ 対人姿勢
+ 談話制約
```

Character LLMが語彙、語尾、文分割、自然な言い淀みを十分に選べる余地を残す。

---

## 5. Character Language Realizer

### 5.1 責務

Character LLMの正規責務は次とする。

> 確定済みSemanticUtterancePlanを、Character Profileと現在の対人・談話Contextに従って、その人物らしい自然な発話へ実現する。

Character LLMは次を決めない。

- 内部状態の事実認定
- Emotion / Drive raw値の意味解釈
- Activity選択
- 実行可否
- Memoryの真偽判定
- targetの決定
- question/new direction budgetの再計算
- TTS engine parameter
- Body関節値

### 5.2 Character LLMへ渡すもの

- `SemanticUtterancePlan`
- `CharacterProfile`
- Character向けに意味化済みの`InterpersonalContext`
- Character向けに意味化済みの`CharacterDiscourseContext`
- high-level `ExpressionIntent`
- 必要最小限の会話履歴
- 言語表現上の禁止事項

### 5.3 Character LLMへ渡さないもの

原則として以下のraw値を直接渡さない。

- Emotion数値
- Desire数値
- Drive数値
- Moral数値
- 内部診断ラベル
- target-specific evidence path/key/value
- Validator内部理由
- Activity実装内部状態
- TTSのspeed/pitch/intonation数値
- Bodyの関節値

### 5.4 Character Profileが所有する情報

Character Profileは**どういう人物として話すか**を所有する。

最低限:

- personality
- speaking style
- preferred vocabulary / vocabulary range
- first-person / addressing style
- sentence ending tendency
- directness / softness
- humor / teasing tendency
- verbosity tendency
- characteristic hesitation / filler tendency
- public/private self-presentation policy
- existence boundary

Character Profileを上流の事実決定へ使わない。

---

## 6. Relationship / Interpersonal Context

Relationshipは「何を言うか」と「どう言うか」の両方に影響するため、二段階で扱う。

### 6.1 上流: Response Semantics

raw Relationship stateを`Relationship Appraisal`で意味化し、発言内容側へ反映する。

例:

```json
{
  "social_distance": "close",
  "trust": "high",
  "current_tension": "low",
  "disclosure_permission": "moderate",
  "boundary_sensitivity": "normal"
}
```

ここでは主に、

- 自己開示量
- 境界設定
- 踏み込み可否
- 返答義務
- 親密な内容を話す可否

へ影響する。

### 6.2 Character Realizer

Character LLMへは、raw trust=0.73等ではなく、意味化済みの対人Contextだけを渡す。

ここでは主に、

- 敬語 / 常体
- 呼び方
- 距離感
- 冗談の強さ
- 省略の多さ
- 柔らかさ
- 親しさが表れる言い回し

へ反映する。

同じRelationshipを二重に独自解釈しない。上流とCharacterで利用するfacetを明示的に分ける。

---

## 7. Emotion / Desire / Driveの流入先

### 7.1 Response Semantics側

Emotion / Desire / Driveは、事実・動機・発言内容へ必要な場合にのみ意味化する。

例:

```text
joy=0
→ 「現在joyは肯定しない」

connection desire high
→ 自己開示や会話継続の候補を強める

curiosity high
→ 関連質問・探索方向の候補を強める
```

### 7.2 Expression側

同じ内部状態はExpression Appraisalにも入る。

```text
Emotion / Desire / Drive
→ Expression Intent
```

例:

- affective valence
- arousal
- tension
- warmth
- restraint
- engagement
- speech energy

ただしCharacter LLMへraw値を再投入しない。

---

## 8. 抑揚・間・話速の責務

抑揚と間は二種類へ分ける。

### 8.1 言語的な間: Character LLM

Character LLMが所有してよいもの:

- 「んー」「えっと」等の言語的filler
- 文をどこで分けるか
- 句読点
- 語尾をどう選ぶか
- どの語を強く見せたいかというhigh-level emphasis
- 言い直し・言い淀みを入れるか

これは言語表現そのものだからCharacter性に属する。

### 8.2 音響的な間: Speech Performance Planner

Speech Performance Plannerが所有する。

- 実pause duration
- phrase segmentation
- speed intent
- pitch contour intent
- intonation strength
- volume
- breathiness
- emphasis timing
- onset / release timing

Character LLMは`pause=0.42秒`や`pitch=+0.13`のような値を直接決めない。

### 8.3 TTS Adapter

TTS AdapterはSpeechPerformancePlanをEngine固有値へ投影する。

```text
SpeechPerformancePlan
→ VOICEVOX / other TTS query parameters
```

Engine固有parameterをCore/Character契約へ逆流させない。

---

## 9. CharacterUtterance契約

Character LLM出力の候補:

```json
{
  "speech": "今は、そこまで楽しいって感じじゃないかな。",
  "linguistic_performance": {
    "phrasing": [
      "今は、",
      "そこまで楽しいって感じじゃないかな。"
    ],
    "emphasis": ["そこまで"],
    "delivery_tags": ["soft", "low_assertiveness"]
  },
  "claims": [
    {
      "semantic_ref": "proposition:current_joy",
      "realized": true
    }
  ]
}
```

`linguistic_performance`は言語的ヒントに留め、msやpitch値等の音響parameterを含めない。

---

## 10. Speech Performance Planner

入力:

- CharacterUtterance
- high-level Expression Intent
- Character Voice Style
- conversation / turn timing
- TTS capability

出力候補:

```json
{
  "segments": [
    {
      "text": "今は、",
      "pause_after_ms": 180,
      "speed": "normal",
      "intonation": "soft_fall"
    },
    {
      "text": "そこまで楽しいって感じじゃないかな。",
      "pause_after_ms": 320,
      "speed": "slightly_slow",
      "intonation": "gentle_fall"
    }
  ]
}
```

Core側では可能な限りengine-independent semantic値を持ち、Adapterで実数parameterへ変換する。

---

## 11. Discourse Appraisalとの境界

#193のDiscourse Appraisalは本設計へ統合し、重複実装しない。

Discourse Appraisalが所有するもの:

- topic transition
- bridge requirement
- acknowledgement need
- response obligation
- selected topic source
- unsupported self-interest claim

Response Semantics Plannerはこの評価を使ってSemanticUtterancePlanへ必要な意味制約を入れる。

Character LLMはその制約を自然な日本語へ実現する。

```text
Discourse Appraisal
→ Semantic Utterance
→ Character Language Realizer
```

固定Prefixや固定導入句は作らない。

---

## 12. Expression Appraisal / Bodyとの境界

#192のExpression Appraisalは、Character LLMとは独立した表現因果系として維持する。

```text
Emotion / Desire / Drive / Motivation
+ Interaction Intention
+ Interaction Process Appraisal
→ Expression Appraisal
├─ Character-facing high-level Expression Intent
├─ Speech Performance Planner
└─ Body / Face / Gaze
```

CharacterとBodyが同じExpression Intentを共有してよいが、CharacterがBody commandを生成しない。

---

## 13. Response Validatorの再配置

Validatorは少なくとも二つの責務へ分けて考える。

### Semantic Validator

Character生成前またはSemantic Plan確定時に、

- targetと内部状態の事実整合
- Activity実行事実
- allowed / forbidden claims
- existence boundary
- Memory根拠

を検証する。

### Realization Validator

Character生成後に、

- SemanticUtterancePlanの意味を保持しているか
- 必須propositionを落としていないか
- 禁止情報を追加していないか
- Character Profile表現が事実を改変していないか

を検証する。

Character LLMがraw内部状態を見なくなるため、現在#210で必要となっている「Characterが数値状態を正しく解釈したか」という検証は原則上流へ移る。

---

## 14. #210 Target-specific Evidenceとの関係

#210で導入中のtarget-specific evidenceは破棄しない。

役割を次へ移す。

```text
現状:
target-specific evidence
→ Character LLM
→ Validator

移行後:
target-specific evidence
→ Response Semantics Planner / Semantic Validator
→ SemanticUtterancePlan
→ Character Language Realizer
→ Realization Validator
```

これによりCharacter LLMが`joy=0.0`等を直接解釈する必要がなくなる。

#210は当面の不具合修正・安全網として維持し、本設計の実装Issueで段階的に置換する。

---

## 15. Character / Response Validator Labとの関係

#223のLabは再利用する。

ただし移行後は観測対象を次へ拡張する。

```text
StructuredInputMeaning
→ InternalDirective
→ SemanticUtterancePlan
→ CharacterUtterance
→ Realization Validation
```

比較できるべき項目:

- raw internal state
- SemanticUtterancePlan
- Characterへ実際に渡した入力
- Character output
- Realization Validator結果
- Speech Performance Plan（別段階）

これにより「意味決定の誤り」と「キャラクター言語化の誤り」を分離検証できる。

---

## 16. 移行方針

一括置換しない。

### Step A: Semantic契約を導入

- `SemanticUtterancePlan`相当のDomain契約
- current ResponseContextから構築するAdapter/Planner
- 既存Character経路と並行して単体検証

### Step B: Character LLMの入力を縮小

- Characterへraw Emotion / Drive / internal evidenceを渡さない
- Character Profile + semantic plan + interpersonal/discourse contextへ限定
- Character出力から音響parameterを外す

### Step C: Speech Performanceを分離

- CharacterUtteranceからSpeechPerformancePlanを生成
- TTS Adapterへengine-independent performance contractを渡す
- #213 Viseme timelineとは同一Audio/TTS timeline上で統合

### Step D: ValidatorをSemantic / Realizationへ分離

- 上流事実検証
- Character言語化後の意味保持検証

### Step E: Lab / Integration検証

- #223 Labでmodule/boundary verification
- #194等のIntegration層で全体確認

---

## 17. 非目標

- Characterごとの固定台詞辞書
- Emotion→台詞Preset
- Relationship→敬語Presetの単純1対1変換
- Character LLMを削除すること
- Character LLMに最終音響parameterを生成させること
- TTS Adapterへ人格判断を持たせること
- BodyへCharacter文章を再解釈させること
- #193 Discourse Appraisalを重複実装すること
- #192 Expression AppraisalをCharacter内へ吸収すること

---

## 18. 完成時の責務表

| 責務 | Owner |
|---|---|
| 入力の意味 | Input Meaning Interpreter |
| 応答方針・Activity方針 | Internal Directive |
| 何を発言するか | Response Semantics Planner |
| 話題橋渡し・談話関係 | Discourse Appraisal |
| 自己開示可否・関係上の境界 | Relationship Appraisal + Response Semantics |
| キャラクターらしい言い回し | Character Language Realizer |
| 一人称・語尾・語彙・言い淀み | Character Language Realizer + Character Profile |
| 感情の意味的事実 | Response Semantics |
| 感情の見せ方 | Expression Appraisal |
| 言語的な間 | Character Language Realizer |
| 音響的な間・抑揚・話速 | Speech Performance Planner |
| TTS engine parameter | TTS Adapter |
| Viseme timing | TTS/Pronunciation timeline + Body speech layer |
| Body動作 | Body Realizer |
| 事実整合 | Semantic Validator |
| Character言語化による意味保持 | Realization Validator |

---

## 19. 設計判断

1. Character LLMは**意味決定器ではなくLanguage Realizer**とする。
2. raw内部状態はCharacterへ渡さない。
3. Character Profileは主に言語表現・存在境界へ使い、事実決定へ使わない。
4. Relationshipは上流の内容制御とCharacterの言い回しの二段階で使うが、raw値を二重解釈しない。
5. Emotion / Desire / DriveはResponse SemanticsとExpression Appraisalへ分岐し、Characterへraw再投入しない。
6. 言語的pauseと音響的pauseを分離する。
7. CharacterはTTS実数parameterを生成しない。
8. #193のDiscourse Appraisal、#192のExpression Appraisal、#213のViseme、#214のBody Styleと責務を重複させない。
9. #210のtarget-specific evidenceはResponse Semantics側へ移行する。
10. #223 Labを新境界のmodule verification基盤として継続利用する。

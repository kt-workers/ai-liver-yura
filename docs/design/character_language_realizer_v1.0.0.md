# Character Language Realizer v1.0.0

## 目的

Parent #225 / Work #227。

Character LLMを、内部状態・Activity・実行事実を解釈して発言内容を決めるLLMから、`SemanticUtterancePlan`で確定済みの意味をCharacter Profileどおりの自然な言語へ変換する **Language Realizer** へ移行する。

```text
SemanticUtterancePlan (#226)
        +
Character Profile
        +
意味化済み Interpersonal / Discourse Context
        ↓
Character Language Realizer
        ↓
CharacterUtterance
        ↓
Speech Performance (#228)
```

## 責務

Character Language Realizerが所有する:

- Character Profileに沿う語彙
- 一人称 / 呼称
- 語尾
- directness / softness
- 自然な言い淀み
- 言語的な区切り
- 文分割
- 語句レベルの強調
- 高レベルなdelivery tag
- interpersonal / discourse facetの言語実現

所有しない:

- Emotion / Desire / Driveの解釈
- Activity実行事実の認定
- target-specific evidenceの解釈
- Memoryの正誤判定
- Discourse Appraisal生成
- TTS speed / pitch / intonation
- acoustic pause duration
- expression / gesture / Body joint
- Viseme

## Character入力境界

新経路ではCharacterへ次だけを渡す。

```text
Character Profile
+ Character-facing Semantic Plan
```

Character-facing Semantic Planは`SemanticUtterancePlan`から次を除去したprojectionである。

- `evidence_refs`
- internal path / key
- raw numeric value
- diagnostic reason

渡すもの:

- speech_act
- target identity
- proposition predicate
- semantic state
- certainty
- semantic concept
- required / optional / forbidden content
- response length
- self disclosure
- question / new-direction budget
- semantic interpersonal facet
- semantic discourse facet

## Model Invocationの情報遮断

Promptだけをsanitizeしても、Model Adapterへ渡す`Activity.context`にfull `ResponseContext`が残っていればCharacter LLMが間接的にraw stateへ依存できる。

そのため新Language Realizer経路では、Model invocation Activityに次を含めない。

- `user_input`
- full `response_context`
- `event_payload`
- `activity_execution_result`
- `ongoing_activity`
- raw Emotion / Drive / Relationship

保持するのはPromptとtrace/correlation用の非意味データのみ。

```text
plugin_prompt_override
llm_role=character_language_realizer
event_id
trace_context
activity_turn_id
llm_attempt
semantic_boundary=true
```

これにより「Promptでは隠したがModel Adapterからraw stateを参照できる」という抜け道をなくす。

## CharacterUtterance

```json
{
  "speech": "今は、そこまで楽しいって感じじゃないかな。",
  "linguistic_performance": {
    "phrasing": ["今は、", "そこまで楽しいって感じじゃないかな。"],
    "emphasis": ["そこまで"],
    "delivery_tags": ["gentle"]
  },
  "semantic_realizations": ["proposition:0:joy"]
}
```

### linguistic_performance

言語表現だけを保持する。

- `phrasing`: 言語上の句・節の区切り
- `emphasis`: 強調したい語句
- `delivery_tags`: `gentle`等の高レベルタグ

次は含めない。

- voice_intent
- speed
- pitch
- intonation
- volume
- breathiness
- pause_after_seconds
- expression
- gesture
- reaction_segments

これらは#228 / #192 / Body側へ分離する。

## 既存CharacterResponseへのCompatibility

現行Pipelineは`CharacterResponse`を要求するため、移行Adapter `CharacterLanguageRealizerService` が新`CharacterUtterance`を一時的に次へ変換する。

```text
speech = CharacterUtterance.speech
expression = neutral
voice_intent = neutral default
gesture = null
pause_after_seconds = 0
claim = conversation_only
```

これらneutral値はCharacter LLMの判断結果ではない。既存契約を破壊しないためのAdapter defaultであり、表現・音声の正本ではない。

#228でSpeechPerformancePlan、#192でExpression Appraisalとの接続が整った後、この互換値への依存を縮小する。

## 初期適用範囲

#226の初期Semantic Planは内部状態直接回答を最も強く意味確定できるため、最初の新経路は次へ限定する。

```text
target.type = internal_state | agent_internal_state
speech_act = direct_answer
propositions != empty
```

この範囲はconversation-onlyとして安全に既存Pipelineへ戻せる。

一般会話・Activity結果・外部事実回答は、Semantic Planが必要なexecution/source propositionを十分に保持できるまでLegacy Character PromptをCompatibilityとして使用する。

これは最終設計ではなく移行境界である。最終的には全Character発話をLanguage Realizer経路へ統一する。

## #210ケース

入力側:

```text
joy = 0.0
curiosity = 0.82
engagement = 0.78
```

#226:

```text
predicate=joy
state=absent
```

#227 Character-facing input:

```text
predicate=joy
state=absent
certainty=high
```

Character LLMには次を渡さない。

```text
joy=0.0
curiosity=0.82
engagement=0.78
emotion.current.reactive.joy
```

したがってCharacterはcuriosityをjoyへ再解釈する責務も材料も持たない。

## Regeneration

既存Validatorから再生成要求が来ても、raw validator payload全体をCharacterへ渡さない。

現段階では`reason`だけを`correction_kind`として提示し、

- 同じSemantic Planを維持
- 言い回しだけ修正
- 未根拠の別状態・関係評価を補足しない

ことを要求する。

#229でRealization Validatorを導入後は、Semantic差分に基づくtyped correctionへ置き換える。

## Character Profile

Character Profileは発言事実を決めない。

利用対象:

- personality
- speaking_style
- streaming_style
- likes / dislikes（Semantic Planが使用を許した文脈に限る）
- behavior_policy
- existence boundary

存在境界は表現上の制約として維持するが、Character Profileを理由にSemantic Planのpolarityやcertaintyを変更しない。

## Relationship

raw relationship scoreは渡さない。

#226で意味化済みの:

- disclosure_permission
- boundary_sensitivity
- social_distance
- current_tension

を、距離感・register・柔らかさ等の表現へ利用する。

将来Character-facing専用facetを追加する場合も、raw scoreの独自再評価は行わない。

## #193 / #192 / #228との境界

- #193: topic transition / acknowledgement等を評価する。Characterは結果を文章化するだけ。
- #192: high-level Expression Intentを生成する。Characterはraw Emotionを再解釈しない。
- #228: acoustic pause / prosody / speed / pitch等を生成する。

## Schema識別

Legacy Character JSONと新`CharacterUtterance`を混同しない。

新Schemaとして受理するには最低限:

- `speech`
- `linguistic_performance`
- `semantic_realizations`

を要求する。

新Semantic経路ではSchema不正時にLegacy parseへ静かにfallbackせず、構造化応答エラーとして再試行/失敗させる。

Legacy経路は従来Schemaをそのまま維持する。

## 検証

自動テスト:

1. Character Promptにsemantic propositionはあるがraw numeric/internal evidence pathがない
2. 同じSemantic PlanでCharacter Profileだけ変えられる
3. CharacterUtterance raw Schemaに音響parameterがない
4. Legacy SchemaをCharacterUtteranceと誤認しない
5. Model invocation Activityからfull ResponseContext / user_input / raw stateが除去される
6. Semantic経路の不完全Schemaを拒否する
7. 一般会話は移行中Legacy経路を維持する

実LLM検証は#223 Labで行う。

重点:

- joy absentを肯定へ反転しない
- 未根拠の「でも話していて心地いい」等を追加しない
- Character Profileの違いで言い回しは変わる
- 内部path/key/数値を発話しない
- Character raw model callにEmotion/Driveが存在しない

## 非目標

- Semantic Validator / Realization Validator（#229）
- Speech Performance（#228）
- general Semantic Planの完成（#226継続範囲）
- Body Character Style（#214）
- fixed paraphrase dictionary

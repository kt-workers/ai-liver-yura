# Semantic / Realization Validation Separation v1.0.0

## 目的

Parent #225 / Work #229。

従来Response Validatorに混在していた次の2責務を分離する。

1. Character生成前に「何を言うか」がstructured factsと整合しているか
2. Character生成後に、言い回しを変えてもその意味が保持されているか

```text
Structured facts
→ ResponseSemanticsPlanner (#226)
→ SemanticUtterancePlan
→ SemanticUtteranceValidator
→ validated SemanticUtterancePlan
→ Character Language Realizer (#227)
→ CharacterUtterance
→ CharacterRealizationValidator
→ validated speech
```

## SemanticUtteranceValidator

### 責務

Character生成前に`SemanticUtterancePlan`を検証する。

検証対象:

- speech act
- typed target
- semantic propositions
- required / optional / forbidden content
- response length
- self disclosure
- question / new-direction budget
- interpersonal content facet
- discourse facet

### 正本

`ResponseSemanticsPlanner`自身がstructured factsから決定論的に生成するcanonical planを正本とする。

ValidatorはEmotion/Drive→semantic stateの変換規則を別実装しない。

```text
ResponseContext
→ ResponseSemanticsPlanner
→ canonical SemanticUtterancePlan
        ↕ compare
candidate SemanticUtterancePlan
```

これにより#226と#229でtarget evidence解釈ロジックを二重化しない。

### production境界

`SemanticValidatedResponseContextBuilder`:

```text
InternalStateAwareResponseContextBuilder
→ SemanticUtterancePlan生成
→ SemanticUtteranceValidator
→ memory.semantic_validation
→ Character
```

不整合PlanはCharacterへ渡さずfail closedする。

## CharacterRealizationValidator

### 責務

Character生成後はraw Emotion / Driveを再解釈せず、`validated SemanticUtterancePlan`とspeechの意味保持だけを検証する。

検証対象:

- primary target propositionのstate/polarity/certainty保持
- primary propositionのnon-null concept保持
- Semantic Planにない強度追加の拒否
- required semantic content
- forbidden additions
- unsupported self-state / relationship / experience / external factの追加
- non-target stateによるprimary targetの置換
- question / new-direction budget
- existence boundary

検証しない:

- 文体の好み
- Character Profileへの主観的な「らしさ」採点
- raw internal numeric state
- target-specific evidence path/value
- prosody / TTS parameter
- Body表現

## CharacterRealizationValidator Prompt

入力:

```text
Character-facing Semantic Plan
+ Character speech
+ Character semantic_realizations
+ linguistic_performance
+ existence boundaries
```

含めない:

- raw Emotion / Drive
- full ResponseContext
- user_input
- activity_execution_result
- evidence_refs
- internal path / key / value

## Model invocation境界

Legacy ResponseValidatorはLLM Activity contextへfull `response_context`と`character_response`を格納していた。

新Semantic経路ではこれを行わない。

```text
plugin_prompt_override
llm_role=character_realization_validator
trace_context
activity_turn_id
llm_attempt
semantic_boundary=true
```

のみを渡す。

これによりRealization Validatorもraw stateを別経路から再解釈できない。

## deterministic fact validation

既存のclaim extractor / deterministic fact validatorは再利用する。

```text
Character speech
→ IndependentClaimExtractor
→ existing DeterministicFactValidator / DeterministicResponseValidator
→ CharacterRealizationValidator
```

Activity実行事実検証を新しく重複実装しない。

## deterministic semantic surface guard

LLM Validatorの`accepted`や`surface_evidence`は意味評価の一要素であり、Runtimeの唯一の正本にはしない。

`state`が`low/moderate/high/very_high`ではないprimary propositionに対して、発話上で明示的な程度・強弱を付与する高確度なsurface markerを検出した場合は、LLM Validatorが`intensity_markers=[]`と誤判定してもRuntime側で`unsupported_intensity_markers:<marker>`を追加しfail closedする。

```text
Semantic Plan: state=present
Character speech: 「少し気になる」
LLM Validator: accepted=true / intensity_markers=[]
        ↓
Runtime surface guard: 「少し」を検出
        ↓
semantic_facet_validation_failed
```

このguardは固定回答やCharacter語彙を生成する辞書ではない。発話後に明示的な程度副詞をsurface evidenceとして検出する限定的なvalidation safety netであり、一般会話全体へ単語禁止を適用しない。`low/moderate/high/very_high`のようにSemantic Plan自身が強度を持つ場合は、強度表現の妥当性をLLM Validatorへ委ねる。

またこのguardはValidator modelの有無に依存せず実行する。modelなし互換経路でも、明示的な未計画強度が見つかれば`semantic_realization_structure_valid`として通さずrejectする。

## semantic_realizationsとrequired facets

#227の`CharacterUtterance.semantic_realizations`を`CharacterResponse`互換境界でも保持する。

初期内部状態直接回答では、primary proposition:

```text
proposition:0:<target>
```

が存在することを構造的に要求する。

ただしIDはCharacterの自己申告なので、IDがあるだけでspeechをacceptedにしない。primary propositionは`required=true`とし、`state`、`certainty`、およびnon-nullの`concept`を`required_facets`としてValidatorへ提示する。

`concept`がnon-nullなら、その意味がspeechに保持されていなければrejectする。`state=present`は存在だけを表し強度を含まないため、Planに強度stateがないのに「少し」「かなり」等の強度を追加することもreject対象とする。`certainty`はepistemic certaintyであり、強度へ読み替えない。

`current_feeling`等ではsecondary Emotion dimensionは利用可能なsupporting semanticsであり、すべてを発話することは要求しない。primary target propositionのみrequiredとし、自然な選択を許容する。

## Validator model unavailable時

既存PipelineはValidator modelなしの場合もdeterministic validationだけで動作可能だったため、互換性を維持する。

Semantic経路でmodelがない場合:

- existing deterministic fact validation
- primary semantic realization IDの構造確認
- deterministic semantic surface guard

までを行う。surface guardに差分がなければ`semantic_realization_structure_valid`として扱い、未計画の明示的強度を検出した場合は`semantic_facet_validation_failed`としてrejectする。

これは実LLM意味検証と同等ではないため、実環境Verificationではvalidator modelを有効にして確認する。

## #210ケース

```text
joy=0.0
↓
#226 Semantic Plan: joy=absent
↓
Semantic Validator: plan consistent
↓
#227 Character Language Realizer
↓
"うん、少し楽しいよ"
↓
Realization Validator
→ target_polarity_changed
→ reject
```

Realization Validatorは`joy=0.0`を見ない。

見るのは:

```text
Semantic Plan: joy=absent
Character speech: 少し楽しい
```

だけである。

## Legacy fallback

初期移行範囲は#227と同様にinternal-state direct answerへ限定する。

Semantic validation済み新経路でない場合は既存Response Validatorへfallbackする。

一般Activity等のSemantic Planが完成したら、このfallback範囲を縮小する。

## #223 Lab

既存Labを拡張して次を別表示する。

- SemanticUtterancePlan
- Semantic Validation Result
- Character-facing prompt/input
- CharacterUtterance
- Realization Validation Result
- regeneration

これにより「上流意味が誤っていた」のか「Characterが意味を変えた」のかを分離する。

## 検証

自動テスト:

1. canonical Semantic Planをaccept
2. proposition改変PlanをCharacter前にreject
3. Realization Validator Promptへraw stateを入れない
4. Validator model invocation contextへfull ResponseContextを入れない
5. primary semantic realization ID欠落をmodel call前にreject
6. realization modelの意味差分をResponseValidationResultへ保持
7. primary propositionのstate/certainty/non-null conceptをrequired facetsとして提示
8. presentから未根拠の強度を追加しない契約を検証
9. LLM Validatorが強度markerを見落としてもdeterministic surface guardでreject
10. Validator modelなしでもdeterministic surface guardを維持

実LLM:

- #223 Lab / joy low-high-curiosity
- current feeling
- anger
- current desire
- regeneration

## 非目標

- Semantic Plannerの再実装
- Character Profile表現の品質採点
- fixed phrase / response dictionary
- Speech Performance
- Body/TTS

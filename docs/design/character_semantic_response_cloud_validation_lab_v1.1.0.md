# Character Semantic Response Cloud Validation Lab v1.1.0

## 目的

Issue #223。

既存Character / Response Validator Labを破棄せず、Parent #225の新しい発話生成境界を全体Runtimeなしで観測できるよう拡張する。

対象stack:

```text
#226 SemanticUtterancePlan
→ #229 Semantic Validation
→ #227 Character Language Realizer
→ #229 Character Realization Validator
```

## 再利用方針

旧 `cloud_validation/character_response_lab.py` は次を既に所有している。

- Input Meaning / Internal Directiveの構造入力UI
- Emotion / Drive / Memory snapshot編集
- Character Profile編集
- OpenAI role adapter構築
- pipeline実行
- Basic Auth
- preset
- JSON Export
- Render向けWeb UI

これらを複製しない。

新規 `cloud_validation/character_semantic_response_lab.py` は薄いwrapperとして、次だけを追加する。

- new fake role schema
- 実際の`llm_role`記録
- model invocation context key診断
- Semantic Plan / Semantic Validationの明示Export
- CharacterUtteranceの明示Export
- Realization Validationの明示Export

## Production logic

Lab専用のSemantic Planner / Character generation / Validatorを実装しない。

`app.runtime`がproduction compositionで次へ差し替えた実クラスを既存Lab pipelineから呼び出す。

```text
ResponseContextBuilder
= SemanticValidatedResponseContextBuilder

CharacterLlmService
= CharacterLanguageRealizerService

ResponseValidator
= CharacterRealizationValidator
```

従ってLabと通常Runtimeで意味決定ロジックを二重化しない。

## 診断snapshotとModel入力を分離する

Labの`response_context`には原因切り分けのためraw Emotion / Drive snapshotを表示してよい。

一方、Character/Validator modelへraw stateが渡っていないことを別の診断値で確認する。

```json
{
  "character_model_boundary": {
    "role": "character_language_realizer",
    "context_keys": ["plugin_prompt_override", "llm_role", "..."],
    "semantic_boundary": true
  }
}
```

本文・raw Activity payloadはmodel boundary診断へ複製せず、key名だけを保持する。

新Semantic経路で以下のkeyが存在しないことを検証する。

- user_input
- response_context
- event_payload
- activity_execution_result
- ongoing_activity
- emotion
- drive

同じ確認を`validator_model_boundary`にも行う。

## Export境界

追加するトップレベル項目:

- `semantic_utterance_plan`
- `semantic_validation`
- `character_utterance`
- `character_model_boundary`
- `realization_validation`
- `validator_model_boundary`
- `linguistic_performance`
- `semantic_realizations`
- `pipeline_boundaries`

`model_calls`も維持し、`include_prompts=true`の場合は各production promptを確認できる。

## fake mode

新Character schema:

```json
{
  "speech": "検証用の応答です。",
  "linguistic_performance": {
    "phrasing": ["検証用の応答です。"],
    "emphasis": [],
    "delivery_tags": ["neutral"]
  },
  "semantic_realizations": ["proposition:0:<target>"]
}
```

Fake modelはCharacter-facing Semantic JSONに含まれるrequired primary realization IDを読み、wiring検証用に返す。

これはproduction generationロジックではなくLab fake mode専用であり、実LLM品質評価には使用しない。

新Validator fake schema:

```json
{
  "accepted": true,
  "reason": "semantic_realization_consistent",
  "differences": []
}
```

## Render

正規branch:

```text
test/character-semantic-response-cloud-validation
```

start module:

```text
cloud_validation.character_semantic_response_lab:app
```

既存環境変数名は維持する。

## #210 Verification

最初に`低いJoy / 高いCuriosity`だけを確認する。

期待因果:

```text
joy=0 / curiosity高
→ Semantic Plan joy=absent
→ Semantic Validation PASS
→ Character Language Realizer
   raw stateなし
→ joyを肯定しない自然な発話
→ Realization Validator
   raw stateなし
→ PASS
```

この1ケースが通った後に:

1. current feeling / repetition
2. anger
3. desire

へ進む。

## 非目標

- Input Meaning LLMの実行
- Internal Directive LLMの実行
- Speech Performance #228
- TTS
- Body
- Avatar
- PostgreSQL必須Memory retrieval
- Lab独自Character Promptによる挙動置換
- fixed answer dictionary

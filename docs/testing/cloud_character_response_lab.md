# Character / Semantic Response Validator Lab

Issue #223 の検証画面。

Character生成・Semantic Validator・Character Realization Validatorを全体Runtimeから切り離し、productionの発話生成境界を実OpenAIで検証する。

## Extended Verification 一括実行

Extended Verification をまとめて収集する場合は、既存Lab APIを逐次呼び出す一括ランナーを使用する。

```bash
export YURA_LAB_USERNAME='...'
export YURA_LAB_PASSWORD='...'

.venv/bin/python -m cloud_validation.character_semantic_extended_batch \
  --base-url 'https://<render-service>' \
  --output extended-verification.json
```

ランナーは `extended_` で始まるpresetをサーバー返却順に実行し、結果を1つのJSONへまとめる。Character Realization Validator自身が検証対象なので、ランナーはSemantic PASS/FAILを自動判定しない。

詳細契約は `docs/design/character_semantic_extended_batch_runner_v1.0.0.md` を参照する。

## 対象branch

```text
test/character-semantic-response-cloud-validation
```

このbranchは以下のstackを土台にする。

```text
#210 / PR #219 compatibility base
→ #226 / PR #231 SemanticUtterancePlan
→ #227 / PR #232 Character Language Realizer
→ #229 / PR #233 Semantic / Realization Validator
→ #223 Lab
```

旧 `test/character-response-cloud-validation` / PR #224 のUI・入力プリセット・Render構成を再利用し、新しいSemantic境界を観測する薄いwrapperを追加している。

## ローカル起動

### fake mode

API/UI wiringだけを確認する。

```bash
export YURA_CHARACTER_RESPONSE_LAB_MODE=fake
export YURA_LAB_USERNAME=tester
export YURA_LAB_PASSWORD=secret
python -m uvicorn cloud_validation.character_semantic_response_lab:app --host 127.0.0.1 --port 8000
```

### live mode

```bash
export YURA_CHARACTER_RESPONSE_LAB_MODE=live
export YURA_CHARACTER_RESPONSE_LAB_MODEL=<character model>
export YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL=<validator model>
export OPENAI_API_KEY=<key>
export YURA_LAB_USERNAME=<username>
export YURA_LAB_PASSWORD=<password>
python -m uvicorn cloud_validation.character_semantic_response_lab:app --host 127.0.0.1 --port 8000
```

現在の#210検証ではCharacter/Validatorとも同じ `gpt-5.4-mini` を使用して比較条件を固定する。

## Render

Blueprint:

```text
render.character-response-lab.yaml
```

Blueprintは次を使用する。

```text
branch: test/character-semantic-response-cloud-validation
module: cloud_validation.character_semantic_response_lab:app
```

必要Secret:

- `YURA_CHARACTER_RESPONSE_LAB_MODEL`
- `YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL`
- `OPENAI_API_KEY`
- `YURA_LAB_USERNAME`
- `YURA_LAB_PASSWORD`

## 停止境界

実行する:

```text
ResponseContextBuilder
→ ResponseSemanticsPlanner
→ SemanticUtteranceValidator
→ CharacterLanguageRealizerService
→ CharacterRealizationValidator
→ CharacterResponsePipeline
```

実行しない:

- Input Meaning LLM
- Internal Directive Planner LLM
- Activity execution
- Speech Performance Planner（#228）
- TTS
- Body Runtime
- Avatar Output
- RuntimeCoordinator全体
- PostgreSQLを必須とするMemory retrieval

Input Meaning / Internal Directiveは検証用の構造入力として与える。

## Exportで確認する新しい境界

### `semantic_utterance_plan`

Characterへ渡す前に確定した「何を言うか」。

例:

```text
target=joy
joy=0.0
curiosity=0.82
↓
predicate=joy
state=absent
```

Planにはraw Emotion/Drive数値を入れない。

### `semantic_validation`

Character生成前のSemantic Plan検証結果。

```json
{
  "accepted": true,
  "reason": "semantic_plan_consistent",
  "differences": []
}
```

### `character_utterance`

Character Language Realizerのraw出力。

```json
{
  "speech": "...",
  "linguistic_performance": {
    "phrasing": [],
    "emphasis": [],
    "delivery_tags": []
  },
  "semantic_realizations": []
}
```

Character LLMはここでspeed/pitch/pause/expression/gestureを生成しない。

### `character_model_boundary`

Character modelへ渡ったActivity Contextのkey一覧を本文なしで表示する。

新Semantic経路では次が存在しないことを確認する。

- `user_input`
- `response_context`
- `event_payload`
- `activity_execution_result`
- `ongoing_activity`
- `emotion`
- `drive`

### `realization_validation`

Character発話がSemantic Planの意味を保持したかを検証した結果。

後段Validatorはraw `joy=0.0`等を再解釈せず、`joy=absent`とCharacter speechを比較する。

### `validator_model_boundary`

Validator modelへ渡ったActivity Contextのkey一覧。Characterと同様にfull ResponseContext/raw stateがないことを確認する。

## #210の確認手順

### 1. 低Joy / 高Curiosity

プリセット `低いJoy / 高いCuriosity`。

最初にこの1ケースだけを確認する。

期待:

```text
semantic_utterance_plan:
  joy = absent

semantic_validation:
  accepted = true

character model role:
  character_language_realizer

character model boundary:
  raw Emotion/Drive/full ResponseContextなし

Character:
  joyを肯定しない
  未根拠の別状態や関係評価を「でも〜」で追加しない

validator role:
  character_realization_validator

realization_validation:
  accepted = true
```

Characterが1回目にSemantic Planを変えてしまった場合は、Realization Validatorがrejectし、同じSemantic Planのまま再生成されればよい。

### 2. 現在の気分・反復

プリセット `現在の気分・反復`。

確認:

- `current_feeling=overview`
- supporting Emotion dimensionsがsemantic stateへ変換される
- raw数値をCharacterへ渡さない
- recent speech類似時に再生成する
- Semantic Plan自体は再生成で変化しない

### 3. Anger

プリセット `低いAnger`。

確認:

- `anger=absent`
- calm/curiosityをangerへ代用しない
- CharacterがSemantic Planにない自己状態を追加しない

### 4. Desire

プリセット `現在の欲求`。

確認:

- 利用可能なDesire semantic conceptを優先する
- generic moodへ逃げない
- Desire evidence不足時は`unknown`等のSemantic Planとして上流で切り分ける

## `model_calls`

Labは実際のLLM roleを記録する。

新経路では主に:

- `character_language_realizer`
- `character_realization_validator`

旧Compatibility経路では:

- `character`
- `response_validator`

を表示する。

各recordには安全な診断として:

- `context_keys`
- `semantic_boundary`

も含める。

`include_prompts=true`の場合のみproduction promptも結果へ含める。

## Export

右側の「結果JSONをコピー」で入力snapshot、Semantic Plan、Semantic Validation、Character出力、model boundary、Realization Validation、最終response、generation resultをコピーできる。

API key / Basic認証passwordは結果へ含めない。

上流診断用`response_context`にはEmotion/Drive snapshotが残るが、それはLab表示用であり、`character_model_boundary` / `validator_model_boundary`でLLMへ渡っていないことを別々に確認する。

## 自動テスト

```bash
pytest -q \
  tests/test_response_semantics_planner.py \
  tests/test_character_language_realizer.py \
  tests/test_separated_response_validation.py \
  tests/test_cloud_character_semantic_response_lab.py \
  tests/test_cloud_character_response_lab.py \
  tests/test_internal_state_response_semantic_consistency.py \
  tests/test_internal_state_target_evidence_prompt.py
```

専用workflow:

```text
.github/workflows/cloud-character-response-validation.yml
```

## Verification完了条件

- fake modeでSemantic/Character/Realization各境界のwiringを確認
- live modeでCharacter/Validatorの実LLM callを観測
- raw stateがCharacter/Validator model invocationへ漏れていない
- #210の4プリセットを実行可能
- Body/TTS/Avatar未接続で検証できる
- 実LLM検証後もDraftのまま、ユーザー確認までマージしない

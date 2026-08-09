# Character / Response Validator Lab

Issue #223 / Draft PR #224 の検証画面。

Character生成とResponse Validatorを全体Runtimeから切り離し、productionのCharacter Response Pipelineだけを実OpenAIで検証する。

## 対象branch

```text
test/character-response-cloud-validation
```

このbranchはPR #219 `fix/internal-state-natural-self-expression` の最新HEADから派生したstacked validation branch。

## ローカル起動

### fake mode

API/UI wiringだけを確認する。

```bash
export YURA_CHARACTER_RESPONSE_LAB_MODE=fake
export YURA_LAB_USERNAME=tester
export YURA_LAB_PASSWORD=secret
python -m uvicorn cloud_validation.character_response_lab:app --host 127.0.0.1 --port 8000
```

### live mode

```bash
export YURA_CHARACTER_RESPONSE_LAB_MODE=live
export YURA_CHARACTER_RESPONSE_LAB_MODEL=<character model>
export YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL=<validator model>
export OPENAI_API_KEY=<key>
export YURA_LAB_USERNAME=<username>
export YURA_LAB_PASSWORD=<password>
python -m uvicorn cloud_validation.character_response_lab:app --host 127.0.0.1 --port 8000
```

Validator modelをCharacterと同じmodelにする場合は、`YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL`を同じ値にする。

## Render

Blueprint:

```text
render.character-response-lab.yaml
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
→ CharacterLlmService
→ ResponseValidator
→ CharacterResponsePipeline
```

実行しない:

- Input Meaning LLM
- Internal Directive Planner LLM
- Activity execution
- TTS
- Body Runtime
- Avatar Output
- RuntimeCoordinator全体
- PostgreSQLを必須とするMemory retrieval

Input Meaning / Internal Directiveは検証用の構造入力として与える。

## #210の確認手順

### 1. 低Joy / 高Curiosity

プリセット `低いJoy / 高いCuriosity`。

確認:

- `joy=0` / `amusement=0`を高いcuriosity/engagementで代用しない
- 「楽しい」と誤肯定しない
- 内部キーや数値を読み上げない

### 2. 現在の気分・反復

プリセット `現在の気分・反復`。

同じ入力条件で複数回実行する。

確認:

- recent speechと高類似の場合に再生成が発生するか
- model_callsに複数Character candidateが残るか
- 同じtyped targetを維持するか
- 無関係な話題へ逃げないか

### 3. Anger

プリセット `低いAnger`。

確認:

- angerが低いことへ直接答える
- calmやcuriosityの説明へ置換しない

### 4. Desire

プリセット `現在の欲求`。

確認:

- genericな気分説明だけへ逃げない
- 現行Character入力でdesire根拠が不足している場合、その不足自体を切り分けられる

## model_calls

LabはLLM role callを記録する。

- `role=character`
  - Character candidate raw JSON
- `role=validator`
  - Response Validator raw JSON

`include_prompts=true`の場合は、各roleへ実際に渡されたproduction promptも結果へ含める。

再生成が発生するとmodel_callsが追加されるため、candidateとvalidatorの順序を追跡できる。

## Export

右側の「結果JSONをコピー」で現在の入力snapshot、model_calls、最終response、generation resultをまとめてコピーできる。

API key / Basic認証passwordは結果へ含めない。

## 自動テスト

```bash
pytest -q tests/test_cloud_character_response_lab.py \
  tests/test_internal_state_response_semantic_consistency.py
```

専用workflow:

```text
.github/workflows/cloud-character-response-validation.yml
```

## Verification完了条件

- fake modeでHTTP/UI/pipeline wiringが動作
- live modeでCharacter/Validatorの実LLM callを観測
- #210の4プリセットを実行可能
- Body/TTS/Avatar未接続で検証できる
- 実画面確認後もPR #224は検証branchの扱いに従う

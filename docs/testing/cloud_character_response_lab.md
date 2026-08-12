# Character / Semantic Response Validator Lab

Issue #223 の検証画面。

Character生成・Semantic Validator・Independent Character Realization Observer・Post-Observation Character Realization Validatorを全体Runtimeから切り離し、productionの発話生成境界を実OpenAIで検証する。

## Extended Verification 一括実行

Extended Verification をまとめて収集する場合は、既存Lab APIを逐次呼び出す一括ランナーを使用する。

```bash
export YURA_LAB_USERNAME='...'
export YURA_LAB_PASSWORD='...'

.venv/bin/python -m cloud_validation.character_semantic_extended_batch \
  --base-url 'https://<render-service>' \
  --output extended-verification.json
```

ランナーは `extended_` で始まるpresetをサーバー返却順に実行し、結果を1つのJSONへまとめる。Observer / Character Realization Validator自身が検証対象なので、ランナーはSemantic PASS/FAILを自動判定しない。

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
→ #223 Lab / PR #234
```

旧 `test/character-response-cloud-validation` / PR #224 のUI・入力プリセット・Render構成を再利用し、新しいSemantic境界を観測する薄いwrapperを追加している。

## ローカル起動

### fake mode

API/UI wiringだけを確認する。

```bash
export YURA_CHARACTER_RESPONSE_LAB_MODE=fake
export YURA_LAB_USERNAME=tester
export YURA_LAB_PASSWORD=secret
python -m uvicorn cloud_validation.character_semantic_contract_completion_lab:app --host 127.0.0.1 --port 8000
```

### live mode

```bash
export YURA_CHARACTER_RESPONSE_LAB_MODE=live
export YURA_CHARACTER_RESPONSE_LAB_MODEL=<character model>
export YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL=<validator model>
export OPENAI_API_KEY=<key>
export YURA_LAB_USERNAME=<username>
export YURA_LAB_PASSWORD=<password>
python -m uvicorn cloud_validation.character_semantic_contract_completion_lab:app --host 127.0.0.1 --port 8000
```

Character / Observer / Post-Observation Validatorは同じResponse Validation接続を役割別に再利用できる。モデル名はRender環境変数で固定する。

## Render

Blueprint:

```text
render.character-response-lab.yaml
```

Blueprintは次を使用する。

```text
branch: test/character-semantic-response-cloud-validation
module: cloud_validation.character_semantic_contract_completion_lab:app
autoDeployTrigger: commit
```

必要Secret:

- `YURA_CHARACTER_RESPONSE_LAB_MODEL`
- `YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL`
- `OPENAI_API_KEY`
- `YURA_LAB_USERNAME`
- `YURA_LAB_PASSWORD`

Renderの実URLやBasic認証値はリポジトリへ保存しない。

## 停止境界

実行する:

```text
ResponseContextBuilder
→ ResponseSemanticsPlanner
→ SemanticUtteranceValidator
→ CharacterLanguageRealizerService
→ Independent Character Realization Observer
→ Runtime typed comparison
→ Post-Observation CharacterRealizationValidator
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

### `realization_observation`

Independent ObserverがCharacter speechから実際に観測したtyped semantics。

主に確認する:

- `realization_id`
- `predicate_realized`
- `observed_state`
- `observed_certainty`
- evidence spans

Observerへexpected state / certainty / concept / intensityを渡さない。User Wording Hintはprimary predicateの意味枠特定にだけ利用し、state/polarity/intensity/certaintyの期待値として扱わない。

### `observer_model_boundary`

Observer modelへ渡ったActivity Contextのkey一覧。

Characterと同様にfull ResponseContext/raw stateが存在しないことを確認する。

### Runtime typed comparison

Observerの `observed_state / observed_certainty` とSemanticUtterancePlanのexpected typed facetsをRuntimeで構造比較する。

ここでの決定論処理はtyped値の比較だけであり、speech中の有限単語・phrase・regex・substringからstate/intensity/certaintyを再推定しない。

`state / polarity / intensity / epistemic certainty` のsemantic authorityはこのObserver + typed comparisonに一本化する。

### `realization_validation`

Observer typed comparisonを通過した候補について、Post-Observation Validatorが残余の意味契約を確認した結果。

後段Validatorは `state / polarity / intensity / certainty` をspeechから再抽出・再解釈しない。確認対象は次に限定する。

- predicateの対象意味
- non-null concept
- required content
- forbidden additions
- unsupported new fact
- existence boundary
- question / new-direction budget

### `validator_model_boundary`

Post-Observation Validator modelへ渡ったActivity Contextのkey一覧。Character / Observerと同様にfull ResponseContext/raw stateがないことを確認する。

## #210由来Basic 4の確認手順

### 1. 低Joy / 高Curiosity

プリセット `低いJoy / 高いCuriosity`。

期待:

```text
semantic_utterance_plan:
  joy = absent

semantic_validation:
  accepted = true

character model role:
  character_language_realizer

observer model role:
  character_realization_observer

Character:
  joyを肯定しない
  未根拠の別状態や関係評価を追加しない

Observer / typed comparison:
  Characterがjoyを肯定した場合はobserved_stateとPlanが不一致になりreject

post-observation validator role:
  character_realization_validator

realization_validation:
  残余契約が保持されればaccepted = true
```

Characterが1回目にSemantic Planを変えてしまった場合は、Observer typed mismatchまたは後段Validatorがrejectし、同じSemantic Planのまま再生成されればよい。

### 2. 現在の気分・反復

プリセット `現在の気分・反復`。

確認:

- `current_feeling=overview`
- supporting Emotion dimensionsがsemantic stateへ変換される
- raw数値をCharacter/Observer/Validatorへ渡さない
- recent speech類似時に再生成する
- Semantic Plan自体は再生成で変化しない
- supporting `low` をbare presenceへ弱めた場合はObserver typed mismatchでrejectする

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
- predicate / concept / certaintyを保持した自然表現をfalse rejectしない

## Extended E1-E8

Basic 4に加えてExtended E1-E8をLive実行する。

特に確認する:

- E3 explicit unknownを特定polarityへ勝手にcommitしない
- E4 supporting lowをbare presenceへ弱めない
- E8 `energy=low` をbare presenceへ弱めない
- finite natural-language辞書なしでunseen paraphraseを扱える

12ケース + 少数のunseen paraphraseに留め、35ケース規模へ不必要に拡張しない。

## `model_calls`

Labは実際のLLM roleをattempt順に記録する。

新経路では主に:

- `character_language_realizer`
- `character_realization_observer`
- `character_realization_validator`

を表示する。

Observer typed mismatchでrejectされたattemptは、後段Validator callが存在しない場合がある。これは正常である。

旧Compatibility経路では:

- `character`
- `response_validator`

を表示する場合がある。

各recordには安全な診断として:

- `context_keys`
- `semantic_boundary`

も含める。

`include_prompts=true`の場合のみproduction promptも結果へ含める。

## Export

右側の「結果JSONをコピー」で入力snapshot、Semantic Plan、Semantic Validation、Character出力、Observer output/model boundary、Post-Observation Validation、最終response、generation resultをコピーできる。

API key / Basic認証passwordは結果へ含めない。

上流診断用`response_context`にはEmotion/Drive snapshotが残るが、それはLab表示用であり、`character_model_boundary` / `observer_model_boundary` / `validator_model_boundary`でLLMへ渡っていないことを別々に確認する。

## 自動テスト

専用workflow:

```text
.github/workflows/cloud-character-response-validation.yml
```

現行workflowはObserver/typed comparison/Post-Observation Validatorを含むFocused gateを実行する。最新PR #234 snapshotでは144 testsがPASSしている。

## Verification完了条件

- fake modeでSemantic/Character/Observer/Post-Observation各境界のwiringを確認
- live modeでCharacter/Observer/Validatorの実LLM callを観測
- raw stateがCharacter/Observer/Validator model invocationへ漏れていない
- Basic4 + E1-E8 = 12ケースを同一条件で実行
- 少数のunseen paraphraseを有限自然語辞書なしで確認
- known false accept / false reject原因クラスが再発しない
- Body/TTS/Avatar未接続で検証できる
- 実LLM検証後もDraftのまま、ユーザー確認までマージしない

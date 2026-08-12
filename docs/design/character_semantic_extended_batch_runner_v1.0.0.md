# Character Semantic Extended Verification Batch Runner v1.0.0

## 目的

Semantic Validation Lab の Extended Verification を、同一の Render / model / branch 条件で一括収集できるようにする。

このランナーの責務は **検証ケースの実行と観測結果の収集** であり、CharacterLLM の意味的妥当性を自動採点することではない。

## 背景

Extended Verification をケースごとに `実行 → FAIL箇所だけ修正 → 次ケース` と進めると、個別ケースへの局所最適化が積み上がる危険がある。

今後は意味空間の代表ケースをまとめて実行し、結果を原因クラス単位で分析する。そのため、ブラウザで各presetを手動実行する代わりに一括収集用コマンドを用意する。

## 境界

ランナーは既存Lab APIだけを利用する。

```text
GET  /health
GET  /api/presets
POST /api/character-response  × selected presets
```

新しいCharacter生成経路、Validator経路、Semantic Plan生成経路は作らない。

## 実行方式

- `/api/presets` から現在のpreset定義を取得する。
- 既定ではkeyが `extended_` で始まるpresetをサーバー返却順に選択する。
- 各presetの `data` を既存 `/api/character-response` へ **逐次** POST する。
- 1ケースのHTTP失敗で残りケースを中断せず、runner errorとして記録して次へ進む。
- 1本の長時間HTTPリクエストに全ケースを詰め込まない。Render / provider timeout時の切り分けと部分失敗の観測を容易にする。

## 自動PASS/FAIL判定をしない理由

今回の検証対象には Character Realization Validator 自身も含まれる。

`generation_result.status=validated` や `realization_validation.accepted=true` をそのまま最終PASSとすると、Validatorのfalse acceptを見逃す可能性がある。

したがってランナーは以下を収集するだけとする。

- Semantic Utterance Plan
- Semantic Validation
- Character Utterance
- Character model boundary
- Realization Validation
- Validator model boundary
- generation_result / attempts
- model_calls
- elapsed time
- request preset identity

意味的な最終PASS/FAILは、別途定義する意味空間テストマトリクスと照合して行う。

## 出力

単一JSONファイルに以下を保存する。

```text
schema_version
executed_at
base_url
health
preset_prefix
selected_preset_keys
transport_error_count
cases[]
  preset_key
  label
  request
  result | runner_error
```

認証passwordは出力しない。

## 認証

既存Labと同じHTTP Basic Authを使用する。

推奨は環境変数:

```text
YURA_LAB_USERNAME
YURA_LAB_PASSWORD
```

CLI引数へpasswordを直接書いてshell historyへ残す運用は推奨しない。

## 終了コード

- `0`: 選択した全ケースのHTTP実行が完了した。SemanticなPASSを意味しない。
- `1`: 1ケース以上でtransport/API errorが発生した。残りケースは可能な限り実行する。
- `2`: URL、認証、preset取得など一括実行開始前の設定エラー。

## 非目標

- CharacterLLMの台詞品質・可愛さ・ゆららしさの採点
- Semantic PASS/FAILの自動決定
- Product Brain runtimeの変更
- TTS / Body / Avatar / full runtime起動
- 並列OpenAI呼び出し

## 推奨コマンド

```bash
YURA_LAB_USERNAME='...' \
YURA_LAB_PASSWORD='...' \
.venv/bin/python -m cloud_validation.character_semantic_extended_batch \
  --base-url 'https://<render-service>' \
  --output extended-verification.json
```

このJSONを1回分の検証証跡として保存し、全ケースをまとめて分析する。

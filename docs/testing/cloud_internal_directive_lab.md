# Cloud Internal Directive Lab

## 概要

`cloud_validation.internal_directive_lab` は、司令塔LLM（`InternalDirectivePlanner`）だけをブラウザから実行する検証用Webアプリです。

入力意味解析済みの `StructuredInputMeaning`、内部状態、Activity情報、Character Profileを入力し、`InternalDirective` の生成後に停止します。入力意味解析、実行可否判定、Character LLM、出力処理は実行しません。

## ローカル起動

```bash
export YURA_INTERNAL_DIRECTIVE_LAB_MODE=fake
export YURA_LAB_USERNAME=tester
export YURA_LAB_PASSWORD=secret
python -m uvicorn cloud_validation.internal_directive_lab:app \
  --host 127.0.0.1 \
  --port 8001
```

ブラウザで `http://127.0.0.1:8001/` を開き、設定したBasic認証情報を入力します。

## liveモード

```bash
export YURA_INTERNAL_DIRECTIVE_LAB_MODE=live
export YURA_INTERNAL_DIRECTIVE_LAB_MODEL='<model-name>'
export OPENAI_API_KEY='<api-key>'
export YURA_LAB_USERNAME='<username>'
export YURA_LAB_PASSWORD='<password>'
python -m uvicorn cloud_validation.internal_directive_lab:app \
  --host 127.0.0.1 \
  --port 8001
```

APIキー名を変更する場合は `YURA_INTERNAL_DIRECTIVE_LAB_API_KEY_ENV` を設定します。

## 画面入力

- `StructuredInputMeaning`: 入力意味解析ラボの `parsed_response` を貼り付け可能
- `内部状態`: emotion、drive、relationship、motivation、moralなど
- `利用可能Activity`: 司令候補として参照させるActivity一覧
- `進行中Activity`: 存在しない場合は `null`
- `Character Profile / 存在境界`: 身体能力、知覚、経験範囲を含むプロフィール

初期値が入力済みのため、そのまま実行して疎通確認できます。

## 結果の確認

- `valid=true`: LLM応答が `InternalDirective` 契約として受理された
- `Parsed InternalDirective`: 後段が利用する構造化結果
- `Raw LLM Response`: モデルの生応答
- `stop stage`: `internal_directive_planner`
- `Prompt`: チェック時のみ表示

`valid=false` の場合は `error_type` と `error_message` を確認します。

## Render

`render.internal-directive-lab.yaml` をBlueprintとして使用します。Secret項目として以下を設定します。

- `YURA_INTERNAL_DIRECTIVE_LAB_MODEL`
- `OPENAI_API_KEY`
- `YURA_LAB_USERNAME`
- `YURA_LAB_PASSWORD`

Render上では `YURA_INTERNAL_DIRECTIVE_LAB_MODE=live` が指定されます。

## テスト

```bash
pytest -q \
  tests/test_cloud_internal_directive_lab.py \
  tests/test_cloud_internal_directive_blueprint.py \
  tests/test_input_meaning_directive_separation.py \
  tests/test_internal_directive_runtime_guards.py
```

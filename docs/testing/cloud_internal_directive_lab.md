# Cloud Internal Directive Lab

## 概要

`cloud_validation.internal_directive_lab_reviewed` は、司令塔LLM（`InternalDirectivePlanner`）だけをブラウザから実行する検証用Webアプリです。

入力意味解析済みの `StructuredInputMeaning`、内部状態、Activity情報、Character Profileを入力し、`InternalDirective` の生成後に停止します。入力意味解析、実行可否判定、Character LLM、出力処理は実行しません。

## ローカル起動

```bash
export YURA_INTERNAL_DIRECTIVE_LAB_MODE=fake
export YURA_LAB_USERNAME=tester
export YURA_LAB_PASSWORD=secret
python -m uvicorn cloud_validation.internal_directive_lab_reviewed:app \
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
python -m uvicorn cloud_validation.internal_directive_lab_reviewed:app \
  --host 127.0.0.1 \
  --port 8001
```

APIキー名を変更する場合は `YURA_INTERNAL_DIRECTIVE_LAB_API_KEY_ENV` を設定します。

## プリセット

画面上部の「検証プリセット」から代表的な条件を選択できます。選択した時点で、次の入力がすべてプリセット値へ置き換わります。

- `StructuredInputMeaning`
- 内部状態
- 利用可能Activity
- 進行中Activity
- Character Profile / 存在境界

現在用意しているプリセットは以下です。

- 現在の気分への直接質問
- うれしい出来事への共感
- 強い好奇心で話題を広げる
- 低活性で聞き続ける
- 会話を短く締める
- 進行中Activityを継続する
- 存在境界に関する質問

「存在境界に関する質問」は`yesterday_outing`を対象とするため、入力意味契約上の`past_reference`は`true`です。

プリセット適用時にLLMは実行されません。値を確認・調整した後、「司令塔LLMを実行」を押します。

プリセット適用後に値を変更し、元の条件へ戻したい場合は「選択中を再適用」を押します。再適用すると追加した内部状態項目やActivityも削除され、プリセットの完全な状態へ戻ります。

## 画面入力

- `StructuredInputMeaning`: 入力意味解析ラボの `parsed_response` を貼り付け可能
- `内部状態`: emotion、drive、relationship、motivation、moralなど
- `利用可能Activity`: 司令候補として参照させるActivity一覧
- `進行中Activity`: 存在しない場合は `null`
- `Character Profile / 存在境界`: 身体能力、知覚、経験範囲を含むプロフィール

各領域はGUI入力とJSON入力を切り替えられます。プリセットを適用した場合、GUIとJSONの両方へ同じ値が同期されます。

初期値が入力済みのため、そのまま実行して疎通確認することもできます。

## セクションの折りたたみ

次の5セクションは、ヘッダー右側の「折りたたむ」「展開する」ボタンで個別に開閉できます。

- `StructuredInputMeaning`
- 内部状態
- 利用可能Activity
- 進行中Activity
- Character Profile / 存在境界

折りたたんでも入力値、GUI/JSONモード、プリセット値は変化しません。

内部状態の円形サマリーは折りたたみ対象外です。内部状態の詳細入力を閉じても、感情・欲求・関係性・動機・善悪の平均値と最大項目は常に確認できます。

## ChatGPT用テキストExport

「ChatGPT用テキストをExport」を押すと、現在の検証条件をUTF-8の `.txt` ファイルとしてダウンロードします。

必ず次の5入力領域を含みます。

- `StructuredInputMeaning`
- 内部状態
- 利用可能Activity
- 進行中Activity
- Character Profile / 存在境界

LLM実行結果が画面に表示されている場合は、次も同じファイルへ追記します。

- valid
- mode / model
- elapsed
- stop stage
- Parsed InternalDirective
- Raw LLM Response
- Prompt（結果へ含めた場合のみ）

ファイル先頭には、ChatGPTへ評価を依頼するための説明文が入ります。ChatGPTへファイルを添付するだけで、入力と司令結果の整合性評価を依頼できます。

ファイル名は次の形式です。

```text
yura-internal-directive-lab-YYYYMMDD-HHMMSS.txt
```

APIキー、Basic認証情報、Render環境変数はExportされません。

JSON入力モードの内容が不正な場合は、ファイルを作らず画面にJSONエラーを表示します。

## 結果の確認

- `valid=true`: LLM応答が `InternalDirective` 契約として受理された
- `Parsed InternalDirective`: 後段が利用する構造化結果
- `Raw LLM Response`: モデルの生応答
- `stop stage`: `internal_directive_planner`
- `Prompt`: チェック時のみ表示

`valid=false` の場合は `error_type` と `error_message` を確認します。

## Render

`render.internal-directive-lab.yaml` をBlueprintとして使用します。起動先は次です。

```text
cloud_validation.internal_directive_lab_reviewed:app
```

Secret項目として以下を設定します。

- `YURA_INTERNAL_DIRECTIVE_LAB_MODEL`
- `OPENAI_API_KEY`
- `YURA_LAB_USERNAME`
- `YURA_LAB_PASSWORD`

Render上では `YURA_INTERNAL_DIRECTIVE_LAB_MODE=live` が指定されます。

## テスト

```bash
pytest -q \
  tests/test_cloud_internal_directive_lab.py \
  tests/test_cloud_internal_directive_reviewed_lab.py \
  tests/test_cloud_internal_directive_blueprint.py \
  tests/test_input_meaning_directive_separation.py \
  tests/test_internal_directive_runtime_guards.py \
  tests/test_internal_directive_impossible_experience_boundary.py \
  tests/test_internal_directive_impossible_experience_boundary_smoke.py
```

# 入力意味解析クラウド検証ラボ

## 目的

PCを使用できない状況でも、スマートフォンのブラウザからInput Meaning Interpreterを実行し、
`StructuredInputMeaning`の生成結果を確認できる一時検証環境を提供する。

この検証環境は`develop`から作成した
`test/input-meaning-cloud-validation`だけに置き、`develop`へはマージしない。

## ブランチ方針

```text
develop
  ├─ refactor/input-meaning-directive-separation
  │    └─ 本来の機能実装
  │
  └─ test/input-meaning-cloud-validation
       ├─ 上記作業ブランチを統合
       ├─ クラウド検証コードを追加
       └─ 検証終了後に閉じる／削除
```

本来の入力意味解析機能は既存の積み上げPR経路から`develop`へ取り込む。
検証ブランチのWeb画面、Render設定、一時認証設定は取り込まない。

## 実行境界

```text
ブラウザ入力
  -> FastAPI
  -> InputMeaningPromptBuilder
  -> InputMeaningInterpreter
  -> InputMeaningModel（FakeまたはOpenAI）
  -> InputMeaningJsonParser
  -> StructuredInputMeaning
  -> ブラウザ表示
  -> 停止
```

次は実行しない。

- Internal Directive Planner
- Activity選択・実行
- Character LLM
- Response Validator
- TTS／VOICEVOX
- Avatar／OBS／YouTube
- Topic Memory永続化
- 自律活動ループ

意味解析のPromptBuilder、Interpreter、Parserは本番コードを再利用する。
クラウド用に意味解析ロジックを複製しない。

## HTTP API

### `GET /health`

認証なしでRenderのHealth Checkに使用する。

秘密値は返さず、以下だけを返す。

- 実行モード
- 認証設定の有無
- Live実行設定の有無
- モデル設定の有無
- 停止位置

### `GET /`

Basic認証後、スマートフォン向け検証画面を返す。

### `POST /api/input-meaning`

Basic認証必須。

入力例:

```json
{
  "text": "今は何をしたい気分ですか？",
  "current_topic": "現在の気分",
  "conversation_history": [],
  "include_prompt": true
}
```

結果例:

```json
{
  "mode": "live",
  "provider": "openai",
  "model": "configured-model",
  "valid": true,
  "raw_response": "{...}",
  "parsed_response": {
    "input_speech_act": "question"
  },
  "stopped_at": "input_meaning_interpreter",
  "executed_later_stages": []
}
```

## 実行モード

### Fake

```text
YURA_INPUT_MEANING_LAB_MODE=fake
```

外部APIを呼ばず、決定的なJSONを返す。
CI、認証、画面、Parser接続の確認に使用する。

### Live

```text
YURA_INPUT_MEANING_LAB_MODE=live
YURA_INPUT_MEANING_LAB_MODEL=<OpenAI model>
OPENAI_API_KEY=<secret>
```

既存の`OpenAIResponseGenerator`と`ResponseGeneratorRoleAdapter`を使用する。
APIキーがない場合はFail Closedとし、意味解析失敗として表示する。

## 認証

必須環境変数:

```text
YURA_LAB_USERNAME
YURA_LAB_PASSWORD
```

未設定の場合、`/`と`/api/input-meaning`は`503`で拒否する。
認証失敗時は`401`と`WWW-Authenticate: Basic`を返す。

APIキー、パスワード、Authorization Headerをレスポンスやログへ出さない。

## Render

検証ラボ専用のBlueprintとして、リポジトリ直下の
`render.input-meaning-lab.yaml`を使用する。
既存の`render.yaml`には他GUIサービスと別ブランチの定義が含まれるため、
本ラボの作成には使用しない。

Render DashboardでBlueprintを作成するときは次を指定する。

```text
Branch: test/input-meaning-cloud-validation
Blueprint Path: render.input-meaning-lab.yaml
```

初回作成画面で次の値を入力する。

```text
YURA_INPUT_MEANING_LAB_MODEL
OPENAI_API_KEY
YURA_LAB_USERNAME
YURA_LAB_PASSWORD
```

起動コマンド:

```bash
python -m uvicorn cloud_validation.input_meaning_lab:app \
  --host 0.0.0.0 \
  --port "$PORT"
```

無料Web Serviceは非アクティブ時に停止し、ファイルシステムは永続化されない。
本ラボは結果をDBやローカルファイルへ永続化しない。

## 検証

```bash
pytest -q \
  tests/test_cloud_input_meaning_lab.py \
  tests/test_input_meaning_test_module.py
```

GitHub Actionsの
`.github/workflows/cloud-input-meaning-validation.yml`
でも同じ範囲を実行する。

## CI結果（2026-08-03）

CI確認専用のDraft PR #128を
`test/input-meaning-cloud-validation`向けに作成し、専用Workflowを実行した。
PRはマージせず、成功確認後に閉じた。

- Workflow: `Cloud input meaning validation`
- Run ID: `30783663899`
- Run number: `2`
- Python: `3.10`
- 新規クラウドラボテスト: 5件
- 既存意味解析テストモジュール: 3件
- 合計: 8件
- 結果: 成功

確認した境界:

- Health Checkは認証なしで利用可能
- 検証画面と解析APIはBasic認証必須
- 認証未設定時はFail Closed
- Fakeモードで本番PromptBuilder／Interpreter／Parserを通過
- `StructuredInputMeaning`生成後に停止
- Internal Directive以降の実行結果は空

## 終了条件

以下を確認後、このブランチを閉じるか削除する。

- スマートフォンから認証できる
- 実入力を送信できる
- OpenAIから生レスポンスを取得できる
- Parserの成否を表示できる
- Internal Directive以降が実行されない
- APIキーや認証情報が画面・ログへ露出しない
- 本来の機能修正が作業ブランチ側へ反映済み

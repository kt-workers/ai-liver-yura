# 内部指示器（司令塔LLM）クラウド検証モジュール設計 v1.0.0

## 1. 目的

ブラウザ上の独立した検証環境で `InternalDirectivePlanner` を実行し、司令塔LLMが生成する `InternalDirective` を観察できるようにする。

本モジュールは入力意味解析ラボと同じく Render の独立Webサービスとして起動する。ただし、検証対象を司令塔LLMだけに限定するため、ユーザーの生テキストは入力せず、入力意味解析済みの `StructuredInputMeaning` を直接受け取る。

## 2. 検証境界

実行する処理は次の1段のみとする。

```text
StructuredInputMeaning
+ Internal State
+ Available Activities
+ Ongoing Activity
+ Character Profile / Existence Boundaries
        ↓
InternalDirectivePromptBuilder
        ↓
InternalDirectivePlanner（司令塔LLM）
        ↓
InternalDirectiveJsonParser
        ↓
停止
```

次の処理は実行しない。

- Input Meaning Interpreter
- Internal Directive Validator
- Capability / Authority / Safetyによる実行可否判定
- Activity実行
- Character LLM
- Response Validator
- TTS、字幕、アバターなどの出力プラグイン

## 3. 入力契約

### 3.1 StructuredInputMeaning

本番の `InputMeaningJsonParser` が受理できるJSONを入力する。これにより、検証画面独自の緩い入力形式を作らず、本番契約と同じ境界を使用する。

主な項目は以下とする。

- `input_speech_act`
- `primary_intent`
- `expected_response`
- `target`
- `entities`
- `references`
- `information_provided`
- `negated`
- `hypothetical`
- `past_reference`
- `conversation_phase_signal`
- `confidence`
- `reason`

### 3.2 Internal State

司令塔LLMが判断材料として利用する状態をJSONで入力する。

- `emotion`
- `drive`
- `relationship`
- `motivation`
- `moral`
- `situation`
- `memory`
- `related_knowledge`
- `last_activity_result`

### 3.3 Activity情報

- `ongoing_activity`: 進行中Activity。存在しない場合は `null`
- `available_activities`: 司令候補として参照できるActivity一覧

司令塔LLMはActivityの意図候補を生成できるが、実行可能性や成功を確定してはならない。

### 3.4 Character Profile

キャラクター性と存在境界を入力する。特に以下を司令の制約へ反映する。

- physical capabilities
- sensory capabilities
- experience boundaries
- world relationship

## 4. 出力契約

APIは以下を返す。

- `valid`: `InternalDirectiveJsonParser` が受理したか
- `raw_response`: LLMの生応答
- `parsed_response`: `InternalDirective.as_context()`
- `prompt`: 指定時のみ実際のプロンプト
- `elapsed_ms`: LLM呼び出しから解析までの時間
- `error_type` / `error_message`
- `stopped_at`: 常に `internal_directive_planner`
- `not_executed`: 実行しなかった後段一覧

## 5. UI方針

入力意味解析ラボと同系統のデザインとし、スマートフォンからも利用可能にする。

画面には次を表示する。

1. StructuredInputMeaning JSON
2. 内部状態 JSON
3. 利用可能Activity JSON
4. 進行中Activity JSON
5. Character Profile / 存在境界 JSON
6. プロンプト表示切替
7. Parsed InternalDirective
8. Raw LLM Response
9. モデル、実行時間、停止位置、契約妥当性

初期値として「現在の気分への直接質問」を用意し、初回表示直後から実行できるようにする。

## 6. 実行モード

### fake

外部APIを使用せず、入力の発話行為と期待応答に応じた決定論的な `InternalDirective` を返す。HTTP、認証、パーサー、停止境界のテストに使用する。

### live

`OpenAIResponseGenerator` と `ResponseGeneratorRoleAdapter` を通して実際のモデルを呼び出す。本番と同じ `InternalDirectivePromptBuilder`、`InternalDirectivePlanner`、`InternalDirectiveJsonParser` を使用する。

## 7. 環境変数

- `YURA_INTERNAL_DIRECTIVE_LAB_MODE`: `fake` または `live`
- `YURA_INTERNAL_DIRECTIVE_LAB_MODEL`: 使用モデル
- `YURA_INTERNAL_DIRECTIVE_LAB_API_KEY_ENV`: APIキーを格納した環境変数名。既定値は `OPENAI_API_KEY`
- `YURA_INTERNAL_DIRECTIVE_LAB_TIMEOUT_SECONDS`: タイムアウト秒数
- `YURA_LAB_USERNAME`: Basic認証ユーザー名
- `YURA_LAB_PASSWORD`: Basic認証パスワード

認証情報が未設定の場合、検証画面とAPIはfail-closedとする。`/health` のみ公開する。

## 8. Render配置

`render.internal-directive-lab.yaml` に独立したWebサービスを定義する。

- Service name: `yura-internal-directive-lab`
- Branch: `test/internal-directive-cloud-validation`
- Start command: `python -m uvicorn cloud_validation.internal_directive_lab:app --host 0.0.0.0 --port $PORT`
- Health check: `/health`
- Plan: free

入力意味解析ラボとはサービス、環境変数、モデル指定を分離する。Basic認証用変数は共通名を使用できる。

## 9. テスト方針

- `/health` が停止位置を返す
- Basic認証なしでは画面/APIへアクセスできない
- fakeモードで有効なInternalDirectiveを返す
- 後段が実行されていないことをレスポンスで確認する
- 不正なStructuredInputMeaningを400で拒否する
- Render Blueprintが専用ブランチ・専用モジュール・Secret placeholderを参照する
- 関連する責務分離・runtime guardテストを専用CIで実行する

## 10. 非目標

- 入力意味解析ラボからの直接API連携
- 本番状態DBの参照・更新
- state update proposalの適用
- Activityの開始・停止
- キャラクター発話の品質評価
- 複数モデルの自動比較

最初の版ではコピー＆ペースト可能なJSON境界を優先し、各LLMを独立して検証できる状態を維持する。

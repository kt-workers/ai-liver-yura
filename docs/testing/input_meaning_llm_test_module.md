# 意味解析LLMテストモジュール

## 目的

会話処理全体を動かすと、Input Meaning Interpreter、Internal Directive、Activity、Character、Validator、TTSなどの結果が混ざり、意味解析だけの妥当性を確認しにくくなります。

このモジュールは通常のCore起動、設定読込、Plugin初期化、Web／Console入力、ユーザー入力のIngress、履歴記録、BehaviorPlanningContext構築までは本番と同じ経路を使用します。

USER_TEXTを受け取ると、Input Meaning Interpreter LLMを実行し、`StructuredInputMeaning`を記録した時点でそのTurnを消費します。

次の処理には進みません。

- Internal Directive Planner
- Activity選択・実行
- Character LLM
- Response Validator
- TTS／音声再生

`APP_STARTED`などUSER_TEXT以外のイベントは通常経路へ渡します。

## 起動方法

対象ブランチを最新化します。

```bash
git switch refactor/input-meaning-directive-separation
git pull --ff-only
```

通常のWeb会話入力を使う場合は、次のコマンドで起動します。

```bash
.venv/bin/python -m app.input_meaning_test
```

Web会話を無効にし、ターミナルから入力する場合は次のように起動します。

```bash
YURA_WEB_CONVERSATION_ENABLED=0 \
  .venv/bin/python -m app.input_meaning_test
```

終了方法は通常起動と同じです。

```text
Ctrl-C
```

## 出力内容

入力ごとに、ターミナルへ次の情報を表示します。

- 入力本文
- LLMの生レスポンス
- Parserが受理した構造化結果
- Schema検証の成否
- 処理時間
- 例外またはSchema不一致の理由

同じ内容を次のJSONLへ1入力1行で保存します。

```text
logs/input_meaning_test.jsonl
```

保存先は環境変数で変更できます。

```bash
YURA_INPUT_MEANING_TEST_LOG=logs/my_meaning_test.jsonl \
  .venv/bin/python -m app.input_meaning_test
```

通常はPrompt全文をJSONLへ保存しません。Promptも比較したい場合だけ次を指定します。

```bash
YURA_INPUT_MEANING_TEST_INCLUDE_PROMPT=1 \
  .venv/bin/python -m app.input_meaning_test
```

## 出力例

```json
{
  "timestamp": "2026-08-03T10:50:00+09:00",
  "source_event_id": "...",
  "input": "今は何をしたい気分ですか？",
  "valid": true,
  "elapsed_ms": 532.418,
  "raw_response": "{...}",
  "parsed_response": {
    "input_speech_act": "question",
    "primary_intent": "ask_agent_internal_state",
    "expected_response": "direct_answer",
    "target": {
      "type": "agent_internal_state",
      "id": "current_desire"
    }
  },
  "error_type": null,
  "error_message": null
}
```

## 通常起動との違い

通常起動は次です。

```bash
.venv/bin/python -m app
```

意味解析テスト起動は次です。

```bash
.venv/bin/python -m app.input_meaning_test
```

通常起動側のCompositionやクラス実装は変更しません。テスト起動時だけ、生成済みRuntimeのBehavior Routingへ診断フックを装着します。

また、通常経路では固定判定される可能性がある挨拶、相槌、終了表現も、このテストでは意味解析LLMへ必ず送ります。これはInput Meaning Interpreter自体の分類結果を確認するためです。

## 推奨テスト入力

```text
おはよう
了解
今日はこのくらいかな
今は何をしたい気分ですか？
眠気ある？
お腹は空いてる？
あいうえお
しまなみ海道だよ
ゲームを始めて
ゲームは始めなくていい
```

各入力について、少なくとも次を確認します。

- `input_speech_act`
- `primary_intent`
- `expected_response`
- `target.type` / `target.id`
- `information_provided`
- `negated`
- `hypothetical`
- `past_reference`
- `conversation_phase_signal`
- `confidence`

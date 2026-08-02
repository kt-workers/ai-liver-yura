# 入力意味解析・内部司令LLM分離 設計追補 v1.0.1

## 1. 目的

`input_meaning_internal_directive_separation_v1.0.0.md`の段階移行方針へ、進行中Activity入力の扱いを追補する。

## 2. 進行中Activity入力の移行境界

進行中Activityが存在するユーザー入力は、今回の変更では既存Situation Evaluatorの安全な継続判定へ残す。

理由は、進行中Activityの入力意味が通常会話だけでは確定せず、次のプラグイン固有契約に依存するためである。

- `expected_input`
- Activity固有の操作
- プラグイン状態要約
- 直近ターン
- start / continue / stopの意味境界

一般会話用`InputMeaningInterpreter`がこれらを独自解釈すると、プラグイン契約とCore判断が競合する可能性がある。

## 3. 現在の経路

```text
通常のuser_text
  -> InputMeaningInterpreter LLM
  -> StructuredInputMeaning
  -> InternalDirectivePlanner LLM
  -> Core Validator

進行中Activityを伴うuser_text
  -> 既存Situation Evaluator
  -> Activity固有の継続・停止判定
```

この例外はShadow動作ではない。通常会話経路は新しい構造化結果を実際に利用し、進行中Activityだけを明示的な移行対象外としている。

## 4. Fallback条件

次の場合は既存Situation Evaluatorへ退避する。

- 進行中Activityが存在する
- Input Meaning JSONの生成またはparseに失敗する
- Internal Directive JSONの生成またはparseに失敗する
- システムイベントである

## 5. 後続移行条件

進行中Activityを二段階LLMへ移行する前に、次の契約を追加する。

```text
ActivityInputMeaningSchema
ActivityInputMeaningInterpreter
ActivityContinuationDirective
```

`ActivityDefinition`またはプラグイン公開契約から、入力候補、操作、制約、状態要約を型付きで渡す。一般会話用の`StructuredInputMeaning`だけで推測しない。

## 6. 回帰保証

既存の進行中Activity回帰テストでは、次を維持する。

- `ongoing_activity_id`
- `expected_input`
- `plugin_state_summary`
- `recent_turns`
- Activity RegistryとCapabilityによる実行前検証

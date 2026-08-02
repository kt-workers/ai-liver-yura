# 入力意味解析・内部司令LLM分離 設計追補 v1.0.1

## 1. 目的

`input_meaning_internal_directive_separation_v1.0.0.md`の段階移行方針へ、進行中Activity入力と旧Situation応答の扱いを追補する。

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

### 4.1 旧Situation応答の単回再利用

Input Meaning用Promptへの最初の応答が`StructuredInputMeaning`ではなく、有効な旧Situation Evaluator JSONだった場合は、その応答を捨てて同じLLMを再呼び出さない。

次の必須フィールドを持つJSONを旧Situation応答として認識し、既存の正規化・検証経路へそのまま渡す。

- `decision`
- `activity_type`
- `operation`
- `confidence`

これにより、段階移行中の旧Adapter、テスト用Generator、旧モデル挙動との互換性を維持しつつ、失敗時の不要な重複呼び出しと遅延を防ぐ。

Input Meaningとして正常に解釈できた後にInternal Directive生成が失敗した場合は、この再利用条件には該当しないため、従来どおり旧Situation Evaluatorへ明示的にFallbackする。

### 4.2 Input Meaning Promptの旧責務境界

段階移行中の監査と既存プロンプト回帰を明確にするため、Input Meaning Promptには旧Situation Evaluatorの責務名を否定形で記載する。

```text
旧責務「入力を総合して次のActivityを決定」は、このRoleでは行わない。
```

また、`available_activities`はInput Meaning Interpreterへ実データを渡さず、未提供であることだけを役割境界メタデータとして示す。Activity候補の参照と選択はInternal Directive Planner以降に限定する。

### 4.3 高確信度の表面Fallback

通常会話の「どんな」「一般的な教えて」「疑問符・語尾」「仮定表現」は固定語句で分類せず、Input Meaning Interpreterへ渡す。

一方、LLM失敗時にも既存Activityの安全な会話回帰を維持するため、意味がほぼ一意な次の表現だけはFallbackとして残す。

- 定義・ルール質問: `〜って何`、`〜とは何`、`ルールを教えて`、`仕組みを教えて`、`意味を教えて`
- 明示的な過去参照: `昨日`等の時点表現と、`〜をした`等の完了表現の組合せ
- 明示的な実行・停止・否定要求

これらはActivityを選択・実行するための分類ではない。`KNOWLEDGE`と`PAST_EVENT`は会話へ固定し、説明、過去参照、否定、仮定がActivity開始へ誤変換されないために使用する。

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

旧Situation応答の互換テストでは、最初の応答が有効な旧契約である場合、基盤Generatorの呼び出しが1回に留まることを保証する。

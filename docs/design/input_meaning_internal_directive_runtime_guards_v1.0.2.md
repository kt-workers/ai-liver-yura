# 入力意味解析・内部司令 実行時Guard設計 v1.0.2

## 1. 背景

二段階LLMを実環境で動作確認した結果、`InputMeaningInterpreter`と`InternalDirectivePlanner`は意図どおり稼働していた。一方、移行前から存在する`ConversationResponseDecision`と`ResponseContentPlan`がCharacter Prompt生成時に再計算され、検証済みInternal Directiveより強い質問・話題展開方針を生成する経路が確認された。

代表例では、Internal Directiveが次を確定していた。

```text
response_mode = listen
question_budget = 0
new_direction_budget = 0
```

しかし、後段の好奇心・欲求ベースの会話方針計算が`mode=ask`と`question_budget=1`を生成し、Character LLMが無関係な質問を追加した。

また、終了意図に対してCharacter LLMが空の`speech`または空JSONを返すと、構造化応答エラーとして一般的な失敗Fallbackが発話される問題も確認された。

## 2. 優先順位

会話表現に関する方針は次の順序で優先する。

```text
Core Safety / Authority / Activity Validation
  > Validated Internal Directive
  > Conversation Response Decision
  > Response Content Plan
  > Character表現上の裁量
```

`ConversationResponseDecision`と`ResponseContentPlan`は、Validated Internal Directiveを変更する独立判断器ではない。欲求・感情・好奇心を表現へ反映する補助計画として、Internal Directiveの上限内でのみ使用する。

## 3. Character Promptへの投影

Validated Internal DirectiveをCharacter Promptへ渡す前に、旧Response Content Planを次のように保守的に投影する。

- `response_mode`に対応する会話戦略だけを残す
- `question_budget`をInternal Directive以下へ制限する
- `new_direction_budget`をInternal Directive以下へ制限する
- `listen`、`react`、`observe`ではinitiativeを低く抑える
- `closing`または`winding_down`を終了段階として維持する
- 旧`primary_desire=curiosity`による質問再許可を行わない

この投影後も、Prompt内にはValidated Internal Directiveを最終方針として明記する。

## 4. 生成後の決定論的検証

Response ValidatorのLLM判定より前に、Core側で次を検証する。

- 質問数が`question_budget`を超えていない
- 明示的な別話題への移動が`new_direction_budget`を超えていない
- 終了段階で質問して会話を再開していない
- 終了挨拶が不必要に長くなっていない
- 存在境界に反する明示的な現地体験・身体感覚を主張していない

違反時はCharacter Responseを採用せず、既存の再生成経路へ戻す。

## 5. 終了意図の出力契約

現行の出力パイプラインでは発話テキストが必須であるため、終了意図を無発話へ変換しない。

Core Validatorは終了意図を次へ確定する。

```text
response_mode = react
question_budget = 0
new_direction_budget = 0
content_requirement = 短い別れの挨拶を1文で返す
```

Character Roleが空JSON、空`speech`、または不正な構造を返した場合は、終了段階に限りRole Adapter境界で次の有効なCharacter Responseへ正常化する。

```text
おやすみ。またね。
```

これは一般的な生成失敗Fallbackではなく、終了意図に対する限定的な契約Fallbackである。

## 6. 回帰保証

次を自動テストで保証する。

- 好奇心が高く旧Planが質問を要求しても、`listen/question_budget=0`を上書きしない
- `question_budget=0`で疑問文を生成した場合は決定論的に拒否する
- `new_direction_budget=0`で明示的に別話題へ移動した場合は拒否する
- `closing`で質問を追加した場合は拒否する
- 終了段階の空Character応答を短い別れの挨拶へ変換する
- 存在境界に反する明示的な現地体験・身体感覚を拒否する

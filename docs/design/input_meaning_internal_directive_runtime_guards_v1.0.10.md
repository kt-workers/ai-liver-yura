# Input Meaning / Internal Directive Runtime Guards v1.0.10

## 目的

ユーザーが既存Knowledge Gapへ回答した場合に、Internal Directive Plannerが回答内容を再説明する候補を返しても、Character LLMへは短い受領・理解反応を渡す。

## 背景

実OpenAIによる13プリセット検証で、次の組み合わせが確認された。

- `input_speech_act=answer`
- `primary_intent=provide_answer_to_existing_gap`
- `expected_response=acknowledgement`
- 対象の既存Knowledge Gapが`resolved_knowledge_gaps`へ登録される

質問の再復元はv1.0.9で防止できたが、Planner候補が`response_mode=answer`のまま、ユーザーが提供済みの情報をゆら自身がもう一度説明する可能性が残っていた。

## 正規化条件

Candidate Normalizerは、次の条件をすべて満たす場合に受領反応へ正規化する。

1. `expected_response=acknowledgement`
2. `input_speech_act=answer`、またはPrimary Intentが既存Gapへの回答・解消を表す
3. 現在targetと一致する`target_interest_updates`に、1件以上の`resolved_knowledge_gaps`がある

単なる回答入力や、解消対象のGapが確認できない場合は変更しない。

## 正規化結果

```text
response_mode = react
question_budget = 0
new_direction_budget = 0
initiative_level <= 0.2
```

`response_goal`と`content_requirements`は次の目的へ置き換える。

- 提供された情報を理解したことが伝わる短い反応を返す
- 既存Knowledge Gapが解消されたことを自然に受け止める
- 提供された内容を必要以上に説明し直さない

`forbidden_claims`には次を追加する。

- ユーザーが提供した説明を、自分の新しい説明として繰り返す
- 追加質問や新しい話題を持ち出す

`target_interest_updates`と`resolved_knowledge_gaps`はそのまま維持する。

## reason

Normalizerが応答モードを変更した場合は、Plannerの旧reasonを残さず、次の趣旨へ更新する。

```text
Core補正: ユーザーの回答により既存Knowledge Gapが解消されたため、
内容を再説明せず短い受領・理解反応を返す
```

Raw LLM Responseは未加工のまま監査用に保持する。

## 処理順序

```text
Planner candidate
  -> Knowledge Gap回答の受領反応正規化
  -> 存在境界文の正規化
  -> 未解決Knowledge Gapの質問復元判定
  -> Core Validator
```

回答入力は質問復元対象外であり、受領反応への正規化後も`question_budget=0`を維持する。

## 回帰確認

- 解消済みGapへの回答は`react`になる
- Plannerが生成した再説明要件を残さない
- `resolved_knowledge_gaps`を維持する
- 質問と新規話題を追加しない
- 解消対象Gapがない通常回答は変更しない
- 高好奇心＋未解決Gapの質問復元を回帰させない
- 非身体入力の存在境界正規化を回帰させない

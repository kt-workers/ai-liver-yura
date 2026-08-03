# 入力意味・内部司令 Runtime Guard設計 v1.0.9

## 1. 目的

13プリセットの実OpenAI検証で、対象別関心、既存Knowledge Gap、Curiosity／Engagementが高い場合の質問復元は機能した。一方、ユーザー入力によって既存Knowledge Gapが解消されたケースでも、Candidate Normalizerが同じGapを質問対象として再利用する問題を確認した。

対象ケースではPlanner生出力が次の判断を正しく返していた。

- `response_mode=answer`
- `question_budget=0`
- 対象の`resolved_knowledge_gaps`へ回答済みGapを登録

しかしNormalizerはPlanning Input内の`related_knowledge.knowledge_gaps`だけを参照し、今回のDirectiveで解消済みかどうかを見ていなかったため、同じGapへ質問を復元した。

本設計では、質問復元対象を「対象に登録されているGap」ではなく、「今回のDirective適用後も未解決として残るGap」に限定する。

## 2. 未解決Gapの算出

現在対象と一致するRelated Knowledgeから既存Gapを取得し、同じ対象に対する`target_interest_updates.resolved_knowledge_gaps`を差し引く。

```text
eligible_gaps = existing_gaps - resolved_knowledge_gaps
```

比較時は前後空白を除去し、大文字・小文字差を無視する。

- `eligible_gaps`が空なら質問を復元しない
- 複数Gapがあり、一部だけ解消済みなら未解決Gapを質問候補にできる
- 別対象の`resolved_knowledge_gaps`は現在対象の質問候補へ影響させない

## 3. 入力意味による禁止条件

次は質問復元対象外とする。

- `input_speech_act=answer`
- `primary_intent`が既存Gapへの回答提供・解消を表す
- 直接質問、closing、command、request
- `expected_response`が`direct_answer`、`action`、`no_response`、`clarification`

これにより、Plannerが解消済みGapの更新を出せなかった場合でも、入力意味が明確な回答なら再質問しない。

## 4. 補正後reason

Normalizerが次を変更した場合、Plannerの元`reason`をそのまま残さない。

- `response_mode`
- `response_goal`
- `question_budget`
- `new_direction_budget`

補正後は、現在対象と一致する未解決Gap、対象別関心、Curiosity／Engagementの閾値によって質問を1件許可したことを`reason`へ明記する。

Raw LLM Responseは従来どおり未加工で保存されるため、Planner判断とCore補正後判断は別々に監査できる。

## 5. JSON契約

`InternalDirective`、`StructuredInputMeaning`、`TargetInterestUpdate`のJSON Schemaは変更しない。

既存フィールドのみを利用する。

- `target_interest_updates[].resolved_knowledge_gaps`
- `reason`
- `response_mode`
- `question_budget`
- `new_direction_budget`

## 6. テスト

次を回帰テストで固定する。

- 高関心・高動機・未解決Gapがある場合は質問を1件復元する
- 補正後`reason`がCore補正内容と一致する
- 回答入力で唯一のGapが解消済みなら質問を復元しない
- 解消済みGapと未解決Gapが混在する場合は未解決Gapだけを質問対象にする
- `input_speech_act=answer`では質問を復元しない
- `primary_intent=provide_answer_to_existing_gap`では質問を復元しない
- 存在境界正規化と高好奇心質問復元の既存挙動を維持する

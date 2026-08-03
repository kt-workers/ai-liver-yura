# 入力意味・内部司令 Runtime Guard設計 v1.0.8

## 1. 目的

実OpenAI検証で、現在対象と一致する高い対象別関心と既存Knowledge Gapが入力されていても、Plannerが`expected_response=acknowledgement`を優先し、`response_mode=react`、`question_budget=0`を返す例を確認した。

全体的なCuriosityだけで質問を許可しない既存方針は維持しつつ、次の根拠が揃う場合に限り、Core側で対象に沿った質問を1件だけ復元する。

## 2. 質問復元条件

すべて成立する場合だけ質問を復元する。

- 会話段階が`continue`
- 入力対象と`related_knowledge`の対象型・対象IDが一致
- 対象別関心が0.75以上
- 既存Knowledge Gapが1件以上
- `drive.curiosity>=0.75`または`motivation.engagement>=0.75`
- 直接質問、終了、命令、Activity操作、明示的な応答要求ではない
- 肯定的体験共有への共感反応ではない

## 3. 復元結果

- `response_mode=ask`
- `question_budget=1`
- `new_direction_budget=0`
- `initiative_level`を最低0.35へ補正
- 現在対象のKnowledge Gapに沿った質問を1件だけ要求
- 対象と無関係な質問、複数質問、別方向の話題展開を禁止

Planner候補に「質問しない」等の矛盾する制約が含まれていた場合、質問復元時にその制約だけを除外する。

## 4. 実装位置

`InternalDirectiveCandidateNormalizer`で、存在境界候補の正規化後に質問復元を行う。PlannerのRaw Responseは変更せず監査可能なまま保持し、Parser受理後の実行候補だけを決定論的に補正する。

`InternalDirectivePlanner`はNormalizerへ`planning_input`を渡す。既存の`InternalDirectiveValidator`は、復元後の`ask`に対して対象別Knowledge Gapを再確認し、質問Budgetの上限を1に維持する。

## 5. 非対象ケース

次の場合は質問を復元しない。

- 対象別Knowledge Gapがない
- 対象が一致しない
- 対象別関心が低い
- CuriosityとEngagementが低い
- closing／winding_down
- direct_answer、action、no_response、clarification
- 共感を優先すべき肯定的体験共有

## 6. JSON契約

`StructuredInputMeaning`、`InternalDirective`、`related_knowledge`のJSON契約は変更しない。

## 7. テスト

- 高い対象別関心、既存Gap、高いCuriosity／Engagementで質問を1件復元する
- 対象不一致、低動機、closingでは復元しない
- Plannerが`planning_input`をNormalizerへ渡す
- 存在境界正規化の既存挙動を維持する

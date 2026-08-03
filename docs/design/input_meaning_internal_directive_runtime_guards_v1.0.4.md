# 入力意味・内部司令 Runtime Guard設計 v1.0.4

## 1. 目的

Internal Directive Plannerの実OpenAI検証で、存在境界と会話予算は適切になった一方、次の更新候補が残る例を確認した。

- 入力状態に存在しないKnowledge Gapを`resolved_knowledge_gaps`へ追加する
- 直接回答や事実判明だけを理由に`interest_change=slightly_decrease`とする
- 現在の話題を「直接回答する話題」と言い換えた値を`state_update_proposals`へ追加する

これらは発話安全性への影響は小さいが、対象別関心、Knowledge Gap、内部状態の履歴を不正確にする。本設計では、Plannerが根拠のある差分だけを提案するよう制約を明確化する。

## 2. Knowledge Gap解決

`resolved_knowledge_gaps`には、`DirectiveInput`内で既存のKnowledge Gapとして確認できる項目だけを入れる。

確認元は次とする。

- `internal_state.related_knowledge`
- `internal_state.memory`
- 将来追加される対象別関心コンテキスト

該当対象に既存Gapがなければ空配列とする。存在境界から導出された事実や、そのターンで初めて表現した疑問を、解決済みGapとして新規作成してはいけない。

## 3. 関心変化

`interest_change`は、入力情報または既存の対象別関心状態に増減の明確な根拠がある場合だけ変更する。

次の事実だけでは関心低下の根拠にならない。

- ユーザーの質問へ回答した
- ある事実が判明した
- Knowledge Gapが閉じた
- そのターンの応答が完了した

根拠がない場合は`unchanged`とする。関心値そのものはPlannerで確定せず、従来どおり増減方向だけを提案する。

## 4. 状態更新候補

`state_update_proposals`には、実際に現在値を変更すべき状態だけを入れる。

次は状態更新として扱わない。

- 現在値の言い換え
- 「直接回答する」「説明する」など応答行為の記録
- `current_topic`の末尾へ「に対する直接回答」などを追加するだけの提案
- 現在値と同一の値

変更がなければ空配列とする。発話方針は`response_goal`と`content_requirements`で表し、内部状態の値へ混入させない。

## 5. Core Validatorとの関係

存在境界上不可能な身体経験については、v1.0.3のCore Validatorが`target_interest_updates`を決定論的に破棄する。したがって完全なRuntimeでは誤ったGap更新は残らない。

v1.0.4は、Validator適用前のPlanner生出力も自然にし、クラウド検証ラボで確認しやすくする改善である。既存のJSON契約と停止境界は変更しない。

## 6. テスト

次を回帰テストで固定する。

- 既存Gapだけを`resolved_knowledge_gaps`へ入れる指針
- 既存Gapがなければ空配列にする指針
- 直接回答や事実判明だけで関心を下げない指針
- 根拠がなければ`interest_change=unchanged`とする指針
- 応答行為の記録や現在値の言い換えを状態更新にしない指針
- 変更がなければ`state_update_proposals=[]`とする指針

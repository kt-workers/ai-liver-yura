# Situation Evaluator意味的同等性証拠Shadow設計 v1.0.0

## 1. 目的

MoralによるActivity候補選好を将来限定的に適用するためには、比較対象の候補が同じ意図・操作・目的を満たす代替候補であることを確認する必要がある。

本設計では、Situation Evaluatorの意味解析結果から型付きの意味的同等性証拠を生成し、既存のMoral候補選好Shadowへ渡す。ただし、実際のActivity候補順、選択、許可、禁止には影響させない。

## 2. 適用範囲

本Versionで追加する範囲は次のとおり。

- Situation Evaluator Promptへの意味的同等性評価項目の追加
- LLM出力からの候補グループ・評価次元の構造検証
- Runtimeによる証拠の出所と追跡IDの付与
- `SituationAnalysis`への型付き証拠の保持
- Moral候補選好Shadowへの証拠伝播
- Shadow結果の診断ログ出力

次は対象外とする。

- Moralによる実候補順の変更
- `activation_permitted`の有効化
- Authority、Capability、Constraint、Safetyの同等性判定
- 決定論Matcher由来の同等性証拠生成
- Character Response内容への価値判断投影
- DB永続化
- GUI表示

## 3. 信頼境界

LLMは意味評価の候補値だけを返す。次の値はLLM出力を信頼しない。

- 証拠の出所
- 証拠ID
- 実適用許可
- Authority、Capability、Constraint、Safetyの同等性

Runtimeが次を検証・付与する。

1. `candidate_group`が2件以上である
2. 候補が重複していない
3. すべての候補が現在の`ActivityDefinition`集合に存在する
4. `intent`、`operation`、`goal`が定義済み列挙値である
5. 理由が文字列配列である
6. 解析結果が確信度閾値以上である
7. `source=situation_evaluator_llm`をRuntimeが付与する
8. `source_event_id`と試行番号から追跡IDをRuntimeが発行する

LLMが`source`や`evidence_id`を出力しても使用しない。

## 4. 評価次元

意味的同等性は次の3次元を独立して評価する。

- `intent`: 同じユーザー意図または自律目的を満たすか
- `operation`: start、continue、stop、explain、discussの操作意味が同等か
- `goal`: 達成結果を相互に代替できるか

各次元は次のいずれかとする。

- `unknown`
- `confirmed`
- `rejected`

候補が2件未満、根拠不足、または実行可否しか判断できない場合は`unknown`とする。

## 5. 処理フロー

```text
BehaviorPlanningContext
    ↓
SituationEvaluatorPromptBuilder
    ├─ Motivation順位を計算
    ├─ moral_fitを観測
    └─ 証拠未設定のMoral Shadowからcandidate_groupを提示
    ↓
Situation Evaluator LLM
    ├─ Activity意味解析
    └─ candidate_groupのintent／operation／goalを出力
    ↓
SituationEvaluator.parse
    ├─ JSON構造を検証
    ├─ 候補集合を現在定義と照合
    ├─ 列挙値を検証
    ├─ LLM由来source／evidence_idを無視
    └─ Runtime由来source／evidence_idで型付きEvidenceを生成
    ↓
確信度検証
    ├─ 閾値未満: Evidenceを破棄
    └─ 閾値以上: Evidenceを維持
    ↓
SituationSemanticEquivalenceShadowObserver
    ├─ Motivation順位を決定論的に再計算
    ├─ moral_fitを決定論的に再計算
    ├─ EvidenceをMoral Shadowへ渡す
    └─ current_orderとhypothetical_orderを診断ログへ記録
```

## 6. 循環参照の回避

同一のLLM呼び出しでShadow結果を再びActivity選択へ戻さない。

Promptに含まれるShadowは証拠未設定状態でcandidate groupを提示するためだけに使用する。Situation Evaluatorが返した証拠は、LLM応答後のShadow観測へ一方向に渡す。

したがって次の循環は作らない。

```text
Moral Shadow → LLM選択 → Moral Shadow → 同一ターンで再選択
```

証拠付きShadowは診断ログにのみ使用し、実選択は最初のSituation Analysisをそのまま使用する。

## 7. 失敗時動作

次の場合は`semantic_equivalence_evidence=None`として処理を継続する。

- `semantic_equivalence`が欠落している
- candidate groupが空または1件だけである
- 候補が重複している
- 未知Activityが含まれる
- 評価次元が定義外である
- 理由が文字列配列ではない
- Runtime由来の出所または追跡IDがない
- Situation Analysisの確信度が閾値未満である

Shadow観測で例外が発生した場合もActivity Planningは失敗させず、警告ログだけを記録する。

## 8. 安全境界

次の境界を維持する。

- `activation_permitted`は常に`false`
- `available_activities`の順序を変更しない
- `current_order`をSituation Evaluatorの再入力にしない
- pinned、active、ongoing候補を移動しない
- Motivation段階を越えて比較しない
- 候補を追加・削除しない
- 決定論Matcherを上書きしない
- ユーザーの明示意図を上書きしない
- Authority、Capability、Constraint、Safety検証を迂回しない
- Moral抑制とSafety禁止を統合しない

## 9. 診断ログ

証拠付きShadow観測では次を記録する。

- `source_event_id`
- Situation Evaluator種別
- 選択候補
- 解析確信度
- 証拠ID
- 意味的同等性状態
- candidate group
- current order
- hypothetical order
- static eligible
- activation permitted
- preferred activity type
- reasons

会話本文、Prompt全文、秘密情報は追加ログへ含めない。

## 10. テスト方針

次を検証する。

- Runtime由来のsource／evidence IDだけを採用する
- LLMが出力したsource／evidence IDを無視する
- 未知候補を含む証拠を破棄する
- Runtime provenanceなしでは型付き証拠を生成しない
- 高確信度証拠をShadow observerへ渡す
- 低確信度証拠をShadow前に破棄する
- confirmed証拠でも`activation_permitted=false`を維持する
- current orderを変更せずhypothetical orderだけを計算する
- 既存のBehavior Planning、Matcher、Capability、Constraint境界を回帰させない

## 11. 後続工程

1. Shadowログから証拠生成率・confirmed率・rejected率を集計する
2. candidate group mismatch率を確認する
3. Situation Evaluatorの実選択とShadow推奨の差分を評価する
4. Authority／Capability／Constraint／Safetyの同等性を別契約で評価する
5. 誤選択率が許容範囲であることを確認する
6. 機能フラグ付きの限定適用を別Versionで設計する

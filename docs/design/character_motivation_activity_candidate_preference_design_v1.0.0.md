# MotivationによるActivity候補選好 実装設計

Version: 1.0.0

## 1. 位置づけ

本書は、`character_motivation_morality_design_report.md` の段階導入方針と、
`character_motivation_appraisal_observation_design_v1.0.1.md` で定義した
Motivation Appraisalを基に、Activity候補評価へMotivationを初めて利用する範囲を定義する。

先行段階ではMotivationを通常・自律Behavior Planningへ読み取り専用で渡したが、
Activity選択結果には影響させなかった。

本段階では、Situation EvaluatorのLLMへ渡す既存Activity候補について、
Motivationが示す推奨順を補助的な選好情報として付与する。

## 2. 目的

- MotivationをActivity候補評価へ限定的に利用する
- 明示的なユーザー意図や決定論Matcherを上書きしない
- 進行中Activityの継続性をMotivationより優先する
- 登録されていないActivityをMotivationから生成しない
- Capability、Authority、Constraint、Safety検証を迂回しない
- 候補順と選好理由を診断可能にする
- Moral Profile未実装の状態で善悪による抑制を追加しない

## 3. 適用範囲

Motivation候補選好を適用するのは、Situation EvaluatorがLLMへ渡す
`available_activities`の順序と補助情報だけである。

次には適用しない。

- 決定論Matcherの解決
- 明示的なユーザー要求の意味判定
- 管理者Authority判定
- ongoing Activity遷移
- Capability可用性判定
- Activity Constraint検証
- Activity実行
- Safety判定
- Character Response本文

## 4. 判断優先順位

Activity判断では次の優先順位を維持する。

```text
1. ユーザーの明示意図とAuthority
2. 進行中Activityの継続・停止・切替条件
3. 決定論Matcher
4. 入力との意味的一致
5. Motivationによる候補選好
6. 元の登録順
```

Motivationは、意味的に妥当な候補が複数存在する場合の補助的な優先情報である。

## 5. 入力

`MotivationActivityCandidateRanker`は次を受け取る。

- 既存の`ActivityDefinition`列
- `MotivationAppraisal.as_context()`の結果
- 固定対象Activity種別

固定対象には次を使用する。

- `active_activity_definition.activity_type`
- `ongoing_activity_type`

Motivationから参照する項目は次だけである。

```text
recommended_activity_types
```

未知のキーや不正な値は無視する。

## 6. 候補並べ替え

候補を次のグループ順で並べる。

1. 固定対象Activity
2. Motivation推奨Activity
3. その他のActivity

各グループ内では次の順序を使用する。

- 固定対象: 固定対象として渡された順
- Motivation推奨: `recommended_activity_types`の順
- その他: 元の登録順

同順位は元の登録順で安定化する。

## 7. 候補を追加・削除しない保証

Rankerは入力された`ActivityDefinition`だけを並べ替える。

Motivationに次が含まれていても候補へ追加しない。

```text
recommended_activity_types = ["unknown_activity"]
```

また、Motivationに含まれない既存候補も削除しない。

このため、候補集合は処理前後で一致する。

未知候補は推奨順位の計算からも除外する。

## 8. 選好診断情報

各候補について次を出力する。

| 項目 | 説明 |
|---|---|
| `activity_type` | Activity識別子 |
| `position` | 並べ替え後の位置 |
| `original_position` | 元の登録位置 |
| `recommendation_rank` | 既知候補だけで正規化したMotivation推奨順位。対象外はnull |
| `motivation_score` | 推奨順位から導出した診断値 |
| `pinned` | 進行中Activity等として固定されたか |
| `reason` | 選好理由 |

`motivation_score`は成功確率や実行許可を表さない。

暫定計算:

```text
固定対象Activity: 1.0
Motivation推奨Activity: 1.0 / recommendation_rank
その他: 0.0
```

`reason`は次のいずれかとする。

- `ongoing_activity_preserved`
- `motivation_recommendation`
- `original_order`

## 9. Prompt投影

`SituationEvaluatorPromptBuilder`は、Rankerの結果を次へ反映する。

```text
planning_input.motivation
planning_input.activity_candidate_preferences
planning_input.available_activities[].motivation_preference
```

`available_activities`自体も選好順で出力する。

Promptには次の制約を明示する。

- ユーザーの明示意図、進行中Activity、意味的一致をMotivationより優先する
- Motivationは意味的に妥当な複数候補間の補助情報としてだけ使う
- 候補外Activityを生成しない
- Authority、Capability、Constraintの結果を推測しない

## 10. Runtimeフロー

```text
BehaviorPlanningContext
  ├─ activity_definitions
  ├─ active_activity_definition
  ├─ ongoing_activity_type
  └─ motivation
        ↓
MotivationActivityCandidateRanker
        ↓
MotivationActivityCandidateRanking
  ├─ ordered definitions
  └─ candidate preferences
        ↓
SituationEvaluatorPromptBuilder
        ↓
Situation Evaluator LLM
        ↓
SituationAnalysis
        ↓
BehaviorPlanner
        ↓
既存Capability・Constraint・Authority検証
```

決定論MatcherはPrompt構築より前に実行されるため、Motivation候補選好の影響を受けない。

## 11. Moral評価との境界

Moral Profile／Moral Stateは未実装である。

本段階では次を変更しない。

```text
moral_evaluation_available = false
suppressed_activity_types = []
suppression_reasons = ["moral_profile_not_available"]
```

Motivation候補選好はActivityを禁止しない。
善悪や安全性による抑制は後続の独立した設計で扱う。

## 12. 非対象

- MotivationだけによるActivity自動決定
- Motivationによる決定論Matcherの上書き
- 明示的ユーザー要求の変更
- Capability未提供Activityの実行許可
- Authorityの昇格
- Constraint検証の省略
- Moral Profile／Moral State
- Moral評価による候補抑制
- Response Content Plan
- Character LLMへの会話戦略投影
- Desire／MotivationのDB永続化
- GUI表示
- Curiosity飽和問題

## 13. テスト方針

- Motivation推奨候補が推奨順へ並ぶ
- 未知の推奨Activityが候補へ追加されない
- 未知候補が推奨順位を消費しない
- Motivation非推奨の既存候補が削除されない
- 進行中ActivityがMotivation推奨候補より先になる
- 同順位で元の登録順が維持される
- PromptへMotivationと候補選好診断が投影される
- `available_activities`と候補選好診断の順序が一致する
- 決定論Matcher成立時にLLMが呼ばれない
- Motivationが決定論Matcher結果を上書きしない
- 既存のCapability、Authority、Constraint、Subsystem境界テストが成功する

## 14. 後続工程

1. 実際のSituation評価ログから候補選好の有効性を観測する
2. Motivation選好が誤選択を増やさないことを確認する
3. 必要に応じて推奨順位と診断スコアを調整する
4. Moral Profile／Moral Stateを追加する
5. Moral評価を許可済み候補内の選好・抑制へ利用する
6. Response Content Planへ推奨会話戦略を投影する

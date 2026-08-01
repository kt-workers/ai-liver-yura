# キャラクターMoral候補限定適用設計 v1.0.0

## 1. 目的

第12工程で統合した`MoralActivityCandidateApplicationCondition`を、既存のActivity選択・実行境界を壊さずに限定的な実候補選択へ接続する。

本工程の目的は、Moral fitが高い候補を無条件に選ぶことではない。次の全条件が同一候補群について確認済みの場合だけ、Situation Evaluatorが選んだ候補を同等候補群内のMoral推奨候補へ差し替えることである。

- Moral静的適格性
- intent／operation／goalの意味的同等性
- Authority要件同等性
- Capability要件同等性
- Constraint schema同等性
- Safety要件同等性
- 明示的な機能フラグ
- 候補群全体のActivity Allowlist登録

## 2. 適用位置

限定適用は、Situation EvaluatorのLLM応答を型検証し、意味的同等性証拠とExecution Boundaryを評価した後、Behavior Plannerへ`SituationAnalysis`を渡す前に一度だけ実行する。

```text
Situation Evaluator LLM
  -> SituationAnalysis parse
  -> confidence validation
  -> Semantic Equivalence Shadow
  -> Execution Boundary Equivalence Shadow
  -> Application Condition
  -> Limited Activation Gate
  -> Behavior Planner
  -> Activity Plan Validator
  -> Plugin／Runtime execution
```

LLMを再呼び出さない。Moral適用後の候補を再びSituation Evaluatorへ入力しないため、同一ターン内の循環選択は発生しない。

## 3. 実際に変更する値

適用条件を満たした場合、`SituationAnalysis.activity_candidate`だけを次の値へ差し替える。

```python
replace(
    analysis,
    activity_candidate=preferred_activity_type,
)
```

次は保持する。

- operation
- goal
- constraints
- speech_act
- confidence
- evaluator_type
- 意味的同等性証拠
- ユーザー入力

候補集合自体やPromptへ渡した`available_activities`の順序は書き換えない。

## 4. 機能フラグ

既定値は無効とする。

```text
YURA_MORAL_CANDIDATE_LIMITED_ACTIVATION_ENABLED=0
```

有効値は次のいずれかに限定する。

```text
1, true, yes, on
```

無効値は次のいずれかに限定する。

```text
0, false, no, off, 空文字
```

それ以外は設定誤りとして起動時に`ValueError`とする。曖昧な値を暗黙に有効化しない。

## 5. Activity Allowlist

候補群全体がAllowlistに含まれる場合だけ適用する。

```text
YURA_MORAL_CANDIDATE_LIMITED_ACTIVATION_ALLOWLIST=
  autonomous_talk,conversation_with_user
```

推奨候補だけをAllowlistへ登録しても適用しない。元候補と推奨候補を含む比較候補群全体の明示登録を要求する。

理由は、未承認Activityから承認Activityへの一方向差し替えだけを許すと、比較元のActivityが持つ意味・運用上の責務を見落とす可能性があるためである。

## 6. Gate条件

次の条件をすべて満たす場合だけ差し替える。

1. 機能フラグが有効
2. Shadow診断結果が存在
3. `application_condition.status == ready`
4. Event種別が`user_text`
5. Situation Evaluator結果が`evaluator_type == llm`
6. operationが`start`
7. active／ongoing Activityが存在しない
8. LLM選択候補が統合条件の候補群内
9. Moral推奨候補が統合条件の候補群内
10. 候補群全体がAllowlist内
11. 候補群全ActivityDefinitionが現在Contextに存在
12. 推奨候補が現在operationをサポート

いずれか一つでも満たさない場合は元の`SituationAnalysis`を返す。

## 7. 対象外

第13工程では次へ適用しない。

- 決定論Matcher結果
- 管理者Direction経路
- autonomous／curiosity peak
- CONTINUE／STOP／PAUSE／RESUME
- active／ongoing／pinned Activity
- 候補群の一部だけがAllowlistにある場合
- semantic／execution boundaryがunconfirmedまたはrejectedの場合
- LLMが候補群外を選択した場合

## 8. Validatorとの関係

限定適用は実行許可ではない。

```text
Moral limited candidate selection
    != Authority permission
    != Capability availability
    != Constraint validity
    != Safety approval
    != Plugin execution success
```

差し替え後の候補は、従来どおりBehavior PlannerとActivity Plan Validatorを通過する。

- Constraintは差し替え先Definitionで再検証する
- Capabilityは実行前に再検証する
- Plugin実行時の状態変化を再確認する
- Authority／Safetyの既存境界を迂回しない

Execution Boundary Equivalenceは候補間の要件同等性であり、現在の要求が許可済み・安全と判定されたことを意味しない。

## 9. Shadowとの分離

`MoralActivityCandidatePreferenceShadow`は診断結果として維持する。

- `current_order`: 従来の候補順
- `hypothetical_order`: Moral fitによる仮想順
- `application_condition`: 限定適用前提

実際の適用可否は`MoralActivityCandidateLimitedActivationApplier`が機能フラグ、Allowlist、Event、operation、現在Activity状態を含めて最終判定する。

第12工程までの`activation_permitted=false`はShadow単体が実適用を行わないことを表す。第13工程の実適用結果は別の`MoralActivityCandidateLimitedActivationDecision`として記録する。

## 10. Trace

次のイベントを記録する。

```text
moral_candidate_limited_activation:evaluated
```

主な項目:

- applied
- reason
- original_activity_type
- selected_activity_type
- candidate_group
- policy_enabled
- allowlisted_activity_types
- application_condition_status
- application_condition_ready
- evaluator_type
- operation
- source_event_id

ユーザー本文、Prompt本文、Secretは記録しない。

## 11. 即時無効化

問題発生時は次の設定だけで従来選択へ戻せる。

```text
YURA_MORAL_CANDIDATE_LIMITED_ACTIVATION_ENABLED=0
```

コード削除、DB migration、候補Definition変更は不要である。

Allowlistを空にした場合も適用されない。

## 12. テスト要件

- 機能フラグ既定値は無効
- 明示的なtrue／false値だけを受理
- Allowlistの空白除去と重複排除
- 曖昧な機能フラグ値を拒否
- 無効時は元候補を維持
- readyかつ候補群全体Allowlist時のみ差し替え
- 部分Allowlistでは差し替えない
- 非STARTでは差し替えない
- Matcher結果では差し替えない
- user_text以外では差し替えない
- Behavior Plannerが差し替え後候補を使用
- 既存Architecture／Runtime／Plugin／Subsystem境界が回帰しない

## 13. 第14工程への受け渡し

第14工程ではActivity選択とは別に、Desire／Motivation／Moralから推奨会話戦略と価値判断をResponse Content Planへ投影する。

第13工程の候補差し替え結果をCharacter Responseへ直接文章化してはならない。応答内容への反映は専用の型付きContent Planを介して実施する。

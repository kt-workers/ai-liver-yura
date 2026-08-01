# Motivation Appraisal 観測・読み取り専用統合設計

Version: 1.0.1

Supersedes: `character_motivation_appraisal_observation_design_v1.0.0.md`

## 1. 位置づけ

本書は、`character_motivation_morality_design_report.md` の第3段階
「Motivation Appraisal」を、通常・自律Behavior Planningへ観測可能な形で
統合する現在仕様を定義する。

Version 1.0.0では通常Behavior Planningのみを実装対象とし、
自律Behavior Planningを後続工程としていた。

Version 1.0.1では、実装済みの自律経路を正式仕様へ反映する。

MotivationによるActivity候補選好は、本書の読み取り専用統合完了後の別段階であり、
次の設計書で定義する。

- `character_motivation_activity_candidate_preference_design_v1.0.0.md`

## 2. 入力

Motivation Appraisalは次を入力とする。

- Desire State
- Relationship State
- Activity結果によるsatisfaction／frustration

Motivationは派生値であり、AgentStateへ重複保存しない。

## 3. 出力

`MotivationAppraisal`は次を保持する。

- `ranked_desires`
- `conflicts`
- `expression_strength`
- `recommended_activity_types`
- `recommended_conversation_strategies`
- `moral_evaluation_available`
- `suppressed_activity_types`
- `suppression_reasons`

`primary_desire`は、`ranked_desires`の最上位項目から導出する。

## 4. 上位欲望

- `effective_level`の降順で並べる
- 同値の場合は`DesireType`定義順で安定化する
- 上位3件を出力する
- `expressed_level`は`effective_level * expression_strength`とする

## 5. Relationshipによる表出強度

Relationshipが存在しない場合:

```text
expression_strength = 0.50
```

Relationshipが存在する場合:

```text
normalized_affinity = (affinity + 1.0) / 2.0

expression_strength = clamp(
    0.35
    + familiarity * 0.20
    + trust * 0.25
    + normalized_affinity * 0.20,
    0.0,
    1.0,
)
```

表出強度は欲望自体を変更せず、外へ示しやすい度合いだけを表す。

## 6. 欲望競合

次の組を観測対象とする。

| 欲望A | 欲望B | reason |
|---|---|---|
| connection | security | `connection_security_tension` |
| expression | security | `expression_security_tension` |
| curiosity | security | `curiosity_security_tension` |
| autonomy | recognition | `autonomy_recognition_tension` |

両方の実効値が`0.55`以上の場合に評価する。

```text
closeness = 1.0 - abs(left_level - right_level)
intensity = min(left_level, right_level) * closeness
```

`intensity >= 0.30`の場合に競合として出力する。

競合情報は、それだけでActivityを禁止しない。

## 7. 推奨Activity候補

上位欲望の順に候補を追加し、重複を除外して最大5件とする。

| 欲望 | 候補 |
|---|---|
| connection | conversation_with_user、stream_comment_response、listening_mode |
| curiosity | topic_exploration、curiosity_research、external_trend_watch、idle_observation |
| expression | autonomous_talk、directed_talk、body_expression_loop |
| recognition | stream_main_segment、stream_comment_response |
| autonomy | autonomous_talk、plugin_activity |
| security | listening_mode、idle_observation |
| achievement | topic_exploration、plugin_activity、stream_main_segment |

候補はCapabilityの可用性や実行許可を意味しない。

## 8. 推奨会話戦略

上位欲望の順に戦略を追加し、重複を除外して最大5件とする。

| 欲望 | 戦略 |
|---|---|
| connection | continue_conversation、acknowledge_other、ask_follow_up |
| curiosity | ask_for_detail、explore_related_topic、observe_before_speaking |
| expression | share_reaction、self_disclose_briefly、state_preference |
| recognition | offer_help、explain_clearly、confirm_contribution |
| autonomy | propose_direction、take_initiative、state_choice |
| security | set_boundary、slow_down、seek_clarification |
| achievement | define_next_step、summarize_progress、complete_current_goal |

戦略は発話本文ではない。

## 9. Moral評価

Moral Profile／Moral Stateは未実装である。

Motivation Appraisalは必ず次を出力する。

```text
moral_evaluation_available = false
suppressed_activity_types = []
suppression_reasons = ["moral_profile_not_available"]
```

仮の善悪判定やキーワード抑制は追加しない。

## 10. 通常Behavior Planning統合

```text
AgentState.current_desire
RelationshipState
        ↓
MotivationAppraiser
        ↓
MotivationAppraisal.as_context()
        ↓
BehaviorPlanningContext.motivation
```

`BehaviorPlanningContextBuilder`は、同一のMotivationスナップショットを
次へ格納する。

- enriched `AgentEvent.payload["motivation"]`
- `BehaviorPlanningContext.motivation`

通常経路では、Event処理時点でpreviewしたRelationshipを使用する。

## 11. 自律Behavior Planning統合

```text
AgentState.current_desire
RelationshipMemory.current
        ↓
MotivationAppraiser
        ↓
AutonomousMotivationContextBuilder
        ↓
CURIOSITY_PEAK.payload["motivation"]
        ↓
AutonomousSituationContext.event_context
        ↓
自律Situation評価用BehaviorPlanningContext
```

自律経路では次へMotivationを伝播する。

- `CURIOSITY_PEAK.payload["motivation"]`
- `AutonomousSituationContext.event_context["motivation"]`
- 自律Situation評価用`BehaviorPlanningContext.situation["event"]["motivation"]`

通常・自律の両経路は同じ`MotivationAppraiser`を使用する。

## 12. 読み取り専用境界

本書で定義する統合自体は、次を変更しない。

- Driveによる自律発話開始可否
- Emotionによる発話抑制
- Situation Evaluatorの意味判定
- 決定論Matcher
- Capability検証
- Authority検証
- Activity Constraint検証
- ongoing Activity遷移
- Character Response本文
- Claim Validator／Response Validator

Activity候補順への限定的な利用は、
`character_motivation_activity_candidate_preference_design_v1.0.0.md`で
独立して定義する。

## 13. 永続化

Motivation AppraisalはDesireとRelationshipから再計算可能なため、
AgentStateやDBへ保存しない。

Motivation履歴の永続化は、観測上の必要性が確認されるまで行わない。

## 14. 非対象

- Moral Profile／Moral State
- Moral評価による候補抑制
- Motivationによる決定論Matcherの上書き
- Motivationによる自律発話開始条件変更
- Character LLMへの直接注入
- Response Content Plan
- GUI表示
- DB永続化
- 外部Subsystem操作
- Curiosity飽和問題

## 15. テスト方針

- 上位3欲望が実効値順で安定して算出される
- Relationshipなしの表出強度が0.50になる
- Relationshipが強いほど表出強度が上がる
- 定義済み欲望ペアだけが競合になる
- 推奨Activityと会話戦略が順位順かつ重複なしになる
- Moral評価が利用不可として明示される
- 通常BehaviorPlanningContextへMotivationが追加される
- enriched Eventと通常Contextが同じMotivationを持つ
- 自律EventへJSON互換のMotivationが追加される
- 自律Situation評価用ContextまでMotivationが伝播する
- 読み取り専用統合だけではActivity Planが変化しない
- Capability、Authority、Constraint、Subsystem境界が維持される

## 16. 後続工程

1. MotivationによるActivity候補選好を観測する
2. 実ログからDesire／Motivation係数を調整する
3. Moral Profile／Moral Stateを追加する
4. Moral評価を許可候補内の選好・抑制へ利用する
5. Response Content Planへ会話戦略を投影する

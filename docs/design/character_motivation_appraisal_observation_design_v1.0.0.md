# Motivation Appraisal 観測・読み取り専用統合設計

Version: 1.0.0

## 1. 位置づけ

本書は、`character_motivation_morality_design_report.md` の第3段階
「Motivation Appraisal」を、既存Behavior Planningを変更せずに導入するための
観測・読み取り専用設計を定義する。

先行実装で追加した次の状態を入力とする。

- Desire State
- Relationship State
- Activity結果によるsatisfaction／frustration

Moral Profile／Moral Stateはまだ存在しないため、価値判断による抑制は
「利用不可」として明示し、推測や仮の善悪判定を適用しない。

本実装単位では、まず外部Eventを起点とする通常Behavior Planningへ統合する。
自律Behavior Planningへの統合は、既存のActivityPlanningService境界を整理した
後続実装として分離する。

## 2. 目的

- 現在の上位欲望を順位付きで算出する
- 強い欲望同士の競合を決定論的に検出する
- Relationshipから表出強度を算出する
- 推奨Activity候補と推奨会話戦略を観測用に出力する
- 通常Behavior Plannerのコンテキストへ読み取り専用で追加する
- 現行のActivity選択、Capability、Authority、Safety判定を変更しない
- 後続のMoral Profile導入前にMotivation値の妥当性を検証できるようにする

## 3. Domain Model

### 3.1 RankedDesire

上位欲望の観測値を保持する。

- `desire_type`
- `rank`
- `effective_level`
- `expressed_level`

`expressed_level`は、実効欲望値へRelationship由来の表出強度を掛けた値である。
欲望そのものを弱める値ではなく、外へ出やすい度合いの観測値として扱う。

### 3.2 DesireConflict

競合する欲望の組を保持する。

- `left`
- `right`
- `intensity`
- `reason`

第1実装で検出する競合候補:

| 欲望A | 欲望B | 意味 |
|---|---|---|
| connection | security | 関わりたいが安全や距離も守りたい |
| expression | security | 表現したいが負担や不快を避けたい |
| curiosity | security | 探索したいが危険や過負荷を避けたい |
| autonomy | recognition | 自分で選びたいが他者評価も得たい |

競合ペアと閾値は観測用の暫定仕様である。

### 3.3 MotivationAppraisal

次を保持する。

- `ranked_desires`
- `conflicts`
- `expression_strength`
- `recommended_activity_types`
- `recommended_conversation_strategies`
- `moral_evaluation_available`
- `suppressed_activity_types`
- `suppression_reasons`

`primary_desire`は`ranked_desires`の先頭から取得する。

## 4. Relationshipによる表出強度

Relationshipがない場合:

```text
expression_strength = 0.50
```

Relationshipがある場合:

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

これは相手への信頼や親しさが高いほど、内的動機を表へ出しやすいという
観測用モデルである。Relationshipが低い場合でも完全に無表情にはしない。

## 5. 上位欲望

- `effective_level`の降順で並べる
- 同値の場合は`DesireType`の定義順で安定化する
- 上位3件を`ranked_desires`へ格納する
- すべての値は`0.0..1.0`へ正規化する

## 6. 競合検出

競合候補の両方が`0.55`以上の場合だけ評価する。

```text
closeness = 1.0 - abs(left_level - right_level)
intensity = min(left_level, right_level) * closeness
```

`intensity`が`0.30`以上の場合に競合として出力する。

競合はActivityを禁止しない。Behavior Plannerが将来参照できる診断情報であり、
現段階では選択結果へ影響させない。

## 7. 推奨Activity候補

上位欲望の順に、次の候補を追加する。重複は除外し、最大5件とする。

| 欲望 | 候補 |
|---|---|
| connection | conversation_with_user、stream_comment_response、listening_mode |
| curiosity | topic_exploration、curiosity_research、external_trend_watch、idle_observation |
| expression | autonomous_talk、directed_talk、body_expression_loop |
| recognition | stream_main_segment、stream_comment_response |
| autonomy | autonomous_talk、plugin_activity |
| security | listening_mode、idle_observation |
| achievement | topic_exploration、plugin_activity、stream_main_segment |

候補は利用可能Capabilityを意味しない。Capability検証やActivity定義解決は
既存のBehavior Planning／Activity検証境界が引き続き担当する。

## 8. 推奨会話戦略

上位欲望の順に、次の戦略を追加する。重複は除外し、最大5件とする。

| 欲望 | 戦略 |
|---|---|
| connection | `continue_conversation`、`acknowledge_other`、`ask_follow_up` |
| curiosity | `ask_for_detail`、`explore_related_topic`、`observe_before_speaking` |
| expression | `share_reaction`、`self_disclose_briefly`、`state_preference` |
| recognition | `offer_help`、`explain_clearly`、`confirm_contribution` |
| autonomy | `propose_direction`、`take_initiative`、`state_choice` |
| security | `set_boundary`、`slow_down`、`seek_clarification` |
| achievement | `define_next_step`、`summarize_progress`、`complete_current_goal` |

戦略は発話本文ではなく、後続のResponse Content Planが利用できる抽象的な候補である。

## 9. Moral評価の扱い

本段階ではMoral Profile／Moral Stateを実装しない。

MotivationAppraisalは必ず次を出力する。

```text
moral_evaluation_available = false
suppressed_activity_types = []
suppression_reasons = ["moral_profile_not_available"]
```

善悪傾向が存在するように見せる仮ルールは追加しない。
Safety／Authority／Capabilityによる既存制約はMoral評価とは独立して維持する。

## 10. Runtime統合

### 10.1 通常Behavior Planning

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

`BehaviorPlanningContextBuilder`は同じ内容をenriched Event payloadにも追加する。

### 10.2 自律Behavior Planning

自律Behavior Planningも将来的には同じ`MotivationAppraiser`を利用する。
ただし本実装単位では、既存の`ActivityPlanningService`が自律計画Contextを
独立して構築しているため、未接続のDTOフィールドだけを先行追加しない。

後続実装では次の経路を追加する。

```text
AgentState.current_desire
RelationshipMemory.current
        ↓
MotivationAppraiser
        ↓
AutonomousSituationContext
        ↓
BehaviorPlanningContext.motivation
```

通常経路と同一Appraiserを使用し、係数や意味規則を複製しないことを必須とする。

## 11. 読み取り専用境界

本段階の通常Behavior PlannerはMotivationをコンテキストとして受け取るが、
次の既存判断を変更しない。

- Driveによる自律発話開始可否
- Emotionによる発話抑制
- Situation EvaluatorのActivity候補
- Capability検証
- Authority検証
- Activity Constraint検証
- ongoing Activity遷移
- Claim Validator／Response Validator

Motivationはdebug traceと将来の評価に利用できる読み取り専用入力とする。

## 12. 永続化

MotivationAppraisalはDesireとRelationshipから再計算可能な派生値であるため、
AgentStateやDBへ重複保存しない。

永続化対象は引き続き元のDesire／Relationship側とし、必要性が確認されるまで
Motivation履歴のDB保存は行わない。

## 13. 非対象

- Moral Profile／Moral State
- 善悪による候補抑制
- MotivationによるActivity選択変更
- Motivationによる自律発話開始条件変更
- 自律Behavior PlanningへのMotivation接続
- Character LLMへの直接注入
- Response Content Plan
- GUI表示
- DB永続化
- 外部Subsystem操作
- Curiosity飽和問題

## 14. テスト方針

- 上位3欲望が実効値順で安定して算出される
- Relationshipなしの表出強度が0.50になる
- familiarity／trust／affinityが高いほど表出強度が上がる
- 定義した欲望ペアだけが閾値以上で競合になる
- 推奨Activityと会話戦略が順位順かつ重複なしで出力される
- Moral評価が利用不可として明示される
- 通常BehaviorPlanningContextへmotivationが追加される
- enriched EventとBehaviorPlanningContextが同じMotivationスナップショットを持つ
- Motivation追加前後で同じSituation Analysisから同じActivity Planが得られる
- 自律計画DTOへ未接続フィールドを追加しない

## 15. 後続段階

1. 自律Behavior Planningへ同じMotivation Appraisalを読み取り専用で接続
2. Motivation観測ログから閾値・競合ペア・候補対応を調整
3. Behavior PlannerがMotivationを候補評価へ使用する設計を追加
4. Moral Profile／Moral Stateを追加
5. Moral評価による許可候補内の選好・抑制を追加
6. Response Content Planへ会話戦略を投影

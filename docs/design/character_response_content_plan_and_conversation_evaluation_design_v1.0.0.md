# Character Response Content Planと連続会話評価 設計

- Document Version: 1.0.0
- Status: Implemented
- Target: Core Character Response Pipeline
- Related PR: #118

## 1. 目的

Desire、Motivation Appraisal、Moral Profile／Moral Stateを、Activityの選択や実行許可ではなく、選択済みActivityに対する発話内容の焦点・態度・展開量へ投影する。

本設計では、内部状態をそのままLLMへ自由解釈させず、有限かつ型付きの`ResponseContentPlan`へ変換する。これにより、次を両立する。

- ゆらの欲望や価値判断が会話表現へ継続的に現れる
- 内部数値やMoral項目名を発話で説明しない
- ユーザーを採点、断罪、説教しない
- 事実、権限、安全、Activity実行結果を上書きしない
- 毎ターン質問する、話題を無制限に広げる、過剰に自己開示する挙動を抑える
- 同一内部状態では複数ターンにわたり安定した表現方針を維持する

## 2. 責務境界

### 2.1 Response Content Planが決めるもの

- 会話戦略の候補
- 発話で自然に強調する価値傾向
- 対人姿勢
- 内面をどの程度表へ出すか
- 短い自己開示を許すか
- 1応答内の質問数上限
- 1応答内の新規話題方向数上限
- Desire競合時の表現上の調停方法

### 2.2 Response Content Planが決めないもの

- Activity候補集合
- Activity候補順位
- Activity選択
- operation
- constraints
- Authority判定
- Capability判定
- Safety判定
- Plugin実行可否
- Activity実行結果
- allowed claims／forbidden claims
- ユーザー発言や外部事実の真偽
- Moralによる禁止・抑制

次の関係を維持する。

```text
Response Content Plan
    != Behavior Plan
    != Activity Plan
    != Execution Permission
    != Safety Approval
    != Fact Source
```

## 3. 型付き契約

```python
@dataclass(frozen=True, slots=True)
class ResponseContentPlan:
    primary_desire: str | None
    conversation_strategies: tuple[str, ...]
    value_emphases: tuple[str, ...]
    interpersonal_stance: str
    expression_mode: str
    self_disclosure_level: str
    conflict_mode: str | None
    question_budget: int
    new_direction_budget: int
    observation_only: bool
    reasons: tuple[str, ...]
```

### 3.1 conversation_strategies

最大3件とする。現在の許可値は次の有限集合である。

- `continue_conversation`
- `acknowledge_other`
- `ask_follow_up`
- `ask_for_detail`
- `explore_related_topic`
- `observe_before_speaking`
- `share_reaction`
- `self_disclose_briefly`
- `state_preference`
- `offer_help`
- `explain_clearly`
- `confirm_contribution`
- `propose_direction`
- `take_initiative`
- `state_choice`
- `set_boundary`
- `state_boundary_calmly`
- `slow_down`
- `seek_clarification`
- `define_next_step`
- `summarize_progress`
- `complete_current_goal`

未知値は境界復元時に破棄する。自由文字列をCharacter Promptへ通さない。

### 3.2 value_emphases

最大3件とする。

- `compassion`
- `honesty`
- `fairness`
- `restraint`
- `respect`
- `autonomy`
- `achievement`

これらは発話内で項目名を列挙するための語ではない。応答の選語、配慮、説明の仕方、境界表明の落ち着きとして反映する。

### 3.3 interpersonal_stance

- `supportive`
- `balanced`
- `guarded`

`guarded`は敵対や攻撃を意味しない。距離、慎重さ、境界を落ち着いて示す表現上の姿勢である。

### 3.4 expression_mode

- `restrained`
- `balanced`
- `open`

Motivation Appraisalの`expression_strength`をカテゴリ化する。内部数値そのものはCharacter LLMへ指示として露出させない。

### 3.5 self_disclosure_level

- `none`
- `brief`

`brief`でも、Character Profile、記憶、確定済み状況に根拠のない体験や経歴を創作しない。

### 3.6 展開量の上限

```text
question_budget ∈ {0, 1}
new_direction_budget ∈ {0, 1}
```

上限は使用義務ではない。質問や話題展開が不自然な場合は0件でよい。

## 4. 導出規則

`ResponseContentPlanner`は、Motivation ContextとMoral Contextを決定論的に読み、Planを生成する。

### 4.1 Motivationからの導出

- `primary_desire`をPlanへ保持
- `recommended_conversation_strategies`から既知値のみ最大3件採用
- `expression_strength`を`restrained／balanced／open`へ分類
- Desire Conflictの最初の確定理由を`conflict_mode`へ保持
- 質問系戦略がある場合のみ`question_budget=1`
- 新方向系戦略がある場合のみ`new_direction_budget=1`

### 4.2 Moralからの導出

Moral Profile、Moral State、Moral Compositeから、しきい値を満たす価値強調を最大3件選ぶ。

- compassion／empathy／prosocial activation → `compassion`
- honesty → `honesty`
- fairness → `fairness`
- restraint／effective restraint → `restraint`
- rule respect → `respect`
- primary desireがautonomy → `autonomy`
- primary desireがachievement → `achievement`

Moral値は会話内容の禁止判定には使用しない。

### 4.3 競合と衝動の調停

次の競合では`slow_down`を優先戦略へ入れる。

- connectionとsecurity
- expressionとsecurity
- curiosityとsecurity

`aggressive_impulse`が高く、かつ`restraint`も維持されている場合は、攻撃ではなく`state_boundary_calmly`を採用する。

```text
aggressive impulse
    + sufficient restraint
    -> calm boundary expression
    != attack
    != insult
    != safety prohibition
```

## 5. データフロー

### 5.1 通常会話

```text
Agent State
  -> Motivation Appraisal
  -> Moral Context
  -> ResponseContentPlanner
  -> typed ResponseContentPlan
  -> enriched AgentEvent.memory.response_content_plan
  -> Activity event_payload
  -> ResponseContext.memory
  -> Character Prompt
```

Behavior Plannerへ渡す`BehaviorPlanningContext.memory`にはResponse Content Planを混在させない。これにより、発話内容用PlanがActivity選択へ逆流しない。

### 5.2 自律発話

```text
Agent State
  -> Autonomous Motivation Context
  -> ResponseContentPlanner
  -> CURIOSITY_PEAK event memory snapshot
  -> Autonomous Activity
  -> ResponseContext
  -> Character Prompt
```

通常会話と自律発話は同じ型付きPlannerを使用する。

## 6. Character Promptの優先順位

Character Promptでは次の順序を固定する。

1. 確定済みResponse Context
2. allowed claims／forbidden claims
3. Authority／Safety／実行事実
4. speech act／conversation phase／initiative level
5. Character Profile
6. Response Content Plan

Response Content Planは常に下位の表現方針であり、上位契約と衝突する場合は無視する。

### 6.1 Prompt上の禁止事項

- 内部欲望名を説明しない
- Moral項目や数値を開示しない
- Planのreasonsを発話しない
- value emphasisをユーザーへの評価や説教に変換しない
- guardedを敵意へ変換しない
- self disclosureで架空経歴を作らない
- question budgetを使い切るためだけに質問しない
- new direction budgetを使い切るためだけに話題を広げない

## 7. 連続会話評価

### 7.1 安定性

同じAgent Stateから生成された複数のUSER_TEXT Eventでは、入力本文だけが変わってもResponse Content Planは一致する。

これにより、発話ごとにキャラクター方針が無関係に揺れることを防ぐ。

### 7.2 適応性

Agent State、Desire順位、Relationship、Moral Stateが変化した場合は、次ターンのPlanだけが新しい状態へ適応する。過去ターンのPlanを将来ターンへ固定しない。

### 7.3 過剰反映の防止

- strategy最大3件
- value emphasis最大3件
- question最大1件
- new direction最大1件
- self disclosureはnoneまたはbrief
- 内部値はカテゴリ化
- 未知値は破棄

### 7.4 事実整合性

Response Claim ValidatorとDeterministic Fact Validatorは従来どおり後段で動作する。Planを反映した発話でも、実行事実と矛盾する主張は拒否する。

## 8. Traceとプライバシー

現段階では既存Response Context Traceを使用する。次をログへ追加しない。

- ユーザー本文の新規複製
- Prompt本文の新規複製
- Secret
- 生のMoral内部数値を新規専用イベントへ複製

必要な診断は、型付きPlanの有限値と既存LLM Traceで行う。

## 9. テスト方針

以下を自動検証する。

- Planの型付きround trip
- strategy／value／budgetの上限
- connectionとprosocial状態からsupportive planを導出
- security競合でslow downを追加
- aggressive impulseとrestraintからcalm boundaryを追加
- 攻撃戦略を生成しない
- 通常会話EventへPlanを格納
- Behavior Planning ContextへPlanを逆流させない
- 同一内部状態の複数ターンでPlanが一致
- Character PromptでPlanよりfacts／claimsが優先
- 自律発話EventへPlanを格納
- Architecture、Runtime、Plugin、Subsystem境界の全体回帰

## 10. 非対象

- Moralによるユーザー評価スコア
- MoralによるActivity禁止
- Safety policyの置換
- Authority許可判定
- Character Response本文の決定論生成
- DB永続化
- Moral ProfileのYAML設定
- GUI表示
- 「こころの潮流」の描画
- LLM出力品質の人手評価自動化

## 11. ロールバック

本工程はActivity選択や外部実行を変更しない。問題発生時は次の順で戻せる。

1. Character PromptのResponse Content Plan指示を外す
2. Event memoryへのPlan格納を外す
3. `ResponseContentPlanner`の生成を外す

第13工程のMoral候補限定適用機能フラグとは独立している。

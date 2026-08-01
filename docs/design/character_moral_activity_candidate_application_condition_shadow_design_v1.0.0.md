# Moral Activity候補 統合適用条件 Shadow設計

- Document Version: v1.0.0
- 対象工程: キャラクター動機・Moral導入 第12工程
- 状態: Shadow観測のみ

## 1. 目的

Moralによる仮想候補順位を将来限定的に適用するために必要な前提を、個別の真偽値や暗黙条件ではなく、一つの型付き診断結果へ統合する。

本工程では適用条件の評価までを行い、実候補順、Activity選択、Activity実行には反映しない。

```text
Moral static eligibility
+ Semantic equivalence
+ Authority equivalence
+ Capability equivalence
+ Constraint equivalence
+ Safety equivalence
        ↓
Typed application condition
        ↓
Shadow observation only
```

## 2. 背景

第11工程までに次の診断情報が独立して存在する。

- Moral静的適格性
- intent／operation／goalの意味的同等性
- Authority要件同等性
- Capability要件同等性
- Constraint schema同等性
- Safety要件同等性

個別結果だけでは、将来の限定適用時にどの条件を満たせばよいかが呼び出し側へ分散する。

第12工程では、これらを一つのDomain契約へ集約し、適用前提の判定責務を一か所へ固定する。

## 3. 非目的

本工程では次を行わない。

- Moralによる実候補順変更
- MoralによるActivity選択
- MoralによるActivity禁止・抑制
- Authority要件による実行許可・拒否
- Safety policyの実評価
- Capability再検証の代替
- Constraint validatorの代替
- 決定論Matcherの上書き
- ユーザー明示意図の上書き
- Feature flagの追加
- Character Response内容の変更
- Response Content Planの変更

## 4. 型付き契約

### 4.1 状態

```python
class MoralActivityCandidateApplicationConditionStatus(str, Enum):
    INELIGIBLE = "ineligible"
    UNCONFIRMED = "unconfirmed"
    REJECTED = "rejected"
    READY = "ready"
```

### 4.2 診断結果

```python
@dataclass(frozen=True, slots=True)
class MoralActivityCandidateApplicationCondition:
    candidate_group: tuple[str, ...]
    preferred_activity_type: str | None
    status: MoralActivityCandidateApplicationConditionStatus
    static_eligible: bool
    semantic_equivalence_status: SemanticEquivalenceStatus
    execution_boundary_equivalence_status: ExecutionBoundaryEquivalenceStatus
    reasons: tuple[str, ...]
```

`ready_for_limited_activation`は`status == READY`を表す派生値である。

この値は、現時点の実適用許可を意味しない。

```text
ready_for_limited_activation
    != activation_permitted
```

## 5. 状態判定

### 5.1 INELIGIBLE

次のいずれかに該当する場合。

- Moral静的適格性が成立しない
- 候補群が2件未満
- 候補群に重複がある
- 推奨候補が候補群に含まれない

Moral静的適格性には既存条件を使用する。

- Moral contextが存在する
- `observation_only=true`
- aggressive impulseが安定閾値未満
- selfish impulseが安定閾値未満
- 同じMotivation score階層に比較可能な候補が2件以上ある
- pinned／active／ongoing候補を比較対象に含めない
- top moral fitが閾値以上
- fit marginが閾値以上

### 5.2 UNCONFIRMED

次のいずれかに該当する場合。

- 意味的同等性が`unconfirmed`
- 実行境界同等性が`unconfirmed`
- 意味的同等性の候補群が現在候補群と一致しない
- 実行境界同等性の候補群が現在候補群と一致しない

候補群不一致は、古い証拠や別候補群の診断結果を再利用しないための防御である。

### 5.3 REJECTED

次のいずれかが明示的に`rejected`の場合。

- 意味的同等性
- Execution Boundary全体

Execution Boundary全体は次の4境界から構成される。

- Authority
- Capability
- Constraint
- Safety

いずれかが`rejected`ならExecution Boundary全体も`rejected`となる。

### 5.4 READY

次をすべて満たす場合だけ`ready`とする。

- Moral静的適格性が成立
- 比較候補群が有効
- 推奨候補が候補群内に存在
- 意味的同等性が`confirmed`
- Execution Boundary全体が`confirmed`
- 意味的同等性とExecution Boundaryの候補群が現在候補群と完全一致

`ready`は第13工程で機能フラグ付き限定適用を検討できる状態を示す。

第12工程では次を維持する。

```text
application_condition.status = ready
activation_permitted = false
```

## 6. 評価タイミング

### 6.1 Situation解析前

Situation Evaluatorへ渡すPrompt構築時点では、意味的同等性証拠と実行境界診断が揃っていない。

このため統合適用条件は原則`unconfirmed`となる。

### 6.2 Situation解析後

`SituationSemanticEquivalenceShadowObserver`で次を順に行う。

1. Motivation順位を算出
2. Moral fitを算出
3. Moral仮想順位と静的適格性を算出
4. Situation解析由来の意味的同等性証拠を評価
5. Authority／Capability／Constraint／Safety同等性を評価
6. 全結果を統合適用条件へ入力
7. Traceへ記録

解析結果を同一ターンのSituation Evaluator、Behavior Planner、Activity Plan Validator、Plugin Commandへ戻さない。

## 7. データフロー

```text
Activity definitions
Motivation preferences
Moral context
Situation semantic evidence
Authority context
Available capabilities
        ↓
MoralActivityCandidatePreferenceShadowEvaluator
        ↓
Moral static eligibility
Semantic equivalence
Hypothetical order
        ↓
ActivityCandidateExecutionBoundaryEquivalenceEvaluator
        ↓
Authority / Capability / Constraint / Safety equivalence
        ↓
MoralActivityCandidateApplicationConditionEvaluator
        ↓
INELIGIBLE / UNCONFIRMED / REJECTED / READY
        ↓
Trace and Shadow context only
```

## 8. Shadow結果への追加

`MoralActivityCandidatePreferenceShadow`へ次を追加する。

```python
application_condition: MoralActivityCandidateApplicationCondition
```

Contextには次を公開する。

```json
{
  "application_condition_ready": false,
  "application_condition": {
    "candidate_group": [],
    "preferred_activity_type": null,
    "status": "unconfirmed",
    "ready_for_limited_activation": false,
    "static_eligible": false,
    "semantic_equivalence_status": "unconfirmed",
    "execution_boundary_equivalence_status": "unconfirmed",
    "reasons": []
  },
  "activation_permitted": false
}
```

## 9. Trace

Situation解析後のTraceへ次を追加する。

- `application_condition_status`
- `application_condition_ready`
- `application_condition`

これにより第13工程の前に、次を観測できる。

- 静的適格性成立率
- 意味的同等性確認率
- Execution Boundary確認率
- 統合条件ready率
- 候補群不一致率
- rejected率
- 仮想順位と現行選択の差分率

## 10. 安全境界

- `available_activities`を変更しない
- `current_order`を変更しない
- `hypothetical_order`は診断値としてのみ保持する
- pinned／active／ongoing候補を移動しない
- Motivation score階層を越えて比較しない
- 未契約候補を安全・許可済みとみなさない
- `ready`を実行許可に読み替えない
- `activation_permitted=false`を維持する
- Authority／Capability／Constraint／Safetyの既存実行時検証を維持する

## 11. テスト方針

### 単体

- 全条件confirmedで`ready`
- Moral静的条件不成立で`ineligible`
- 明示的同等性拒否で`rejected`
- 未確認境界で`unconfirmed`
- 意味候補群不一致で`unconfirmed`
- 実行境界候補群不一致で`unconfirmed`

### 統合

- Situation解析後に全条件が揃うと`ready`
- `ready_for_limited_activation=true`でも`activation_permitted=false`
- 実候補順が変わらない
- 仮想順位だけがMoral fit順になる
- Character ResponseとPlugin Commandへ影響しない

## 12. 第13工程への受け渡し

第13工程では、本契約を唯一の前提集約結果として利用し、さらに次を別条件として追加する。

- 明示的な機能フラグ
- 適用対象ActivityのAllowlist
- Shadow観測での誤選択率基準
- 実行前の既存Authority／Capability／Constraint／Safety再検証
- 障害時の即時無効化
- 実適用結果と従来順序の監査ログ

第13工程でも、MoralによるSafety禁止や既存Validatorの迂回は行わない。

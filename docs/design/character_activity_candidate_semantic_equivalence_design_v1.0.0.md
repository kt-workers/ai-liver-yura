# Activity Candidate Semantic Equivalence 設計

Version: 1.0.0

## 1. 目的

本書は、Moral候補選好Shadowが比較するActivity候補同士について、
「同じユーザー意図を満たす代替候補として扱ってよいか」を型付きで評価する契約を定義する。

本段階では意味的同等性を実際の候補順変更へ使用しない。
型付き証拠が存在しない場合は必ず`unconfirmed`とし、
Moralによる実選択、並べ替え、抑制、禁止を有効化しない。

## 2. 基本方針

意味的同等性は、同じMotivation段階に存在することだけでは成立しない。

次の3観点がすべて確認された場合だけ`confirmed`とする。

1. `intent`
   - 同じユーザー意図または同じ自律目的を満たすか
2. `operation`
   - 同じ開始・継続・停止・説明・議論の意味を持つか
3. `goal`
   - 達成しようとする結果が代替可能か

Authority、Capability、Constraint、Safetyの同等性は、この契約だけでは確認しない。
これらは後続の別契約として扱う。

## 3. 評価状態

### 3.1 観点別状態

```python
class SemanticEquivalenceDimension(str, Enum):
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
```

### 3.2 グループ全体状態

```python
class SemanticEquivalenceStatus(str, Enum):
    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
```

判定規則:

- 3観点のいずれかが`rejected`
  - 全体を`rejected`
- 3観点がすべて`confirmed`
  - 証拠の出所とIDが有効なら全体を`confirmed`
- それ以外
  - 全体を`unconfirmed`

## 4. 型付き証拠

```python
@dataclass(frozen=True, slots=True)
class ActivityCandidateSemanticEquivalenceEvidence:
    candidate_group: tuple[str, ...]
    intent: SemanticEquivalenceDimension
    operation: SemanticEquivalenceDimension
    goal: SemanticEquivalenceDimension
    source: str
    evidence_id: str | None
    reasons: tuple[str, ...]
```

### 4.1 candidate_group

Moral候補選好Shadowが選択した比較対象グループと完全一致しなければならない。
順序も含めて一致しない証拠は、古い候補集合に対する証拠として拒否する。

### 4.2 source

証拠を生成した評価境界を示す。
空文字は許可しない。

現段階の通常Prompt経路には証拠生成器を接続しないため、
実行時の既定値は`unavailable`である。

### 4.3 evidence_id

証拠の追跡IDである。
3観点がすべて`confirmed`でも、`evidence_id`がない場合は
`semantic_equivalence_provenance_missing`として`unconfirmed`に留める。

## 5. 評価結果

```python
@dataclass(frozen=True, slots=True)
class ActivityCandidateSemanticEquivalenceAssessment:
    candidate_group: tuple[str, ...]
    status: SemanticEquivalenceStatus
    intent: SemanticEquivalenceDimension
    operation: SemanticEquivalenceDimension
    goal: SemanticEquivalenceDimension
    source: str
    evidence_id: str | None
    reasons: tuple[str, ...]
```

`confirmed`プロパティは、`status == confirmed`の場合だけ`true`となる。

主な理由識別子:

- `semantic_equivalence_candidate_group_insufficient`
- `semantic_equivalence_evidence_unavailable`
- `semantic_equivalence_candidate_group_mismatch`
- `semantic_equivalence_provenance_missing`
- `semantic_equivalence_unconfirmed`
- `semantic_equivalence_confirmed`
- `semantic_equivalence_rejected`

## 6. Moral候補選好Shadowへの接続

`MoralActivityCandidatePreferenceShadowEvaluator`は、
同じMotivation段階から比較対象グループを選択した後、
`ActivityCandidateSemanticEquivalenceEvaluator`へ候補グループと型付き証拠を渡す。

Shadow結果へ次を追加する。

```text
semantic_equivalence
semantic_equivalence_confirmed
```

ただし、本Versionでは次の状態を維持する。

```text
activation_permitted = false
```

意味的同等性が`confirmed`でも、次が未確認だからである。

- Authorityの同等性
- Capabilityの同等性
- Constraint適用結果の同等性
- Safety判定の同等性
- 実ログ上の誤選択率
- 機能フラグによる限定有効化

## 7. Situation Evaluatorへの投影

Promptの`planning_input`へ次を追加する。

```text
activity_candidate_semantic_equivalence
```

同じ評価は`moral_candidate_preference_shadow.semantic_equivalence`にも含める。

Prompt規則では次を明示する。

```text
意味的同等性がconfirmedでもMoral候補選好の実適用許可を意味しない。
semantic_equivalence_confirmedをActivity選択へ使用しない。
```

通常Prompt経路は型付き証拠をまだ生成しないため、
現段階の実行時評価は`unconfirmed`となる。

## 8. 維持する境界

- ユーザーの明示意図を上書きしない
- active／ongoing Activityを移動しない
- 決定論Matcherを上書きしない
- Motivationの異なる段階を越えない
- 候補を追加・削除しない
- Authority、Capability、Constraint、Safetyを推測しない
- Moralによる実際の候補順変更を行わない
- MoralによるActivity抑制・禁止を行わない
- Character Response内容へ投影しない

## 9. 本段階で変更しない範囲

- Situation Evaluatorからの意味的同等性証拠生成
- 実際の候補並べ替え
- `activation_permitted`の有効化
- Authority／Capability／Constraint／Safety同等性契約
- Moral抑制
- Safety禁止
- Response Content Plan
- YAML設定
- DB永続化
- GUI表示

## 10. テスト方針

- 証拠がない場合に`unconfirmed`となること
- 3観点がすべて確認され、出所とIDがある場合だけ`confirmed`となること
- 1観点でも拒否された場合に`rejected`となること
- 出所またはIDが不足する場合に`unconfirmed`となること
- 候補グループが一致しない古い証拠を使用しないこと
- 意味的同等性が`confirmed`でも`activation_permitted`が`false`であること
- Promptへ評価を投影しても実際の候補順を変更しないこと

## 11. 後続工程

1. Situation Evaluatorまたは決定論的意味解析境界から型付き証拠を生成する
2. Authority／Capability／Constraint／Safetyの同等性契約を追加する
3. Shadowログで意味的同等性の成立率と実選択差分を観測する
4. 誤選択率が許容範囲であることを確認する
5. 機能フラグ付きで限定的な実適用を設計する
6. Moral抑制とSafety禁止を別契約として設計する

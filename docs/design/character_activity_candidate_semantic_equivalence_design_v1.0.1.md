# Activity Candidate Semantic Equivalence 設計

Version: 1.0.1

## 1. 変更概要

v1.0.0で定義した型付き意味的同等性契約へ、Situation Evaluator由来の証拠生成Shadow経路を接続する。

詳細な信頼境界と処理フローは次を参照する。

- `docs/design/character_situation_semantic_equivalence_evidence_shadow_design_v1.0.0.md`

本Versionでも、意味的同等性は実際の候補順変更へ使用しない。

## 2. 基本契約

意味的同等性は次の3観点で評価する。

1. `intent`
   - 同じユーザー意図または同じ自律目的を満たすか
2. `operation`
   - 同じ開始・継続・停止・説明・議論の意味を持つか
3. `goal`
   - 達成しようとする結果が代替可能か

各観点は`unknown`、`confirmed`、`rejected`のいずれかとする。

全体評価は次のとおり。

- 1観点でも`rejected`: 全体を`rejected`
- 3観点がすべて`confirmed`かつRuntime provenanceが有効: 全体を`confirmed`
- それ以外: 全体を`unconfirmed`

## 3. 型付き証拠

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

`candidate_group`はMoral候補選好Shadowが選択した比較対象グループと順序を含めて完全一致しなければならない。

## 4. Situation Evaluator証拠生成

Situation Evaluator Promptは、証拠未設定Shadowが提示したcandidate groupについて、次を出力する。

```text
semantic_equivalence.candidate_group
semantic_equivalence.intent
semantic_equivalence.operation
semantic_equivalence.goal
semantic_equivalence.reasons
```

LLM出力に含まれる`source`や`evidence_id`は信頼しない。

Runtimeが次を付与する。

```text
source = situation_evaluator_llm
evidence_id = <source_event_id>:semantic-equivalence:<attempt>
```

Runtimeは候補集合、重複、現在ActivityDefinitionへの所属、列挙値、理由配列を検証する。不正な場合は証拠を生成しない。

Situation Analysisの確信度が設定閾値未満の場合も、生成済み証拠をShadowへ渡す前に破棄する。

## 5. Shadowへの接続

`SituationSemanticEquivalenceShadowObserver`は、Situation Evaluator応答後に次を決定論的に再計算する。

- Motivation候補順位
- candidate moral fit
- Moral候補選好Shadow

`SituationAnalysis.semantic_equivalence_evidence`をShadow Evaluatorへ渡し、次を診断ログへ記録する。

- current order
- hypothetical order
- semantic equivalence status
- candidate group
- evidence ID
- static eligibility
- preferred activity type
- reasons

証拠付きShadowを同一ターンのSituation Evaluatorへ戻さない。

## 6. 実適用状態

本Versionでも次を維持する。

```text
activation_permitted = false
```

意味的同等性が`confirmed`でも、実際の候補順・Activity選択は変更しない。

理由は次のとおり。

- Authorityの同等性が未確認
- Capabilityの同等性が未確認
- Constraint適用結果の同等性が未確認
- Safety判定の同等性が未確認
- 実ログ上の誤選択率が未評価
- 機能フラグによる限定有効化が未実装

## 7. 維持する境界

- ユーザーの明示意図を上書きしない
- active／ongoing Activityを移動しない
- 決定論Matcherを上書きしない
- Motivationの異なる段階を越えない
- 候補を追加・削除しない
- Authority、Capability、Constraint、Safetyを意味的同等性から推測しない
- Moralによる実際の候補順変更を行わない
- MoralによるActivity抑制・禁止を行わない
- Character Response内容へ投影しない

## 8. 失敗時動作

次の場合は証拠を使用せず`unconfirmed`として扱う。

- semantic equivalence出力がない
- candidate groupが2件未満
- 候補が重複している
- 未知Activityが含まれる
- 評価次元が定義外
- Runtime provenanceがない
- 解析確信度が閾値未満
- candidate groupが現在のShadowグループと一致しない

Shadow観測失敗はActivity Planningを失敗させない。

## 9. テスト方針

- Runtime provenanceだけが採用されること
- LLM由来source／evidence IDを信用しないこと
- 未知候補・重複候補・不正列挙を破棄すること
- 高確信度証拠をShadowへ渡すこと
- 低確信度証拠をShadow前に破棄すること
- candidate group不一致を`unconfirmed`とすること
- `confirmed`でも`activation_permitted=false`であること
- current orderを変更しないこと
- 既存のMatcher、Authority、Capability、Constraint、Safety境界を回帰させないこと

## 10. 後続工程

1. 証拠生成率・confirmed率・rejected率をShadowログで観測する
2. candidate group mismatch率を確認する
3. Situation Evaluator実選択とShadow推奨の差分を収集する
4. Authority／Capability／Constraint／Safetyの同等性契約を追加する
5. 誤選択率が許容範囲であることを確認する
6. 機能フラグ付き限定適用を別Versionで設計する

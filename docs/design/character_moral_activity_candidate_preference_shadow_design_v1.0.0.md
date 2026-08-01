# Character Moral Activity Candidate Preference Shadow 設計

Version: 1.0.0

## 1. 目的

本書は、観測専用で追加したMoral Profile、Moral State、候補別`moral_fit`を、将来「意味的に妥当な候補が複数ある場合の補助選好」へ利用するための適用条件を定義する。

本段階では実際のActivity候補順、Activity選択、禁止、抑制を変更しない。現在順序とは別に仮想順序をシャドー計算し、適用条件の成立頻度と誤差を観測できる契約だけを追加する。

## 2. 基本方針

Moralは次の境界を越えない。

- ユーザーの明示意図を上書きしない
- active／ongoing Activityを移動しない
- 決定論Matcherの結果を上書きしない
- Motivationの異なる優先段階を越えない
- Authority、Capability、Constraint、Safetyを許可済みと推測しない
- 候補を追加・削除しない
- Moralによる抑制とSafetyによる禁止を同一結果にしない

Moral選好は、将来も「すでに意味的・権限的・機能的に同等と確認された候補間の最終的な補助判断」に限定する。

## 3. 二段階の適用判定

### 3.1 静的適格性

現在のMoral状態と候補診断情報だけで判定できる条件を`static_eligible`として表す。

静的適格性には次をすべて要求する。

1. Moral ProfileとMoral Stateが利用可能である
2. Moral文脈が観測専用として生成されている
3. Moral Stateが不安定域にない
4. pinned候補を除外している
5. 同じMotivation段階に候補が2件以上ある
6. 比較対象候補が型付きMoral Policyを持つ
7. 最高`moral_fit`が最低適合値以上である
8. 1位と2位の`moral_fit`差が最小差以上である

### 3.2 実適用許可

実際に候補選好へ利用できるかを`activation_permitted`として表す。

本Versionでは常に`false`とする。静的適格性が成立しても、次が未確認だからである。

- 候補同士が意味的に同等であること
- Authority、Capability、Constraint、Safetyの結果が同等であること
- Moral選好がユーザー意図や進行中Activityを変えないこと
- 実ログ上で誤選択率が許容範囲であること

## 4. 暫定閾値

| 項目 | 暫定値 | 意味 |
|---|---:|---|
| minimum top fit | 0.58 | 選好候補として扱う最低適合値 |
| minimum fit margin | 0.08 | 1位と2位を区別する最低差 |
| maximum aggressive impulse | 0.80 | 以上の場合は不安定状態として停止 |
| maximum selfish impulse | 0.80 | 以上の場合は不安定状態として停止 |

閾値は実ログで調整する。現段階では設定ファイルへ公開しない。

## 5. Motivation段階の維持

MoralはMotivationの異なる優先段階を越えてはならない。

候補は`motivation_score`が同じものだけを比較対象グループとする。これにより次を維持する。

- pinned候補は常に固定
- Motivation推奨順位1位をMoral推奨順位で追い越さない
- Motivation非推奨候補が推奨候補を追い越さない
- 同じMotivation段階内だけで仮想順序を計算する

## 6. Shadow結果

```python
@dataclass(frozen=True, slots=True)
class MoralActivityCandidatePreferenceShadow:
    mode: str
    static_eligible: bool
    activation_permitted: bool
    preferred_activity_type: str | None
    candidate_group: tuple[str, ...]
    current_order: tuple[str, ...]
    hypothetical_order: tuple[str, ...]
    top_fit: float | None
    runner_up_fit: float | None
    fit_margin: float | None
    reasons: tuple[str, ...]
```

### 6.1 current_order

Motivation Ranker適用後にSituation Evaluatorへ渡す実際の候補順である。

### 6.2 hypothetical_order

静的適格性が成立した場合だけ、同じMotivation段階内を`moral_fit`降順へ並べた仮想順序である。

実際の`available_activities`には使用しない。

### 6.3 reasons

成立しない条件と、実適用しない理由を機械判定可能な識別子で保持する。

主な識別子:

- `moral_context_unavailable`
- `moral_context_not_observation_only`
- `moral_state_unstable`
- `equivalent_motivation_group_unavailable`
- `top_fit_below_threshold`
- `fit_margin_below_threshold`
- `shadow_mode_only`
- `semantic_tie_confirmation_required`

## 7. Situation Evaluatorへの投影

Promptの`planning_input`へ次を追加する。

```text
moral_candidate_preference_shadow
```

Prompt規則では次を明示する。

```text
Moral preference shadowは診断専用である。
current_orderを変更せず、hypothetical_order、preferred_activity_type、static_eligibleをActivity選択へ使用しない。
```

`available_activities`の順序は従来どおりMotivation Rankerの結果とする。

## 8. 本段階で変更しない範囲

- 実際の候補順
- Situation EvaluatorのActivity選択規則
- 決定論Matcher
- active／ongoing候補の固定
- Motivation推奨順位
- Moralによる候補削除
- MoralによるActivity抑制・禁止
- Safety Policy
- Authority、Capability、Constraint検証
- Character Response内容
- Response Content Plan
- YAML設定
- DB永続化
- GUI表示

## 9. テスト方針

- 同じMotivation段階に十分なfit差がある場合、静的適格性が成立すること
- 仮想順序が計算されても実順序を変更しないこと
- fit差が小さい場合は適格性が成立しないこと
- 攻撃衝動または自己中心衝動が不安定域の場合は停止すること
- pinned候補を比較・移動しないこと
- 未定義Activityを比較対象にしないこと
- PromptへShadow結果を投影しても`available_activities`順を変更しないこと
- `activation_permitted`が常に`false`であること

## 10. 後続工程

1. Shadowの静的適格性成立率をログで観測する
2. `current_order`と`hypothetical_order`の差分を収集する
3. Situation Evaluatorの実選択とShadow推奨を比較する
4. 誤選択候補をActivity Policy単位で分析する
5. 意味的同等性を表す型付き評価契約を追加する
6. 実適用を機能フラグ付きで限定導入する
7. Moral抑制とSafety禁止を別契約として設計する

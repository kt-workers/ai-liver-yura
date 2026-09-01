# V2 Attention Policy Lifecycle D10 binding

Owner: #333
Canonical authority: `attention_turn_contracts.md`, `concurrency_architecture.md`
Related: #322, #327, #328, #329, #348, #366
Status: implementation binding

## 1. 目的

既存#333 Attention / Autonomy / TurnのFocus、Turn、response obligation、priority、fairness、interrupt schedulingを維持したまま、Scheduling Policyの生成・切替を明示的なversioned lifecycleへ接続する。

本補完では注意対象の意味、Goal、Speech内容、Activity実行、Internal Stateを決めない。

## 2. Policy注入

`AttentionTurnStore`は`AttentionSchedulingPolicy`をconstructorで必須受領する。

- production hidden defaultを持たない。
- `AttentionSchedulingPolicy.production()`はcomposition root / test fixture等が明示的に選択するためのfactoryとして残してよい。
- Store自身が「productionだからこの数値」と判断してPolicyを生成しない。

これにより、Store stateの`policy_id / policy_revision`と実際に適用しているPolicy世代を一致させる。

## 3. Policy generation不変条件

Policyは`policy_id / policy_revision`でgenerationを識別する。

- currentと同じ`policy_id / policy_revision`の再設定は、Policy内容が完全一致するときだけidempotentとして許可する。
- 同じgeneration identityのままbudget、priority、threshold、fairness数値を変更することを禁止する。
- 内容を変更する場合は新しい`policy_revision`を使用する。
- `policy_id`を切り替える場合も新しい明示generationとして扱う。

## 4. Atomic policy update

Storeへ`update_policy(policy, occurred_at)`を追加する。

Policy切替は同じStore lock内で次を一括実施する。

1. new Policy型・時刻を検証する。
2. current stateがnew Policyでもそのまま有効か検証する。
3. 不適合ならstateもPolicyも一切変更せずfail-closedする。
4. 適合する場合だけPolicyとstateの`policy_id / policy_revision`を同時に置換する。
5. Attention state revisionを1回だけ進める。

## 5. Revalidation rules

Policy変更時に既存Attention sourceを勝手に削除、並び替え、priority変更しない。

次のすべてを満たす場合のみnew Policyを受理する。

- `len(state.sources) <= new.attention_budget`
- source kindごとの現在件数が`new.source_kind_budgets`以内
- 各sourceの`effective_priority`がnew Policyのそのkindの`default_priority <= effective_priority <= maximum_priority`を満たす
- `DIRECT_USER` sourceは引き続き`USER_INTERACTION` kindだけである

不適合時:

- weakest sourceを自動evictしない。
- priorityをsilent clampしない。
- foreground / turn / obligationを勝手に解除しない。
- callerがsource resolve等で状態を明示的に整えてから、新generationを再適用する。

## 6. Fairness state

`selection_epoch`はtrigger identityの単調性に使うためPolicy変更でも維持する。

一方、次は旧fairness Policyに依存する派生履歴なので、new Policy受理時にリセットする。

- `last_selected_source_ref = None`
- `same_source_burst = 0`
- `last_selected_priority = None`
- `priority_burst = 0`
- `cooldowns = ()`

Focus / monitors / turn / response obligation / current sources / source context revisionは保持する。

## 7. Timestamp / revision

- `occurred_at`はtimezone-awareを必須とする。
- current `updated_at`より過去のPolicy切替を拒否する。
- successful updateでAttention state `revision += 1`。
- source context revisionは変更しない。
- idempotentな同一generation・同一内容の再設定はstate revisionを進めない。

## 8. Authority boundary

本補完は次を変更しない。

- source admission / evictionの既存priority rule
- same-source / priority burst fairnessの通常claim挙動
- interruption thresholdの意味
- direct user protection
- Executive由来AttentionTransition
- #348 Speech lifecycle Authority
- #329 Activity lifecycle Authority

Policy更新は現在のAttention stateを新しい運用条件へ安全に移すだけで、新しいconscious focusを選ばない。

## 9. Required tests

- `AttentionTurnStore()`のhidden Policy default禁止
- 明示production/test Policyで既存回帰維持
- same generation / same contentはidempotent
- same generation / different contentはreject
- new revisionへ正常切替しstate policy provenance更新
- global budget縮小でcurrent source countが超える場合atomic reject
- source kind budget縮小でatomic reject
- priority許可範囲変更でcurrent sourceが不適合ならatomic reject
- failed updateでstate / Policy / revisionが完全不変
- successful updateでFocus / Turn / obligation / sourceを保持
- successful updateでfairness burst/cooldownだけリセット
- selection epoch / source context revision保持
- stale `occurred_at` reject

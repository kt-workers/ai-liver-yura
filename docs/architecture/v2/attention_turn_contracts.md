# Attention / Autonomy / Turn 型付き契約

## 1. 目的

この文書はIssue #333の実装正本である。`AttentionTurnStore` はcurrent Focus、Turn、bounded source monitoring、Executive trigger eligibility及びglobal `attention_revision` を所有する。意味、Goal、Speech内容、Body gesture及びInternal Stateは決定しない。

## 2. Authority境界

- Input Meaning #326 はEventの意味を、Appraisal #327はsalience/relevance候補を所有する。
- Executive #328だけが意識的なfocus shiftを選び、typed `AttentionIntentPayload` を出せる。
- Goal/Commitment #366はpending/due stateを保持するが、次の行動又はfocusを決めない。
- `AttentionTurnStore` はvalidated attention transition、source priority policy、turn/response obligation及びeligible trigger snapshotだけをatomicに更新する。
- Body #337/#340は`AttentionFocusView`を視線・姿勢へ投影できるが、Focusを書き戻さない。

## 3. State契約

`AttentionFocusState`:

- revision / source_context_revision / updated_at
- foreground_focus_ref?
- secondary_monitor_refs[]
- current_turn_owner?
- response_obligation?
- attention_budget（正の有限整数）
- active source entries（source ref、priority、kind、受信時刻、coalesced count）

source entryは意味本文・Goal・Speech内容を持たない。高頻度sourceは同一`source_ref`ごとにcoalesceし、`attention_budget`を超えるentryはpriorityと受信順の安定規則でreject又はreplaceする。foreground user interactionはbackground/autonomous sourceより低いpriorityにできない。

`AttentionFocusView` はimmutableなbounded read modelであり、Executive/Bodyが読む。全Event履歴、raw text、provider objectは含めない。

`ExecutiveTriggerEligibility` は`trigger_id`、source refs、reason kind、priority、source/goal/attention revision、created_atを持つ。これはExecutiveの起動候補であり、Goal、Speech又はActionの決定ではない。

## 4. Transitionとrevision

`AttentionTransition` は`expected_attention_revision`、operation、target/monitor refs、turn owner、response obligation及びoccurred_atを持つ。合法operationは次だけとする。

```text
acquire_foreground / release_foreground
add_monitor / remove_monitor
assign_turn / release_turn
set_response_obligation / clear_response_obligation
```

- transitionはExecutive由来のtyped intent又は信頼済みruntime factにより作られる。raw text、Appraisal candidate、Body outputから直接mutationしない。
- expected revisionがcurrentと異なる場合、batch全体をfail-closedでrejectする。
- batchはcopy上でvalidateし、成功時だけrevisionを一回増やしてatomicに置換する。
- 同一transition IDはidempotentに再適用せずrejectする。lock区間にawait、LLM、外部I/O、callbackを含めない。

## 5. Eligibility / fairness

`evaluate_eligibility` はcurrent snapshotとtyped source entryから候補を返すだけである。

- direct user sourceはforeground候補として優先できる。
- active/pending Goal、due Commitment、Activity result、Appraisal salience、aggregated Streaming/Game eventはreason kindを区別する。
- background sourceはforeground turn、response obligation又はbudgetを無視してeligibleにしない。
- 同一sourceだけが継続選択される場合、bounded fairness policyにより他のeligible sourceをstarveさせない。
- source/goal/attention revisionが変わったcandidateはExecutive commit前にstaleとしてrejectする。

## 6. 検証

- immutable snapshot / serialization / finite budget / unique refs
- foreground acquire/shift/release、secondary monitor、turn/obligation lifecycle
- stale revision、duplicate transition、invalid owner/source、atomic batch rollback
- user priority、coalescing、budget overflow、fairness、background starvation防止
- Goal/Commitment/Appraisal/Activity由来triggerのtyped区別と、直接Goal/Actionを作らないこと
- concurrent same-base transitionは高々一件だけ成功し、Store mutationが外部workを待たないこと
- `AttentionFocusView` をExecutive/Bodyへ渡してもBody/CharacterがStateをmutationできないこと

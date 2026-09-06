# V2 Executive Appraisal Facts Contract

Status: Implementation Contract / Issue #401

## 境界

`InternalStateSnapshot`はReducerが確定したEmotion・Desire・Drive等の持続状態だけを表す。Executiveが判断で参照するsalience、relevance、Appraisal dimension、bounded evidenceは別のimmutable `AppraisalFactsSnapshot`とする。

`AppraisalCandidate`は提案であり、Executive入力へ直接渡さない。Appraisal ownerがsource context・Internal State revision・evidence上限を検証してfacts snapshotへ確定する。

## Snapshot

- `revision`、`source_context_revision`、`internal_state_revision`、`source_event_ids`
- `salience`、`relevance`、unique dimensions、bounded evidence refs
- `captured_at`

source event / evidenceはimmutable tupleで、raw user text、LLM自由文、unbounded payloadを持たない。Internal StateとAppraisal factsは一方の更新だけでも独立revisionを進められる。

## Executive

`ExecutiveContextSnapshot`は`internal_state`と`appraisal_facts`を別fieldで受け取る。両者のsource context revisionは一致しなければならない。

`ExecutiveFreshnessStamp`はInternal State revisionに加えてAppraisal facts revisionを持つ。LLM await後のlive snapshotで両revisionを再取得し、いずれかが変化していればcandidateをcommitしない。

Appraisal factsはGoal、Attention、Activity、Speech、Body、Actual FactのAuthorityを持たない。

## 検証

- candidateをfactsへ無検証昇格できない
- Internal Stateのみ、factsのみ、両方のrevision変更を検出
- duplicate dimension、unbounded evidence、context/state revision不一致を拒否
- Executive requestとcommit freshnessのAdjacent test

## 状態更新を伴う評価の確定

状態変更を提案する評価を実行判断へ渡す接続では、`InternalStateReducer.commit_with_facts`を使う。返却値`AppraisalStateCommit`は、元の`candidate`、更新後の`internal_state`、その状態版を参照する`appraisal_facts`を保持する。

確定主体は同じロックの中で既存の候補・状態・文脈・時刻・根拠・減衰方針の検査を行い、次の状態と評価事実の双方を構築してから状態を更新する。評価事実の型や根拠上限に不適合があれば状態も更新しない。評価事実の版は従来の確定入口と同様に呼出し側が指定する。

候補の`base_state_revision`は変更しない。評価事実の`internal_state_revision`は、この確定主体が実際に生成した更新後状態の版である。呼出し側が「基底版に1を足した状態」を作って評価事実を昇格する入口は設けない。

状態変更なしで評価事実だけを確定する既存の`freeze_appraisal_facts`と、状態のみを更新する`commit`は維持する。実行判断は返された状態と評価事実を一組で受け取り、待機後は両方の版を従来どおり再確認する。後続の別更新によって古くなった組を新しい状態へ付け替えない。

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

# Goal Planning D10 容量方針binding補足 — Issue #361

## 1. 目的

`goal_planning_contracts.md` §11 の実装決定を固定する。

#366 `GoalContextView` と #361 Goal Planningは同じ `BrainOperationalBoundsPolicy` 世代を使用する。Planning側で同一の `policy_id / policy_revision` を複数DTOへ重複保存して別Authorityを作らず、既存のGoal Context provenanceをPlanning request generationへ引き継ぐ。

## 2. policy generationの正本

Planning Snapshotのpolicy generationは次で表す。

```text
GoalContextView.policy_id / policy_revision
→ GoalPlanningContextSnapshot.goal_context
→ Goal Planning LLM request input
→ exact request generationにbindされたCandidate
```

`GoalPlanningPolicy` は使用する `BrainOperationalBoundsPolicy` 本体を保持する。

Production Snapshot builderは、`GoalContextView` provenanceと注入されたpolicyの `policy_id / policy_revision` が一致しない場合にSnapshotを生成しない。

Candidateへ同じprovenance fieldを重複追加することは必須としない。Candidateはrequest/result exchangeとsnapshot identity/revisionの一致でrequest generationへbindされ、commit時にそのgenerationのpolicyを再検証する。

## 3. async policy freshness

LLM awaitを含むproduction pathはcurrent policy generationを取得できるPortを持つ。

```text
request時 policy generation
→ Provider await
→ current policy generation再取得
→ same generationならcommit gate
→ 異なればstale reject
```

古いCandidateを新policyへ付け替えない。

simple deterministic pathでも同じPlanningBoundsを適用し、LLM pathだけに上限検証を限定しない。

## 4. Snapshot容量

`build_bounded_goal_planning_context` は生のtrusted Snapshot候補とpolicyを受ける。

- planning requirementに関連するCapability Descriptorを必須集合として保持する。
- 必須集合が `max_capability_descriptors` を超える場合は `PLANNING_CONTEXT_TOO_LARGE`。
- 残りCapabilityは `capability_type → capability_id → revision desc` のstable orderで空き容量へ選択する。
- PlanningBlockerは意味を勝手に落とせないため、上限超過ならfirst-Nせず `PLANNING_CONTEXT_TOO_LARGE`。
- ActivityContextRefはresume/nonterminal重複判定の証拠なので、上限超過ならfirst-Nせず `PLANNING_CONTEXT_TOO_LARGE`。
- Snapshot builderは入力Snapshotをmutationせず、新しいimmutable Snapshotを返す。

## 5. Candidate容量

`validate_plan_bounds` をsimple directive、LLM parse後、Authority commit前の共通防御として使用する。

超過時は `PLAN_TOO_LARGE` とし、first-N / dependency切断 / condition切断を行わない。

対象:

- steps 64
- dependencies per step 16
- preconditions per step 32
- completion refs per step 32
- plan completion refs 64
- checkpoint refs 64

`retry_limit` は既存typed contractどおりconcrete非負intを要求し、boolを拒否する。

## 6. 責務境界

この補完では既存のGoal Planning意味論、DAG検証、Capability live再検証、Goal stale gate、Activity Runtime境界を再実装しない。

D10補完が所有するのは容量選択、容量超過理由、policy generation binding、late policy freshnessだけである。

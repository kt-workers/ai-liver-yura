# Goal / Commitment State 型付き契約

## 1. 目的

この文書はIssue #366の実装正本である。turnやLLM requestを跨ぐcurrent Goal / Commitment Stateを単一Storeが所有し、#328 Executiveで確定したtyped transitionだけをatomicに適用する。

## 2. Authority境界

- Executiveは新しいGoal・Commitmentを選び、transition intentを確定する唯一の意識的Authorityである。
- `GoalCommitmentStore`はcurrent state、global `goal_revision`、適用済みdecision/intent IDを所有する唯一のState Authorityである。
- Storeは新しいGoalを自発的に作らず、validated Executive decisionのtransitionだけを適用する。
- Planner、Activity、Attention、Memory、Characterはsnapshot/viewを読み、Storeを直接mutationしない。
- Character発話だけでCommitmentを作らない。Activity完了だけでGoal完了を確定せず、Activity Resultを見たExecutive transitionを必要とする。

## 3. State契約

`GoalState`:

- goal_id / kind / semantic_goal_ref / target_ref
- created_from_decision_id
- status: proposed / active / suspended / completed / abandoned / failed / superseded
- priority（0..100）
- motivation_refs / commitment_refs
- preconditions / completion_condition_refs
- interruption_policy
- created_at / updated_at / revision

`CommitmentState`:

- commitment_id / semantic_commitment_ref / counterparty_ref
- source event / decision
- related_goal_refs
- status: proposed / active / suspended / released / fulfilled / violated
- strength / priority（0..100）
- due_condition_refs / release_condition_refs
- created_at / updated_at / revision

全collectionはowned tuple、参照はnon-empty identifier、時刻はtimezone-aware、snapshotはimmutableとする。

## 4. Lifecycle

Goalの合法遷移:

```text
create → proposed
proposed → active | abandoned | superseded
active → suspended | completed | abandoned | failed | superseded
suspended → active | abandoned | superseded
```

`reprioritize`はterminal以外でstatusを変えずpriorityだけを更新する。terminal stateからのtransitionは拒否する。

Commitmentの合法遷移:

```text
create → proposed
proposed → active | released
active → suspended | released | fulfilled | violated
suspended → active | released | violated
```

duplicate commitment spec、存在しないtarget、二重terminal、違法resumeをfail-closedで拒否する。

## 5. Atomic batchとrevision

`GoalCommitmentStore.apply(decision)`はdecision内のGoal/Commitment transition全件を1 batchとして扱う。

1. decision ID、intent IDの重複を検査する。
2. `candidate.goal_revision`、全transitionの`expected_goal_revision`、current global revisionが同一であることを検査する。
3. lifecycle、target、spec、参照、duplicateをcopy上で検証・適用する。
4. 1件でも失敗したらStoreを変更しない。
5. 全件成功時だけglobal revisionを1増やし、変更stateへ同じ新revisionを付けて一括置換する。
6. decision / intent IDを処理済みledgerへ追加し、immutable snapshotを返す。

Store lock区間にawait、LLM、Repository I/O、外部callbackを含めない。永続化は後続Port/Integrationがsnapshotまたはeventをlock外で扱う。

CREATE payloadはStateの正規fieldを欠落なく運ぶ。Goalはkind、target、commitment/precondition/completion参照、interruption policyを、Commitmentはcounterparty、related Goal、strength/priority、due/release条件をtyped fieldで受ける。Storeはこれらを固定既定値へ退化させない。同一semantic commitment / counterparty / related Goal / due / release条件を持つnonterminal Commitmentは別IDでもduplicateとして拒否する。

初期snapshotを受けるrehydration境界は`GoalCommitmentSnapshot`のruntime型を必須とする。

## 6. Bounded view

`GoalContextView`はglobal revisionと次のbounded tupleを返す。

- priority順のactive Goal
- relevant suspended Goal
- due/active Commitment
- recently changed Goal/Commitment

件数上限を必須とし、全履歴をExecutive Promptへ投入しない。Planner requestはgoal IDとstate revisionとglobal goal revisionを保持し、commit前にcurrent revisionを再検証する。

`AutonomyTrigger`はpending/active Goal、due条件の再評価が必要なCommitment、通常のCommitment review、resume候補をtyped sourceとして区別するだけで、due成立や次の行動をStoreが決めない。条件成立は後続のcurrent fact評価を経てExecutiveへ戻す。

## 7. 検証

- 全Goal/Commitment lifecycle、reprioritize、duplicate、wrong target、stale revision
- 同一baseの競合batchは高々1件成功
- multi-transitionのall-or-nothing
- turn/contextを跨ぐsnapshot保持
- GoalとActivity、current StateとMemory evidenceを型・所有権で分離
- GoalContextView上限・priority順・immutability
- pending Goal / due CommitmentからExecutive向けtriggerを生成し、直接actionを生成しない
- realtime経路を待たせるawait/外部callbackがStore mutationに存在しない

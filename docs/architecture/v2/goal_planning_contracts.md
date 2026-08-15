# Goal Planning Contracts 正本 — Issue #361

## 1. 目的

Goal Planningは、#366が正本化したactive Goalを、#329が実行可能な複数Activityの依存グラフへ分解する。

```text
GoalPlanningContextSnapshot
→ deterministic directive または Goal Planning Role
→ GoalPlanningCandidate
→ GoalPlanningAuthority
→ ActivityPlan
```

Goal PlanningはGoalの意味・状態を変更せず、実行結果も生成しない。

## 2. Authority境界

Goal Planningが所有するもの:

- Activity stepと依存関係
- stepごとのCapability requirement
- checkpoint、completion condition、failure recovery
- interruption後に再開可能な構造
- `goal_id / goal_revision`を保持したcommitted `ActivityPlan`

所有しないもの:

- Goal/Commitmentの作成・遷移・priority変更
- Capabilityの存在・availability
- Activityの実行開始・完了・effect
- raw user textの意味解釈
- Attention、Speech、Bodyの意思決定

## 3. 入力Snapshot

`GoalPlanningContextSnapshot`は次をfreezeする。

- Foundation `RevisionVector`
- #366 `GoalContextView`
- 対象active `GoalState`
- bounded `CapabilityDescriptor`
- bounded current `ActivityContextRef`
- trusted simple-path `DeterministicPlanningDirective`（任意）
- captured timestamp

対象Goalは`GoalContextView.active_goals`にexactly oneで含まれ、`goal_revision`はViewとFoundation revisionに一致しなければならない。terminal/suspended/proposed Goalはplanning対象にしない。

## 4. typed候補

`GoalPlanningCandidate`は次を持つ。

- candidate / goal identity
- source event IDsと3 revision
- outcome: `planned / no_plan_required / impossible`
- orderedではなく依存グラフとしての`ActivityPlanStep`
- plan completion condition refs
- checkpoint step refs
- failure policy: `fail / retry_bounded / replan_required`
- `impossible`時の未充足Capability requirement
- created timestamp

各stepは次を持つ。

- `step_id`
- `activity_type`
- `operation_ref`
- optional target ref
- dependency step IDs
- required `CapabilityRequirement`
- Goal由来precondition IDs
- Goal由来completion condition refs
- interruption policy
- retry上限
- failure時に再計画を要求するか

自由なSDK payload、実行済みfact、effect、command、最終発話、Body jointは持たない。

## 5. 構造的不変条件

- step IDと参照はunique/non-empty
- dependencyは同一candidate内にgroundし、self-referenceとcycleを拒否
- checkpointは存在するstepだけを参照
- `planned`は1件以上のstepと1件以上のplan completion conditionを必要とする
- `no_plan_required / impossible`はstep/checkpoint/completionを持たない
- `no_plan_required`はtrusted deterministic directive由来だけを許可する
- `impossible`は1件以上の未充足Capability requirementを必要とし、bounded/current snapshotの双方で本当に満たせないことをAuthorityが検証する
- step precondition/completion refsは対象Goalの正本集合からのみ選ぶ
- targetは対象Goalのtargetと同一、またはnullに限る
- 全Capability requirementはbounded Capability snapshotで満たされる
- degraded Capabilityはrequirementが明示許可した場合だけ使用可能
- `activity_type / operation_ref`は同じCapabilityDescriptorで満たせる組合せに限る
- CandidateはGoalのsemantic ref、priority、status、commitmentを出力しない
- `fail`ではretry/replan flagを禁止し、`retry_bounded`では正のretry上限を、`replan_required`ではreplan対象stepを必須にする

## 6. Commit Gate

Authorityは次をatomicに検証・commitする。

1. candidateとrequest snapshotのidentity/source/revision一致
2. current `source_context_revision / goal_revision / attention_revision`一致
3. current対象Goalが同じID・同じGoal state revision・ACTIVE・同じsemantic/target/condition集合
4. required CapabilityのID/revision/availability/operationをcurrent snapshotで再検証
5. DAG、参照、completion、checkpoint、retry/interruption schema検証
6. 同一`goal_id + goal_revision`の二重plan commit拒否

不一致は実行可能Planへ弱めずstale/replan_requiredとしてfail-closedにする。Authorityのlock区間にLLM awaitや外部callbackを含めない。

## 7. simple / complex path

simple Actionでは専用LLMを呼ばない。snapshotにtrusted `DeterministicPlanningDirective`がある場合だけ同じCandidateへ投影し、complex pathと同一Authorityへcommitする。

complex GoalはFoundation LLM typed exchangeを使う。requestはsnapshot全体をfreezeし、result到着後にlive stateを再取得してcommitする。LLM出力は候補であり、Capability存在・Goal current state・実行事実のAuthorityではない。

## 8. Concurrency / cancellation

- slow planning中もcurrent Speech、Body、Activity、unrelated inputをblockしない
- LLM await前後でAuthority lockを保持しない
- foregroundに不要になったplanning taskはcaller/runtimeがcancel・supersede可能
- cancellationされたRole resultはcommitしない
- Goal abandon/supersede/revision更新後のcandidateは必ずstale rejectする

## 9. 隣接境界

- #328 Executive: 何をしたいかを決める
- #366 Goal Store: 現在何を目指しているかを所有する
- #361 Goal Planning: complex Goalをどう実行するかを分解する
- #329 Activity Execution: committed stepから作られたcommandをpreflightしActual Factを所有する

Activity failureはGoalを直接変更せず、Execution ResultからAppraisal/Executiveを経て#366 transitionへ戻る。

## 10. Acceptance

- simple no-LLM pathとcomplex LLM pathが同一commit gateを通る
- multi-step DAG、checkpoint、completion、recoveryをtyped化する
- missing/degraded Capability、unknown operation、dangling/cyclic dependencyを拒否する
- impossible/no-plan outcomeのclosed schemaを検証する
- source/goal/attention stale、Goal state stale、Capability revision staleを拒否する
- same-goal競合では1件だけcommitする
- slow planningがunrelated simple planningをblockしない
- Provider SDK、raw user text、Execution/Goal mutationを境界へ混入させない

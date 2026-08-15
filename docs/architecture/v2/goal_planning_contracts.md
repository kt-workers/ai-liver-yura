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
- precondition/constraintが成立しているというActual Factの生成

## 3. 入力Snapshot

`GoalPlanningContextSnapshot`は次をfreezeする。

- Foundation `RevisionVector`
- #366 `GoalContextView`
- 対象active `GoalState`
- bounded `CapabilityDescriptor`
- upstream/policy由来のtrusted planning `CapabilityRequirement`
- upstream/policy由来のtrusted `PlanningBlocker`
- bounded current `ActivityContextRef`
- trusted simple-path `DeterministicPlanningDirective`（任意）
- captured timestamp

対象Goalは`GoalContextView.active_goals`にexactly oneで含まれ、`goal_revision`はViewとFoundation revisionに一致しなければならない。terminal/suspended/proposed Goalはplanning対象にしない。

`PlanningBlocker`はLLMが生成する自由文理由ではなく、Snapshot構築側が信頼済み事実として供給するtyped blockerである。

- `precondition_unsatisfied`: `subject_ref`は対象Goalの`precondition_ids`へgroundする
- `constraint_conflict`: upstream/policyが評価済みのconstraint refを`subject_ref`として保持する

候補はblockerそのものを新規生成せず、bounded Snapshotに存在する`blocker_id`だけを参照できる。

`ActivityContextRef`は再開対象を曖昧化しないため、`activity_id / goal_id / activity_type / capability_id / operation_ref / status`を保持する。Snapshot構築時に`capability_id`がbounded `CapabilityDescriptor`へ存在し、`activity_type / operation_ref`がそのDescriptorと一致することを検証する。

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
- `impossible`時のtrusted PlanningBlocker ID
- created timestamp

各stepは次を持つ。

- `step_id`
- `activity_type`
- `operation_ref`
- optional target ref
- optional resume activity ID
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
- `planned`は1件以上のstepと1件以上のplan completion conditionを必要とし、不能理由を持たない
- `no_plan_required / impossible`はstep/checkpoint/completionを持たない
- `no_plan_required`はtrusted deterministic directive由来だけを許可し、不能理由を持たない
- `impossible`は1件以上の未充足Capability requirementまたはPlanningBlocker IDを必要とする
- `impossible`の未充足Capabilityはbounded/current snapshotの双方で本当に満たせないことをAuthorityが検証する
- `impossible`の未充足requirementはtrusted planning requirement集合にgroundし、無関係な架空Capabilityを不能理由にできない
- `impossible`のPlanningBlocker IDはtrusted PlanningBlocker集合にgroundし、commit時にも同じblockerがlive stateに残っていなければならない
- `planned`のstep群はtrusted planning requirementをすべて充足する
- step precondition/completion refsは対象Goalの正本集合からのみ選ぶ
- targetは対象Goalのtargetと同一、またはnullに限る
- nonterminal Activityの重複判定は`activity_type + operation_ref`のnamespaceを最低条件とし、resume時はbounded `activity_id`とその`capability_id`がstepを満たすDescriptorへgroundする
- 別Capability namespaceで同名`operation_ref`が存在しても重複Activityとして扱わない
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
5. `impossible`が参照したPlanningBlockerをcurrent live stateで再検証
6. DAG、参照、completion、checkpoint、retry/interruption schema検証
7. 同一`goal_id + goal_revision`の二重plan commit拒否

不一致は実行可能Planへ弱めずstale/replan_requiredとしてfail-closedにする。Authorityのlock区間にLLM awaitや外部callbackを含めない。

## 7. simple / complex path

simple Actionでは専用LLMを呼ばない。snapshotにtrusted `DeterministicPlanningDirective`がある場合だけ同じCandidateへ投影し、complex pathと同一Authorityへcommitする。

complex GoalはFoundation LLM typed exchangeを使う。requestはsnapshot全体をfreezeし、result到着後にlive stateを再取得してcommitする。LLM出力は候補であり、Capability存在・PlanningBlocker・Goal current state・実行事実のAuthorityではない。

## 8. Concurrency / cancellation

- slow planning中もcurrent Speech、Body、Activity、unrelated inputをblockしない
- LLM await前後でAuthority lockを保持しない
- foregroundに不要になったplanning taskはcaller/runtimeがcancel・supersede可能
- cancellationされたRole resultはcommitしない
- Goal abandon/supersede/revision更新後のcandidateは必ずstale rejectする
- PlanningBlockerが解消・置換された後の`impossible` candidateはcommitしない

## 9. 隣接境界

- #328 Executive: 何をしたいかを決める
- #366 Goal Store: 現在何を目指しているかを所有する
- #361 Goal Planning: complex Goalをどう実行するかを分解する
- #329 Activity Execution: committed stepから作られたcommandをpreflightしActual Factを所有する

Activity failureはGoalを直接変更せず、Execution ResultからAppraisal/Executiveを経て#366 transitionへ戻る。

## 10. Acceptance

- simple no-LLM pathとcomplex LLM pathが同一commit gateを通る
- 2件以上のstepを持つ正常なmulti-step DAG、checkpoint、completion、recoveryをcommitできる
- missing/degraded Capability、unknown operation、dangling/cyclic dependencyを拒否する
- 同名operationが別Capability namespaceに存在してもresume/duplicate判定を混同しない
- impossible/no-plan outcomeのclosed schemaを検証する
- Capability不足だけでなくtrusted precondition/constraint blockerによる`impossible`を表現し、live blocker解消後は拒否する
- source/goal/attention stale、Goal state stale、Capability revision staleを拒否する
- same-goal競合では1件だけcommitする
- slow planningがunrelated simple planningをblockしない
- Provider SDK、raw user text、Execution/Goal mutationを境界へ混入させない

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
- auxiliary Capabilityの具体的な実行先ID・descriptor revisionの選択と固定（実行時bindingは#329）
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

`ActivityContextRef`は再開対象を曖昧化しないため、正規化後に`activity_id / goal_id / activity_type / capability_id / operation_ref / status`を保持する。producerは`activity_type / capability_id`を明示することを原則とする。互換入力としてそれらが省略された場合でも、Snapshot構築時に`operation_ref`と指定済みidentityからbounded `CapabilityDescriptor`がexactly oneに決まる場合だけ補完し、0件または複数候補ならfail-closedで拒否する。明示済みidentityは同じDescriptorと一致しなければならない。

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
- nonterminal Activityの重複判定は`activity_type + operation_ref`のnamespaceを最低条件とし、resume時はbounded `activity_id`とその`capability_id`がstepのprimary requirementを満たすDescriptorへgroundする。既存activityのprimary Descriptor自身にauxiliaryの充足は要求しない
- 別Capability namespaceで同名`operation_ref`が存在しても重複Activityとして扱わない
- identity省略の互換ActivityContextはbounded Capabilityがexactly oneへ解決できる場合だけ正規化する
- 全Capability requirementはそれぞれ個別にbounded Capability snapshot内のいずれかのDescriptorで満たされる。1つのDescriptorが全requirementsを同時に満たすことは要求しない
- degraded Capabilityはrequirementが明示許可した場合だけ使用可能
- `activity_type / operation_ref`にtype / operationが一致するprimary requirementをexactly one必要とし、その実行主体を#649のexact bindingで検証する（§5.1）
- CandidateはGoalのsemantic ref、priority、status、commitmentを出力しない
- `fail`ではretry/replan flagを禁止し、`retry_bounded`では正のretry上限を、`replan_required`ではreplan対象stepを必須にする

### 5.1. primaryとauxiliaryの分離（#653）

各`ActivityPlanStep`のprimary requirementは、`requirement.capability_type == step.activity_type`かつ`requirement.operation == step.operation_ref`を満たす要件とする。0件・2件以上は拒否し、先頭選択やsortによる選別は行わない。同じtype / operationで`allow_degraded`だけが異なる2要件も曖昧なprimaryとして拒否する。`CapabilityRequirement`の型にCapability IDを追加しない。

primary以外の`required_capabilities`はauxiliaryとする。例えば`research / collect`の手順が`research / collect`と`network / access`を必要とする場合、それぞれをresearch-capabilityとnetwork-capabilityが満たせば正常なPlanとなる。research-capability自身にnetwork/accessを要求しない。

snapshot検証とcommit直前current検証では、各requirementについて、その読取時点のbounded Capability集合に`descriptor.satisfies(requirement)`が真となるDescriptorが少なくとも1件存在することを要求する。degradedの判定を独自実装せず、既存の`CapabilityRequirement.allow_degraded`に従う。DEGRADEDは当該要件が`allow_degraded=True`の場合だけ充足とする。

Goal Planningはauxiliaryの必要性と現在の充足を検証するが、具体的な`capability_id / descriptor revision`を実行先として選択・Planへ保存しない。候補が複数あっても存在検査にとどめ、実行時の個別bindingは#329へ残す。snapshotのnetwork-aがcurrentのnetwork-bへ交代しても、同じ要件を両時点で満たしていれば、その交代だけではPlanをstaleにしない。

primaryも要件単位の充足を検査するが、それだけで確定しない。#649 `ActivityExecutionBinding`が保持するexact Capability ID・revision・descriptor・operation・publicationの現在性を、既存`selected_bindings()`で照合する。確定primaryの消失、revision変更、stale publicationを、同じ要件を満たす別Capabilityで救済しない。#649のAuthorityを維持し、Plannerに新しいProvider選択Authorityを設けない。

nonterminal Activityのresume / duplicate照合は、既存の`activity_type / operation_ref / capability_id`で実行主体とprimary要件を照合する。auxiliaryの充足はsnapshot集合に対する個別検査であり、既存activityのprimary Descriptorへ強制しない。`ActivityContextRef`のidentity・正規化、明示resumeの要求、異なるnamespaceの区別は維持する。実行要求側のresume exact binding契約は#651の責務であり、本節では再設計しない。

## 6. Commit Gate

Authorityは次をatomicに検証・commitする。

1. candidateとrequest snapshotのidentity/source/revision一致
2. current `source_context_revision / goal_revision / attention_revision`一致
3. current対象Goalが同じID・同じGoal state revision・ACTIVE・同じsemantic/target/condition集合
4. 全required Capabilityをsnapshotとcurrentの双方で要件ごとに再検証する。primaryはさらに#649 exact bindingのID/revision/descriptor/operation/publicationの現在性を照合する。auxiliaryはRequirement-levelのcurrent充足を検証し、具体ID/revisionの継続を要求しない
5. `impossible`が参照したPlanningBlockerをcurrent live stateで再検証
6. DAG、参照、completion、checkpoint、retry/interruption schema検証
7. 初回計画の二重確定拒否。再計画では§12の明示的な置換対象と現在計画の一致を検査する

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
- source/goal/attention stale、Goal state stale、exact primary Capability revision staleを拒否する。auxiliary Provider交代だけではstaleにしない
- same-goal競合では1件だけcommitする
- slow planningがunrelated simple planningをblockしない
- Provider SDK、raw user text、Execution/Goal mutationを境界へ混入させない

### 10.1. primary / auxiliary追加Acceptance（#653）

- primary-only stepが従来どおりcommit可能。
- primaryとauxiliaryを別Descriptorで満たしてcommit可能。
- auxiliary候補が複数でもPlanが特定Provider IDを選択・保持しない。
- snapshotまたはcurrentでauxiliaryの充足Descriptorが0件なら拒否。
- degraded auxiliaryは`allow_degraded=False`で拒否、Trueで充足可能。
- primaryはexactly one。欠落・同type / operationの複数要件はdegraded許可の差だけでも拒否。
- exact primaryの消失・revision変更・binding staleを、同等Capabilityやauxiliaryの存在で救済しない。
- auxiliaryがsnapshotとcurrentで別Providerへ交代しても要件を満たせばcommit可能。
- 補助要件付きでもnonterminal重複を拒否し、既存identityで明示resumeを照合する。
- 同じ検査をdeterministic / LLM経路へ適用し、既存replan・bounds・impossibleの意味を維持する。

## 11. D10共有容量方針

Goal Planningの容量上限は `BrainOperationalBoundsPolicy.planning` を唯一の正本とし、Module固有のmagic numberを持たない。SnapshotとCandidateは使用した `policy_id / policy_revision` を保持し、非同期LLM request中に別世代へ差し替えない。

初期V2上限:

```text
max_capability_descriptors = 128
max_planning_blockers = 64
max_activity_context_refs = 128
max_plan_steps = 64
max_dependencies_per_step = 16
max_precondition_refs_per_step = 32
max_completion_refs_per_step = 32
max_plan_completion_refs = 64
max_checkpoint_refs = 64
```

### 11.1 Snapshot構築

- `CapabilityDescriptor` はtrusted planning requirementを満たすDescriptorを必須集合として先に保持し、残りをstable orderで容量内へ選択する。
- required Capability集合が128件を超える、またはtrusted planning requirementを容量内で満たせない場合は必要項目を落とさず `PLANNING_CONTEXT_TOO_LARGE` とする。
- trusted `PlanningBlocker` が64件を超える場合はfirst-Nで黙って切らず `PLANNING_CONTEXT_TOO_LARGE` とする。
- current `ActivityContextRef` が128件を超える場合、resumeやnonterminal重複判定に必要な項目を黙って落とさず `PLANNING_CONTEXT_TOO_LARGE` とする。
- Snapshot生成後のcollectionは上限以下で、同一section内の識別子重複を許可しない。

### 11.2 Candidate / deterministic directive

LLM候補とtrusted deterministic directiveは同じ技術上限を通す。

- plan step: 64
- dependency refs / step: 16
- precondition refs / step: 32
- completion refs / step: 32
- plan completion refs: 64
- checkpoint refs: 64

上限超過をfirst-Nへ切ってcommitしない。候補が上限を超えた場合は `PLAN_TOO_LARGE` としてcommit不可とする。

64 stepを超える構造が本当に必要なGoalは、Plannerが任意に意味を縮めて別Goal相当へ変更しない。上流Executiveへ再計画要求を返せる `REPLAN_REQUIRED / PLAN_TOO_LARGE` evidenceへ閉じる。

### 11.3 retryと方針世代

`retry_limit` は各stepのtyped fieldまたはtrusted planning policyが明示する非負整数であり、boolを整数として受理しない。generic runtime backoffは別契約であり、Goal Planningが暗黙のretry回数を生成しない。

`GoalPlanningContextSnapshot`、`GoalPlanningCandidate`、`GoalPlanningCommitState` は同一 `policy_id / policy_revision` にbindされる。commit直前にcurrent policy世代が変わっていれば古いCandidateを新世代へ付け替えずstaleとして拒否する。 Snapshotに保持された方針のidentity・リビジョンは、要求構築・候補生成・所有者の確定で実際に使用する容量方針とも照合する。current policyの取得口を省略した場合でも、この入力照合を省略せず、異なる方針の上限を適用する前に`POLICY_STALE`で拒否する。

### 11.4 D10追加Acceptance

- PlanningBoundsの各count境界 below / equal / above
- required Capability / blocker / activity context overflowでsilent truncationなし
- 64/65 step境界
- dependency 16/17、precondition 32/33、step completion 32/33、plan completion 64/65、checkpoint 64/65境界
- `retry_limit` のbool拒否
- policy provenanceのrequestへの固定
- policy revision変更後のlate LLM result reject
- oversized Candidateをfirst-N acceptしない


## 計画から活動への公開接続（#334）

確定計画の採用は実行承認を意味しない。計画全体への明示的承認と手順進行は`plan_execution_approval_contracts.md`に従い、#361の計画と#328の判断と#329の実行事実を分ける。

## 12. 置換対象を明示した再計画

初回の計画確定と、既存計画の置換を区別する。活動失敗などを受けた再計画で、目標を別の内容に変えたり、再計画を通すためだけに目標のリビジョンを進めたりしない。

`GoalPlanningContextSnapshot.previous_plan`に置換する確定計画を保持し、判断中に取得した`GoalPlanningCommitState.previous_plan`と一致させる。再計画対象は同じ目標の計画に限る。旧計画全体を計画入力へ含め、既存の計画容量検査も通す。旧計画はさらに前の計画の識別子だけを持ち、履歴全体を再帰的に判断入力へ含めない。置換対象は信頼済み入力側が明示し、LLMが候補へ任意の置換対象を追加することはない。

`GoalPlanningAuthority`は目標ごとの現在計画を保持し、確定の排他区間で置換対象が現在計画と一致することを再検査する。同じ旧計画から競合する再計画が到着しても、確定できるのは1件だけとする。別の計画へ置換済み、未登録、別目標、古いリビジョン・能力・方針、不正な候補の場合、旧計画も現在計画への参照も更新しない。

初回確定では既存計画がないことを検査する。既存計画がある場合は、目標全体のリビジョンが進んだだけで暗黙に置換せず、置換対象を明示する。成功した新計画には`supersedes_plan_id`を記録する。`snapshot(plan_id)`は旧計画を含む確定内容を返し、`current_plan(goal_id)`は現在採用する1件だけを返す。

再計画も既存の単純経路・LLM経路と同じ確定検査を通る。正常な置換でも新しい計画の実行は未承認であり、旧計画の実行承認を引き継がない。進行所有者は現在計画との一致を確認してから承認登録・命令発行を行う。実行中の旧活動の取消・照合・回収は活動所有者と進行所有者の接続で扱い、計画所有者が完了事実や取消結果を生成しない。

本節の検証では、目標のリビジョンを変えない計画置換、競合候補の排他、旧計画の保持、古い置換対象の拒否、LLM待機中の現在計画変更による拒否、失敗時の状態非更新を確認する。本体の再計画要求からこの入口への接続は後続の結合検証に残る。

## #649 操作引数の由来付きbinding

`ActivityPlanStep.binding_ref`は、bounded snapshotへ信頼済み構成が提示した正規publicationのidentityを参照する。Plannerがoperation・target・activity_type・手順の意味を所有し、binding側はそれらとの完全一致を検査する。引数値を自然言語や候補から生成しない。現在のpublicationとsnapshotの一致、全出典tokenを同じ同期読取集合で保護してからPlanを確定する。確定Planには使用したpublicationだけを保持する。

出典は`ArgumentSourceOwnerPort`が実値Owner自身のparticipantで公開する。fact数とOwner数は区別し、同じOwnerの複数factで独立participantを増やさない。複数stepから同じOwnerを参照できるが、独立Ownerのコピー集約は禁止する。操作供給はprovider非依存の`ActivityOperationPublicationPort`を利用し、Pluginであることを要件にしない。step required_capabilitiesの検査は#653で事前確定した§5.1のprimary一意性・要件ごとの個別充足へ同期する。旧来の一Descriptor全要件検査は適用しない。#649 ActivityExecutionBinding Authority自体は変更せず、exact primaryの検査を維持する。binding publication自身と後続Plan Authorizationは、それぞれの実際のparticipant集合で#632容量を満たす必要がある。

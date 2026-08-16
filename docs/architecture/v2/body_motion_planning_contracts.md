# V2 Body Motion Planning Contracts

Owner Issue: #338
Parent: #335
Upstream: #323 / #328 / #336 / #337
Related canonical:
- `docs/architecture/v2/system_architecture.md`
- `docs/architecture/v2/cognitive_llm_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/body_architecture.md`
- `docs/architecture/v2/executive_authority_contracts.md`
- `docs/architecture/v2/llm_role_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

D04 Body Motion Planning の詳細契約を定める。

本Moduleは、Executiveが確定した高レベルBody Intentを、current Body State・Canonical Body Model・BodyExpressionContext・trusted Activity/Environment constraintから、#339 deterministic Compiler / Solver が物理的に解釈可能な高レベル `BodyMotionPlan` へ構造化する。

```text
Committed Executive BODY intent
+ current CanonicalBodyModel
+ current BodyState snapshot
+ current BodyExpressionContext
+ bounded BodyMotionConstraintView[]
        ↓
Body Motion Planning
  deterministic directive when sufficient
  LLM role when open-ended composition is needed
        ↓
BodyMotionPlanCandidate
        ↓
BodyMotionPlanAuthority
        ↓
BodyMotionPlan
        ↓
#339 deterministic Compiler / Solver
```

`BodyMotionPlan` はExecution Factではない。physical feasibility、joint angle、trajectory、current pose mutation、実行開始/完了は後段Authorityが所有する。

---

## 2. Authority boundary

### 2.1 Executive is the Action Authority

#328 `CommittedExecutiveDecision` / `ExecutiveIntent(kind=BODY)` が「身体で何をしたいか」の意識的Authorityである。

既存 `BodyIntentPayload`:

```text
BodyIntentPayload
- motion_goal_ref
- target_ref?
- constraint_refs[]
```

#338は新しい意識的Body Intentを作らない。

Plannerが利用してよい自然言語semanticは、**Executiveがcommitした `ExecutiveIntent.purpose` のみ**とする。これはraw user textではなく、Executiveが選択・確定した高レベルAction semanticsである。

禁止:

- raw user textを再解釈する
- Character utteranceをBody semantic authorityにする
- Input Meaningを直接「命令」として扱う
- Plannerが別のbody purposeへ変更する
- Plannerがtarget / constraint refを新規発明する

### 2.2 SystemCommand / Foundation boundary

実行可能BODY intentは#328 projectorがFoundation `SystemCommand`へ投影する。

#338 planning snapshotは、BODY intentとSystemCommandのidentityを必ずbindする。

必須一致:

- `command.decision_id == committed_decision.decision_id`
- `command.intent_ref.kind == BODY`
- `command.intent_ref.intent_id == executive_intent.intent_id`
- `command.authority.owner == executive`
- `command.authority.scope == conscious_goal_action`
- command revision / precondition / capability requirementはExecutive commit結果と一致

LLM candidateはpriority、interruptibility、precondition、required capabilityを上書きできない。

committed Planでは:

- `priority / interruptibility`は`CommittedExecutiveDecision`から
- `preconditions / required_capabilities`はvalidated `SystemCommand`から

Authorityがcopyする。

### 2.3 Body Model / Body State

#336 `CanonicalBodyModel` がskeleton / region / side / chain / end-effector / DOF / limitsのAuthorityである。

#336 `BodyState` がcurrent pose / velocity / historyのAuthorityである。

Plannerはread-only snapshotとしてのみ利用する。

- BodyStateをmutationしない
- current poseからPlanを考えるがNeutral/Home Poseを起点にしない
- LLMへunchecked final joint angleを出させない
- body modelに存在しないchain / end-effector / region refをcommitしない

### 2.4 Body Expression

#337 `BodyExpressionContext` がcurrent high-level expression biasのAuthorityである。

Plannerはexpression valueを最終Motion値として焼き付けない。

`BodyMotionPlan`は必要に応じて「どのExpression axisをどの程度motion shapingへ利用するか」というbindingだけを持てる。actual axis valueは#339/#340がlatest `BodyExpressionContext`から読む。

これによりLLM待機中のEmotion / Energy / Attention変化でBody realtimeを停止しない。

### 2.5 Activity / Environment constraint

#338はActivityやEnvironmentの正本を所有しない。

Executive `constraint_refs[]` が参照する制約について、trusted upstream owner / snapshot builderはbounded read-only `BodyMotionConstraintView`へ投影する。

```text
BodyMotionConstraintView
- constraint_id
- kind
- source_owner
- source_ref
- source_revision
- semantic_description
- subject_refs[]
```

`source_owner / source_ref / source_revision` は**upstream canonical sourceのprovenance**であり、#338独自の新しいconstraint state世代ではない。

初回`kind`:

- `REGION_AVAILABILITY`
- `CONTACT_REQUIREMENT`
- `SPATIAL_BOUNDARY`
- `TARGET_AVOIDANCE`
- `TIMING`
- `BALANCE`
- `PRESERVE_ACTIVE_MOTION`
- `ENVIRONMENT`

`semantic_description`はtrusted upstreamが確定したconstraint semanticsであり、raw user textではない。Plannerがconstraint ID / source_refの文字列名から意味を推測してはならない。

必須:

- `constraint_id`はExecutive intentの`constraint_refs[]`に存在する
- `source_owner / source_ref`はnon-empty
- `source_revision`はnon-negative
- subject refはbounded/current sourceから取得
- LLMは新しいconstraintを作れない
- candidateは未知constraint IDを参照できない
- live commitではsame source owner/ref/revisionを再検証する
- same revisionでpayloadが変わるowner invariant violationはfail closed

---

## 3. Body Motion Intent View

#338は`CommittedExecutiveDecision` / `ExecutiveIntent` / `SystemCommand`からread-only `BodyMotionIntentView`を構築する。

```text
BodyMotionIntentView
- decision_id
- intent_id
- purpose
- motion_goal_ref
- target_ref?
- constraint_refs[]
- source_event_ids[]
- revisions: RevisionVector
- priority
- interruptibility
- preconditions[]
- required_capabilities[]
```

`purpose`はExecutive commit済みsemanticであり、raw user text fieldではない。

`motion_goal_ref / target_ref / constraint_refs` はExecutive commit時にbounded snapshotへground済みであることを前提にし、#338が新しいsemantic referenceを推測しない。

Planner outputに現れるtarget referenceは、原則として `BodyMotionIntentView.target_ref` だけを許可する。新しい外界target IDをLLMが作ることを禁止する。

---

## 4. Planning Context Snapshot

`BodyMotionPlanningContextSnapshot`はLLM / deterministic planning開始時に次をfreezeする。

```text
BodyMotionPlanningContextSnapshot
- request_id
- intent: BodyMotionIntentView
- body_model: CanonicalBodyModel
- body_state: BodyState
- expression: BodyExpressionContext
- constraints: BodyMotionConstraintView[]
- deterministic_directive?
- captured_at
- trace_id
```

不変条件:

- `body_state.body_model_id == body_model.body_model_id`
- snapshot内のBODY intent / command identityが一致
- commandのFoundation revisionsとintent revisionが一致
- expressionはcurrent accepted `BodyExpressionContext`
- constraint ID集合はintentの`constraint_refs[]`とexactly一致する。欠損・余剰はreject
- duplicate constraint ID/source identity reject
- raw provider SDK objectを含めない
- raw user text / Character utterance / renderer stateを含めない

### 4.1 Current BodyState revision is planning evidence, not a hard commit generation

Body realtimeはPlanner/LLM待ち中も更新し続ける。

> `BodyState.revision` の完全一致をBodyMotionPlan commitの必須条件にしてはならない。

slow LLM中にBodyが1frameでも更新しただけで全Planをstaleにすると、Body realtime非停止というV2 invariantと矛盾する。

Planはcurrent poseを参考に構成するが、最終trajectoryは#339が**commit後のlatest BodyStateからrebase / solve**する。

Planはplanning時の`body_state_revision`をprovenanceとして保持する。

### 4.2 BodyExpression revision is also rebaseable

ExpressionもPlanner待ち中に進められる。

`BodyExpressionContext.revision`だけが進んだことを理由にPlanを自動rejectしない。

Planにexpression値そのものを固定せず、後述するExpression Bindingを使い、#339/#340がlatest expressionを参照する。

### 4.3 Constraint revision is hard freshness

Activity / Environment constraintはPlanの構造自体を変え得るため、BodyState / Expressionとは扱いを分ける。

LLM await中に:

- same source owner/refのrevisionが進んだ
- constraintが消えた
- source identityが置換された
- same revisionでdifferent payloadになった

場合:

```text
old planning candidate
→ stale / replan_required
→ no commit
```

---

## 5. Planning primitive model

Body Motion Planningは`jump`、`wave`、`happy_pose`等のpreset名を正規primitiveにしない。

Planは物理的高レベルeffectの組合せとして表現する。

### 5.1 BodyMotionEffect

初回contract:

- `ORIENT` — region / chainの向きを方向又はtargetへ向ける
- `TRANSLATE` — root / chain / end-effectorを方向又はtargetへ移動させる
- `CONTACT` — end-effectorをtargetへ接触させる高レベルgoal
- `IMPULSE` — root / chainへ一時的な加速・跳躍等を要求する高レベルgoal

これはpresetではない。

### 5.2 BodyMotionSelector

```text
BodyMotionSelector
- region: AnatomicalRegion
- side: AnatomicalSide
- chain_ids[]
- end_effector_joint_ids[]
```

- Canonical Body ModelのIDだけを参照
- renderer bone名禁止
- screen-left/right禁止。anatomical left/rightを使う
- chain / end-effectorはModel内へground
- specified end-effectorは指定chainの末端又はmodel上整合するend-effectorでなければならない

### 5.3 BodySpatialTarget

```text
BodySpatialTarget
- kind: DIRECTION | TARGET_REF
- direction?: Vector3
- target_ref?: str
- extent: [0,1]
```

`DIRECTION`:

- canonical right-handed 3D座標
- `+X` anatomical right
- `+Y` up
- `+Z` forward
- directionはfinite non-zero unit vector
- `target_ref`はNone
- `extent`はphysical distanceやjoint角ではなく相対的motion extent / effort hint

`TARGET_REF`:

- `target_ref`はExecutive BodyIntentが許可したtargetだけ
- `direction`はNone
- Plannerはworld座標を捏造しない
- #339又はPerception/Body integrationがcurrent geometryをresolveする

`extent`は`[0,1]`。physical feasibilityは保証しない。

### 5.4 BodyMotionGoal

```text
BodyMotionGoal
- goal_id
- effect: BodyMotionEffect
- selector: BodyMotionSelector
- spatial_target?
- intensity: [0,1]
- constraint_refs[]
```

`intensity`はforce / velocity / joint angleではない。大小jump、small/large gesture等の高レベル相対強度である。

Constraint refはsnapshot内の`BodyMotionConstraintView`だけを参照できる。

### 5.5 Effect-specific structural invariants

`ORIENT`:

- selectorにregion又はchainが必要
- spatial target必須
- direction又はallowed target refへ向ける

`TRANSLATE`:

- selectorにregion / chain / end-effectorの少なくとも1つが必要
- spatial target必須

`CONTACT`:

- selectorにknown end-effectorが1件以上必要
- spatial targetは`TARGET_REF`必須
- target refはExecutive intent targetと一致

`IMPULSE`:

- selectorにroot / region / chainの対象が必要
- spatial targetは`DIRECTION`必須
- intensityは0より大きい

これらはphysical feasibility判定ではない。構造的に意味のないCandidateを#339へ渡さないためのschema invariantである。

---

## 6. Motion phases

Planはordered phase sequenceを持つ。

```text
BodyMotionPhase
- phase_id
- goal_ids[]
- relative_duration_weight: positive finite number
- balance_mode
- expression_binding_ids[]
```

同一phase内の複数goalは同時に成立させる対象である。

phase間はorderedであり、absolute秒数はLLMがAuthorityとして決めない。`relative_duration_weight`は#339がcurrent pose、distance、limits、style、controller policyからactual timingを計算するための相対hintである。

### 6.1 Balance mode

- `STABLE_SUPPORT_REQUIRED`
- `TEMPORARY_FLIGHT_ALLOWED`
- `RECOVER_STABLE_SUPPORT`

Plannerがbalance成立をFactとして宣言するものではない。

#339がCoM / support / trajectoryから物理的に検証する。

### 6.2 Jump example

jumpはpresetではなく、例として:

```text
prepare
→ compression
→ extension
→ airborne
→ landing
→ recovery
```

- compression: root / lower-body TRANSLATE toward -Y
- extension: lower-body coordination + root IMPULSE toward +Y
- airborne: TEMPORARY_FLIGHT_ALLOWED
- recovery: RECOVER_STABLE_SUPPORT

actual hip/knee/ankle angle、force、velocity、landing trajectoryは#339。

---

## 7. Coordination

```text
BodyCoordinationConstraint
- coordination_id
- goal_ids[]
- mode
```

初回mode:

- `SYNCHRONIZED`
- `COUPLED`
- `COUNTERBALANCED`
- `STAGGERED`

これはkinematic solutionではなく高レベルcoordination semanticsである。

---

## 8. Expression binding

Plannerはcurrent `BodyExpressionContext`を参照できるが、axis valueをPlanへ固定しない。

```text
BodyExpressionBinding
- binding_id
- axis: BodyExpressionAxis
- influence: [0,1]
```

`influence`はcurrent axisをmotion shapingへどの程度利用するかのblend hint。

actual expression valueは#339/#340がlatest contextから読む。

PlannerがEmotion名やCharacter textから新しいExpression値を作らない。

---

## 9. BodyMotionPlanCandidate

LLM / deterministic pathが生成するのは未確定candidate。

```text
BodyMotionPlanCandidate
- candidate_id
- request_id
- source_decision_id
- source_intent_id
- source revisions
- body_model_id
- planning_body_state_revision
- planning_expression_revision
- planning_constraint_stamps[]
- goals[]
- phases[]
- coordination_constraints[]
- expression_bindings[]
- created_at
```

`planning_constraint_stamps`は:

```text
constraint_id
source_owner
source_ref
source_revision
```

のimmutable provenanceであり、LLMが変更できないrequest echoとしてvalidateする。

Candidateが所有しないもの:

- Executive priority変更
- interruptibility変更
- SystemCommand precondition変更
- required capability変更
- BodyState mutation
- final joint angles
- physical success / started / completed fact
- renderer parameter
- raw user text
- final BodyPoseFrame

---

## 10. Committed BodyMotionPlan

Authorityがcandidateを検証後、trusted metadataを付与してimmutable `BodyMotionPlan`へcommitする。

```text
BodyMotionPlan
- plan_id
- source_decision_id
- source_intent_id
- motion_goal_ref
- source revisions
- body_model_id
- planning_body_state_revision
- planning_expression_revision
- planning_constraint_stamps[]
- goals[]
- phases[]
- coordination_constraints[]
- expression_bindings[]
- priority
- interruptibility
- preconditions[]
- required_capabilities[]
- committed_at
```

`priority / interruptibility / preconditions / required_capabilities`はtrusted Executive/SystemCommandからcopyし、candidateの自由出力にしない。

BodyMotionPlanは#339へ渡すplanning artifactであり、current active trajectoryやExecution Factの正本ではない。

---

## 11. Structural validation

### Identity

- request / decision / intent / body model identity一致
- source revision一致
- candidate source IDs / planning provenanceはrequestから変更不可

### Canonical body references

- region / sideはCanonical enum
- chain IDはcurrent modelに存在
- end-effector IDはcurrent modelに存在
- selectorのchain / end-effector関係がmodelと矛盾しない
- renderer固有名禁止

### Spatial target / effect

- DIRECTIONはfinite non-zero unit 3D vector
- TARGET_REFはExecutiveで許可済みtargetだけ
- extent / intensityはfinite `[0,1]`
- effect-specific invariantを満たす

### Constraints

- candidate constraint refはsnapshotの`BodyMotionConstraintView`にground
- unknown ref reject
- planning constraint stampをcandidateが変更不可

### Phase graph

- phase ID unique
- goal ID unique
- phase goal refはcandidate内にground
- 全goalは少なくとも1 phaseから参照
- relative durationはpositive finite
- 空phase禁止

### Coordination

- coordination ID unique
- goal refはcandidate内にground
- 2件未満goalのcoordinationはreject

### Expression

- binding ID unique
- axisは#337 known axis
- influenceは`[0,1]`
- phase binding refはcandidate内にground

---

## 12. LLM role

```text
role_id: body_motion_planning
input_schema_id: body.motion-planning.context.v1
output_schema_id: body.motion-planning.candidate.v1
authority_scope: body_motion_plan_candidate
activation: conditional
```

Foundation #323 `LLMRoleRequest / LLMRoleResult / LLMRolePort`を使う。

### 12.1 Request

Request inputはPlanning Context Snapshotをstrict structured payloadへfreezeする。

含められる:

- Executive commit済みpurpose
- BodyIntent refs
- Canonical Body Model bounded view
- current BodyState snapshot
- current BodyExpressionContext
- bounded BodyMotionConstraintView

含めない:

- raw user message
- Character utterance
- renderer/provider SDK object

### 12.2 Result

ResultはFoundation role exchange validation後、`BodyMotionPlanCandidate` schemaへparseする。

LLM resultがsucceededでもPlan commit済みではない。

---

## 13. Deterministic simple path

LLM常時必須にしない。

Snapshotにtrusted `DeterministicBodyPlanningDirective`が存在する場合、LLMを呼ばず同じCandidate schemaへ投影できる。

Directiveはraw natural language keyword matcherから作らない。

```text
DeterministicBodyPlanningDirective
- goals[]
- phases[]
- coordination[]
- expression bindings[]
```

simple / complex pathは**同一BodyMotionPlanAuthority commit gate**を通す。

---

## 14. Live state / commit gate

LLM await後、開始時snapshotをcurrentとして再利用しない。

`BodyMotionPlanningLiveStatePort`はcommit直前に最低限次を返す。

```text
BodyMotionPlanningCommitState
- current RevisionVector
- current active/superseded status for source decision + BODY intent
- current SystemCommand precondition facts
- current CapabilityDescriptor snapshot
- current CanonicalBodyModel
- current BodyState
- current BodyExpressionContext
- current BodyMotionConstraintView[]
- captured_at
```

Authorityは:

1. request/result role・schema・identity一致
2. candidate source decision / intent / revisionsがrequestと一致
3. current `source_context_revision / goal_revision / attention_revision` がrequest/SystemCommandと一致
4. source BODY intentがsuperseded/cancelledされていない
5. SystemCommand precondition identity / actual / expectedをcurrent stateで再検証
6. required Capability ID / revision / availabilityをcurrent stateで再検証
7. current CanonicalBodyModel IDがplanning snapshotと一致
8. current constraint source owner/ref/revisionとsemantic payloadがplanning snapshotと一致
9. candidateのregion / chain / end-effector / target / constraint refsをcurrent model/intentionへ再ground
10. candidate構造を再validation

### 14.1 BodyState revision drift

`current BodyState.revision > planning BodyState.revision` は単独ではstale理由にしない。

- Planはcurrent poseを固定joint outputにしていない
- #339がlatest BodyStateからsolve/rebaseする

body_model_id変更、source revision rollback、same revision/different immutable payload等はfail closed。

### 14.2 Expression revision drift

`current BodyExpressionContext.revision > planning expression revision` も単独ではstale理由にしない。

- Planはaxis valueを固定していない
- #339/#340がlatest axis valueを使用

### 14.3 Constraint revision drift

constraintはhard freshness。

- source revision advance
- constraint disappearance
- source identity replacement
- same revision/different payload

のいずれかでcandidateをstale/replan_requiredとしてrejectする。

---

## 15. Cancellation / supersede

Body Motion Planningはglobal Body lockを持たない。

new BODY intentやExecutive supersedeによりin-flight requestをcancel可能。

Providerがhard cancel不可でもold resultをlive identity/revisionでrevalidateし、supersededならcommitしない。

Plan commit後のactive trajectory replacement / body-region conflict arbitrationは#339/#340 responsibility。

#338はsingle global `current_plan` slotを所有しない。別BODY intentは並列planning可能。

---

## 16. Physical Authority boundary with #339

#338が決める:

- high-level physical effect
- target region / chain / end-effector
- direction / target ref
- phase structure
- relative timing hint
- coordination semantics
- balance requirement hint
- expression binding

#339が決める:

- IK / FK
- actual joint angles
- actual trajectory
- hard/comfortable limits
- velocity / acceleration
- balance / center of mass feasibility
- contact feasibility
- actual timing
- interpolation / smoothing
- current trajectoryへのblend / interruption
- unsupported / infeasible physical result

Planner candidateにfinal joint angle等が含まれた場合はschema外としてrejectする。

---

## 17. Examples

### Look upper-right

```text
selector: HEAD/CENTER
ORIENT
direction: (+X,+Y,+Z normalized)
```

Solverがeyes / head / neck / torso contributionをcurrent poseとcomfortable rangeから決める。

### Right hand reach

```text
selector: ARM/RIGHT + right-arm chain + right-hand end effector
TRANSLATE
TARGET_REF or 3D direction
```

shoulder/elbow/wrist/torsoのactual contributionは#339。

### Bilateral wave

- left/right arm goalsを同一phaseへ置く
- end-effector ORIENT / TRANSLATE goalを複数phaseで変化
- `SYNCHRONIZED`又は`STAGGERED`
- movement_amplitude / motion_softness expression binding

`WAVE_PRESET`は存在しない。

### Jump

prepare → compression → extension → airborne → landing → recovery。

大小差は`intensity / extent`とlatest Expression / Solver policyで表現し、`SMALL_JUMP_1 / BIG_JUMP_2`等を持たない。

---

## 18. Failure behavior

### Provider / LLM failure

- typed LLM failure
- Body realtime継続
- current trajectory継続
- fake Plan / success factを生成しない
- trusted deterministic directiveが別途存在しない限り自由文fallbackしない

### Schema invalid / unknown body reference

- candidate reject
- no Plan commit

### Stale / superseded intent

- no Plan commit
- current Body realtime継続

### BodyState advanced

- model identity維持なら単独ではrejectしない
- latest stateで#339 rebase

### Expression advanced

- 単独ではrejectしない
- latest expressionを#339/#340が利用

### Constraint changed

- hard stale / replan_required
- old constraint semanticsでcommitしない

---

## 19. Required tests

### Domain contract

- strict IDs / tuple ownership
- finite `[0,1]` extent / intensity / expression influence
- invalid direction zero / non-finite / non-unit reject
- duplicate goal / phase / coordination / binding ID reject
- dangling goal / binding refs reject
- constraint source provenance validation
- effect-specific structural invariant

### Executive boundary

- non-BODY ExecutiveIntent reject
- SystemCommand decision/intent/authority mismatch reject
- candidate cannot change purpose / target / constraint identity
- priority / interruptibility / preconditions / capabilities are copied from trusted Executive/SystemCommand
- raw user text field不存在

### Constraint boundary

- all intent constraint refs resolve exactly once
- unknown/missing constraint reject
- constraint ID/source ref名からsemantic推測しない
- source revision drift reject
- disappearance/source replacement reject
- same revision/different payload reject

### Canonical Body references

- known region / side / chain / end-effector accept
- unknown chain / end-effector reject
- selector chain/end-effector inconsistency reject
- anatomical left/right維持
- renderer bone / Live2D parameter field不存在

### Motion composition

- 3D orientation: up/down/left/right/front/back/diagonal
- unilateral reach
- bilateral simultaneous motion
- whole-body composite motion
- jump phase structure
- multiple goals in same phase
- coordination constraint
- expression binding without baking current expression value
- CONTACT requires allowed target + end-effector
- IMPULSE requires direction + positive intensity

### Freshness / concurrency

- exact source/goal/attention revisions accept
- source revision drift reject
- goal revision drift reject
- attention revision drift reject
- superseded BODY intent reject
- precondition change reject
- capability revision/availability change reject
- body model change reject
- constraint source revision change reject
- **BodyState native revision advance alone does not reject**
- **BodyExpression revision advance alone does not reject**
- same body model / same intentでlatest state rebase前提Planをcommit可能
- slow LLM中もBody realtime mock/frame counterが進む
- separate BODY intent planningをglobal lockで直列化しない

### Authority regression

- PlanはExecution Factではない
- Planにfinal joint angle / frame streamなし
- Character textからBody goalを作らない
- raw user textをPlannerへ渡さない
- PlannerがExecutive Goal/Action Authorityを変更しない
- #336 BodyStateをmutationしない

---

## 20. Live LLM Verification

Unit / adjacent contractがPASSした後、Live LLMで少なくとも:

- 斜めを含む3D orientation
- unilateral / bilateral reach
- small / large jump semantics
- compound whole-body motion
- constraintあり/なしのPlan差
- expression違いでPlan structure / bindingが自然に変化するがExecutive purposeは保持
- fixed preset名、renderer bone、unchecked joint angleを生成しない

を確認する。

Live LLM品質確認はProject `Verification`対象とする。

実画面Body motionそのもののphysical qualityは#339/#340/#341で確認するため、#338単独Verificationではtyped Plan構造を主に確認する。

---

## 21. Explicit non-goals

- Canonical Skeleton/BodyState再設計 (#336)
- Body Expression再計算 (#337)
- IK/FK/kinematic feasibility (#339)
- current trajectory / controller ownership (#339)
- gaze/blink/breath/viseme realtime (#340)
- Avatar/Live2D projection (#346)
- raw user language understanding (#326)
- conscious Action selection (#328)
- Character language generation (#330)

---

## 22. Design Gate acceptance

#338 Code実装開始前に次を満たす。

- 本文書を#338 canonical supplementとして登録
- active lineageは`feature/v2-body-motion-planner`のみ
- baseはcurrent `rebuild/v2-foundation`
- Executive BODY intent / SystemCommand bindingが確定
- raw user text禁止とExecutive purpose利用境界が確定
- Activity / Environment constraintsのbounded upstream provenance / freshnessが確定
- high-level compositional primitive schemaとeffect-specific invariantが確定
- current BodyState / Expression revision driftをrebaseableとして扱うboundaryが確定
- #339 physical Authority boundaryが確定
- LLM / deterministic pathが同一candidate / commit gateを通る
- Project #7 Statusは`In progress`
- exact-head deterministic CI PASS
- Design Reviewでblocking finding 0

以後 Design -> Code を維持する。

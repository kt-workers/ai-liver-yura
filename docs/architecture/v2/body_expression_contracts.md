# V2 Body Expression Projection Contracts

Owner Issue: #337
Parent: #335
Upstream: #327 / #333 / #336 / #355
Related canonical: `docs/architecture/v2/body_architecture.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

D03 Body Expression Projectionの詳細契約を定める。

本Moduleは、現在のInternal State、Attention / Focus、Character Body Styleを、Body Motion Planner / Realtime Layerが利用できる高レベルな身体表現傾向へ決定論的に投影する。

固定Pose、Gesture preset、Motion名、joint angle、renderer parameterを生成しない。

```text
InternalStateSnapshot
+ AttentionFocusView
+ CharacterBodyStyleProfile
+ BodyExpressionProjectionPolicy
        ↓
Body Expression Projection
        ↓
BodyExpressionContext
        ↓
#338 Motion Planner / #340 Realtime Layers
```

`Emotion名 -> Motion名`、`processing -> thinking gesture`等の1対1規則を正規経路にしない。

## 2. Authority boundary

### 2.1 Internal State

#327 `InternalStateSnapshot`がcurrent Emotion / Desire / Drive / Motivation / Value appraisal / Interest / Relationship / Energy / ArousalのAuthorityである。

Body Expressionは次を変更しない。

- `InternalStateFacet.current`
- `previous`
- `last_delta`
- `confidence`
- `cause_refs`
- target relationship / interest

Body側はread-only evidenceとしてのみ使用する。

### 2.2 Attention / Focus

#333 `AttentionFocusView`がcognitive Focus / TurnのAuthorityである。

Body Expressionは次をそのまま参照する。

- `foreground_focus_ref`
- `active_focus_intent_ref`
- `secondary_monitor_refs`
- `current_turn_owner`
- `response_obligation`

Focusの存在から新しいsemantic targetやpriorityを作らない。

### 2.3 Character Body Style

#355 `CharacterBodyStyleProfile`はstatic Character Styleのread-only projectionである。

`RuntimeAvailability.CONFIRMED`のfacetだけがCharacter-specific baselineへ寄与できる。

`UNRESOLVED` / `NOT_CONFIGURED`はCharacter factを補完しない。Body Expression上の「寄与なし」は、Character設定値が0であることを意味しない。

### 2.4 Activity

#337 v1ではraw `ActivityExecutionRecord`、`operation_ref`、`details`、free-text payloadをBody Expressionが意味解釈しない。

Activity execution phaseやCapability payloadから「楽しそう」「忙しそう」「考え中」等を推測しない。

Activityによるcurrent感情・覚醒・Relationship変化は#327のInternal Stateを通して反映される。物理的なActivity constraintは#338/#339のPlanning / Solver側のAuthorityで扱う。

将来、Activity ownerがBody向けの明示的なtyped expression/occupancy viewを提供する場合は別契約として追加できるが、#337実装がraw Activityから独自に生成してはならない。

## 3. Existing source facts

### 3.1 InternalStateSnapshot

既存#327契約をそのまま利用する。

```text
InternalStateSnapshot
- revision
- source_context_revision
- facets[]
- updated_at

InternalStateFacet
- ref.kind
- ref.state_key
- ref.target_ref?
- current: [-1, 1]
- previous: [-1, 1]
- last_delta: [-1, 1]
- confidence: [0, 1]
- cause_refs[]
- updated_at
```

Body Expressionは`state_key`文字列をコード内のfinite reaction dictionaryへ変換しない。

### 3.2 AttentionFocusView

既存#333契約をそのまま利用する。

```text
AttentionFocusView
- revision
- source_context_revision
- policy_id
- policy_revision
- foreground_focus_ref?
- active_focus_intent_ref?
- secondary_monitor_refs[]
- current_turn_owner?
- response_obligation?
```

このViewには「注視強度」の数値が存在しないため、Body Expressionが0.8等の強度を創作してはならない。

### 3.3 CharacterBodyStyleProfile

既存#355契約を利用する。

Body Styleの既知facet ID:

- `amplitude_tendency`
- `continuity_tendency`
- `gaze_tendency`
- `head_expression_tendency`
- `motion_softness`
- `posture_expression_tendency`
- `spatial_extent_tendency`
- `symmetry_tendency`

#337がこれらを利用する場合、`CONFIRMED` valueはcanonical decimal textとして`[-1, 1]`へstrict parseする。

例:

```yaml
body:
  motion_softness:
    state: confirmed
    value: "0.65"
```

- NaN / Infinityは禁止
- 範囲外は禁止
- 非数値textをBody側で自然言語解釈しない
- parse不能はtyped invalid-style failure
- Character content変更は同じfacet IDと数値域の範囲ならCore code変更不要

## 4. Normalized expression domain

BodyExpressionContextのcontinuous axisはすべてsigned unit domain `[-1, 1]`を使う。

- `-1`: axisの負方向が強い
- `0`: 中立 / 当該axisへのbiasなし
- `+1`: axisの正方向が強い

`0`は「Character設定が0」と同義ではない。未解決sourceが寄与しない場合にも結果的に0となり得る。

非有限値は禁止し、最終値は必ず`[-1, 1]`へclampする。

## 5. BodyExpressionAxis

初回contractでは次を定義する。

| Axis | -1 | +1 |
|---|---|---|
| `posture_expressiveness` | restrained | expressive |
| `movement_energy` | subdued | energetic |
| `movement_amplitude` | small | large |
| `motion_softness` | sharp | soft |
| `spatial_extent` | compact | expansive |
| `motion_continuity` | segmented | continuous |
| `movement_tempo` | slow | fast |
| `gaze_freedom` | anchored | exploratory/free |
| `head_expressiveness` | restrained | expressive |
| `torso_expressiveness` | restrained | expressive |
| `symmetry` | asymmetric | symmetric |
| `coordination` | loosely coupled | strongly coordinated |
| `breathing_amplitude` | shallow | deep |
| `breathing_tempo` | slow | fast |
| `idle_variation` | minimal | varied |
| `gesture_density` | sparse | dense |

これらはMotion commandではない。

例えば`movement_amplitude=0.8`は腕を何度動かすか、どのPoseを取るかを決めない。#338/#339がcurrent Body State、BodyIntent、Canonical Body Model等と組み合わせて実現する。

## 6. Character Style baseline mapping

Character Body Styleは次のaxisへbaseline biasを提供する。

| Character facet | Expression axis |
|---|---|
| `amplitude_tendency` | `movement_amplitude` |
| `continuity_tendency` | `motion_continuity` |
| `gaze_tendency` | `gaze_freedom` |
| `head_expression_tendency` | `head_expressiveness` |
| `motion_softness` | `motion_softness` |
| `posture_expression_tendency` | `posture_expressiveness` |
| `spatial_extent_tendency` | `spatial_extent` |
| `symmetry_tendency` | `symmetry` |

1つのCharacter facetから複数のMotion結果を直接生成しない。

Character baselineはaxisの初期biasであり、current state contributionによって強まる、弱まる、反対側へ動くことができる。

## 7. BodyExpressionProjectionPolicy

Internal StateからExpression axisへの変換はversioned typed policyとして表現する。

```text
BodyExpressionProjectionPolicy
- policy_id
- policy_revision
- rules[]
```

```text
BodyExpressionInfluenceRule
- rule_id
- facet_kind: StateFacetKind
- state_key?              # exact key。Noneはkind単位の明示wildcard
- target_scope
- component
- transform
- axis_weights[]
```

policyはCharacter Definitionではない。

Character固有の人格値ではなく、「typed state evidenceをBody expression axisへどう連続投影するか」というBody projection policyである。

同じschema内でrule / weightを変更する場合、Core algorithmを変更せずpolicy revisionを更新できる構造にする。

## 8. State signal extraction

### 8.1 Component

ruleは次のどちらを読むか明示する。

- `CURRENT`: `InternalStateFacet.current`
- `DELTA`: `InternalStateFacet.last_delta`

`previous`を別Authorityとして再解釈しない。

### 8.2 Transform

許可transform:

- `SIGNED`: `x`
- `MAGNITUDE`: `abs(x)`
- `POSITIVE_ONLY`: `max(x, 0)`
- `NEGATIVE_MAGNITUDE`: `max(-x, 0)`

その後、常に`confidence`を乗算する。

```text
signal = transform(component_value) * confidence
```

rule weightは`[-1, 1]`。

```text
axis_delta = signal * weight
```

### 8.3 Target scope

Targeted Interest / Relationship等を現在の相手・対象へ限定するため、ruleはtarget scopeを持てる。

- `GLOBAL`: `target_ref is None`のみ
- `ANY_TARGET`: targetを問わない
- `FOREGROUND`: `target_ref == AttentionFocusView.foreground_focus_ref`
- `TURN_OWNER`: `target_ref == AttentionFocusView.current_turn_owner`

Bodyが文字列類似度等で対象を推測しない。

## 9. Composition algorithm

Projectionはpure deterministic functionとする。

1. Character confirmed baselineをaxisごとに取得する。
2. Internal State facetsとpolicy rulesをexact typed matchする。
3. ruleごとのcontinuous contributionを計算する。
4. axisごとに全寄与をstable orderで合算する。
5. `[-1, 1]`へclampする。
6. Attention / Focus refsをcategorical expression constraintとしてそのまま付加する。
7. provenanceを保持する。

```text
axis = clamp(character_baseline + sum(dynamic_contributions), -1, 1)
```

浮動小数の走査順で結果が変わらないよう、rule/sourceのstable orderingと安定した加算を使用する。

### 9.1 Forbidden composition

禁止:

```text
emotion.fear -> run_away_pose
emotion.joy -> happy_motion
activity.processing -> thinking_gesture
foreground exists -> gaze_strength = 0.8
```

許可されるのは、明示policyを介した複数axisへのcontinuous contributionとcategorical Focus constraintまでである。

## 10. Focus expression constraint

Attentionは数値axisへ暗黙変換しない。

BodyExpressionContextは次をread-only provenance/constraintとして保持する。

```text
BodyFocusExpressionConstraint
- foreground_focus_ref?
- active_focus_intent_ref?
- secondary_monitor_refs[]
- current_turn_owner?
- response_obligation?
```

#338/#340はこれをgaze target / posture attention expressionの入力にできるが、Body側がcognitive focus priorityを変更しない。

## 11. Stable read fence

`source_context_revision`は各ownerが最後に更新された文脈世代を表し得るため、Internal StateとAttentionの値が常に完全一致することを要求しない。

代わりに、Body Expression coordinatorはcurrent snapshotsをstable read fence内で取得する。

```text
read global source context revision -> R1
read current InternalStateSnapshot
read current AttentionFocusView
read current CharacterBodyStyleProfile
read global source context revision -> R2
accept only when R1 == R2
```

受理条件:

- `R1 == R2`
- `internal_state.source_context_revision <= R1`
- `attention.source_context_revision <= R1`
- source objectは各ownerのcurrent read-only snapshotから取得
- read中にgenerationが変わった場合はbounded retryまたはtyped stale/unavailable

古いcached objectを「revisionが小さいからまだ使える」とBody側が独断で採用しない。

stable readを確立できない場合、新しいExpression Contextをcommitしない。現在のBody realtime / previous accepted expressionは継続可能でなければならない。

## 12. Provenance

BodyExpressionContextは最低限次を保持する。

```text
BodyExpressionContext
- revision
- capture_source_context_revision
- internal_state_revision
- internal_state_source_context_revision
- attention_revision
- attention_source_context_revision
- character_id
- character_schema_version
- character_definition_revision
- projection_policy_id
- projection_policy_revision
- axes
- focus_constraint
- applied_rule_ids[]
- source_facet_refs[]
- generated_at
```

`revision`はBody Expression ownerのcurrent context revisionであり、入力ownerのrevisionを代用しない。

## 13. Atomic context commit

Projection計算そのものはpure / synchronousとする。

current BodyExpressionContextを保持する場合、Body Expression store/reducerだけが書込みAuthorityを持つ。

commit時:

- expected expression revision不一致 -> stale reject
- capture source context revisionを巻き戻さない
- Internal State revisionを巻き戻さない
- Attention revisionを巻き戻さない
- Character definition revisionを巻き戻さない
- Projection policy revisionを巻き戻さない

同じinput provenanceと同じpolicyから異なるaxis結果が出た場合はdeterminism violationとしてfail closedする。

同じprovenance・同じ結果の再計算はidempotent no-opにできる。

## 14. Failure behavior

### Invalid Character style

confirmed valueがcanonical decimalではない、非有限、範囲外:

- typed invalid-style failure
- natural language interpretation禁止
- invented neutral Character fact禁止

### Incoherent read

stable fenceを確立できない:

- typed stale/incoherent
- new context未commit
- previous accepted context / realtime continuationを停止しない

### Missing / unresolved style

- Character contributionなし
- dynamic state projectionは継続可能
- missing valueをCharacter factとして0に確定しない

### Missing policy rule

- そのstate facetはExpressionへ寄与しない
- fallback emotion dictionaryを使用しない
- source state自体は変更しない

## 15. Body State boundary

#336 `BodyState`はcurrent pose / velocity / historyのAuthorityである。

#337はBodyStateをmutationしない。

BodyExpressionContextはposeでもtrajectoryでもないため、#336のjoint / velocity contractへ表現axisを埋め込まない。

#338以降が次のように合成する。

```text
Executive BodyIntent
+ BodyExpressionContext
+ current BodyState
+ CanonicalBodyModel
-> BodyMotionPlan
```

## 16. Character psychological structure boundary

#355 `CharacterPsychologicalProfile`は本質・Deep Prior・形成史・Belief・Value・Self Model・Adaptation等を保持するが、#337 v1がこれらの自由文valueを直接意味解析してBody axisへ変換してはならない。

Body固有Styleは`CharacterBodyStyleProfile`を直接利用する。

将来、心理facetからBody Expressionへの追加投影を行う場合も、free-text LLM interpretationではなく明示typed policy / projection contractを設計してから導入する。

これにより:

```text
Character cause structure
-> Appraisal / current Internal State
-> Body Expression
```

という因果経路を維持し、Character free-textをBody command Authorityにしない。

## 17. Non-blocking requirement

#337はBody realtime loopのblocking prerequisiteにならない。

- ProjectionはLLMを呼ばない。
- DB / TTS / rendererを呼ばない。
- stable snapshot read失敗時にframe loopを停止しない。
- new context待ちの間はprevious accepted expression / realtime layersを継続できる。
- #338 Motion Plannerがslowでも#337 current context readは独立して可能。

## 18. Required tests

### Domain

- normalized axis範囲
- NaN / Infinity reject
- Character decimal parse
- unresolved/not-configured styleはvalueをinventしない
- body style facet -> expected baseline axis
- policy rule validation
- duplicate rule ID reject
- invalid weight reject
- target scope validation

### Projection

- same Internal State + different Character Style -> axis差
- same Style + different current state -> axis差
- multiple state contributions compose
- CURRENT / DELTAを区別
- confidence=0は寄与なし
- target Relationshipがforegroundと一致/不一致
- current Turn owner target matching
- no policy rule -> no hidden fallback
- clamp at [-1, 1]
- stable orderingでdeterministic

### Attention boundary

- Focus refsをそのままconstraintへ保持
- Focus presenceからnumeric gaze strengthをinventしない
- Body outputからAttention stateをmutationしない

### Authority regression

- raw Activity payloadを意味解釈しない
- Emotion名からPose/Motionを生成しない
- Character psychological free-textをBody commandへ変換しない
- BodyExpressionContextにjoint angle / Pose / Gesture presetを持たせない
- BodyExpressionContextがExecutive BodyIntentを作らない

### Freshness / concurrency

- stable fence R1 == R2でaccept
- R1 != R2でnew context reject
- source last-update context revisionがcapture revision以下なら保持可能
- source future revision reject
- stale expression revision commit reject
- source revision rollback reject
- invalid projectionでもprevious context継続

## 19. Non-goals

- Body Motion Planning (#338)
- IK / kinematics / balance (#339)
- blink / breath / gaze per-frame controller (#340)
- raw Activity semantics interpretation
- Emotion classification
- Character free-text interpretation
- renderer parameter generation
- fixed Pose / Gesture / Motion preset selection

## 20. Design Gate acceptance

#337 implementation開始前に次を満たす。

- 本文書を#337 canonical supplementとして記録
- active lineageは`feature/v2-body-expression`のみ
- V2 trunk/baseとのdriftなし、または同期済み
- source Authority / normalized domain / policy / stable read fenceが確定
- Project #7 Statusは`In progress`

以後Design -> Codeを維持する。

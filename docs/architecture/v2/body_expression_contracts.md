# V2 Body Expression Projection Contracts

Owner Issue: #337
Parent: #335
Upstream: #327 / #333 / #336 / #355
Related canonical: `docs/architecture/v2/body_architecture.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

D03 Body Expression Projectionの詳細契約を定める。

本Moduleは、現在のInternal State、Attention / Focus、Character Body Styleを、Body Motion Planner / Realtime Layerが利用できる高レベルな身体表現傾向へ決定論的に投影する。

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

固定Pose、Gesture preset、Motion名、joint angle、renderer parameterを生成しない。

`Emotion名 -> Motion名`、`processing -> thinking gesture`等の1対1規則を正規経路にしない。

---

## 2. Authority boundary

### 2.1 Internal State

#327 `InternalStateSnapshot`がcurrent Emotion / Desire / Drive / Motivation / Value appraisal / Interest / Relationship / Energy / ArousalのAuthorityである。

#337は次をread-only evidenceとして利用し、書き換えない。

- `InternalStateFacet.ref`
- `current`
- `previous`
- `last_delta`
- `confidence`
- `cause_refs`
- `updated_at`

### 2.2 Attention / Focus

#333 `AttentionFocusView`がcognitive Focus / TurnのAuthorityである。

#337は次をそのまま参照する。

- `foreground_focus_ref`
- `active_focus_intent_ref`
- `secondary_monitor_refs`
- `current_turn_owner`
- `response_obligation`

Focusの存在から新しいsemantic target、priority、数値強度を作らない。

### 2.3 Character Body Style

#355 `CharacterBodyStyleProfile`がstatic Character Body Styleのread-only projectionである。

`RuntimeAvailability.CONFIRMED`のfacetだけがCharacter-specific baselineへ寄与できる。

`UNRESOLVED` / `NOT_CONFIGURED`はCharacter factを補完しない。「寄与なし」はCharacter設定値が0であることを意味しない。

重要:

- #355は`RuntimeCharacterFacet.value`をnon-empty stringとして保持するが、その文字列に`[-1,1]`数値尺度を定義していない。
- #337は既存#355 valueの意味を暗黙に数値化・自然言語解釈してはならない。
- Character Body StyleをExpression axisへ結び付ける意味変換は、後述するversioned `CharacterStyleInfluenceRule`で**exact value matchとして明示**する。

### 2.4 Activity

#337 v1ではraw `ActivityExecutionRecord`、`operation_ref`、`details`、free-text payloadをBody Expressionが意味解釈しない。

Activity execution phaseやCapability payloadから「楽しそう」「忙しそう」「考え中」等を推測しない。

Activityによるcurrent感情・覚醒・Relationship変化は#327 Internal Stateを通して反映される。物理的なActivity constraintは#338/#339のPlanning / Solver側Authorityで扱う。

将来、Activity ownerがBody向けの明示typed expression/occupancy viewを提供する場合は別契約として追加できるが、#337がraw Activityから独自生成してはならない。

---

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
- ref.kind: StateFacetKind
- ref.state_key
- ref.target_ref?
- current: [-1, 1]
- previous: [-1, 1]
- last_delta: [-1, 1]
- confidence: [0, 1]
- cause_refs[]
- updated_at
```

`state_key`の意味はopen-endedである。#337 codeに`fear`等のfinite reaction dictionaryを埋め込まない。

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

既存#355契約をそのまま利用する。

既知facet ID:

- `amplitude_tendency`
- `continuity_tendency`
- `gaze_tendency`
- `head_expression_tendency`
- `motion_softness`
- `posture_expression_tendency`
- `spatial_extent_tendency`
- `symmetry_tendency`

`CONFIRMED(value)`のvalueは#355のCharacter contentであり、#337がdecimal等の新しい表現契約を後付けしない。

---

## 4. Normalized expression domain

`BodyExpressionContext`のcontinuous axisはsigned unit domain `[-1, 1]`を使う。

- `-1`: axisの負方向が強い
- `0`: 中立 / 当該axisへのbiasなし
- `+1`: axisの正方向が強い

非有限値は禁止し、最終値は必ず`[-1,1]`へclampする。

`0`はCharacter設定値が0という事実ではない。未解決sourceが寄与しない結果として0になり得る。

---

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

`movement_amplitude=0.8`は腕を何度動かすか、どのPoseを取るかを決めない。#338/#339がBodyIntent、current Body State、Canonical Body Model等と組み合わせて実現する。

---

## 6. BodyExpressionProjectionPolicy

Internal StateとCharacter Body StyleからExpression axisへの意味変換は、versioned typed policyとして明示する。

```text
BodyExpressionProjectionPolicy
- policy_id
- policy_revision
- state_rules[]
- character_style_rules[]
```

policyはCharacter DefinitionでもInternal State Authorityでもない。

同じcontract内でrule / weight / exact style bindingを変更する場合、Core algorithmを変更せずpolicy revisionとpolicy dataを更新できる構造にする。

### 6.1 State influence rule

```text
BodyExpressionInfluenceRule
- rule_id
- facet_kind: StateFacetKind
- state_key?               # exact key。Noneは明示wildcard
- target_scope
- component
- transform
- axis_weights[]
```

ruleの存在自体が意味変換のAuthorityである。code内にhidden fallback dictionaryを持たない。

### 6.2 Character style rule

```text
CharacterStyleInfluenceRule
- rule_id
- facet_id                 # #355の既知Body Style facet ID
- confirmed_value          # exact string match
- axis_weights[]
```

例:

```text
facet_id = motion_softness
confirmed_value = soft
axis_weights = {motion_softness: +0.6}
```

この例は契約形式の説明であり、`soft`や`+0.6`をゆらのproduction値として確定するものではない。

必須:

- `confirmed_value`は完全一致。部分一致、regex、埋め込み、LLM意味解釈を行わない。
- `UNRESOLVED` / `NOT_CONFIGURED`はstyle ruleへ入力しない。
- 同一`facet_id + confirmed_value`に複数ruleを許可する場合もrule IDと寄与順を決定論的にする。
- confirmed Body Style facetに適用可能なruleがなく、そのfacetを利用する構成ではtyped `UNMAPPED_CHARACTER_STYLE`としてfail closedする。
- Character value変更に伴うpolicy data更新は許可するが、Core projector algorithmを書き換えない。

これにより#337は#355 valueへ新しい暗黙数値尺度を後付けしない。

---

## 7. State signal extraction

### 7.1 Component

state ruleは次のどちらを読むか明示する。

- `CURRENT`: `InternalStateFacet.current`
- `DELTA`: `InternalStateFacet.last_delta`

`previous`を独自のcurrent Authorityとして再解釈しない。

### 7.2 Transform

許可transform:

- `SIGNED`: `x`
- `MAGNITUDE`: `abs(x)`
- `POSITIVE_ONLY`: `max(x, 0)`
- `NEGATIVE_MAGNITUDE`: `max(-x, 0)`

その後、常に`confidence`を乗算する。

```text
signal = transform(component_value) * confidence
axis_delta = signal * weight
```

`weight`は`[-1,1]`。

### 7.3 Target scope

Targeted Interest / Relationship等を現在の相手・対象へ限定するため、ruleはtarget scopeを持てる。

- `GLOBAL`: `target_ref is None`のみ
- `ANY_TARGET`: targetを問わない
- `FOREGROUND`: `target_ref == AttentionFocusView.foreground_focus_ref`
- `TURN_OWNER`: `target_ref == AttentionFocusView.current_turn_owner`

Bodyが文字列類似度や名前推定で対象を対応付けない。

---

## 8. Composition algorithm

Projectionはpure deterministic functionとする。

1. `CONFIRMED` Character Body Style facetをexact style ruleへ照合する。
2. style ruleのaxis contributionをCharacter baseline contributionとして得る。
3. Internal State facetをstate ruleへtyped / exact matchする。
4. state ruleのcontinuous contributionを計算する。
5. axisごとに全寄与をstable orderで合算する。
6. `[-1,1]`へclampする。
7. Attention / Focus refsをcategorical expression constraintとしてそのまま付加する。
8. provenanceを保持する。

```text
axis = clamp(sum(character_style_contributions)
             + sum(dynamic_state_contributions), -1, 1)
```

浮動小数の走査順で結果が変わらないよう、rule/sourceのstable orderingとstable summationを使用する。

### 8.1 Forbidden composition

禁止:

```text
emotion.fear -> run_away_pose
emotion.joy -> happy_motion
activity.processing -> thinking_gesture
foreground exists -> gaze_strength = 0.8
CharacterBodyStyleProfile.value -> float(value)  # #355が数値尺度を定義していない
```

許可されるのは、明示policyを介したcontinuous multi-axis contributionとcategorical Focus constraintまでである。

---

## 9. Focus expression constraint

Attentionは数値axisへ暗黙変換しない。

```text
BodyFocusExpressionConstraint
- foreground_focus_ref?
- active_focus_intent_ref?
- secondary_monitor_refs[]
- current_turn_owner?
- response_obligation?
```

#338/#340はこれをgaze target / posture attention expressionの入力にできるが、Bodyがcognitive Focusやpriorityを書き換えない。

---

## 10. Read-only ports

#337は既存ownerを置換せず、read-only Portだけを定義できる。

概念上:

```text
InternalStateReadPort.current_snapshot() -> InternalStateSnapshot
AttentionFocusReadPort.current_view() -> AttentionFocusView
CharacterBodyStyleReadPort.current_profile() -> CharacterBodyStyleProfile
BodyExpressionPolicyReadPort.current_policy() -> BodyExpressionProjectionPolicy
BodyExpressionLiveContextPort.current_source_context_revision() -> int
```

これは新しいstate Authorityではない。各Portはそれぞれ既存ownerのcurrent immutable snapshotを返す。

---

## 11. Multi-owner stable read fence

`source_context_revision`が同じでも、#327 decayや#333内部遷移等で各ownerのnative revisionだけが進み得る。

したがってglobal source-contextの前後一致だけではstable cutを保証しない。

Body Expression coordinatorはglobal generationと各native generationを二重読みによって固定する。

概念上:

```text
R1 = read global source_context_revision
S1 = read current InternalStateSnapshot
A1 = read current AttentionFocusView
C1 = read current CharacterBodyStyleProfile
P1 = read current BodyExpressionProjectionPolicy

S2 = read current InternalStateSnapshot
A2 = read current AttentionFocusView
C2 = read current CharacterBodyStyleProfile
P2 = read current BodyExpressionProjectionPolicy
R2 = read global source_context_revision
```

受理条件:

- `R1 == R2`
- `S1 == S2`かつ`S1.revision == S2.revision`
- `A1 == A2`かつ`A1.revision == A2.revision`
- `C1 == C2`かつcharacter/schema/definition revisionが一致
- `P1 == P2`かつpolicy id/revisionが一致
- `S1.source_context_revision <= R1`
- `A1.source_context_revision <= R1`

同一revisionで異なるimmutable payloadが返る場合はsource owner invariant violationとしてfail closedする。

read中にgenerationが変わった場合はbounded retryまたはtyped `STALE/INCOHERENT`とする。global lockを導入しない。

古いcached objectを「revisionが小さいからまだ使える」とBody側が独断で採用しない。

stable readを確立できない場合、新しいExpression Contextをcommitしない。previous accepted expression / current trajectory / realtime layersは継続できなければならない。

---

## 12. BodyExpressionContext

最低限:

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
- applied_state_rule_ids[]
- applied_character_style_rule_ids[]
- source_facet_refs[]
- generated_at
```

`revision`はBody Expression ownerのcurrent context revisionであり、入力ownerのrevisionを代用しない。

`axes`は全`BodyExpressionAxis`を一度ずつ持つimmutable normalized value集合とする。

`BodyExpressionContext`はBodyIntent、Pose、Trajectory、joint command、Execution Factではない。

---

## 13. Atomic context commit

Projection計算はpure / synchronousとする。

current `BodyExpressionContext`を保持する場合、Body Expression store/reducerだけが書込みAuthorityを持つ。

commit時:

- expected expression revision不一致 -> stale reject
- capture source context revisionを巻き戻さない
- Internal State revisionを巻き戻さない
- Attention revisionを巻き戻さない
- 同一characterでCharacter definition revisionを巻き戻さない
- 同一policy IDでpolicy revisionを巻き戻さない

同じinput provenance + 同じpolicyから異なるaxis結果が出た場合はdeterminism violationとしてfail closedする。

同じprovenance・同じ結果の再計算はidempotent no-opにできる。

Character IDやpolicy IDそのものを切り替えるlifecycleは#337 projection commitが独断で決めず、Composition / configuration ownerから明示的に渡されたcurrent sourceを使用する。

---

## 14. Failure behavior

### Unmapped confirmed Character style

confirmed valueにexact style ruleがない:

- typed `UNMAPPED_CHARACTER_STYLE`
- natural language interpretation禁止
- implicit numeric parse禁止
- invented neutral Character fact禁止
- new context未commit

### Missing / unresolved style

- Character contributionなし
- dynamic state projectionは継続可能
- missing valueをCharacter factとして0に確定しない

### Missing state rule

- そのstate facetはExpressionへ寄与しない
- fallback emotion dictionaryを使用しない
- source state自体は変更しない

### Incoherent read

stable fenceを確立できない:

- typed `STALE/INCOHERENT`
- new context未commit
- previous accepted context / realtime continuationを停止しない

---

## 15. Body State boundary

#336 `BodyState`はcurrent pose / velocity / historyのAuthorityである。

#337は`BodyState`をmutationしない。Expression axisを#336 joint/velocity contractへ埋め込まない。

#338以降が次を合成する。

```text
Executive BodyIntent
+ BodyExpressionContext
+ current BodyState
+ CanonicalBodyModel
-> BodyMotionPlan
```

---

## 16. Character psychological structure boundary

#355 `CharacterPsychologicalProfile`は本質・Deep Prior・形成史・Belief・Value・Self Model・Adaptation等を保持するが、#337 v1がこれらのfree-text valueを直接意味解析してBody axisへ変換してはならない。

Body固有Styleは`CharacterBodyStyleProfile`を、明示`CharacterStyleInfluenceRule`を介して利用する。

心理facetからBody Expressionへの追加投影を将来導入する場合も、free-text LLM interpretationではなく新しいtyped policy / projection contractを設計してから追加する。

正規因果経路は原則:

```text
Character cause structure
-> Appraisal / current Internal State
-> Body Expression
```

である。

---

## 17. Non-blocking requirement

#337はBody realtime loopのblocking prerequisiteにならない。

- ProjectionはLLMを呼ばない。
- DB / TTS / rendererを呼ばない。
- stable snapshot read失敗時にframe loopを停止しない。
- new context待ちの間はprevious accepted expression / current trajectory / realtime layersを継続できる。
- #338 Motion Plannerがslowでも#337 current context readは独立して可能。

---

## 18. Required tests

### Domain

- normalized axis `[-1,1]`
- NaN / Infinity reject
- policy id/revision validation
- duplicate rule ID reject
- invalid weight reject
- duplicate axis weight reject
- target scope validation
- Character style ruleは#355既知Body facet IDだけを受理

### Character style

- exact confirmed value matchでのみ寄与
- partial / case-insensitive / regex相当の暗黙matchをしない
- `UNRESOLVED` / `NOT_CONFIGURED`はvalueをinventしない
- confirmed but unmapped -> typed failure
- Character値変更 + policy data変更でCore algorithm変更不要

### Projection

- same Internal State + different Character Style mapping -> axis差
- same Style + different current state -> axis差
- multiple state/style contributions compose
- CURRENT / DELTAを区別
- confidence=0はdynamic寄与なし
- target Relationshipがforegroundと一致/不一致
- current Turn owner target matching
- no policy rule -> no hidden fallback
- clamp at `[-1,1]`
- stable ordering / summationでdeterministic

### Attention boundary

- Focus refsをconstraintへそのまま保持
- Focus presenceからnumeric gaze strengthをinventしない
- Body outputからAttention stateをmutationしない

### Authority regression

- raw Activity payloadを意味解釈しない
- Emotion名からPose/Motionを生成しない
- Character psychological free-textをBody commandへ変換しない
- BodyExpressionContextにjoint angle / Pose / Gesture presetを持たせない
- BodyExpressionContextがExecutive BodyIntentを作らない

### Freshness / concurrency

- global R1 == R2かつ各native snapshot二重読み一致でaccept
- global revision変化でreject
- Internal State native revision変化でreject/retry
- Attention native revision変化でreject/retry
- Character definition revision変化でreject/retry
- policy revision変化でreject/retry
- source last-update context revisionがcapture revision以下なら保持可能
- source future context revision reject
- stale expression revision commit reject
- source revision rollback reject
- invalid projectionでもprevious context継続

---

## 19. Non-goals

- Body Motion Planning (#338)
- IK / kinematics / balance (#339)
- blink / breath / gaze per-frame controller (#340)
- raw Activity semantics interpretation
- Emotion classification
- Character free-text interpretation
- renderer parameter generation
- fixed Pose / Gesture / Motion preset selection

---

## 20. Design Gate acceptance

#337 implementation開始前に次を満たす。

- 本文書を#337 canonical supplementとして記録
- active lineageは`feature/v2-body-expression`のみ
- V2 trunk/baseとのdriftなし、または同期済み
- source Authority / normalized axis domain / explicit style+state policy / multi-owner stable read fenceが確定
- #355 value semanticsへ暗黙の数値尺度を追加しない
- Project #7 Statusは`In progress`
- exact-head deterministic CI PASS
- Design Reviewでblocking finding 0

以後Design -> Codeを維持する。

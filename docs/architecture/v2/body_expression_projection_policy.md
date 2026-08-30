# V2 Body Expression Projection Policy — Initial Yura Calibration

Owner: #337
Character source: #354 / #442 / `character_definitions/v2/yura.yaml`
Mechanism: #355 / `body_expression_contracts.md`
Design gate: #445 D10
Status: Canonical Production Policy Data / implementation-decidability correction

## 1. 目的

#337の`BodyExpressionProjectionPolicy`について、現行`yura.yaml definition_revision=1`のconfirmed Body Styleを、実装者が自然言語解釈して数値へ変換せずに`BodyExpressionAxis`へ投影できるinitial production policyを固定する。

Character本文の意味Authorityは#354/#442に残す。本書の数値は**projection calibration data**であり、新しい人物設定ではない。

Human Verificationで調整する場合、Character本文ではなく本policy revisionを進める。Core algorithmを変更しない。

## 2. Policy identity

```text
policy_id = yura.body-expression.v1
policy_revision = 1
character_id = yura
character_schema_version = 1
compatible_definition_revision = 1
```

Definition revisionが進み、exact confirmed valueが変わった場合はold ruleを意味近似で再利用しない。対応policy revisionを明示追加するまで`UNMAPPED_CHARACTER_STYLE`。

## 3. Normalized authoring levels

Codeへscatterしたmagic numberを作らないため、closed authoring levelを使う。

```text
NONE      = 0.00
SUBTLE    = 0.15
MILD      = 0.30
MODERATE  = 0.50
STRONG    = 0.70
```

axis contributionはsignを明示する。

Dynamic gainは倍率として:

```text
NEUTRAL_GAIN = 1.00
MILD_GAIN    = 1.10
MODERATE_GAIN = 1.20
```

とする。

## 4. D10 schema amendment for Character Style rules

`body_expression_contracts.md` Section 6.2の`CharacterStyleInfluenceRule`をproductionで次へ具体化する。

```text
CharacterStyleInfluenceRule
- rule_id
- facet_id
- confirmed_value                 # exact string
- axis_weights[]                  # static baseline contribution
- dynamic_gain_overrides[]        # optional
- disposition: APPLY | NO_BASELINE_ONLY_DYNAMIC | IGNORE_EXPLICITLY

BodyExpressionDynamicGainOverride
- axis
- gain: finite float in [0, 2]
```

Rules:

- `APPLY`: axis_weightsとgainを適用。
- `NO_BASELINE_ONLY_DYNAMIC`: axis_weightsは空でなければならず、gainだけを適用。
- `IGNORE_EXPLICITLY`: contribution/gainなし。当該confirmed facetを「未実装」と誤解しないための明示無視。
- 同一`facet_id + confirmed_value`はexactly one rule。
- unknown/unmapped confirmed valueをsubstring/embedding/LLMで近似しない。
- gainは**dynamic state contributionにだけ**掛け、Character baseline自身へ掛けない。
- 複数gain ruleが同一axisへ適用される場合、rule_id Unicode code-point ascのstable順で乗算し、productが`[0,2]`外ならpolicy invalid。runtime clamp禁止。

## 5. Current Yura Body Style exact bindings

### 5.1 motion_softness

Exact value:

```text
柔らかな軌道、timing、余韻を基調とする
```

Rule:

```text
rule_id = yura.motion_softness.v1
axis_weights:
  motion_softness: +MODERATE
  motion_continuity: +SUBTLE
disposition = APPLY
```

意味: static baselineは柔らかさを持つが、具体joint trajectory/solver algorithmは決めない。

### 5.2 continuity_tendency

Exact value:

```text
落ち着いている時も生命感のある繊細な動きを好む
```

Rule:

```text
rule_id = yura.continuity.v1
axis_weights:
  motion_continuity: +MODERATE
  idle_variation: +MILD
disposition = APPLY
```

`idle_variation`はrandom joint noiseを意味せず、#340 band-limited policyのintensity inputになる。

### 5.3 amplitude_tendency

Exact value:

```text
興味や感情が強い時は表現量が自然に増え得る
```

静的に常時大きく動く意味ではないためbaselineを置かない。

```text
rule_id = yura.amplitude_dynamic.v1
dynamic_gain_overrides:
  movement_amplitude: MILD_GAIN
  spatial_extent: MILD_GAIN
  gesture_density: MILD_GAIN
disposition = NO_BASELINE_ONLY_DYNAMIC
```

### 5.4 gaze_tendency

Exact value:

```text
興味や感情の強さに応じて視線の表現量が自然に変化し得る
```

```text
rule_id = yura.gaze_dynamic.v1
dynamic_gain_overrides:
  gaze_freedom: MILD_GAIN
disposition = NO_BASELINE_ONLY_DYNAMIC
```

Cognitive Focus強度を捏造せず、dynamic state ruleから既に得たgaze contributionだけをmodulateする。

### 5.5 head_expression_tendency

Exact value:

```text
興味や感情の強さに応じて頭の表現量が自然に変化し得る
```

```text
rule_id = yura.head_dynamic.v1
dynamic_gain_overrides:
  head_expressiveness: MILD_GAIN
disposition = NO_BASELINE_ONLY_DYNAMIC
```

### 5.6 posture_expression_tendency

Exact value:

```text
興味や感情の強さに応じて姿勢の表現量が自然に変化し得る
```

```text
rule_id = yura.posture_dynamic.v1
dynamic_gain_overrides:
  posture_expressiveness: MILD_GAIN
  torso_expressiveness: MILD_GAIN
disposition = NO_BASELINE_ONLY_DYNAMIC
```

### 5.7 symmetry_tendency

Exact value:

```text
可愛らしさは固定Poseではなく左右差を含むMotion Styleとして表し得る
```

左右差を許す軽いbaselineとして:

```text
rule_id = yura.symmetry.v1
axis_weights:
  symmetry: -SUBTLE
disposition = APPLY
```

これは左右非対称Pose presetを選ぶ規則ではない。

## 6. Initial generic dynamic state rules

Named Emotion→Motionの固定対応を避け、open-ended state familiesをcontinuous axisへ投影する。

### 6.1 ENERGY

```text
facet_kind = ENERGY
state_key = None
component = CURRENT
transform = SIGNED
target_scope = GLOBAL
axis_weights:
  movement_energy: +MODERATE
  movement_tempo: +MILD
  movement_amplitude: +MILD
  gesture_density: +SUBTLE
  breathing_tempo: +MILD
```

### 6.2 AROUSAL

```text
facet_kind = AROUSAL
state_key = None
component = CURRENT
transform = SIGNED
target_scope = GLOBAL
axis_weights:
  movement_energy: +MILD
  movement_tempo: +MILD
  posture_expressiveness: +MILD
  head_expressiveness: +MILD
  gesture_density: +MILD
  breathing_amplitude: +SUBTLE
  breathing_tempo: +MILD
```

### 6.3 EMOTION magnitude

Emotion種別を有限辞書へせず、「Emotionが強い」という共通量だけを使う。

```text
facet_kind = EMOTION
state_key = None
component = CURRENT
transform = MAGNITUDE
target_scope = GLOBAL
axis_weights:
  movement_amplitude: +MILD
  posture_expressiveness: +MILD
  head_expressiveness: +MILD
  gesture_density: +SUBTLE
```

これによりjoy/fear/anger等を同じPoseへするのではなく、**強い内的反応ほど表現量が増え得る**というCharacter設定だけを反映する。方向性/意味はExecutive/BodyIntent/他state ruleが所有する。

### 6.4 INTEREST foreground

Interestは対象付きfacetで、現在Focus対象に一致する場合だけgaze/head expressionへ寄与する。

```text
facet_kind = INTEREST
state_key = None
component = CURRENT
transform = POSITIVE_ONLY
target_scope = FOREGROUND
axis_weights:
  gaze_freedom: +MILD
  head_expressiveness: +SUBTLE
  posture_expressiveness: +SUBTLE
```

Focus ref文字列の意味解釈は禁止しexact identityだけを使う。

## 7. Composition

Initial production order:

```text
zero vector
→ Yura static baseline axis_weights
→ generic dynamic state contributions
→ applicable Yura dynamic gain overrides
→ validate finite
→ clamp final mathematical sum to [-1,1] as #337 canonical
→ attach categorical Focus constraints
```

Policy authoringのinvalid値をruntime final clampで隠さない。各weight/gainはload時にvalidateする。

Dynamic contribution:

```text
signal = transform(state_component) * confidence
raw_axis_dynamic = sum(signal * weight)
modulated_dynamic = raw_axis_dynamic * product(applicable gains)
axis = clamp(static_baseline + modulated_dynamic, -1, 1)
```

stable summation/rule orderingは#337 canonicalどおり。

## 8. Not mapped intentionally

現行`yura.yaml`にconfirmed valueが存在しないBody Style facet（例: `spatial_extent_tendency`が未定義の場合）について、値を補作しない。

`UNRESOLVED / NOT_CONFIGURED / absent`はCharacter baseline contributionなし。

## 9. Freshness

`BodyExpressionContext` provenanceへ:

- character_id/schema/definition revision
- BodyExpressionProjectionPolicy id/revision
- source InternalState revision
- Attention revision
- source_context_revision

を保持する。

Definition/policy revision変更後のold contextをcurrent Character styleとして再利用しない。multi-owner stable readは`snapshot_consistency_contracts.md`を使う。

## 10. Human Verification tuning boundary

Human Verificationで確認する:

- 常時大振りにならない
- calmでも完全静止しない
- strong emotion/interest時に表現量が自然に増える
-左右差が固定Pose化しない
- BodyIntent/physical constraintをCharacter baselineが上書きしない
- repeated frameでjitterを増幅しない

調整はpolicy values/revisionで行う。Characterの確定本文を数値調整のためだけに書き換えない。

## 11. Required tests

- current `yura.yaml` 7 confirmed Body facetsがexactly one ruleへbind
- changed wordingでold ruleがmatchしない
- no substring/LLM/embedding mapping
- dynamic-only facetsがbaselineを作らない
- ENERGY/AROUSAL/EMOTION/foreground INTEREST deterministic contribution
- named Emotionによるfixed Pose/Motion lookupなし
- gain product/order deterministic
- unknown state key hidden mappingなし
- policy/definition revision stale reject
- policy load invalid weights/gains reject
- same inputs same context

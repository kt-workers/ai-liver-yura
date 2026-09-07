# V2 Avatar Binding / Numerical Contracts

Owner: #346
Related: `avatar_presentation_contracts.md`, `body_architecture.md`, `body_physical_numeric_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

`AvatarModelBinding.transform_mapping / scale_mapping / channel mapping`を、renderer Adapterがbone名・軸・scale・parameter rangeから推測せず実装できるclosed/versioned data contractとして定義する。

Canonical Body座標のAuthorityはBodyのまま維持する。

Canonical frame:
- right-handed
- +X anatomical right
- +Y up
- +Z forward
- world/root position unit meter
- orientation unit quaternion `(x,y,z,w)`

Avatar mappingはpresentation-only derived projectionであり、renderer値からBodyStateを書き戻さない。

## 2. Binding generation

`AvatarModelBinding`は次を追加で必須とする。

```text
- renderer_generation
- canonical_body_model_revision
- canonical_body_model_fingerprint
- coordinate_mapping: AvatarCoordinateMapping
```

frame適用時にbody model ID/revision/fingerprint、binding revision、renderer generationを全て一致確認する。

## 3. AvatarCoordinateMapping

```text
AvatarCoordinateMapping
- mapping_id
- mapping_revision: non-negative int
- renderer_handedness: RIGHT_HANDED | LEFT_HANDED
- canonical_to_renderer_basis: Matrix3x3
- meters_to_renderer_units: finite float > 0
- root_translation_offset_renderer: Vector3
- quaternion_output_order: XYZW | WXYZ
```

### 3.1 Basis matrix

`canonical_to_renderer_basis`はcanonical vectorをrenderer vectorへ変換する3x3 matrix `B`。

```text
v_renderer = meters_to_renderer_units * B * v_canonical
```

Requirements:

- 全要素finite。
- 各columnはunit vector `1 ± 1e-9`。
- column間dot product absolute <= `1e-9`。
- `|det(B)| = 1 ± 1e-9`。
- renderer_handedness=RIGHT_HANDEDなら`det(B) > 0`。
- LEFT_HANDEDなら`det(B) < 0`を許可する。
- axis名/bone名からBを自動推測しない。

root world position:

```text
p_renderer =
  root_translation_offset_renderer
  + meters_to_renderer_units * B * p_canonical_world_m
```

## 4. Rotation mapping

Canonical rotation matrix `R_c`からrenderer rotationはbasis conjugationで得る。

```text
R_r = B * R_c * inverse(B)
```

- `B`がreflectionを含むLEFT_HANDED mappingでも上式を使う。
- `R_r`をrenderer quaternionへ変換し、bindingの`quaternion_output_order`で並べる。
- qと-qは同じrotation。
- Euler角への暗黙変換をcanonical mappingにしない。
- rendererがEuler parameterしか持たない場合はjoint/channel binding内に明示`EulerProjectionRule`を持つ。rotation orderを必須指定する。

```text
EulerProjectionRule
- order: XYZ | XZY | YXZ | YZX | ZXY | ZYX
- units: RADIANS | DEGREES
- wrap_policy: NEAREST_CONTINUOUS
```

`NEAREST_CONTINUOUS`は前frameのrenderer angle vectorに対し同値表現のうちEuclidean angular distanceが最小の表現を選び、不連続な±2π jumpを避ける。gimbal singularityを含む同値候補で一意に決められない場合はtyped degradationとし、別branchを任意選択しない。

## 5. Joint transform binding

```text
AvatarJointBinding
- canonical_joint_id
- renderer_target_ref
- translation_mode: NONE | LOCAL_POSITION | WORLD_POSITION
- rotation_mode: NONE | LOCAL_QUATERNION | WORLD_QUATERNION | EULER_PARAMETERS
- translation_scale: optional finite positive Vector3
- translation_offset: optional Vector3
- rotation_pre: optional unit Quaternion
- rotation_post: optional unit Quaternion
- euler_projection?: EulerProjectionRule
- supported_axes[]
```

Translation:

```text
base = B * canonical_position_m * meters_to_renderer_units
mapped = componentwise(base, translation_scale or [1,1,1])
       + (translation_offset or [0,0,0])
```

Rotation:

```text
Qmapped = rotation_pre * Qbasis_mapped * rotation_post
```

all quaternions normalize to unit length before output. norm `<=1e-12`はinvalid。

Rules:

- unsupported canonical axisを0へsilent projectionして`APPLIED`にしない。degraded itemへ記録する。
- renderer rest-pose correctionは`rotation_pre/post` dataに明示し、joint名から推測しない。
- scale/offsetがmissingならidentity mappingだけを意味する。renderer-specific empirical constantをcodeに埋め込まない。

## 6. Channel mapping

Canonical realtime channelはnormalized scalar rangeをowner contractどおり受ける。

```text
AvatarChannelBinding
- canonical_channel
- renderer_target_ref
- input_min
- input_neutral
- input_max
- output_min
- output_neutral
- output_max
- monotonicity: INCREASING | DECREASING
- missing_behavior: DROP_DEGRADED | FAIL_BINDING
```

mappingは`input_neutral`を保つpiecewise linearとする。

For `x <= input_neutral`:

```text
t = (x - input_min) / (input_neutral - input_min)
y = output_min + t * (output_neutral - output_min)
```

For `x > input_neutral`:

```text
t = (x - input_neutral) / (input_max - input_neutral)
y = output_neutral + t * (output_max - output_neutral)
```

- input range外をsilent clampしない。
- denominator 0を許可しない。
- monotonicityに合わないoutput endpointsをpolicy validationでreject。
- unknown channelをrenderer target文字列の近似でbindしない。

## 7. Mirror policy

`mirror_policy`はpresentation transformだけに適用する。

```text
NONE
DISPLAY_REFLECT_X
```

`DISPLAY_REFLECT_X`は最終renderer presentation座標でX reflectionを追加する。Canonical anatomical joint IDやBodyStateを左右入替しない。

bindingの`canonical_to_renderer_basis`とdisplay mirrorを二重適用してhandednessを偶然合わせない。mirrorは明示別stageとしてtraceする。

## 8. Update-rate / frame coalescing policy

```text
AvatarPresentationPolicy
- policy_id
- policy_revision
- queue_capacity: int >= 1
- latest_frame_coalescing: bool
- max_output_rate_hz?: finite float > 0
- stale_frame_age_seconds: finite float >= 0
```

- renderer capability `max_update_rate`が存在する場合、effective output rateはpolicyとcapabilityの小さい方。
- frame ageは`presentation_now_absolute - frame.observed_at_absolute`。
- `age > stale_frame_age_seconds`でDROPPED_STALE。等値は期限内。
- latest-frame coalescing時もbinding generation違いframeをまとめない。
- queue pressureでBody producerをawaitさせない。

## 9. Failure / degradation

closed reasonへ少なくとも追加:

```text
BODY_MODEL_BINDING_MISMATCH
INVALID_COORDINATE_MAPPING
UNSUPPORTED_JOINT_AXIS
UNSUPPORTED_CHANNEL
EULER_PROJECTION_AMBIGUOUS
STALE_FRAME
RENDERER_GENERATION_CHANGED
```

missing renderer mappingを「近いparameterへ適用成功」としない。

## 10. Required tests

- canonical X/Y/Z basis identity mapping
- right→left handed explicit reflection mapping
- meter→renderer unit scale
- basis conjugation quaternion rotation
- q/-q equivalence
- rest correction pre/post
- explicit Euler order / continuity / ambiguity degradation
- channel -/neutral/+ endpoint exact mapping
- out-of-range no clamp
- anatomical left/right preserved under display mirror
- stale age equality boundary
- binding/body model/generation mismatch reject
- slow renderer latest-frame coalescingでBody producer nonblocking

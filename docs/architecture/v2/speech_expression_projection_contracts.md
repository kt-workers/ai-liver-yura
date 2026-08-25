# V2 Speech Expression / Performance Projection Contracts

Owner Issue: #331
Upstream: #327 / #328 / #333 / #355
Related: `speech_performance_contracts.md` / #445
Status: Canonical Supplement / Cross-Design Audit Resolution

## 1. Purpose

本書は、#327のdynamic Internal Stateと#355 `CharacterVoiceStyleProfile`を、#331のnormalized `SpeechExpressionContext` / `SpeechPerformancePlan`へ**暗黙の自然言語解釈なしに**投影するversioned policy契約を定義する。

```text
InternalStateSnapshot
+ Attention/Turn typed view
+ CharacterVoiceStyleProfile
+ SpeechPerformanceProjectionPolicy
→ SpeechExpressionContext
→ SpeechPerformancePlan
```

`Emotion名 -> Voice preset`の固定1対1辞書は正規方式にしない。一方で、どのsourceがどのperformance axisへ寄与し得るかを実装者の推測にも委ねない。

---

## 2. Authority boundary

- #327 owns current Emotion / Desire / Drive / Motivation / Relationship / Energy / Arousal.
- #333 owns current Focus/Turn.
- #355 owns static Character Voice Style values.
- #331 policy owns only **performance projection semantics**.
- #331 does not alter current state or Character Definition.
- #358 owns provider-specific mapping.

Projection policy is configuration/behavior design, not Character fact authority.

---

## 3. Policy identity

```text
SpeechPerformanceProjectionPolicy
- policy_id
- policy_revision
- compatible_character_schema_versions[]
- character_style_rules[]
- state_rules[]
- expression_to_performance_rules[]
- linguistic_rules
- constraint_rules[]
- neutral_fallback_policy
```

The policy object is immutable/versioned.

A policy revision change is observable and invalidates cached projection results that bind the older revision.

No hidden Python dictionary may supply additional mappings outside this policy.

---

## 4. Character Voice Style binding

#355 profile values are human-readable strings. #331 must not parse words such as「柔らかい」「落ち着いた」by substring/embedding/LLM.

```text
CharacterVoiceStyleInfluenceRule
- rule_id
- character_id?
- facet_id
- expected_confirmed_value
- baseline_delta: PerformanceIntentDelta
- expression_gain_overrides[]
- disposition
```

`expected_confirmed_value` is exact match to the confirmed profile value.

`disposition`:

```text
APPLY
NO_BASELINE_ONLY_DYNAMIC
IGNORE_EXPLICITLY
```

If a confirmed facet changes value and no exact rule matches:
- do not guess new meaning;
- report `UNMAPPED_CHARACTER_VOICE_STYLE`;
- either use explicitly allowed system-neutral fallback or fail the Character-specific projection according to policy.

---

## 5. Current Yura voice policy semantics

For `character_id=yura`, `definition_revision=1`, current confirmed voice facets are bound as follows conceptually.

### baseline_softness

Value: `柔らかく親しみがある`

Design meaning:
- establishes a moderate positive baseline on `softness`;
- establishes a mild negative baseline on `tension`;
- does not force fixed pitch/speed.

### calmness_tendency

Value: `比較的落ち着いた基調`

Design meaning:
- mild slower pacing bias;
- mild lower energy baseline;
- mild lower tension / pitch-range baseline;
- does not prevent strong current state from overriding/modulating the baseline.

### emotional_expressiveness_tendency

Value: `EmotionやSituationに応じて相対的に変化し、喜びや驚きが強い時は普段より素直に表出が増え得る`

Design meaning:
- **no fixed emotion output baseline**;
- increases permitted dynamic modulation gain for `expressiveness` and related axes;
- does not map `joy -> high pitch`, `surprise -> loud`, etc.

### energy_tendency

Value: `常時高energyで押さず、現在のEmotionやSituationに応じて自然に変化する`

Design meaning:
- no positive constant energy baseline;
- keeps dynamic `Energy/Arousal` contribution active;
- prevents a Character-static rule from forcing consistently high energy.

These semantics are projection behavior, not new Character biography/facts.

---

## 6. Normalized influence levels

To avoid arbitrary numeric literals scattered through code, policy authoring may use closed normalized influence levels.

```text
NONE      = 0.00
SUBTLE    = 0.15
MILD      = 0.30
MODERATE  = 0.50
STRONG    = 0.70
```

Sign is explicit per axis.

Initial Yura baseline authoring uses:

```text
baseline_softness:
  softness: +MODERATE
  tension:  -MILD

calmness_tendency:
  pace:        -SUBTLE
  energy:      -SUBTLE
  tension:     -MILD
  pitch_range: -SUBTLE

emotional_expressiveness_tendency:
  baseline: none
  expressiveness dynamic gain: 1.15
  energy dynamic gain:          1.10

energy_tendency:
  baseline: none
  energy dynamic gain: 1.00
```

These are initial calibration values and must remain policy data. Human Verification may tune them by changing policy revision without changing Core algorithm or Character Definition.

---

## 7. Dynamic Internal State rules

```text
SpeechStateInfluenceRule
- rule_id
- facet_kind
- state_key?
- target_scope
- component
- transform
- expression_axis_weights[]
```

`component`:
- CURRENT
- DELTA

`transform`:
- SIGNED
- MAGNITUDE
- POSITIVE_ONLY
- NEGATIVE_MAGNITUDE

Contribution is multiplied by source confidence.

Unknown state keys have no hidden interpretation.

### Initial generic dynamic rules

Initial system-level rules rely on standardized `ENERGY` and `AROUSAL` families rather than enumerating every emotion.

```text
ENERGY current SIGNED
→ energy +MODERATE
→ pacing_bias +MILD
→ expressiveness +SUBTLE

AROUSAL current SIGNED
→ activation +MODERATE
→ energy +MILD
→ pacing_bias +MILD
→ tension +MILD
→ expressiveness +MILD
```

This makes current state audible without encoding every named Emotion as a fixed voice preset.

Emotion-specific continuous rules may be added later only as explicit policy data with tests/Human Verification. They never become hidden code branches.

---

## 8. Targeted state / relationship rules

Target-specific Relationship/Interest state may affect speech performance only when an explicit rule declares a target scope.

Allowed scopes:

```text
GLOBAL
TURN_OWNER
FOREGROUND_FOCUS
SPEECH_TARGET
```

The target identity comes from trusted typed views; #331 does not match names/free text.

No default rule assumes Relationship closeness means louder/softer/etc.

---

## 9. Expression-to-performance mapping

`SpeechExpressionContext` and `PerformanceIntentVector` are distinct normalized spaces.

Mapping is explicit:

```text
ExpressionPerformanceRule
- expression_axis
- performance_axis_weights[]
```

Initial structural mapping:

```text
activation     → energy +, pitch_range +, pace +
energy         → energy +, loudness +small, pace +small
softness       → softness +, tension -small
warmth         → softness +small, expressiveness +small
 tension       → tension +, softness -small
expressiveness → expressiveness +, pitch_range +small
pacing_bias    → pace +
emphasis_bias  → segment emphasis gain +
```

Actual magnitudes are versioned policy levels; code does not infer these relationships from axis names.

All output is clamped to normalized domain after deterministic composition. Silent clamp of invalid policy definitions is forbidden; invalid policy fails validation before use.

---

## 10. Linguistic structure rules

#330 already owns linguistic `boundary_after / emphasis / hesitation`.

#331 mapping must be explicit and monotonic rather than provider-specific.

```text
LinguisticPerformancePolicy
- continue_boundary_min
- phrase_boundary_min
- sentence_boundary_min
- emphasized_min_strength
- deemphasized_max_strength
- hesitant_min_strength
```

Invariants:
- SENTENCE boundary strength >= PHRASE >= CONTINUE.
- EMPHASIZED cannot become weaker than neutral minimum.
- DEEMPHASIZED cannot become stronger than emphasized.
- HESITANT cannot add text/filler words.
- values remain relative normalized intents, not milliseconds/Hz/dB.

---

## 11. Constraint rules

`SpeechPerformanceConstraintView.kind/value` is not free text to interpret arbitrarily.

```text
SpeechPerformanceConstraintRule
- kind
- accepted_typed_value_schema
- affected_axes[]
- combination_mode
```

Unknown constraint kind/value fails closed or is explicitly ignored according to its owner contract; no substring matching.

Safety/accessibility hard bounds take precedence over Character/style soft preferences, but they never rewrite text semantics.

---

## 12. Stable multi-owner read

Projection snapshot requires a coherent set of:
- source_context_revision
- InternalState revision
- Attention/Turn revision where used
- Character definition revision
- projection policy revision

Do not hold a Core-global lock across reads.

Use a version-stabilized composite read or owner snapshot fence equivalent to #337.

If a coherent set cannot be established, return typed projection unavailable/stale rather than mixing generations.

---

## 13. Composition order

Deterministic conceptual order:

```text
system neutral vector
→ Character baseline deltas
→ dynamic state expression projection
→ Character dynamic gain modulation
→ typed situation/performance constraints
→ linguistic segment constraints
→ validate normalized result
```

Order is part of policy semantics.

No stage mutates CharacterUtterance text.

---

## 14. Degradation

- Character style rule missing: `UNMAPPED_CHARACTER_VOICE_STYLE`.
- policy invalid: `INVALID_PERFORMANCE_PROJECTION_POLICY`.
- stable state read unavailable: `EXPRESSION_CONTEXT_UNAVAILABLE`.
- optional unknown state facet: no contribution + diagnostic, not guessed mapping.
- Character unavailable: only explicitly permitted system-neutral performance; marked degraded.

System-neutral fallback is not Yura Character style and must be observable.

---

## 15. Required tests

- exact Character value match; changed wording does not silently retain old mapping
- no substring/embedding/LLM interpretation of Voice Style
- Yura baseline softness/calmness rules
- expressive/energy facets alter modulation gain rather than fixed output
- Energy/Arousal generic dynamic modulation
- unknown Emotion/state key no hidden voice preset
- multi-axis deterministic composition
- policy revision changes output/provenance
- stable multi-owner read race
- invalid policy values rejected
- linguistic monotonic invariants
- unknown performance constraint no free-text interpretation
- no text mutation/provider-specific values

---

## 16. #445 Gate

This supplement resolves the D8 gap where `SpeechExpressionContext` mapping could otherwise be implementation-defined.

Implementation remains frozen until final #445 Gate PASS.

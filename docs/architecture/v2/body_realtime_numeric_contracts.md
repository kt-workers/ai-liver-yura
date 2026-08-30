# V2 Body Realtime Numerical Contracts

Owner: #340
Upstream: #336 / #337 / #339 / #358
Related: `body_realtime_layers_contracts.md`, `body_physical_numeric_contracts.md`, `snapshot_consistency_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

Gaze / Blink / Breathing / Viseme / subtle motion / expression parameter transitionの更新式、時間単位、rate limit、seeded variationを固定し、#340実装者が「自然そうな値」を任意に発明しないようにする。

#339がfinal physical constraint/BodyState commit Authorityであることは変更しない。

## 2. Time / strict numeric rules

- 全durationはseconds、angular値はradians、angular rateはrad/s、accelerationはrad/s²。
- realtime integrationはinjectable monotonic clockの`elapsed_seconds`を使う。
- `elapsed_seconds`はfiniteかつ`>=0`。
- bool、NaN、±Infinityをnumberとして受理しない。
- scheduler遅延時もactual elapsedを1回だけ積分し、missed tick数ぶんloop replayしない。

## 3. BodyRealtimePolicy

```text
BodyRealtimePolicy
- policy_id
- policy_revision: non-negative int
- target_rate_hz: finite float > 0
- max_elapsed_seconds_per_tick: finite float > 0
- gaze: GazeRealtimePolicy
- blink: BlinkRealtimePolicy
- breathing: BreathingRealtimePolicy
- articulation: ArticulationRealtimePolicy
- subtle_motion: SubtleMotionPolicy
- expression_transition: ExpressionTransitionPolicy
```

Initial V2 baseline:

```text
target_rate_hz = 60
max_elapsed_seconds_per_tick = 0.100
```

`max_elapsed_seconds_per_tick`はclock timeを偽るclampではない。actual elapsedが上限を超えた場合、そのtickでlarge-step integrationを行わず`REALTIME_GAP_TOO_LARGE` degradationとしてstateful layerをsafe resynchronizeし、#339へsnap poseを提案しない。

## 4. Common one-frame bounded transition

normalized scalar channel `x`をtarget `t`へ近づける標準更新:

```text
delta_desired = t - x
delta_by_rate = clamp(delta_desired,
                      -max_rate_per_second * dt,
                      +max_rate_per_second * dt)
delta = clamp(delta_by_rate,
              -max_displacement_per_frame,
              +max_displacement_per_frame)
x_next = x + delta
```

- `dt=0`ならno change。
- `max_rate_per_second > 0`。
- `max_displacement_per_frame > 0`。
- target到達時overshootしない。
- slow tickでもper-frame capがsnapを防ぐ。
- fast tickでもelapsed比例rateを超えない。

同じ規則をexpression parameter / articulation degradation fade等へ使う場合、各policyがrate/frame capを明示する。

## 5. Gaze policy

```text
GazeRealtimePolicy
- deadband_radians: finite >= 0
- max_angular_velocity_radps: finite > 0
- max_angular_acceleration_radps2: finite > 0
- max_angular_displacement_per_frame: finite > 0
- release_to_forward_rate_radps: finite > 0
```

Initial baseline:

```text
deadband_radians = 0.008726646259971648       # 0.5 deg
max_angular_velocity_radps = 2.0943951023931953 # 120 deg/s
max_angular_acceleration_radps2 = 8.377580409572781 # 480 deg/s²
max_angular_displacement_per_frame = 0.05235987755982989 # 3 deg
release_to_forward_rate_radps = 0.5235987755982988 # 30 deg/s
```

### 5.1 Canonical update

State:

```text
current_direction: unit Vector3
angular_velocity_radps >= 0
```

Target unit directionとのshortest angular error:

```text
error = acos(clamp_for_numeric_dot(dot(current, target), -1, 1))
```

`clamp_for_numeric_dot`はunit-vector floating error専用で、semantic targetをrange correctionするものではない。

- `error <= deadband`: desired_velocity=0。
- otherwise `desired_velocity=min(max_velocity, error/dt)` (`dt=0`なら0)。
- velocityは`max_acceleration * dt`以内でdesiredへ近づける。
- proposed_angle=`min(error, velocity_next * dt)`。
- actual step angle=`min(proposed_angle, max_angular_displacement_per_frame)`。
- current→target shortest great-circle interpolationでstepする。

Target lost時はcurrent targetを瞬間的canonical forwardへsnapせず、`release_to_forward_rate_radps`上限でBody/current planned gaze-compatible neutral directionへ戻す。high-level focus targetを#340が作らない。

## 6. Blink policy / deterministic variation

```text
BlinkRealtimePolicy
- base_interval_seconds: finite > 0
- interval_variation_fraction: finite in [0,1)
- closing_seconds: finite > 0
- closed_seconds: finite >= 0
- opening_seconds: finite > 0
- min_open_interval_seconds: finite >= 0
- seed: unsigned 64-bit int
```

Initial baseline:

```text
base_interval_seconds = 4.5
interval_variation_fraction = 0.35
closing_seconds = 0.090
closed_seconds = 0.045
opening_seconds = 0.120
min_open_interval_seconds = 0.750
seed = 0x595552415F5632
```

### 6.1 PRNG

ReproducibilityのためBlink interval variationはxorshift64*をcanonicalとする。

For nonzero uint64 state `x`:

```text
x ^= x >> 12
x ^= x << 25   (uint64 wrap)
x ^= x >> 27
output = x * 2685821657736338717 (uint64 wrap)
u = output / 2**64
```

seed=0はinvalid。

Interval:

```text
signed = 2*u - 1
interval = base_interval_seconds * (1 + interval_variation_fraction * signed)
interval = max(interval, min_open_interval_seconds)
```

各completed blink後にexactly one PRNG sampleを消費してnext eligibilityを決める。frameごとにrandom sampleを消費しない。

### 6.2 Eyelid trajectory

- OPEN→CLOSING: openness `1→0` smoothstep `s(t)=3t²-2t³`。
- CLOSED: 0。
- OPENING: openness `0→1` smoothstep。
- phase progressはactual elapsed/duration。
- late tickでphaseを複数回loop/replayしない。elapsedでcurrent phase位置を直接評価し、one-frame channel displacementはarticulationとは別のeyelid physical/output policy上限を#339が再検証する。

## 7. Breathing policy

```text
BreathingRealtimePolicy
- baseline_breaths_per_minute: finite > 0
- min_breaths_per_minute: finite > 0
- max_breaths_per_minute: finite >= min
- baseline_amplitude: finite in [0,1]
- min_amplitude: finite in [0,1]
- max_amplitude: finite in [min,1]
- tempo_axis_gain: finite >= 0
- amplitude_axis_gain: finite >= 0
- parameter_rate_per_second: finite > 0
- parameter_max_displacement_per_frame: finite > 0
```

Initial baseline:

```text
baseline_breaths_per_minute = 14
min_breaths_per_minute = 8
max_breaths_per_minute = 24
baseline_amplitude = 0.35
min_amplitude = 0.15
max_amplitude = 0.70
tempo_axis_gain = 6.0
amplitude_axis_gain = 0.20
parameter_rate_per_second = 0.50
parameter_max_displacement_per_frame = 0.05
```

Expression axes `breathing_tempo`, `breathing_amplitude` are `[-1,1]`.

```text
target_bpm = clamp(baseline_bpm + breathing_tempo * tempo_axis_gain,
                   min_bpm, max_bpm)
target_amp = clamp(baseline_amp + breathing_amplitude * amplitude_axis_gain,
                   min_amp, max_amp)
```

これらのclampは**明示policy formula**でありinvalid inputのsilent clampではない。input axis範囲外はreject。

current bpm/amplitudeはSection 4 rate-limited transitionでtargetへ追従。

phase:

```text
phase_next = (phase + dt * current_bpm / 60.0) mod 1.0
breath_wave = 0.5 - 0.5*cos(2*pi*phase_next)
channel_amplitude = current_amp * breath_wave
```

plan/expression revisionでphaseをresetしない。

## 8. Articulation policy

```text
ArticulationRealtimePolicy
- attack_rate_per_second: finite > 0
- release_rate_per_second: finite > 0
- max_channel_displacement_per_frame: finite > 0
- gap_release_seconds: finite >= 0
- symbol_targets: exact closed mapping
```

Initial baseline:

```text
attack_rate_per_second = 8.0
release_rate_per_second = 10.0
max_channel_displacement_per_frame = 0.20
gap_release_seconds = 0.060
```

`symbol_targets` maps canonical `VISEME/PHONEME/MORA` normalized symbols to:

```text
mouth_openness [0,1]
mouth_roundness [-1,1]
jaw_openness [0,1]
lip_closure [0,1]
```

Mapping is versioned policy data。symbol stringから母音等をsubstring推測しない。

Current timing unitのtargetへattack rate、unit gap/end/unsupported/degradation時はneutral targetへrelease rateを使い、Section 4のper-frame capを常に適用する。

Timing unitがtick間で既に終了していても、future unitsをcatch-up animationとして逐次再生しない。actual presentation timeに該当するunitを1件選び、そのtargetへbounded transitionする。

## 9. Expression transition policy

```text
ExpressionTransitionPolicy
- normalized_axis_rate_per_second: finite > 0
- normalized_axis_max_displacement_per_frame: finite > 0
```

Initial baseline:

```text
normalized_axis_rate_per_second = 1.5
normalized_axis_max_displacement_per_frame = 0.08
```

#337 context revision変更時、breath/subtle/gaze parameter sourceはnew axisへSection 4で追従する。blink mid-cycleやbreath phaseをresetしない。

## 10. Subtle motion policy

White noiseを避けるため、initial canonical subtle motionはseeded band-limited oscillator bankとする。

```text
SubtleMotionPolicy
- seed: nonzero uint64
- oscillator_rules[]
- max_normalized_intensity: finite in [0,1]
- intensity_rate_per_second: finite > 0
- intensity_max_displacement_per_frame: finite > 0

SubtleOscillatorRule
- oscillator_id
- target_joint_or_channel
- axis
- frequency_hz: finite > 0
- amplitude_radians_or_normalized: finite >= 0
- phase_offset_fraction: finite in [0,1)
```

Initial generic frequency band must satisfy:

```text
0.05 <= frequency_hz <= 0.60
```

Actual oscillator set/amplitudes are Body policy data bound to model capabilities; joint名から自動生成しない。

Phase:

```text
phase = (elapsed_from_layer_generation * frequency_hz + phase_offset_fraction) mod 1
value = amplitude * sin(2*pi*phase)
```

Seedはpolicy authoring時にphase offsetsを生成するためだけに使用し、framewise random noiseを足さない。runtime oscillatorはpure time function。

`subtle_motion_permitted=false`ならtarget intensity=0。new sway proposalを即時停止し、保持値のresidualを#339へ新規提案しない。再許可時はintensityをSection 4方式で0から上げる。

## 11. Gaps / scheduler pause handling

`dt > max_elapsed_seconds_per_tick`:

- blink/breath phaseはabsolute elapsedからcurrent physiological phaseを再評価してよいが、joint/channel outputをtargetへsnapしない。
- gaze/articulation/subtle parameterはprevious outputからone-frame boundを守る。
- `REALTIME_GAP_TOO_LARGE`をlayer statusへ記録。
- missed intermediate framesを生成/queueしない。

## 12. Policy/model freshness

Realtime overlay bundleは:

- based_on_body_state_revision
- BodyRealtimePolicy id/revision
- relevant #337/#333/#358 source revision

をbindする。

policy revision変更時はlayer generationを進める。old overlay bundleをnew policy generationへ適用しない。

## 13. Required tests

### Gaze
- deadband equality
- velocity/acceleration/per-frame displacement bound
- delayed tickでもsnapなし
- target release bounded

### Blink
- xorshift64* deterministic sequence
- interval min/max bound
- exact phase durations/smoothstep
- no per-frame random sample

### Breath
- 60sでBPMどおりcycle count
- expression target mapping
- phase continuity across revision
- delayed tick no replay burst

### Articulation
- attack/release rate + per-frame cap
- unsupported/timing gap fade
- delayed tick skips expired units rather thanreplay
- all channels range-safe

### Subtle motion
- frequency band validation
- identical seed/policy/time yields identical output
- no white-noise per-frame randomness
- permission false => no new sway

### Cross-layer
- one failed layer does not stop others
- policy revision fence
- #339 remains final hard-limit/body-state writer

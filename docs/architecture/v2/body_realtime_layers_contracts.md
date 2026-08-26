# V2 Body Realtime Layers Contracts

Owner Issue: #340
Parent: #335
Upstream: #333, #336, #337, #339, #358
Downstream: #339 final frame composer, #341 Integration, #346 Avatar
Related:
- `docs/architecture/v2/body_architecture.md`
- `docs/architecture/v2/body_expression_contracts.md`
- `docs/architecture/v2/body_solver_controller_contracts.md`
- `docs/architecture/v2/tts_provider_contracts.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#340はMotion Planner/LLM更新周期とは独立して、**視線・瞬き・呼吸・Viseme・微動・小さな姿勢補正**を高頻度に生成するBody realtime layerである。

#340自身はCanonical BodyStateを書き換えない。

```text
previous committed BodyState
+ BodyExpressionContext
+ typed gaze target
+ committed Speech timing/audio activity
+ realtime clock
        ↓
#340 Realtime Layers
        ↓
RealtimeOverlayBundle
        ↓
#339 final physical composition / limits / BodyState commit
```

これによりBodyStateの書込みAuthorityを#339に一本化しつつ、#340は高頻度挙動を独立更新できる。

---

## 2. Authority boundary

### #340 owns

- realtime layer local state machines
- low-latency gaze tracking / micro-adjustment
- blink scheduling/state
- breathing phase/state
- speech viseme/articulation overlay generation
- subtle smooth spontaneous motion
- small posture/balance-assist hint generation within bounded overlay authority
- realtime overlay composition ordering inside #340
- layer degradation status

### #340 does not own

- cognitive Focus selection (#333)
- BodyExpression semantic projection (#337)
- high-level Motion goal/planning (#338)
- IK/FK/hard joint safety/final state commit (#339)
- Speech generation/performance/TTS synthesis (#330/#331/#358)
- renderer parameters (#346)

---

## 3. RealtimeOverlayBundle

```text
RealtimeOverlayBundle
- overlay_bundle_id
- based_on_body_state_revision
- expression_revision?
- attention_revision?
- speech_presentation_id?
- generated_at
- joint_overlays[]
- channel_overlays[]
- layer_status[]
```

Each overlay is immutable and bounded.

```text
JointOverlay
- overlay_id
- layer
- joint_id
- mode: ADDITIVE_ROTATION | TARGET_BIAS
- value
- strength
- priority
```

```text
ChannelOverlay
- overlay_id
- layer
- channel
- value
- strength
- quality
```

Canonical channels may include:
- gaze direction
- eyelid openness
- mouth openness
- mouth roundness
- lip spread
- jaw bias
- breath phase/amplitude

Renderer-specific parameter names never enter this contract.

---

## 4. Single BodyState writer

#340 reads previous committed BodyState and emits overlays only.

#339:
1. computes base trajectory pose
2. consumes latest compatible RealtimeOverlayBundle
3. applies/conflict-resolves overlays
4. rechecks hard limits/balance/safety
5. commits final next BodyState/BodyPoseFrame

#340 never races #339 by independently mutating joint pose.

If an overlay is stale relative to current body revision beyond policy tolerance, #339 may discard/recompute it.

---

## 5. Realtime cadence

Realtime layer cadence is configuration/capability based, not tied to renderer FPS.

Requirements:
- monotonic clock
- bounded target interval
- late tick handling without catch-up burst explosion
- layer computations bounded enough for realtime lane
- renderer slowdown does not dictate canonical Body tick

If a tick is late:
- compute from actual elapsed time
- do not execute N hidden catch-up animation steps that create visible jump/jitter

---

## 6. Gaze input boundary

Cognitive Focus Authority is #333.

#340 consumes a typed `BodyGazeTargetView` produced by a trusted projection/perception boundary.

```text
BodyGazeTargetView
- target_ref
- spatial_direction_or_point?
- source_attention_revision
- source_owner
- confidence
- observed_at
```

Rules:
- #340 does not turn arbitrary `foreground_focus_ref` strings into coordinates by guessing.
- if spatial target is unavailable, semantic Focus can remain cognitively valid while Body gaze degrades/holds current behavior.
- eye/head/body allocation beyond low-level gaze overlay is coordinated with #339 planned orientation constraints.

---

## 7. Gaze tracking

Realtime gaze handles:
- small target motion tracking
- eye-leading micro-adjustment
- smooth target acquisition/release
- bounded natural fixation variation

It does not own large full-body orientation intent.

When target requires motion beyond eye/head realtime comfortable allowance:
- realtime gaze saturates safely
- a high-level BodyIntent/Plan may separately orient head/torso
- #340 does not create a new conscious BodyIntent itself

No uncontrolled target-chasing oscillation.

---

## 8. Gaze smoothing

Use bounded smooth dynamics rather than framewise direct snap.

Canonical behavior requirements:
- maximum angular velocity/acceleration
- deadband/hysteresis where needed
- low-pass/spring-like convergence
- target revision changes retarget continuously

Exact numerical algorithm is implementation choice if deterministic tests satisfy response/overshoot/jitter tolerances.

---

## 9. Blink state machine

Blink is a realtime physiological-style layer, not a fixed animation preset library.

State:

```text
OPEN
CLOSING
CLOSED
OPENING
```

`BlinkState` tracks:
- phase
- phase progress
- next eligibility time
- last blink time

Scheduling uses:
- bounded base interval policy
- BodyExpressionContext influence if explicitly mapped
- recent blink state
- speech/gaze constraints only where typed

Do not use raw Emotion names to select `BLINK_PRESET_X`.

For deterministic tests, pseudo-random variation is seedable/reproducible. Production variation is bounded, not white-noise per frame.

---

## 10. Breathing

Breathing is a continuous oscillator/stateful dynamic, not periodic full-body preset playback.

Inputs:
- previous breath phase
- elapsed time
- #337 `breathing_amplitude`
- #337 `breathing_tempo`
- physical activity constraint if a future trusted typed view provides one

Outputs:
- canonical breath phase/amplitude channel
- small torso/root/joint bias where permitted

Rules:
- smooth phase continuity
- no reset at plan boundary
- no sudden amplitude jump on expression revision; interpolate
- full-body motion remains active concurrently

---

## 11. Speech / viseme admission

Only **actually committed/started Presentation** may activate speech-mouth realtime.

Required binding:

```text
SpeechPresentationStarted
- presentation_id
- audio_artifact_id?
- timing_track_id?
- actual_start_time
- realtime monotonic start reference
```

Prepared/speculative Speech does not move the mouth.

Presentation interruption/completion stops or transitions the speech-mouth layer according to actual report/timing.

---

## 12. Viseme/articulation input

#358 provides provider-independent `SpeechTimingTrack` when available.

`PHONEME` は#358から渡るtrustedな汎用日本語phonemeのclosed setを用いる。#340は母音を
`A/I/U/E/O`、両唇閉鎖を`M`、それ以外の対応子音を中立の子音channelへ正規化する。raw provider
IDやrenderer parameterをこの境界へ入れない。未対応symbolはspeech layerだけをtyped degradationする。

#340 maps timing symbols to canonical articulatory channels, not renderer-specific mouth parameters.

Preferred evidence order:
1. trusted VISEME timing
2. trusted PHONEME/MORA timing mapped to canonical articulation
3. presentation/audio envelope if a typed audio-activity signal exists
4. no exact speech-mouth overlay / explicit degraded state

Do not invent exact phoneme timing when unavailable.

Do not fall back to arbitrary periodic “パクパク”.

---

## 13. Canonical mouth articulation

Initial canonical channels:

```text
mouth_openness   [0,1]
mouth_roundness  [-1,1]  # spread ↔ round
jaw_openness     [0,1]
lip_closure      [0,1]
```

Optional future channels require a contract revision.

Provider viseme IDs are normalized before this boundary. Avatar mapping is #346.

Expression baseline may bias mouth/face presentation, but viseme articulation during speech must preserve intelligible timing priority where conflicts exist.

---

## 14. Viseme interpolation

For each timing unit:
- use monotonic start/end
- smooth entry/exit
- avoid instantaneous discontinuity
- coarticulation/blending between adjacent units allowed
- interruption truncates future units without replaying them
- Presentation終端でspeech sourceが外れた場合も、保持中のarticulationをneutralへboundedにfadeしてから解放する
- timing unavailableやunsupported symbolへのtyped degradationでも、直前articulationをneutralへboundedにfadeする
- 遅延tickでもgazeの一frame変位はboundedにし、target座標へsnapしない
- speech articulationも通常のtiming遷移・gap・degradation fadeの全経路で一frame変位をboundedにする

Exact interpolation is deterministic configuration, not LLM-generated per frame.

---

## 15. Subtle spontaneous motion

Non-instruction time must not be perfectly static, but “random movement” alone is not canonical life-likeness.

Subtle motion is generated from:
- current pose/velocity
- BodyExpressionContext `idle_variation`, `motion_softness`, `movement_energy`
- breathing phase
- current active plan occupancy
- gaze state

Use smooth band-limited/stateful variation.

Forbidden:
- framewise independent random joint offsets
- fixed idle animation roulette as primary path
- reset-to-neutral between micro motions
- motion that breaks active hard task/contact/balance

Variation generator is seedable in tests.

---

## 16. Posture correction / balance assist

#340 may emit low-amplitude correction hints for drift/realtime stabilization, but #339 remains final physical/balance Authority.

Realtime assist:
- cannot override hard Motion target
- cannot bypass limits
- may be attenuated/rejected by #339

Safety-critical recovery requiring large movement belongs to #339 trajectory/control or a new high-level plan, not hidden realtime animation.

---

## 17. Layer conflict order

Within #340, generate independent layer intents; final physical conflict resolution remains #339.

Recommended relative priority semantics:
1. speech articulation timing for mouth-specific channel while speaking
2. gaze target tracking for eye-specific channel
3. blink for eyelid channel
4. breathing
5. subtle variation

Cross-joint conflicts with planned physical tasks are resolved by #339 hard/safety constraints first.

Priority does not mean one layer globally pauses all others.

---

## 18. Layer degradation

Each realtime layer has status:

```text
ACTIVE
DEGRADED
INACTIVE_NO_SOURCE
DISABLED_BY_CAPABILITY
FAILED
```

Examples:
- no spatial gaze target → gaze semantic target unavailable, body can keep stable gaze behavior
- no TTS timing → speech-mouth degraded
- Avatar missing → #340 still computes canonical Body state; output publication may be unavailable

One layer failure does not stop other realtime layers.

---

## 19. Expression revision updates

#337 BodyExpressionContext can change asynchronously.

#340 uses latest accepted context and interpolates local realtime parameters over bounded transition windows.

Do not hard reset:
- breathing phase
- blink mid-cycle
- gaze velocity
- subtle motion state

on every expression revision.

---

## 20. Motion Planner delay

During #338 Motion Planner 5s/20s delay:
- #339 continues existing trajectory or stable controller behavior
- #340 gaze/blink/breath/viseme/subtle layers continue
- BodyPoseFrame production continues

No “planning pose” fixed preset is inserted solely because a Planner request is in flight.

---

## 21. Speech/Body independence

Speech and Body are sibling outputs.

- Character/TTS generation completion is not a prerequisite for non-speech realtime Body.
- Body Planner completion is not prerequisite for Speech preparation.
- actual Presentation timing only affects speech-specific mouth overlay.
- Character text is not parsed for gesture selection.

---

## 22. Lifecycle / cancellation

Realtime service owns long-lived layer local states under RuntimeCoordinator.

On shutdown:
- stop admitting new targets/timing
- settle current tick
- stop timers/tasks
- no pending blink/breath/gaze task left after close

Per-speech viseme state is presentation-scoped and cancelled on interruption/end.

A new gaze target supersedes old target smoothly without global Body cancellation.

---

## 23. Observability

Per frame/layer:
- target interval / actual interval / jitter
- layer computation time
- current layer status
- source revision/identity
- applied/degraded/rejected overlay ref

Speech:
- presentation/timing ID
- timing quality
- viseme unit index
- interruption/completion

Gaze:
- target ref/revision
- tracking error
- saturation/degraded state

Do not emit renderer parameter dumps as Body canonical telemetry.

---

## 24. Required tests

### Gaze
- smooth target acquire/retarget/release
- #333 Focus without spatial target degrades without guessing coordinates
- large target saturates realtime allowance rather than hidden torso semantic decision
- no oscillatory jitter

### Blink
- state-machine lifecycle
- bounded interval variation
- seed determinism
- no fixed Emotion→blink preset

### Breath
- continuous phase
- expression amplitude/tempo interpolation
- no reset across Motion plan switch

### Viseme
- prepared speech does not move mouth
- Presentation STARTED activates exact timing
- trusted viseme/phoneme/mora mapping
- timing unavailable typed degradation
- no arbitrary periodic mouth fallback
- interruption truncates future units

### Subtle motion
- nonzero life-like variation when allowed
- band-limited/no white-noise jitter
- active task constraint respected
- test seed reproducibility

### Composition
- #340 does not mutate BodyState directly
- #339 rechecks hard limits after overlay
- one failed layer does not stop others

### Concurrency
- Motion Planner 20s delay while frame/layers continue
- slow TTS/verifier while non-speech Body layers continue
- renderer unavailable while canonical Body continues
- shutdown leaves no realtime task

---

## 25. Non-goals

- cognitive focus selection
- large high-level orientation/motion planning
- IK/FK/final joint safety
- provider TTS timing fabrication
- renderer mouth/bone mapping
- fixed idle/blink/breath animation preset library
- raw user text interpretation

---

## 26. Design Gate

#340 implementation starts only after:
- #339 single BodyState writer / overlay composition boundary aligned
- #337 normalized Expression axes remain canonical
- #358 Presentation/timing identity aligned
- #333 Focus remains cognitive Authority
- #341 Integration defines full frame/service lifecycle
- #445 Design Completion Gate PASS

#340 detailed design completion alone does not lift the global Implementation Freeze.

# V2 Body Solver / Continuous Controller Contracts

Owner Issue: #339
Parent: #335
Upstream: #336, #337, #338
Downstream: #340, #341, #346, #329
Related:
- `docs/architecture/v2/body_architecture.md`
- `docs/architecture/v2/body_motion_planning_contracts.md`
- `docs/architecture/v2/concurrency_architecture.md`
Status: Canonical Supplement / Design Gate

## 1. Purpose

#339はaccepted `BodyMotionPlan`を、Canonical Body Model上で**物理・解剖学的制約を守る連続的な実行軌道**へ変換し、current Body Stateから次frameを決定論的に更新するphysical Authorityである。

```text
accepted BodyMotionPlan
+ CanonicalBodyModel
+ latest BodyState
+ BodyExpressionContext
        ↓
Plan compiler / feasibility
        ↓
IK/FK + limits + balance + coordination
        ↓
ExecutableBodyTrajectory
        ↓
Continuous Controller
+ #340 RealtimeOverlayBundle
        ↓
next BodyState + BodyPoseFrame
```

Planner/LLMが生成した目標はphysical factではない。#339がfeasibility/continuityを満たして初めて実行可能になる。

---

## 2. Authority boundary

### #339 owns

- BodyMotionPlan structural/physical validation
- canonical selector/chain resolution
- task-space target compilation
- IK/FK solving
- hard DOF/joint limit enforcement
- comfortable-range / relaxed-range soft costs
- root / center-of-mass / balance constraints
- contact/support constraints
- trajectory timing concretization
- velocity / acceleration / jerk bounds
- multi-chain coordination
- current-state rebasing
- plan interruption / trajectory supersede blending
- base trajectory continuation
- final Body State frame commit
- plan execution progress/physical outcome report

### #339 does not own

- high-level BodyIntent (#328)
- Character/Emotion meaning
- BodyExpression projection (#337)
- open-ended Motion composition (#338)
- cognitive Focus selection (#333)
- blink/breath/viseme/gaze micro-adjustment policy (#340)
- renderer bone/parameter mapping (#346)

#339 is deterministic physical control, not another semantic planner.

---

## 3. Input snapshot

```text
BodySolveContext
- solve_request_id
- motion_plan
- canonical_body_model
- latest_body_state
- expression_context
- realtime_capability_view
- source_context_revision
- goal_revision?
- attention_revision?
- captured_at
- trace_id
```

Rules:
- model ID/revision/fingerprint must match accepted Plan binding.
- latest BodyState may have advanced since #338 planning; ordinary BodyState revision drift is rebaseable.
- hard source/goal/attention/intent/model/constraint staleness remains #338/#341 rejection condition.
- mutable BodyState aliases are forbidden.

---

## 4. Plan compilation

Each BodyMotionPlan goal resolves into one or more typed task constraints.

Initial compiled task kinds:

```text
ORIENTATION_TARGET
POSITION_TARGET
CONTACT_TARGET
ROOT_IMPULSE_TARGET
POSTURE_BIAS
COORDINATION_CONSTRAINT
BALANCE_CONSTRAINT
```

Compilation uses only canonical joint/chain/end-effector IDs and 3D canonical coordinates.

No renderer parameter names or screen coordinates enter the compiled trajectory.

---

## 5. ExecutableBodyTrajectory

```text
ExecutableBodyTrajectory
- trajectory_id
- plan_id
- body_model_id
- start_body_state_revision
- phases[]
- involved_joint_ids[]
- involved_chain_ids[]
- contact_schedule[]
- balance_policy
- completion_tolerances
- priority
- interruptibility
- created_at
```

Each phase:

```text
BodyTrajectoryPhase
- phase_id
- start_offset_s
- end_offset_s
- task_targets[]
- root_target?
- joint_soft_biases[]
- contact_constraints[]
- velocity_limits[]
- acceleration_limits[]
- blending_policy
```

The trajectory may use splines/interpolants internally. Canonical contract does not require one numerical solver algorithm, but all implementations must satisfy the same constraints and deterministic test tolerances.

---

## 6. Time concretization

#338 may express relative timing/phase relationships. #339 converts these into concrete monotonic trajectory time using:
- current pose/velocity distance
- joint/chain capability limits
- BodyExpression movement tempo/energy
- plan relative timing
- configured physical safety bounds

Rules:
- no negative/zero-length invalid phase
- no impossible instantaneous displacement
- style can alter tempo within safety bounds but cannot violate hard limits
- exact real-time duration is a controller plan, not proof of actual completion

---

## 7. Hard vs soft constraints

### Hard constraints

Must never be violated by accepted frame output:
- finite numbers only
- declared DOF axes only
- joint hard limits
- canonical hierarchy
- required contact constraints when active
- non-penetrating/structural constraints where implemented as safety-critical
- configured root/velocity/acceleration physical bounds
- required support/balance constraints for grounded phases

### Soft objectives

Optimization may trade:
- comfortable range
- relaxed reference deviation
- end-effector error within tolerance
- motion smoothness
- velocity/acceleration/jerk continuity
- minimal unnecessary joint travel
- BodyExpression softness/energy/compactness
- symmetry/asymmetry tendency
- torso contribution

Soft style never overrides hard safety/DOF constraints.

---

## 8. IK / FK contract

The solver may use analytic, Jacobian, optimization or hybrid IK.

Canonical acceptance is behavior-based:
- deterministic for same input/config
- converges within bounded iteration/time budget
- respects hard limits at every committed output
- returns explicit residual/error metrics
- fails typed when target cannot be reached within acceptance tolerance

No unconstrained LLM-generated final angles are accepted.

FK is the canonical way to derive world joint/end-effector positions from root + local joint transforms.

---

## 9. Reachability / partial feasibility

A target may be unreachable.

Closed result:

```text
FEASIBLE
FEASIBLE_WITH_RESIDUAL
INFEASIBLE
UNSUPPORTED
```

`FEASIBLE_WITH_RESIDUAL` is allowed only when Plan/constraint tolerance explicitly permits approximation.

The solver must not silently clamp to an unrelated pose and report success.

Diagnostics expose target/residual IDs, not fabricated semantic interpretation.

---

## 10. Balance / center of mass

Grounded motion uses support/contact state from Canonical Body/trajectory.

At minimum:
- identify support contacts
- compute/reference center-of-mass projection
- maintain configured support margin during phases requiring balance
- coordinate root/hip/leg/torso adjustments

For airborne phases such as jump:
- grounded support constraint is intentionally released only during declared airborne phase
- takeoff/landing contact transitions are explicit
- landing generates a bounded deceleration/recovery trajectory

A jump is not a root-Y animation alone.

---

## 11. Jump contract

Canonical phase family:

```text
PREPARE
COMPRESSION
EXTENSION
AIRBORNE
LANDING
RECOVERY
```

Depending on magnitude/style, phases may vary in duration/contribution but must preserve:
- coordinated hip/knee/ankle/root
- optional arm/torso contribution according to plan/style
- takeoff/landing continuity
- joint limit/balance constraints

Small jump and large jump differ by target magnitude/trajectory, not fixed named animation presets.

---

## 12. Look/orient coordination

Orientation target may distribute across:
- eye/gaze capability (via #340 realtime channel where appropriate)
- head
- neck
- chest/torso
- root when required

#339 handles planned skeletal orientation allocation while #340 handles low-latency gaze tracking/micro-adjustment.

Small direction error can stay mostly in gaze/head; larger target may recruit neck/torso according to comfortable range and plan constraints.

No fixed `head_yaw + gaze_x` recipe is canonical.

---

## 13. Multi-chain / simultaneous motion

Multiple goals can share/compete for joints.

Compiler builds a conflict graph with:
- joint/chain ownership
- hard vs soft task
- plan priority
- exclusivity/additivity
- coordination relation

Resolution:
1. hard safety constraints
2. explicit plan coordination/priority
3. task feasibility
4. style/comfort soft objective

Unresolvable hard conflict returns typed infeasible rather than arbitrary winner.

---

## 14. Continuous Controller

Controller advances from **previous committed BodyState**, not from a Neutral/Home pose.

Per control tick:

```text
previous BodyState
+ active ExecutableBodyTrajectory
+ elapsed monotonic time
+ latest #340 RealtimeOverlayBundle
+ feedback/capability state
→ solve/compose/clamp
→ next BodyState
→ BodyPoseFrame
```

Only #339 BodyStateAuthority commits the next canonical BodyState revision.

#340 computes overlays but does not independently write BodyState.

---

## 15. Body State revision / frame commit

Each committed frame/state update:
- monotonic `BodyState.revision`
- timezone-aware/monotonic-correlated observation time as defined by runtime clock boundary
- exact active trajectory/motion refs
- current root/joint pose + velocity
- bounded immutable history according to #336 policy

A renderer failure does not roll back canonical BodyState.

A frame not accepted by hard validation is not committed.

---

## 16. Rebase on latest BodyState

A valid #338 Plan may have been generated from BodyState revision N while realtime advanced to N+k.

If only rebaseable body/expression state changed:
- compile/rebase from latest current pose/velocity
- preserve Plan high-level goals/identity
- produce a new trajectory identity bound to latest start revision

Do not snap current state back to Plan's original pose.

If hard Plan authority/fingerprint/constraint changed, discard/replan instead of rebase.

---

## 17. Interruption / supersede

When a higher-authority accepted Plan supersedes current motion:

```text
current pose + velocity
→ transition/blend segment
→ new trajectory
```

Requirements:
- position continuity
- velocity continuity where physically feasible
- bounded acceleration/jerk
- no implicit Home reset
- preserve non-conflicting realtime overlays

If immediate interruption is required for safety, continuity may be sacrificed only according to explicit emergency/safety policy and must be observable.

---

## 18. Completion / progress

Trajectory progress is physical/runtime status, not Goal completion.

```text
BodyMotionExecutionReport
- plan_id
- trajectory_id
- status
- started_at?
- observable_at?
- completed_at?
- achieved_target_refs[]
- residuals[]
- failure_code?
```

Status:
- PLANNED
- STARTED
- OBSERVABLE
- COMPLETED
- INTERRUPTED
- SUPERSEDED
- INFEASIBLE
- UNSUPPORTED
- FAILED

#329 consumes trusted Body execution reports to normalize generic Actual Execution Facts.

#339 does not complete an Executive Goal directly.

---

## 19. Failure model

Closed failures at minimum:
- INVALID_PLAN
- MODEL_MISMATCH
- UNKNOWN_BODY_REFERENCE
- UNSUPPORTED_CAPABILITY
- INFEASIBLE_TARGET
- HARD_LIMIT_CONFLICT
- BALANCE_INFEASIBLE
- CONTACT_INFEASIBLE
- NUMERICAL_FAILURE
- STALE_HARD_DEPENDENCY
- CANCELLED

Numerical failure never causes unchecked last iterate to be committed.

---

## 20. Realtime overlay composition boundary

#340 returns canonical overlay intents/deltas with explicit affected channel/joint refs and strength bounds.

#339 final composer:
- applies overlays after base trajectory solve according to layer policy
- re-runs/clamps hard joint limits
- preserves balance/safety
- can attenuate an overlay when it conflicts with a hard task
- records applied/degraded overlay refs

Realtime overlay is not allowed to bypass joint safety because it is “small”.

---

## 21. No uncontrolled jitter

Frame-to-frame output must satisfy continuity thresholds.

Sources such as gaze/micro-motion may vary, but:
- input is filtered/band-limited where necessary
- no independent white-noise joint offsets
- velocity/acceleration/jerk limits remain enforced
- numerical solver iteration noise must not appear as visible high-frequency vibration

---

## 22. Scheduling / concurrency

- controller/realtime frame lane does not await Motion Planner/LLM/TTS/DB.
- when no new trajectory is ready, current trajectory continues or stable expression baseline/realtime layers continue.
- Plan compilation can occur outside critical frame tick where expensive.
- only short atomic state commit occurs in frame lane.
- new Plan/cancel command is read via bounded lock-free/short-lock handoff.
- slow renderer publication does not block state evolution; output adapter uses bounded/latest-frame policy.

---

## 23. Observability

Per plan/trajectory:
- plan/trajectory ID
- start BodyState revision
- compile latency
- solver iteration/residual summary
- infeasible/unsupported reason
- rebase count
- interruption/supersede

Per frame:
- BodyState revision
- target frame interval
- actual interval/jitter
- solve duration
- hard-limit clamp count
- balance margin
- applied/degraded overlay refs

Metrics must not include renderer-specific parameter dumps as canonical Body state.

---

## 24. Required tests

### Model/plan
- unknown model/joint/chain/end-effector reject
- hard stale dependency reject
- ordinary BodyState revision rebase

### IK/FK
- unilateral arm reach
- bilateral reach
- small/large look distribution
- hard limit enforcement
- comfortable-range soft preference
- unreachable target typed infeasible
- deterministic repeated solve

### Balance / jump
- grounded CoM support
- prepare/compression/extension/airborne/landing/recovery
- small/large jump
- no root-only fake jump
- landing continuity

### Continuity
- current pose start
- no Home reset
- plan supersede C0/C1 continuity
- velocity/acceleration bounds
- no solver jitter

### Multi-motion
- non-conflicting simultaneous goals
- shared-joint soft conflict resolution
- unresolvable hard conflict reject

### Realtime composition
- overlay accepted within limits
- conflicting overlay attenuated/degraded
- hard limits rechecked after overlay

### Runtime
- planner 5s/20s delay while current frames continue
- renderer slow/unavailable while BodyState continues
- cancellation/supersede without pending control task

### Actual fact
- accepted Plan != started motion
- STARTED/OBSERVABLE/COMPLETED reports only after controller evidence
- partial/interrupted motion not falsely reported complete

---

## 25. Non-goals

- natural-language motion understanding
- high-level Motion composition
- Emotion/Character semantic interpretation
- renderer parameter mapping
- per-frame LLM generation
- fixed action/preset animation library
- cognitive Focus/Goal decision

---

## 26. Design Gate

#339 implementation starts only after:
- #336 Canonical Body Model/State is current trunk Authority
- #338 BodyMotionPlan contract is reconciled into #445 canonical
- #340 overlay contract aligns with single BodyState writer rule
- #341 integration owns end-to-end orchestration rather than #339
- #445 Design Completion Gate PASS

#339 detailed design completion alone does not lift the global Implementation Freeze.

# V2 Body Solver Target Tracking Dynamics

Owner Issue: #546
Parent/owner context: #339
Blocks verification: #341 / #346
Canonical parent: `docs/architecture/v2/body_solver_controller_contracts.md`
Status: Implementation Design / Canonical Supplement for #546

## 1. Problem

Human Verification #545 exposed a production Body Solver failure while tracking a valid D10 arm target.

- requested target: `-0.65 rad`
- D10 comfortable range: `[-0.8, +0.8]`
- D10 hard range: `[-1.2, +1.2]`
- observed final arm angle before failure: approximately `-1.194 rad`
- fatal: `BodySolverError(DYNAMIC_LIMIT_CONFLICT)`

The target itself is feasible and comfortably inside the hard boundary. The failure is therefore not an infeasible-target case.

The existing scalar joint dynamics computes desired velocity as:

```text
(target_position - current_position) / dt
```

and then independently clips velocity, acceleration and jerk. For any ordinary control-rate `dt`, this behaves like a very high-gain position servo. While approaching the target it keeps requesting maximum target-directed velocity until the position error becomes very small. Because acceleration cannot reverse instantaneously under the jerk bound, the joint crosses the target with substantial velocity, continues toward the hard limit, and can finally require a hard-limit clamp that itself violates acceleration/jerk bounds.

## 2. Canonical requirements preserved

This change keeps the #339 authority boundary unchanged.

- `BodyContinuousController` remains the only physical BodyState writer.
- IK still produces a feasible target DOF; IK does not become a trajectory integrator.
- velocity / acceleration / jerk limits remain hard constraints.
- joint hard limits remain hard constraints.
- the controller advances from the previous committed BodyState; there is no Home/Neutral reset.
- true infeasible / impossible current physical states still fail typed; hard limits are not silently clamped and reported as success.
- #340 realtime overlays remain channel-only and do not alter skeletal target tracking.
- #341 activation/supersede continues to reuse the same controller state and therefore preserves velocity/acceleration continuity.

## 3. Target-aware acceleration servo

For each scalar joint DOF, use a bounded critically-damped position/velocity servo to compute the desired acceleration before jerk limiting.

Definitions:

```text
error = target_position - current_position
omega = max_acceleration / max_velocity
position_gain = omega^2
velocity_gain = 2 * omega

desired_acceleration =
    clamp(position_gain * error - velocity_gain * current_velocity,
          -max_acceleration,
          +max_acceleration)
```

`omega` is derived only from the Canonical joint dynamic limits. No renderer, animation preset, character semantics or arbitrary per-motion tuning enters the physical loop.

Then preserve the existing hard derivative gates:

```text
acceleration_delta = clamp(
    desired_acceleration - current_acceleration,
    -max_jerk * dt,
    +max_jerk * dt,
)

next_acceleration = clamp(
    current_acceleration + acceleration_delta,
    -max_acceleration,
    +max_acceleration,
)

next_velocity = clamp(
    current_velocity + next_acceleration * dt,
    -max_velocity,
    +max_velocity,
)

next_position = current_position + next_velocity * dt
```

This makes deceleration begin according to both remaining position error and current velocity instead of waiting until the target has already been crossed.

## 4. Target crossing

The target is a goal, not a hard physical wall. A small transient crossing can be physically valid when current momentum cannot be removed instantly under jerk/acceleration bounds.

Therefore:

- do not snap to target if doing so would invent an impossible velocity/acceleration/jerk discontinuity;
- do not treat target crossing itself as a hard failure;
- continue the damped servo until position/velocity converge;
- hard-limit enforcement remains independent and must never be bypassed.

For the nominal zero-velocity D10 target step used in Human Verification, the critically-damped servo is expected to approach without material overshoot.

## 5. Hard limit behavior

The existing hard-limit boundary remains fail-closed.

If the integrated next position exceeds a hard joint limit:

1. compute the exact velocity/acceleration/jerk required to land on the hard boundary for that frame;
2. accept the boundary only when all dynamic limits remain satisfied;
3. otherwise raise `DYNAMIC_LIMIT_CONFLICT`.

#546 must not convert a truly unsafe current state into silent hard clamping.

## 6. Completion and trajectory time

`ExecutableBodyTrajectory.end_offset_s` remains a timing boundary, not proof of actual physical completion. If the target is not yet within completion residual when nominal trajectory time is reached, the last phase remains active and the controller continues bounded convergence until the existing completion condition is satisfied.

The change therefore does not weaken residual-based completion and does not require a fixed-duration animation.

## 7. Verification matrix

Required regression coverage:

1. D10 `0 → -0.65 rad` at 30 Hz converges without approaching the `-1.2 rad` hard boundary.
2. Mirrored positive target behaves symmetrically.
3. Every committed step respects max velocity, acceleration and jerk.
4. Non-zero current velocity toward the target is damped without hard-limit runaway.
5. Non-zero current velocity away from the target reverses under the same derivative limits.
6. Sequential target changes preserve current velocity/acceleration state and remain bounded.
7. Existing #339 post-completion continuation and #341 activation tests remain green.
8. Verification-only Browser surface is rebuilt from the merged/final #546 production head before Human Verification is repeated.

## 8. Out of scope

- changing IK objective/coordinate-descent behavior;
- changing Canonical hard/comfortable ranges;
- weakening dynamic limits;
- renderer-side smoothing;
- Body Motion LLM behavior;
- root translational/orientation target servo unless independently reproduced and tracked as its own physical-control defect.

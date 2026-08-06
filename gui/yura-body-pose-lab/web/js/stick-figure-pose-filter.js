const FILTERED_FIELDS = Object.freeze([
  "head_yaw",
  "head_pitch",
  "head_roll",
  "gaze_x",
  "gaze_y",
  "torso_yaw",
  "torso_pitch",
  "torso_roll",
  "body_height",
  "left_arm_raise",
  "right_arm_raise",
  "left_arm_in",
  "right_arm_in",
]);

const FIELD_DEADBAND = Object.freeze({
  gaze_x: 0.0008,
  gaze_y: 0.0008,
  body_height: 0.0005,
  torso_yaw: 0.0008,
  torso_pitch: 0.0008,
  torso_roll: 0.0008,
  head_yaw: 0.0008,
  head_pitch: 0.0008,
  head_roll: 0.0008,
  left_arm_raise: 0.0012,
  right_arm_raise: 0.0012,
  left_arm_in: 0.0012,
  right_arm_in: 0.0012,
});

function finite(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function responseFor(delta) {
  const magnitude = Math.abs(delta);
  if (magnitude >= 0.28) return { alpha: 0.74, maximumStep: 0.20 };
  if (magnitude >= 0.09) return { alpha: 0.52, maximumStep: 0.10 };
  if (magnitude >= 0.025) return { alpha: 0.36, maximumStep: 0.045 };
  return { alpha: 0.22, maximumStep: 0.018 };
}

export class StickFigurePoseFilter {
  constructor() {
    this.previous = null;
  }

  reset() {
    this.previous = null;
  }

  apply(pose) {
    if (!pose || typeof pose !== "object") return pose;
    if (this.previous === null) {
      this.previous = { ...pose };
      return this.previous;
    }

    const filtered = { ...pose };
    for (const field of FILTERED_FIELDS) {
      const before = finite(this.previous[field]);
      const current = finite(pose[field], before);
      const delta = current - before;
      const deadband = FIELD_DEADBAND[field] ?? 0.001;
      if (Math.abs(delta) <= deadband) {
        filtered[field] = before;
        continue;
      }
      const response = responseFor(delta);
      const step = clamp(
        delta * response.alpha,
        -response.maximumStep,
        response.maximumStep,
      );
      filtered[field] = before + step;
    }

    this.previous = filtered;
    return filtered;
  }
}

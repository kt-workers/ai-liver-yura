export function clamp(value, min = -1, max = 1) {
  return Math.max(min, Math.min(max, Number(value) || 0));
}

export function projectFrontViewDirection(horizontal = 0, vertical = 0) {
  return {
    x: -clamp(horizontal),
    y: -clamp(vertical),
  };
}

function pointFrom(origin, length, angle) {
  return {
    x: origin.x + Math.cos(angle) * length,
    y: origin.y + Math.sin(angle) * length,
  };
}

function offsetFrom(origin, x, y, angle) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return {
    x: origin.x + x * cosine - y * sine,
    y: origin.y + x * sine + y * cosine,
  };
}

export function computeArmGeometry({ shoulder, side, raise, inward, scale, torsoAngle }) {
  const resolvedRaise = clamp(raise, 0, 1);
  const resolvedInward = clamp(inward);
  const restingAngle = Math.PI / 2 - side * 0.45;
  const liftAngle = side * resolvedRaise * Math.PI * 0.70;
  const inwardAngle = side * resolvedInward * 0.28;
  const upperAngle = restingAngle - liftAngle + inwardAngle + torsoAngle;
  const elbowBend = side * (0.10 + Math.abs(resolvedInward) * 0.16);
  const lowerAngle = upperAngle + elbowBend;
  const elbow = pointFrom(shoulder, scale * 0.48, upperAngle);
  const wrist = pointFrom(elbow, scale * 0.42, lowerAngle);
  return { shoulder, elbow, wrist };
}

export function computeLegGeometry({ hip, side, scale, torsoAngle }) {
  const upperAngle = Math.PI / 2 - side * 0.14 + torsoAngle * 0.18;
  const lowerAngle = upperAngle + side * 0.05;
  const knee = pointFrom(hip, scale * 0.55, upperAngle);
  const ankle = pointFrom(knee, scale * 0.58, lowerAngle);
  const toe = { x: ankle.x + side * scale * 0.16, y: ankle.y };
  return { hip, knee, ankle, toe };
}

export function computeStickFigureGeometry(pose, width, height) {
  const scale = Math.min(width, height) / 5.1;
  const torsoAngle = clamp(pose.torso_roll) * 0.23;
  const pelvis = {
    x: width * 0.5 + clamp(pose.torso_yaw) * scale * 0.12,
    y: height * 0.72 - clamp(pose.body_height) * scale * 0.23,
  };
  const chest = offsetFrom(
    pelvis,
    clamp(pose.torso_yaw) * scale * 0.04,
    -scale * 0.82 - clamp(pose.torso_pitch) * scale * 0.09,
    torsoAngle,
  );
  const neck = offsetFrom(chest, 0, -scale * 0.16, torsoAngle);

  // BodyPoseFrame の left/right と方向符号は、ゆら自身の身体座標を表す。
  // 正面向きの検証Rendererでは、解剖学的左/身体座標+Xは画面右/左へ反転し、
  // 身体座標+Y（上）はCanvasの-Yへ投影する。
  const shoulderLeft = offsetFrom(chest, scale * 0.34, scale * 0.04, torsoAngle);
  const shoulderRight = offsetFrom(chest, -scale * 0.34, scale * 0.04, torsoAngle);
  const hipAngle = torsoAngle * 0.35;
  const hipLeft = offsetFrom(pelvis, scale * 0.18, 0, hipAngle);
  const hipRight = offsetFrom(pelvis, -scale * 0.18, 0, hipAngle);
  const headAngle = torsoAngle + clamp(pose.head_roll) * 0.32;
  const projectedHeadDirection = projectFrontViewDirection(pose.head_yaw, pose.head_pitch);
  const head = offsetFrom(
    neck,
    projectedHeadDirection.x * scale * 0.16,
    -scale * 0.32 + projectedHeadDirection.y * scale * 0.12,
    headAngle,
  );
  const headBottom = offsetFrom(head, 0, scale * 0.31, headAngle);

  return {
    scale,
    torsoAngle,
    headAngle,
    pelvis,
    chest,
    neck,
    head,
    headBottom,
    shoulderLeft,
    shoulderRight,
    hipLeft,
    hipRight,
    leftArm: computeArmGeometry({
      shoulder: shoulderLeft,
      side: 1,
      raise: pose.left_arm_raise,
      inward: pose.left_arm_in,
      scale,
      torsoAngle,
    }),
    rightArm: computeArmGeometry({
      shoulder: shoulderRight,
      side: -1,
      raise: pose.right_arm_raise,
      inward: pose.right_arm_in,
      scale,
      torsoAngle,
    }),
    leftLeg: computeLegGeometry({ hip: hipLeft, side: 1, scale, torsoAngle: hipAngle }),
    rightLeg: computeLegGeometry({ hip: hipRight, side: -1, scale, torsoAngle: hipAngle }),
  };
}

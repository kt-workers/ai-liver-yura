(() => {
  function drawJoint(x, y, radius = 9) {
    ctx.save();
    ctx.fillStyle = "#041018";
    ctx.strokeStyle = "#d8f8ff";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function drawEndPoint(x, y, radius = 10) {
    ctx.save();
    ctx.fillStyle = "#d8f8ff";
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawTorsoTriangle(points, alpha = 0.1) {
    ctx.save();
    ctx.fillStyle = `rgba(143, 231, 242, ${alpha})`;
    ctx.strokeStyle = "#d8f8ff";
    ctx.lineWidth = 9;
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    ctx.lineTo(points[1].x, points[1].y);
    ctx.lineTo(points[2].x, points[2].y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function drawWavingArm(x, y, side, inward, torsoAngle) {
    const upperAngle = (
      (side > 0 ? -0.72 : Math.PI + 0.72)
      + torsoAngle
    );
    const upperLength = 96;
    const lowerLength = 94;
    const elbowX = x + Math.cos(upperAngle) * upperLength;
    const elbowY = y + Math.sin(upperAngle) * upperLength;
    const waveSignal = clamp((inward + 0.16) / 0.42, -1, 1);
    const lowerAngle = -Math.PI / 2 + waveSignal * 0.48 + torsoAngle * 0.15;
    const handX = elbowX + Math.cos(lowerAngle) * lowerLength;
    const handY = elbowY + Math.sin(lowerAngle) * lowerLength;

    line(x, y, elbowX, elbowY, 11);
    line(elbowX, elbowY, handX, handY, 10);
    drawJoint(x, y, 9);
    drawJoint(elbowX, elbowY, 9);
    drawEndPoint(handX, handY, 11);
  }

  function drawJointedArm(
    x,
    y,
    side,
    raise,
    inward,
    torsoAngle,
    armInVelocity = 0,
  ) {
    const waveDeviation = Math.abs(inward + 0.16);
    const isWaving = (
      raise > 0.52
      && (waveDeviation > 0.13 || Math.abs(armInVelocity) > 0.32)
    );
    if (isWaving) {
      drawWavingArm(x, y, side, inward, torsoAngle);
      return;
    }

    const restingAngle = side > 0 ? 0.48 : Math.PI - 0.48;
    const liftAngle = raise * Math.PI * 0.63;
    const upperAngle = (
      restingAngle
      - side * liftAngle
      + side * inward * 0.24
      + torsoAngle
    );
    const elbowBend = 0.08 + Math.abs(inward) * 0.1 + (1 - raise) * 0.09;
    const lowerAngle = upperAngle - side * elbowBend;
    const upperLength = 104;
    const lowerLength = 94;
    const elbowX = x + Math.cos(upperAngle) * upperLength;
    const elbowY = y + Math.sin(upperAngle) * upperLength;
    const handX = elbowX + Math.cos(lowerAngle) * lowerLength;
    const handY = elbowY + Math.sin(lowerAngle) * lowerLength;

    line(x, y, elbowX, elbowY, 11);
    line(elbowX, elbowY, handX, handY, 10);
    drawJoint(x, y, 9);
    drawJoint(elbowX, elbowY, 8);
    drawEndPoint(handX, handY, 10);
  }

  function quaternionEulerX(rotation) {
    if (!rotation) return 0;
    const x = Number(rotation.x) || 0;
    const y = Number(rotation.y) || 0;
    const z = Number(rotation.z) || 0;
    const w = Number(rotation.w);
    const resolvedW = Number.isFinite(w) ? w : 1;
    return Math.atan2(
      2 * (resolvedW * x + y * z),
      1 - 2 * (x * x + y * y),
    );
  }

  function legRaiseFromFrame(frame, side) {
    const jointId = `${side}_upper_leg`;
    const joint = Array.isArray(frame?.joints)
      ? frame.joints.find((candidate) => candidate?.joint_id === jointId)
      : null;
    return clamp(Math.abs(quaternionEulerX(joint?.rotation)) / (Math.PI * 0.43), 0, 1);
  }

  function drawJointedLeg(x, y, side, pose, torsoAngle, legRaise = 0) {
    const explicitBend = Number(
      side < 0 ? pose.left_knee_bend : pose.right_knee_bend,
    );
    const kneeBend = Number.isFinite(explicitBend)
      ? clamp(explicitBend, 0, 1)
      : clamp(
        0.12
          + Math.abs(pose.torso_roll) * 0.18
          + Math.abs(pose.body_height) * 0.12
          + legRaise * 0.58,
        0.08,
        0.82,
      );
    const restingAngle = Math.PI / 2 - side * 0.28 + torsoAngle * 0.18;
    const upperAngle = restingAngle - side * legRaise * 1.08;
    const lowerAngle = upperAngle + side * (0.12 + kneeBend * 0.52);
    const upperLength = 108;
    const lowerLength = 102;
    const kneeX = x + Math.cos(upperAngle) * upperLength;
    const kneeY = y + Math.sin(upperAngle) * upperLength;
    const ankleX = kneeX + Math.cos(lowerAngle) * lowerLength;
    const ankleY = kneeY + Math.sin(lowerAngle) * lowerLength;

    line(x, y, kneeX, kneeY, 12);
    line(kneeX, kneeY, ankleX, ankleY, 11);
    drawJoint(x, y, 9);
    drawJoint(kneeX, kneeY, 9);
    drawJoint(ankleX, ankleY, 7);
  }

  drawStickPerson = function drawJointedStickPerson(frame) {
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    if (!frame?.pose) return;

    const pose = frame.pose;
    const velocity = frame.velocity || {};
    const rootPosition = frame.root_transform?.position || {};
    const rootX = Number(rootPosition.x);
    const rootY = Number(rootPosition.y);
    const rootOffsetX = Number.isFinite(rootX) ? rootX * 100 : 0;
    const rootOffsetY = Number.isFinite(rootY) ? -rootY * 92 : 0;
    const waistX = width / 2 + rootOffsetX;
    const waistY = height * 0.58 - pose.body_height * 46 + rootOffsetY;
    const torsoAngle = pose.torso_roll * 0.26 + pose.torso_yaw * 0.08;
    const lowerTorsoAngle = torsoAngle * 0.62 + pose.torso_pitch * 0.035;
    const upperTorsoAngle = torsoAngle + pose.torso_pitch * 0.055;

    const shoulderCenterOffset = rotatePoint(0, -112, upperTorsoAngle);
    const shoulderCenterX = waistX + shoulderCenterOffset.x;
    const shoulderCenterY = waistY + shoulderCenterOffset.y;
    const shoulderSpread = rotatePoint(70, 0, upperTorsoAngle);
    const leftShoulderX = shoulderCenterX - shoulderSpread.x;
    const leftShoulderY = shoulderCenterY - shoulderSpread.y;
    const rightShoulderX = shoulderCenterX + shoulderSpread.x;
    const rightShoulderY = shoulderCenterY + shoulderSpread.y;

    const pelvisCenterOffset = rotatePoint(0, 88, lowerTorsoAngle);
    const pelvisCenterX = waistX + pelvisCenterOffset.x;
    const pelvisCenterY = waistY + pelvisCenterOffset.y;
    const hipSpread = rotatePoint(30, 0, lowerTorsoAngle);
    const leftHipX = pelvisCenterX - hipSpread.x;
    const leftHipY = pelvisCenterY - hipSpread.y;
    const rightHipX = pelvisCenterX + hipSpread.x;
    const rightHipY = pelvisCenterY + hipSpread.y;

    const headAngle = upperTorsoAngle + pose.head_roll * 0.34;
    const neckOffset = rotatePoint(0, -34, headAngle);
    const neckX = shoulderCenterX + neckOffset.x;
    const neckY = shoulderCenterY + neckOffset.y;
    const headRadiusX = 70 * (1 - Math.abs(pose.head_yaw) * 0.22);
    const headRadiusY = 73;
    const headOffset = rotatePoint(0, -(headRadiusY + 17), headAngle);
    const headX = neckX + headOffset.x;
    const headY = neckY + headOffset.y;
    const headBottom = rotatePoint(0, headRadiusY, headAngle);
    const headBottomX = headX + headBottom.x;
    const headBottomY = headY + headBottom.y;
    const leftLegRaise = legRaiseFromFrame(frame, "left");
    const rightLegRaise = legRaiseFromFrame(frame, "right");

    ctx.save();
    ctx.shadowColor = "rgba(111, 222, 242, .42)";
    ctx.shadowBlur = 18;

    drawJointedLeg(
      leftHipX,
      leftHipY,
      -1,
      pose,
      lowerTorsoAngle,
      leftLegRaise,
    );
    drawJointedLeg(
      rightHipX,
      rightHipY,
      1,
      pose,
      lowerTorsoAngle,
      rightLegRaise,
    );

    drawTorsoTriangle(
      [
        { x: leftShoulderX, y: leftShoulderY },
        { x: rightShoulderX, y: rightShoulderY },
        { x: waistX, y: waistY },
      ],
      0.11,
    );
    drawTorsoTriangle(
      [
        { x: waistX, y: waistY },
        { x: rightHipX, y: rightHipY },
        { x: leftHipX, y: leftHipY },
      ],
      0.07,
    );

    drawJointedArm(
      leftShoulderX,
      leftShoulderY,
      -1,
      pose.left_arm_raise,
      pose.left_arm_in,
      upperTorsoAngle,
      Number(velocity.left_arm_in) || 0,
    );
    drawJointedArm(
      rightShoulderX,
      rightShoulderY,
      1,
      pose.right_arm_raise,
      pose.right_arm_in,
      upperTorsoAngle,
      Number(velocity.right_arm_in) || 0,
    );

    line(shoulderCenterX, shoulderCenterY, neckX, neckY, 10);
    line(neckX, neckY, headBottomX, headBottomY, 9);
    drawJoint(shoulderCenterX, shoulderCenterY, 9);
    drawJoint(neckX, neckY, 8);
    drawJoint(waistX, waistY, 11);
    drawJoint(leftHipX, leftHipY, 9);
    drawJoint(rightHipX, rightHipY, 9);

    ctx.save();
    ctx.translate(headX, headY);
    ctx.rotate(headAngle);
    ctx.strokeStyle = "#d8f8ff";
    ctx.lineWidth = 11;
    ctx.beginPath();
    ctx.ellipse(0, 0, headRadiusX, headRadiusY, 0, 0, Math.PI * 2);
    ctx.stroke();
    drawFace(pose, headRadiusX);
    ctx.restore();
    ctx.restore();
  };
})();

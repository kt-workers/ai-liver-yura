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

  function drawJointedArm(x, y, side, raise, inward, torsoAngle) {
    const liftAngle = raise * Math.PI * 0.9;
    const upperAngle = (
      (side > 0 ? 0.48 : Math.PI - 0.48)
      + side * liftAngle
      - side * inward * 0.42
      + torsoAngle
    );
    const elbowBend = 0.16 + Math.abs(inward) * 0.24 + raise * 0.08;
    const lowerAngle = upperAngle + side * elbowBend;
    const upperLength = 106;
    const lowerLength = 96;
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

  function drawJointedLeg(x, y, side, pose, torsoAngle) {
    const explicitBend = Number(
      side < 0 ? pose.left_knee_bend : pose.right_knee_bend,
    );
    const kneeBend = Number.isFinite(explicitBend)
      ? clamp(explicitBend, 0, 1)
      : clamp(
        0.12
          + Math.abs(pose.torso_roll) * 0.18
          + Math.abs(pose.body_height) * 0.12,
        0.08,
        0.34,
      );
    const upperAngle = Math.PI / 2 - side * 0.34 + torsoAngle * 0.2;
    const lowerAngle = upperAngle + side * (0.14 + kneeBend * 0.42);
    const upperLength = 112;
    const lowerLength = 106;
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
    const pelvisX = width / 2;
    const pelvisY = height * 0.70 - pose.body_height * 46;
    const torsoAngle = pose.torso_roll * 0.26 + pose.torso_yaw * 0.08;
    const lowerTorsoAngle = torsoAngle * 0.62 + pose.torso_pitch * 0.035;
    const upperTorsoAngle = torsoAngle + pose.torso_pitch * 0.055;

    const lowerTorso = rotatePoint(0, -88, lowerTorsoAngle);
    const spineX = pelvisX + lowerTorso.x;
    const spineY = pelvisY + lowerTorso.y;
    const upperTorso = rotatePoint(0, -96, upperTorsoAngle);
    const chestX = spineX + upperTorso.x;
    const chestY = spineY + upperTorso.y;

    const headAngle = upperTorsoAngle + pose.head_roll * 0.34;
    const neckOffset = rotatePoint(0, -56 - pose.head_pitch * 5, headAngle);
    const headX = chestX + neckOffset.x;
    const headY = chestY + neckOffset.y;
    const headRadiusX = 72 * (1 - Math.abs(pose.head_yaw) * 0.22);
    const headRadiusY = 76;

    const leftHip = rotatePoint(-21, 3, lowerTorsoAngle);
    const rightHip = rotatePoint(21, 3, lowerTorsoAngle);
    const leftHipX = pelvisX + leftHip.x;
    const leftHipY = pelvisY + leftHip.y;
    const rightHipX = pelvisX + rightHip.x;
    const rightHipY = pelvisY + rightHip.y;

    const leftShoulder = rotatePoint(-63, 4, upperTorsoAngle);
    const rightShoulder = rotatePoint(63, 4, upperTorsoAngle);
    const leftShoulderX = chestX + leftShoulder.x;
    const leftShoulderY = chestY + leftShoulder.y;
    const rightShoulderX = chestX + rightShoulder.x;
    const rightShoulderY = chestY + rightShoulder.y;

    ctx.save();
    ctx.shadowColor = "rgba(111, 222, 242, .42)";
    ctx.shadowBlur = 18;

    drawJointedLeg(leftHipX, leftHipY, -1, pose, lowerTorsoAngle);
    drawJointedLeg(rightHipX, rightHipY, 1, pose, lowerTorsoAngle);

    line(pelvisX, pelvisY, spineX, spineY, 13);
    line(spineX, spineY, chestX, chestY, 13);
    drawJoint(pelvisX, pelvisY, 11);
    drawJoint(spineX, spineY, 10);
    drawJoint(chestX, chestY, 10);

    drawJointedArm(
      leftShoulderX,
      leftShoulderY,
      -1,
      pose.left_arm_raise,
      pose.left_arm_in,
      upperTorsoAngle,
    );
    drawJointedArm(
      rightShoulderX,
      rightShoulderY,
      1,
      pose.right_arm_raise,
      pose.right_arm_in,
      upperTorsoAngle,
    );

    drawJoint(chestX, chestY, 9);
    drawJoint(headX, headY + headRadiusY - 4, 7);

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

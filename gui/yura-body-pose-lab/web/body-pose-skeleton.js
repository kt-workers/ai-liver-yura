(() => {
  function drawJoint(x, y, radius = 8) {
    ctx.save();
    ctx.fillStyle = "#041018";
    ctx.strokeStyle = "#d8f8ff";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function drawEndPoint(x, y, radius = 9) {
    ctx.save();
    ctx.fillStyle = "#d8f8ff";
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawPolygon(points, width = 11) {
    if (points.some((point) => !point)) return;
    ctx.save();
    ctx.strokeStyle = "#d8f8ff";
    ctx.lineWidth = width;
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (const point of points.slice(1)) ctx.lineTo(point.x, point.y);
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
  }

  function kinematicView(frame, width, height) {
    const kinematic = frame?.kinematic_pose;
    if (!kinematic?.joints) return null;
    const scale = Math.min(width, height) * 0.31;
    const root = kinematic.root_position || { x: 0, y: 0, z: 0 };
    const centerX = width * 0.5;
    const centerY = height * 0.57;
    const points = new Map();
    for (const joint of kinematic.joints) {
      const position = joint?.position;
      if (!joint?.joint_id || !position) continue;
      points.set(joint.joint_id, {
        x: centerX + (position.x + root.x) * scale,
        y: centerY - (position.y + root.y) * scale,
        z: position.z + root.z,
      });
    }
    return { points, scale };
  }

  function fallbackKinematic(frame, width, height) {
    if (!frame?.pose) return null;
    const pose = frame.pose;
    const scale = Math.min(width, height) * 0.31;
    const centerX = width * 0.5;
    const centerY = height * 0.57 - pose.body_height * scale * 0.12;
    const point = (x, y, z = 0) => ({
      x: centerX + x * scale,
      y: centerY - y * scale,
      z,
    });
    return {
      scale,
      points: new Map([
        ["pelvis", point(0, 0)],
        ["spine", point(0, 0.34)],
        ["chest", point(0, 0.70)],
        ["neck", point(0, 0.91)],
        ["head", point(0, 1.15)],
        ["left_shoulder", point(-0.32, 0.73)],
        ["left_elbow", point(-0.52, 0.39)],
        ["left_hand", point(-0.66, 0.05)],
        ["right_shoulder", point(0.32, 0.73)],
        ["right_elbow", point(0.52, 0.39)],
        ["right_hand", point(0.66, 0.05)],
        ["left_hip", point(-0.18, 0)],
        ["left_knee", point(-0.19, -0.55)],
        ["left_ankle", point(-0.20, -1.10)],
        ["right_hip", point(0.18, 0)],
        ["right_knee", point(0.19, -0.55)],
        ["right_ankle", point(0.20, -1.10)],
      ]),
    };
  }

  function drawChain(points, ids, widths) {
    for (let index = 0; index < ids.length - 1; index += 1) {
      const start = points.get(ids[index]);
      const end = points.get(ids[index + 1]);
      if (!start || !end) continue;
      line(start.x, start.y, end.x, end.y, widths[index] || 10);
    }
  }

  drawStickPerson = function drawKinematicStickPerson(frame) {
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    const view = kinematicView(frame, width, height)
      || fallbackKinematic(frame, width, height);
    if (!view) return;

    const points = view.points;
    const pose = frame.pose || {};
    const pelvis = points.get("pelvis");
    const spine = points.get("spine");
    const chest = points.get("chest");
    const neck = points.get("neck");
    const head = points.get("head");
    const leftShoulder = points.get("left_shoulder");
    const rightShoulder = points.get("right_shoulder");
    const leftHip = points.get("left_hip");
    const rightHip = points.get("right_hip");

    ctx.save();
    ctx.shadowColor = "rgba(111, 222, 242, .42)";
    ctx.shadowBlur = 18;

    drawChain(points, ["left_hip", "left_knee", "left_ankle"], [12, 11]);
    drawChain(points, ["right_hip", "right_knee", "right_ankle"], [12, 11]);
    drawChain(points, ["left_shoulder", "left_elbow", "left_hand"], [11, 10]);
    drawChain(points, ["right_shoulder", "right_elbow", "right_hand"], [11, 10]);

    // 上半身は肩から腰へ向かう逆三角形、下半身は腰から股関節へ広がる三角形。
    drawPolygon([leftShoulder, rightShoulder, pelvis], 12);
    drawPolygon([pelvis, leftHip, rightHip], 11);
    if (spine && chest) line(pelvis.x, pelvis.y, spine.x, spine.y, 9);
    if (spine && chest) line(spine.x, spine.y, chest.x, chest.y, 9);

    // 首は胸部、首関節、頭を別々に接続する。
    if (chest && neck) line(chest.x, chest.y, neck.x, neck.y, 9);
    const headRadiusY = view.scale * 0.19;
    const headRadiusX = headRadiusY * (1 - Math.abs(Number(pose.head_yaw) || 0) * 0.22);
    if (neck && head) {
      line(neck.x, neck.y, head.x, head.y + headRadiusY * 0.82, 8);
    }

    for (const id of [
      "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
      "pelvis", "spine", "chest", "neck", "left_hip", "right_hip",
      "left_knee", "right_knee", "left_ankle", "right_ankle",
    ]) {
      const point = points.get(id);
      if (point) drawJoint(point.x, point.y, id === "pelvis" ? 10 : 7);
    }
    for (const id of ["left_hand", "right_hand"]) {
      const point = points.get(id);
      if (point) drawEndPoint(point.x, point.y, 9);
    }

    if (head) {
      ctx.save();
      ctx.translate(head.x, head.y);
      ctx.rotate((Number(pose.head_roll) || 0) * 0.34);
      ctx.strokeStyle = "#d8f8ff";
      ctx.lineWidth = 10;
      ctx.beginPath();
      ctx.ellipse(0, 0, headRadiusX, headRadiusY, 0, 0, Math.PI * 2);
      ctx.stroke();
      drawFace(pose, headRadiusX);
      ctx.restore();
    }
    ctx.restore();
  };
})();

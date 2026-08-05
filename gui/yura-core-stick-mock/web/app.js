const canvas = document.getElementById("avatar");
const ctx = canvas.getContext("2d");
const connection = document.getElementById("connection");
const sequenceNode = document.getElementById("sequence");
const ageNode = document.getElementById("age");
const attentionNode = document.getElementById("attention");
const expressionNode = document.getElementById("expression");
const payloadNode = document.getElementById("payload");

let latestFrame = null;
let latestReceivedAt = 0;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, Number(value) || 0));
}

function shapeMap(frame) {
  return new Map((frame?.blend_shapes || []).map((item) => [item.name, Number(item.value) || 0]));
}

function rotatePoint(x, y, angle) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return { x: x * cosine - y * sine, y: x * sine + y * cosine };
}

function line(x1, y1, x2, y2, width = 10) {
  ctx.strokeStyle = "rgba(221, 249, 255, .96)";
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function joint(x, y, radius = 8) {
  ctx.fillStyle = "#07141d";
  ctx.strokeStyle = "#dff9ff";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function drawArm(x, y, side, raise, inward, torsoAngle) {
  const restingAngle = side > 0 ? 0.52 : Math.PI - 0.52;
  const upperAngle = restingAngle - side * raise * Math.PI * 0.64 + side * inward * 0.22 + torsoAngle;
  const lowerAngle = upperAngle - side * (0.10 + Math.abs(inward) * 0.16);
  const elbowX = x + Math.cos(upperAngle) * 102;
  const elbowY = y + Math.sin(upperAngle) * 102;
  const handX = elbowX + Math.cos(lowerAngle) * 91;
  const handY = elbowY + Math.sin(lowerAngle) * 91;
  line(x, y, elbowX, elbowY, 11);
  line(elbowX, elbowY, handX, handY, 10);
  joint(x, y, 8);
  joint(elbowX, elbowY, 7);
  joint(handX, handY, 9);
}

function drawLeg(x, y, side, torsoAngle) {
  const upperAngle = Math.PI / 2 - side * 0.28 + torsoAngle * 0.16;
  const lowerAngle = upperAngle + side * 0.18;
  const kneeX = x + Math.cos(upperAngle) * 112;
  const kneeY = y + Math.sin(upperAngle) * 112;
  const ankleX = kneeX + Math.cos(lowerAngle) * 105;
  const ankleY = kneeY + Math.sin(lowerAngle) * 105;
  line(x, y, kneeX, kneeY, 12);
  line(kneeX, kneeY, ankleX, ankleY, 11);
  joint(x, y, 8);
  joint(kneeX, kneeY, 8);
  joint(ankleX, ankleY, 7);
}

function drawFace(pose, shapes, radiusX) {
  const eyeSpread = Math.min(31, radiusX * 0.43);
  const gazeX = clamp(pose.gaze_x, -1, 1) * 11;
  const gazeY = clamp(pose.gaze_y, -1, 1) * 8;
  const squintLeft = shapes.get("eye_squint_left") || 0;
  const squintRight = shapes.get("eye_squint_right") || 0;
  const browRaise = shapes.get("brow_raise") || 0;
  const browLower = shapes.get("brow_lower") || 0;

  ctx.strokeStyle = "#dff9ff";
  ctx.fillStyle = "#dff9ff";
  ctx.lineWidth = 6;
  for (const side of [-1, 1]) {
    const openness = clamp(
      (side < 0 ? pose.eye_left_open : pose.eye_right_open)
      - (side < 0 ? squintLeft : squintRight) * 0.38,
      0,
      1,
    );
    const x = side * eyeSpread + gazeX;
    const y = -15 + gazeY;
    if (openness < 0.30) {
      ctx.beginPath();
      ctx.moveTo(x - 10, y);
      ctx.quadraticCurveTo(x, y + 4, x + 10, y);
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.ellipse(x, y, 5, Math.max(2, 8 * openness), 0, 0, Math.PI * 2);
      ctx.fill();
    }

    const browY = y - 22 - browRaise * 8 + browLower * 5;
    const browTilt = side * (browLower * 6 - browRaise * 2);
    ctx.beginPath();
    ctx.moveTo(x - 12, browY + browTilt);
    ctx.quadraticCurveTo(x, browY - 3, x + 12, browY - browTilt);
    ctx.stroke();
  }

  const mouthOpen = Math.max(Number(pose.mouth_open) || 0, shapes.get("jaw_open") || 0);
  const smile = Math.max(Number(pose.mouth_form) || 0, shapes.get("mouth_smile") || 0);
  const frown = Math.max(-(Number(pose.mouth_form) || 0), shapes.get("mouth_frown") || 0);
  ctx.beginPath();
  if (mouthOpen > 0.10) {
    ctx.ellipse(0, 29, 12 + smile * 5, 7 + mouthOpen * 17, 0, 0, Math.PI * 2);
  } else if (smile >= frown) {
    ctx.arc(0, 13, 23, 0.12 * Math.PI, 0.88 * Math.PI);
  } else {
    ctx.arc(0, 42, 21, 1.14 * Math.PI, 1.86 * Math.PI);
  }
  ctx.stroke();
}

function expressionLabel(frame) {
  const shapes = shapeMap(frame);
  const smile = Math.max(shapes.get("mouth_smile") || 0, Number(frame?.pose?.mouth_form) || 0);
  const frown = Math.max(shapes.get("mouth_frown") || 0, -(Number(frame?.pose?.mouth_form) || 0));
  if ((shapes.get("brow_lower") || 0) > 0.55 && frown > 0.35) return "怒り・不快";
  if ((shapes.get("brow_raise") || 0) > 0.55 && (shapes.get("jaw_open") || 0) > 0.35) return "驚き";
  if (smile > 0.38) return "喜び・微笑み";
  if (frown > 0.38) return "悲しみ・不安";
  return "穏やか・中立";
}

function drawBackground() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0, "rgba(33, 108, 137, .46)");
  gradient.addColorStop(1, "rgba(2, 11, 18, .96)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

function drawWaiting() {
  drawBackground();
  ctx.fillStyle = "rgba(225, 248, 255, .82)";
  ctx.font = "600 23px system-ui";
  ctx.textAlign = "center";
  ctx.fillText("CoreのBodyPoseFrameを待っています", canvas.width / 2, canvas.height / 2);
}

function drawFrame(frame) {
  drawBackground();
  const pose = frame?.pose;
  if (!pose) {
    drawWaiting();
    return;
  }
  const shapes = shapeMap(frame);
  const root = frame.root_transform?.position || {};
  const rootX = (Number(root.x) || 0) * 95;
  const rootY = -(Number(root.y) || 0) * 90;
  const waistX = canvas.width / 2 + rootX;
  const waistY = canvas.height * 0.58 - (Number(pose.body_height) || 0) * 46 + rootY;
  const torsoAngle = (Number(pose.torso_roll) || 0) * 0.27 + (Number(pose.torso_yaw) || 0) * 0.08;
  const shoulderOffset = rotatePoint(0, -120 + (Number(pose.torso_pitch) || 0) * 20, torsoAngle);
  const shoulderX = waistX + shoulderOffset.x;
  const shoulderY = waistY + shoulderOffset.y;
  const spread = rotatePoint(68, 0, torsoAngle);
  const leftShoulder = { x: shoulderX - spread.x, y: shoulderY - spread.y };
  const rightShoulder = { x: shoulderX + spread.x, y: shoulderY + spread.y };
  const hipSpread = rotatePoint(31, 78, torsoAngle * 0.55);
  const leftHip = { x: waistX - hipSpread.x, y: waistY + hipSpread.y };
  const rightHip = { x: waistX + hipSpread.x, y: waistY + hipSpread.y };

  ctx.save();
  ctx.shadowColor = "rgba(111, 222, 242, .42)";
  ctx.shadowBlur = 18;
  drawLeg(leftHip.x, leftHip.y, -1, torsoAngle);
  drawLeg(rightHip.x, rightHip.y, 1, torsoAngle);
  line(waistX, waistY, shoulderX, shoulderY, 14);
  line(leftShoulder.x, leftShoulder.y, rightShoulder.x, rightShoulder.y, 11);
  drawArm(leftShoulder.x, leftShoulder.y, -1, pose.left_arm_raise, pose.left_arm_in, torsoAngle);
  drawArm(rightShoulder.x, rightShoulder.y, 1, pose.right_arm_raise, pose.right_arm_in, torsoAngle);
  joint(waistX, waistY, 10);

  const headAngle = torsoAngle + (Number(pose.head_roll) || 0) * 0.34;
  const neck = rotatePoint(0, -35, headAngle);
  const neckX = shoulderX + neck.x;
  const neckY = shoulderY + neck.y;
  const radiusX = 70 * (1 - Math.abs(Number(pose.head_yaw) || 0) * 0.20);
  const radiusY = 74;
  const headOffset = rotatePoint(0, -(radiusY + 17), headAngle);
  const headX = neckX + headOffset.x;
  const headY = neckY + headOffset.y + (Number(pose.head_pitch) || 0) * 4;
  line(shoulderX, shoulderY, neckX, neckY, 10);

  ctx.save();
  ctx.translate(headX, headY);
  ctx.rotate(headAngle);
  ctx.strokeStyle = "#dff9ff";
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.ellipse(0, 0, radiusX, radiusY, 0, 0, Math.PI * 2);
  ctx.stroke();
  drawFace(pose, shapes, radiusX);
  ctx.restore();
  ctx.restore();
}

function applySnapshot(snapshot) {
  latestFrame = snapshot?.frame || null;
  latestReceivedAt = Number(snapshot?.received_at || 0) * 1000;
  const frame = latestFrame || {};
  sequenceNode.textContent = String(frame.sequence || 0);
  attentionNode.textContent = String(frame.attention_target_id || "ambient_scan");
  expressionNode.textContent = expressionLabel(frame);
  payloadNode.textContent = JSON.stringify(frame, null, 2);
  connection.textContent = "Core接続中";
  connection.classList.add("connected");
  drawFrame(frame);
}

function connect() {
  const events = new EventSource("/api/events");
  events.addEventListener("body-pose-frame", (event) => {
    try {
      applySnapshot(JSON.parse(event.data));
    } catch (error) {
      console.error(error);
    }
  });
  events.onerror = () => {
    connection.textContent = "再接続中";
    connection.classList.remove("connected");
  };
}

setInterval(() => {
  if (!latestReceivedAt) {
    ageNode.textContent = "-";
    return;
  }
  const age = Math.max(0, Date.now() - latestReceivedAt);
  ageNode.textContent = `${age} ms`;
  if (age > 3000) {
    connection.textContent = "Frame停止";
    connection.classList.remove("connected");
  }
}, 250);

window.addEventListener("resize", () => drawFrame(latestFrame));
drawWaiting();
connect();

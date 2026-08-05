const canvas = document.getElementById("avatar");
const context = canvas.getContext("2d");
const connectionNode = document.getElementById("connection");
const sequenceNode = document.getElementById("sequence");
const ageNode = document.getElementById("age");
const motionsNode = document.getElementById("motions");
const holdsNode = document.getElementById("holds");
const sourceNode = document.getElementById("source");
const payloadNode = document.getElementById("payload");

const links = [
  ["pelvis", "spine"],
  ["spine", "chest"],
  ["chest", "neck"],
  ["neck", "head"],
  ["chest", "left_shoulder"],
  ["left_shoulder", "left_elbow"],
  ["left_elbow", "left_hand"],
  ["chest", "right_shoulder"],
  ["right_shoulder", "right_elbow"],
  ["right_elbow", "right_hand"],
  ["pelvis", "left_hip"],
  ["left_hip", "left_knee"],
  ["left_knee", "left_ankle"],
  ["pelvis", "right_hip"],
  ["right_hip", "right_knee"],
  ["right_knee", "right_ankle"],
];

let latestReceivedAt = 0;
let latestFrame = null;

function screenPoint(point, root) {
  const scale = Math.min(canvas.width, canvas.height) * 0.29;
  const rootX = Number(root?.x || 0);
  const rootY = Number(root?.y || 0);
  return {
    x: canvas.width * 0.5 + (Number(point.x || 0) + rootX) * scale,
    y: canvas.height * 0.60 - (Number(point.y || 0) + rootY) * scale,
    z: Number(point.z || 0),
  };
}

function drawBackground() {
  context.clearRect(0, 0, canvas.width, canvas.height);
  const gradient = context.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0, "rgba(226, 247, 255, 0.98)");
  gradient.addColorStop(1, "rgba(15, 43, 67, 0.98)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "rgba(183, 231, 255, 0.20)";
  context.lineWidth = 1;
  for (let y = 80; y < canvas.height; y += 80) {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(canvas.width, y);
    context.stroke();
  }
}

function drawWaiting() {
  drawBackground();
  context.fillStyle = "rgba(239, 250, 255, 0.82)";
  context.font = "600 24px system-ui";
  context.textAlign = "center";
  context.fillText("Core BodyPoseFrameを待っています", canvas.width / 2, canvas.height / 2);
}

function drawFrame(frame) {
  drawBackground();
  const pose = frame?.kinematic_pose;
  if (!pose || !Array.isArray(pose.joints)) {
    drawWaiting();
    return;
  }
  const root = pose.root_position || { x: 0, y: 0, z: 0 };
  const points = new Map();
  for (const joint of pose.joints) {
    if (!joint || typeof joint.joint_id !== "string" || !joint.position) continue;
    points.set(joint.joint_id, screenPoint(joint.position, root));
  }

  context.lineCap = "round";
  context.lineJoin = "round";
  for (const [fromId, toId] of links) {
    const from = points.get(fromId);
    const to = points.get(toId);
    if (!from || !to) continue;
    const depth = Math.max(-1, Math.min(1, (from.z + to.z) * 0.5));
    context.strokeStyle = `rgba(226, 245, 255, ${0.72 + depth * 0.12})`;
    context.lineWidth = 11 + depth * 2;
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.stroke();
  }

  for (const [jointId, point] of points.entries()) {
    const endEffector = jointId.endsWith("hand") || jointId.endsWith("ankle") || jointId === "head";
    context.fillStyle = endEffector ? "#dff8ff" : "#89c9e8";
    context.strokeStyle = "rgba(8, 36, 57, 0.82)";
    context.lineWidth = 3;
    context.beginPath();
    context.arc(point.x, point.y, endEffector ? 13 : 9, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  }

  const head = points.get("head");
  if (head) {
    context.strokeStyle = "rgba(223, 248, 255, 0.95)";
    context.lineWidth = 6;
    context.beginPath();
    context.arc(head.x, head.y, 31, 0, Math.PI * 2);
    context.stroke();
  }
}

function applySnapshot(snapshot) {
  const frame = snapshot?.frame || {};
  latestReceivedAt = Number(snapshot?.received_at || 0) * 1000;
  latestFrame = frame;
  sequenceNode.textContent = String(frame.sequence || 0);
  motionsNode.textContent = Array.isArray(frame.active_motion_ids) && frame.active_motion_ids.length
    ? frame.active_motion_ids.join(", ")
    : "-";
  holdsNode.textContent = Array.isArray(frame.held_targets) && frame.held_targets.length
    ? frame.held_targets.join(", ")
    : "-";
  sourceNode.textContent = String(frame.source || "-");
  payloadNode.textContent = JSON.stringify(frame, null, 2);
  connectionNode.textContent = "Core接続中";
  connectionNode.classList.add("connected");
  drawFrame(frame);
}

function updateAge() {
  if (!latestReceivedAt) {
    ageNode.textContent = "-";
    return;
  }
  const age = Math.max(0, Date.now() - latestReceivedAt);
  ageNode.textContent = `${age} ms`;
  if (age > 3000) {
    connectionNode.textContent = "Frame停止";
    connectionNode.classList.remove("connected");
  }
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
    connectionNode.textContent = "再接続中";
    connectionNode.classList.remove("connected");
  };
}

window.addEventListener("resize", () => {
  if (latestFrame) drawFrame(latestFrame);
});

setInterval(updateAge, 250);
drawWaiting();
connect();

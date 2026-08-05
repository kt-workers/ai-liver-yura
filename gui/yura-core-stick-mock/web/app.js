let canvas = document.getElementById("canvas");
let ctx = canvas.getContext("2d");
const mainCanvas = canvas;
const mainCtx = ctx;
const floatingPreview = document.getElementById("floatingPreview");
const floatingCanvas = document.getElementById("floatingCanvas");
const floatingCtx = floatingCanvas.getContext("2d");
const stageCard = document.querySelector(".stage-card");
const connection = document.getElementById("connection");
const connectionText = document.getElementById("connectionText");
const trackingLabel = document.getElementById("trackingLabel");
const fpsValue = document.getElementById("fpsValue");
const attentionValue = document.getElementById("attentionValue");
const floatingAttention = document.getElementById("floatingAttention");
const sourceValue = document.getElementById("sourceValue");
const frameAgeValue = document.getElementById("frameAgeValue");
const schemaValue = document.getElementById("schemaValue");
const axisGrid = document.getElementById("axisGrid");
const payloadView = document.getElementById("payload");

let drawStickPerson = () => {};
let latestFrame = null;
let latestReceivedAt = 0;
let eventCount = 0;
let fpsWindowStarted = performance.now();
let mainStageVisible = true;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function rotatePoint(x, y, angle) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return {
    x: x * cosine - y * sine,
    y: x * sine + y * cosine,
  };
}

function line(x1, y1, x2, y2, width = 8) {
  ctx.strokeStyle = "#d8f8ff";
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function drawFace(pose, headRadiusX) {
  const gazeX = clamp(Number(pose.gaze_x) || 0, -1, 1);
  const gazeY = clamp(Number(pose.gaze_y) || 0, -1, 1);
  const leftOpen = clamp(Number(pose.eye_left_open) || 0, 0, 1);
  const rightOpen = clamp(Number(pose.eye_right_open) || 0, 0, 1);
  const eyeOffsetX = headRadiusX * 0.34;
  const eyeY = -5;
  const pupilX = gazeX * 8;
  const pupilY = gazeY * 6;

  ctx.save();
  ctx.strokeStyle = "#d8f8ff";
  ctx.fillStyle = "#d8f8ff";
  ctx.lineWidth = 6;
  for (const [side, openness] of [[-1, leftOpen], [1, rightOpen]]) {
    const x = side * eyeOffsetX;
    if (openness < 0.18) {
      line(x - 11, eyeY, x + 11, eyeY, 5);
      continue;
    }
    ctx.beginPath();
    ctx.ellipse(x, eyeY, 12, Math.max(3, 10 * openness), 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x + pupilX, eyeY + pupilY, 4.5, 0, Math.PI * 2);
    ctx.fill();
  }

  const mouthOpen = clamp(Number(pose.mouth_open) || 0, 0, 1);
  const mouthForm = clamp(Number(pose.mouth_form) || 0, -1, 1);
  ctx.beginPath();
  if (mouthOpen > 0.08) {
    ctx.ellipse(0, 34, 17, 4 + mouthOpen * 14, 0, 0, Math.PI * 2);
  } else {
    ctx.moveTo(-17, 34 - mouthForm * 4);
    ctx.quadraticCurveTo(0, 38 + mouthForm * 8, 17, 34 - mouthForm * 4);
  }
  ctx.stroke();
  ctx.restore();
}

function setConnection(state, text) {
  connection.dataset.state = state;
  connectionText.textContent = text;
}

const axisNames = [
  ["head_yaw", "Head Yaw"],
  ["head_pitch", "Head Pitch"],
  ["gaze_x", "Gaze X"],
  ["gaze_y", "Gaze Y"],
  ["torso_yaw", "Torso Yaw"],
  ["torso_pitch", "Torso Pitch"],
  ["torso_roll", "Torso Roll"],
  ["body_height", "Body Height"],
  ["left_arm_raise", "Left Arm"],
  ["right_arm_raise", "Right Arm"],
];

function updateAxisGrid(frame) {
  const pose = frame.pose || {};
  axisGrid.replaceChildren();
  for (const [name, label] of axisNames) {
    const value = Number(pose[name]) || 0;
    const row = document.createElement("div");
    row.className = "axis-row";
    const caption = document.createElement("span");
    caption.textContent = label;
    const meter = document.createElement("div");
    meter.className = "axis-meter";
    const fill = document.createElement("i");
    const normalized = name.includes("eye_") || name.includes("arm_raise")
      ? clamp(value, 0, 1)
      : (clamp(value, -1, 1) + 1) / 2;
    fill.style.width = `${normalized * 100}%`;
    meter.appendChild(fill);
    const output = document.createElement("b");
    output.textContent = value.toFixed(3);
    row.append(caption, meter, output);
    axisGrid.appendChild(row);
  }
}

function drawOn(targetCanvas, targetContext, frame) {
  const previousCanvas = canvas;
  const previousContext = ctx;
  canvas = targetCanvas;
  ctx = targetContext;
  try {
    drawStickPerson(frame);
  } finally {
    canvas = previousCanvas;
    ctx = previousContext;
  }
}

function render() {
  if (latestFrame) {
    drawOn(mainCanvas, mainCtx, latestFrame);
    if (!mainStageVisible) {
      drawOn(floatingCanvas, floatingCtx, latestFrame);
    }
  } else {
    mainCtx.clearRect(0, 0, mainCanvas.width, mainCanvas.height);
    mainCtx.fillStyle = "rgba(216,248,255,.72)";
    mainCtx.font = "28px sans-serif";
    mainCtx.textAlign = "center";
    mainCtx.fillText("Core BodyPoseFrame待機中", mainCanvas.width / 2, mainCanvas.height / 2);
  }
  requestAnimationFrame(render);
}

function setupStream() {
  const source = new EventSource("/api/frames");
  source.addEventListener("open", () => {
    if (!latestFrame) setConnection("waiting", "Core Frame待機中");
  });
  source.addEventListener("error", () => setConnection("error", "モックへ再接続中"));
  source.addEventListener("body-pose-frame", (event) => {
    try {
      latestFrame = JSON.parse(event.data);
      latestReceivedAt = performance.now();
      eventCount += 1;
      setConnection("connected", "Core接続済み");
      trackingLabel.textContent = `BodyPoseFrame #${latestFrame.sequence}`;
      const attention = latestFrame.attention_target_id || "ambient_scan";
      attentionValue.textContent = attention;
      floatingAttention.textContent = attention;
      sourceValue.textContent = latestFrame.source || "yura-core";
      schemaValue.textContent = String(latestFrame.schema_version ?? "-");
      payloadView.textContent = JSON.stringify(latestFrame, null, 2);
      updateAxisGrid(latestFrame);
    } catch (error) {
      setConnection("error", `Frame解析失敗: ${error.message}`);
    }
  });
}

function setupFloatingPreview() {
  const observer = new IntersectionObserver(
    ([entry]) => {
      mainStageVisible = entry.isIntersecting;
      floatingPreview.classList.toggle("visible", !mainStageVisible);
      floatingPreview.setAttribute("aria-hidden", mainStageVisible ? "true" : "false");
    },
    { threshold: 0.16 },
  );
  observer.observe(stageCard);
}

window.setInterval(() => {
  const now = performance.now();
  const elapsed = now - fpsWindowStarted;
  if (elapsed >= 1000) {
    fpsValue.textContent = String(Math.round(eventCount * 1000 / elapsed));
    eventCount = 0;
    fpsWindowStarted = now;
  }
  if (latestReceivedAt > 0) {
    const age = Math.round(now - latestReceivedAt);
    frameAgeValue.textContent = `${age} ms`;
    if (age > 2500) setConnection("waiting", "Core Frame停止中");
  }
}, 250);

setupStream();
setupFloatingPreview();
render();

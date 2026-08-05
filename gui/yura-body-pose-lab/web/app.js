const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const connection = document.getElementById("connection");
const connectionText = document.getElementById("connectionText");
const trackingLabel = document.getElementById("trackingLabel");
const fpsValue = document.getElementById("fpsValue");
const attentionValue = document.getElementById("attentionValue");
const axisGrid = document.getElementById("axisGrid");
const payloadView = document.getElementById("payload");
const slidersRoot = document.getElementById("sliders");
const candidateControls = document.getElementById("candidateControls");
const targetLayer = document.getElementById("targetLayer");

const stateDefinitions = [
  ["arousal", "覚醒度"],
  ["tension", "緊張"],
  ["curiosity", "好奇心"],
  ["confidence", "自信"],
  ["engagement", "関与"],
  ["avoidance", "回避"],
  ["movement_energy", "運動エネルギー"],
];

const presets = {
  calm: {
    arousal: 0.22,
    tension: 0.08,
    curiosity: 0.32,
    confidence: 0.62,
    engagement: 0.48,
    avoidance: 0.04,
    movement_energy: 0.22,
  },
  curious: {
    arousal: 0.58,
    tension: 0.18,
    curiosity: 0.94,
    confidence: 0.58,
    engagement: 0.72,
    avoidance: 0.03,
    movement_energy: 0.62,
  },
  nervous: {
    arousal: 0.72,
    tension: 0.91,
    curiosity: 0.46,
    confidence: 0.22,
    engagement: 0.44,
    avoidance: 0.58,
    movement_energy: 0.48,
  },
  engaged: {
    arousal: 0.52,
    tension: 0.16,
    curiosity: 0.68,
    confidence: 0.72,
    engagement: 0.96,
    avoidance: 0.01,
    movement_energy: 0.55,
  },
};

const stateValues = { ...presets.calm };

const candidates = [
  {
    candidate_id: "viewer",
    label: "会話相手",
    enabled: true,
    x: 0,
    y: 0,
    salience: 0.72,
    novelty: 0.05,
    threat: 0,
    relevance: 1,
    stability: 0.94,
  },
  {
    candidate_id: "left_light",
    label: "左の光",
    enabled: true,
    x: -0.78,
    y: -0.24,
    salience: 0.46,
    novelty: 0.82,
    threat: 0,
    relevance: 0.26,
    stability: 0.42,
  },
  {
    candidate_id: "right_sound",
    label: "右の物音",
    enabled: true,
    x: 0.82,
    y: 0.1,
    salience: 0.58,
    novelty: 0.48,
    threat: 0.34,
    relevance: 0.34,
    stability: 0.32,
  },
];

let latestFrame = null;
let eventCount = 0;
let fpsWindowStarted = performance.now();
let lastPayloadUpdate = 0;
let postStateTimer = null;
let postCandidatesTimer = null;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function createSlider(name, label, value, onInput) {
  const row = document.createElement("div");
  row.className = "slider-row";
  const caption = document.createElement("label");
  caption.htmlFor = `slider-${name}`;
  caption.textContent = label;
  const input = document.createElement("input");
  input.id = `slider-${name}`;
  input.type = "range";
  input.min = "0";
  input.max = "1";
  input.step = "0.01";
  input.value = String(value);
  const output = document.createElement("output");
  output.textContent = Number(value).toFixed(2);
  input.addEventListener("input", () => {
    const next = Number(input.value);
    output.textContent = next.toFixed(2);
    onInput(next);
  });
  row.append(caption, input, output);
  return { row, input, output };
}

const sliderBindings = {};
for (const [name, label] of stateDefinitions) {
  const binding = createSlider(name, label, stateValues[name], (value) => {
    stateValues[name] = value;
    scheduleStatePost();
  });
  slidersRoot.appendChild(binding.row);
  sliderBindings[name] = binding;
}

for (const button of document.querySelectorAll("[data-preset]")) {
  button.addEventListener("click", () => {
    const preset = presets[button.dataset.preset];
    if (!preset) return;
    Object.assign(stateValues, preset);
    for (const [name] of stateDefinitions) {
      sliderBindings[name].input.value = String(stateValues[name]);
      sliderBindings[name].output.textContent = stateValues[name].toFixed(2);
    }
    scheduleStatePost(true);
  });
}

function candidateField(candidate, name, label) {
  const field = document.createElement("div");
  field.className = "mini-field";
  const caption = document.createElement("span");
  caption.textContent = label;
  const input = document.createElement("input");
  input.type = "range";
  input.min = "0";
  input.max = "1";
  input.step = "0.01";
  input.value = String(candidate[name]);
  input.addEventListener("input", () => {
    candidate[name] = Number(input.value);
    scheduleCandidatesPost();
  });
  field.append(caption, input);
  return field;
}

function buildCandidateControls() {
  candidateControls.replaceChildren();
  targetLayer.replaceChildren();
  for (const candidate of candidates) {
    const card = document.createElement("div");
    card.className = "candidate-card";
    const title = document.createElement("div");
    title.className = "candidate-title";
    const label = document.createElement("label");
    label.textContent = candidate.label;
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = candidate.enabled;
    enabled.addEventListener("change", () => {
      candidate.enabled = enabled.checked;
      marker.hidden = !candidate.enabled;
      scheduleCandidatesPost(true);
    });
    title.append(label, enabled);
    const fields = document.createElement("div");
    fields.className = "candidate-fields";
    fields.append(
      candidateField(candidate, "salience", "顕著性"),
      candidateField(candidate, "novelty", "新規性"),
      candidateField(candidate, "threat", "脅威度"),
      candidateField(candidate, "relevance", "関連度"),
      candidateField(candidate, "stability", "安定性"),
    );
    card.append(title, fields);
    candidateControls.appendChild(card);

    const marker = document.createElement("div");
    marker.className = "target-dot";
    marker.dataset.candidateId = candidate.candidate_id;
    marker.style.left = `${50 + candidate.x * 42}%`;
    marker.style.top = `${50 + candidate.y * 42}%`;
    marker.hidden = !candidate.enabled;
    const markerLabel = document.createElement("span");
    markerLabel.textContent = candidate.label;
    marker.appendChild(markerLabel);
    targetLayer.appendChild(marker);
  }
}

buildCandidateControls();

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status}: ${text}`);
  }
  return response.json();
}

function scheduleStatePost(immediate = false) {
  window.clearTimeout(postStateTimer);
  postStateTimer = window.setTimeout(async () => {
    try {
      await postJson("/api/state", stateValues);
    } catch (error) {
      setConnection("error", `状態送信失敗: ${error.message}`);
    }
  }, immediate ? 0 : 90);
}

function scheduleCandidatesPost(immediate = false) {
  window.clearTimeout(postCandidatesTimer);
  postCandidatesTimer = window.setTimeout(async () => {
    try {
      const enabled = candidates
        .filter((candidate) => candidate.enabled)
        .map(({ label, enabled: _enabled, ...candidate }) => candidate);
      await postJson("/api/candidates", enabled);
    } catch (error) {
      setConnection("error", `候補送信失敗: ${error.message}`);
    }
  }, immediate ? 0 : 120);
}

function setConnection(state, text) {
  connection.dataset.state = state;
  connectionText.textContent = text;
}

function setupStream() {
  const source = new EventSource("/api/frames");
  source.addEventListener("open", () => setConnection("connected", "接続済み"));
  source.addEventListener("error", () => setConnection("error", "再接続中"));
  source.addEventListener("body-pose-frame", (event) => {
    try {
      latestFrame = JSON.parse(event.data);
      eventCount += 1;
      trackingLabel.textContent = `BodyPoseFrame #${latestFrame.sequence}`;
      attentionValue.textContent = latestFrame.attention_target_id || "ambient_scan";
      updateTargetMarkers(latestFrame.attention_target_id);
      updateAxisGrid(latestFrame);
      const now = performance.now();
      if (now - lastPayloadUpdate > 300) {
        payloadView.textContent = JSON.stringify(latestFrame, null, 2);
        lastPayloadUpdate = now;
      }
    } catch (error) {
      setConnection("error", `Frame解析失敗: ${error.message}`);
    }
  });
}

function updateTargetMarkers(activeId) {
  for (const marker of targetLayer.querySelectorAll(".target-dot")) {
    marker.classList.toggle("active", marker.dataset.candidateId === activeId);
  }
}

const axisNames = [
  ["head_yaw", "Head Yaw"],
  ["head_pitch", "Head Pitch"],
  ["gaze_x", "Gaze X"],
  ["gaze_y", "Gaze Y"],
  ["torso_yaw", "Torso Yaw"],
  ["torso_roll", "Torso Roll"],
  ["body_height", "Body Height"],
  ["left_arm_raise", "Left Arm"],
  ["right_arm_raise", "Right Arm"],
  ["eye_left_open", "Eye Open"],
];

function updateAxisGrid(frame) {
  if (!frame?.pose) return;
  const values = axisNames.map(([name, label]) => [label, frame.pose[name] ?? 0]);
  values.push(["3D Joints", frame.joints?.length ?? 0]);
  values.push(["BlendShapes", frame.blend_shapes?.length ?? 0]);
  axisGrid.replaceChildren(...values.map(([label, value]) => {
    const item = document.createElement("div");
    item.className = "axis-item";
    const caption = document.createElement("span");
    caption.textContent = label;
    const number = document.createElement("b");
    number.textContent = typeof value === "number" && !Number.isInteger(value)
      ? value.toFixed(3)
      : String(value);
    item.append(caption, number);
    return item;
  }));
}

function rotatePoint(x, y, angle) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return { x: x * cosine - y * sine, y: x * sine + y * cosine };
}

function line(x1, y1, x2, y2, width = 9, alpha = 1) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = "#d8f8ff";
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.restore();
}

function drawStickPerson(frame) {
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  if (!frame?.pose) return;
  const pose = frame.pose;
  const centerX = width / 2;
  const hipY = height * 0.72 - pose.body_height * 46;
  const torsoAngle = pose.torso_roll * 0.26 + pose.torso_yaw * 0.08;
  const torsoLength = 190;
  const torsoOffset = rotatePoint(0, -torsoLength, torsoAngle);
  const shoulderX = centerX + torsoOffset.x;
  const shoulderY = hipY + torsoOffset.y + pose.torso_pitch * 30;
  const headAngle = torsoAngle + pose.head_roll * 0.34;
  const neckOffset = rotatePoint(pose.head_yaw * 20, -52 - pose.head_pitch * 10, headAngle);
  const headX = shoulderX + neckOffset.x;
  const headY = shoulderY + neckOffset.y;
  const headRadiusX = 72 * (1 - Math.abs(pose.head_yaw) * 0.22);
  const headRadiusY = 76;

  ctx.save();
  ctx.shadowColor = "rgba(111, 222, 242, .42)";
  ctx.shadowBlur = 18;
  line(centerX, hipY, shoulderX, shoulderY, 13);

  const leftShoulder = rotatePoint(-63, 4, torsoAngle);
  const rightShoulder = rotatePoint(63, 4, torsoAngle);
  const leftShoulderX = shoulderX + leftShoulder.x;
  const leftShoulderY = shoulderY + leftShoulder.y;
  const rightShoulderX = shoulderX + rightShoulder.x;
  const rightShoulderY = shoulderY + rightShoulder.y;

  drawArm(
    leftShoulderX,
    leftShoulderY,
    -1,
    pose.left_arm_raise,
    pose.left_arm_in,
    torsoAngle,
  );
  drawArm(
    rightShoulderX,
    rightShoulderY,
    1,
    pose.right_arm_raise,
    pose.right_arm_in,
    torsoAngle,
  );

  const leftLegEnd = rotatePoint(-76, 190, torsoAngle * 0.25);
  const rightLegEnd = rotatePoint(76, 190, torsoAngle * 0.25);
  line(centerX, hipY, centerX + leftLegEnd.x, hipY + leftLegEnd.y, 12);
  line(centerX, hipY, centerX + rightLegEnd.x, hipY + rightLegEnd.y, 12);

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
}

function drawArm(x, y, side, raise, inward, torsoAngle) {
  const liftAngle = raise * Math.PI * 0.9;
  const baseAngle = side > 0 ? 0.48 : Math.PI - 0.48;
  const angle = baseAngle + side * liftAngle - side * inward * 0.42 + torsoAngle;
  const upperLength = 110;
  const lowerLength = 98;
  const elbowX = x + Math.cos(angle) * upperLength;
  const elbowY = y + Math.sin(angle) * upperLength;
  const forearmAngle = angle + side * (0.14 + inward * 0.18);
  const handX = elbowX + Math.cos(forearmAngle) * lowerLength;
  const handY = elbowY + Math.sin(forearmAngle) * lowerLength;
  line(x, y, elbowX, elbowY, 11);
  line(elbowX, elbowY, handX, handY, 10);
  ctx.fillStyle = "#d8f8ff";
  ctx.beginPath();
  ctx.arc(handX, handY, 11, 0, Math.PI * 2);
  ctx.fill();
}

function drawFace(pose, headRadiusX) {
  const eyeSpread = Math.min(30, headRadiusX * 0.42);
  const eyeY = -15;
  const gazeX = pose.gaze_x * 12;
  const gazeY = pose.gaze_y * 9;
  ctx.strokeStyle = "#d8f8ff";
  ctx.fillStyle = "#d8f8ff";
  ctx.lineWidth = 7;
  for (const side of [-1, 1]) {
    const openness = side < 0 ? pose.eye_left_open : pose.eye_right_open;
    const x = side * eyeSpread + gazeX;
    const y = eyeY + gazeY;
    if (openness < 0.35) {
      ctx.beginPath();
      ctx.moveTo(x - 9, y);
      ctx.quadraticCurveTo(x, y + 4, x + 9, y);
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.ellipse(x, y, 5, Math.max(2, 7 * openness), 0, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.beginPath();
  if (pose.mouth_open > 0.08) {
    ctx.ellipse(0, 27, 13, 8 + pose.mouth_open * 18, 0, 0, Math.PI * 2);
  } else if (pose.mouth_form >= 0) {
    ctx.arc(0, 14, 22, 0.12 * Math.PI, 0.88 * Math.PI);
  } else {
    ctx.arc(0, 40, 20, 1.15 * Math.PI, 1.85 * Math.PI);
  }
  ctx.stroke();
}

function animationLoop() {
  drawStickPerson(latestFrame);
  const now = performance.now();
  if (now - fpsWindowStarted >= 1000) {
    fpsValue.textContent = String(Math.round(eventCount * 1000 / (now - fpsWindowStarted)));
    eventCount = 0;
    fpsWindowStarted = now;
  }
  requestAnimationFrame(animationLoop);
}

scheduleStatePost(true);
scheduleCandidatesPost(true);
setupStream();
requestAnimationFrame(animationLoop);

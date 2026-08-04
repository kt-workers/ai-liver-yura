const canvas = document.getElementById("avatarCanvas");
const context = canvas.getContext("2d");
const connection = document.getElementById("connection");
const connectionText = document.getElementById("connectionText");
const expressionValue = document.getElementById("expressionValue");
const gestureValue = document.getElementById("gestureValue");
const gazeValue = document.getElementById("gazeValue");
const receivedValue = document.getElementById("receivedValue");
const sequenceLabel = document.getElementById("sequenceLabel");
const performanceLabel = document.getElementById("performanceLabel");
const payloadView = document.getElementById("payloadView");
const historyList = document.getElementById("historyList");
const historyCount = document.getElementById("historyCount");

const model = {
  expression: "neutral",
  gesture: null,
  gaze: { target: "neutral", behavior: "maintain", intensity: 1 },
  gestureStartedAt: 0,
  gestureDuration: 1500,
  sequence: 0,
};

const gestureDurations = {
  small_nod: 900,
  head_tilt: 1400,
  wave: 1900,
  lean_forward: 1400,
  bounce: 1200,
};

function setConnection(state, text) {
  connection.dataset.state = state;
  connectionText.textContent = text;
}

function applyState(state) {
  if (!state || typeof state !== "object") return;
  model.expression = state.expression || "neutral";
  if (state.gesture && (state.sequence !== model.sequence || state.gesture !== model.gesture)) {
    model.gesture = state.gesture;
    model.gestureStartedAt = performance.now();
    model.gestureDuration = gestureDurations[state.gesture] || 1500;
  }
  model.gaze = state.gaze || model.gaze;
  model.sequence = Number(state.sequence || 0);

  expressionValue.textContent = model.expression;
  gestureValue.textContent = model.gesture || "idle";
  gazeValue.textContent = model.gaze.target || "neutral";
  sequenceLabel.textContent = `#${model.sequence}`;
  performanceLabel.textContent = `${model.expression} / ${model.gesture || "idle"} / ${model.gaze.target || "neutral"}`;
  receivedValue.textContent = state.received_at ? formatTime(state.received_at) : "未受信";
  payloadView.textContent = JSON.stringify(state.latest_action || { status: "waiting" }, null, 2);
  renderHistory(Array.isArray(state.history) ? state.history : []);
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function renderHistory(items) {
  historyCount.textContent = `${items.length} actions`;
  if (!items.length) {
    historyList.innerHTML = '<p class="empty-state">CoreまたはプリセットからActionが届くと、ここに表示されます。</p>';
    return;
  }
  historyList.replaceChildren(...items.map((item) => {
    const row = document.createElement("div");
    row.className = "history-item";
    const action = item.action || {};
    const summary = action.action === "gaze"
      ? `${action.target} / ${action.behavior}`
      : action.name || "-";
    const sequence = document.createElement("span");
    sequence.className = "history-sequence";
    sequence.textContent = `#${item.sequence}`;
    const type = document.createElement("span");
    type.className = "history-type";
    type.textContent = action.action || "unknown";
    const code = document.createElement("code");
    code.textContent = summary;
    const time = document.createElement("span");
    time.className = "history-time";
    time.textContent = formatTime(item.received_at);
    row.append(sequence, type, code, time);
    return row;
  }));
}

async function loadInitialState() {
  try {
    const response = await fetch("/api/avatar/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    applyState(await response.json());
  } catch (error) {
    console.error("initial state failed", error);
  }
}

function connectEvents() {
  setConnection("connecting", "接続中");
  const source = new EventSource("/api/avatar/events");
  source.addEventListener("open", () => setConnection("connected", "接続済み"));
  source.addEventListener("avatar-state", (event) => {
    setConnection("connected", "接続済み");
    try {
      applyState(JSON.parse(event.data));
    } catch (error) {
      console.error("invalid avatar state", error);
    }
  });
  source.addEventListener("error", () => {
    setConnection("error", "再接続中");
  });
}

async function sendAction(action, name) {
  const payload = {
    schema_version: 1,
    type: "avatar.action",
    action,
    intensity: 1,
  };
  if (action === "gaze") {
    payload.target = name;
    payload.behavior = name === "away" ? "glance" : "maintain";
  } else {
    payload.name = name;
  }

  const response = await fetch("/api/avatar/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Action rejected: ${response.status} ${body}`);
  }
}

for (const button of document.querySelectorAll("button[data-action]")) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await sendAction(button.dataset.action, button.dataset.name);
    } catch (error) {
      console.error(error);
      setConnection("error", "送信失敗");
    } finally {
      button.disabled = false;
    }
  });
}

document.getElementById("randomButton").addEventListener("click", async () => {
  const expressions = ["neutral", "happy", "sad", "surprised", "angry", "curious"];
  const gestures = ["small_nod", "head_tilt", "wave", "lean_forward", "bounce"];
  const gazes = ["viewer", "left", "right", "up", "down", "away"];
  try {
    await sendAction("expression", choose(expressions));
    await new Promise((resolve) => setTimeout(resolve, 120));
    await sendAction("gesture", choose(gestures));
    await new Promise((resolve) => setTimeout(resolve, 120));
    await sendAction("gaze", choose(gazes));
  } catch (error) {
    console.error(error);
    setConnection("error", "送信失敗");
  }
});

function choose(values) {
  return values[Math.floor(Math.random() * values.length)];
}

function gesturePose(now) {
  if (!model.gesture) return { progress: 1, active: false };
  const elapsed = now - model.gestureStartedAt;
  const progress = Math.min(1, Math.max(0, elapsed / model.gestureDuration));
  if (progress >= 1) {
    model.gesture = null;
    gestureValue.textContent = "idle";
    performanceLabel.textContent = `${model.expression} / idle / ${model.gaze.target || "neutral"}`;
    return { progress: 1, active: false };
  }
  return { progress, active: true };
}

function easeInOut(value) {
  return value < 0.5
    ? 2 * value * value
    : 1 - Math.pow(-2 * value + 2, 2) / 2;
}

function pulse(progress, count = 1) {
  return Math.sin(progress * Math.PI * 2 * count);
}

function draw(now) {
  const width = canvas.width;
  const height = canvas.height;
  context.clearRect(0, 0, width, height);

  const time = now / 1000;
  const idleY = Math.sin(time * 1.55) * 4;
  const pose = gesturePose(now);
  let bodyX = width / 2;
  let bodyY = height * 0.55 + idleY;
  let bodyRotation = 0;
  let headRotation = 0;
  let headOffsetY = 0;
  let rightArmLift = 0;
  let rightArmWave = 0;

  if (pose.active) {
    const p = easeInOut(pose.progress);
    switch (model.gesture) {
      case "small_nod":
        headOffsetY = Math.sin(p * Math.PI * 2) * 18;
        headRotation = Math.sin(p * Math.PI * 2) * 0.06;
        break;
      case "head_tilt":
        headRotation = Math.sin(p * Math.PI) * -0.28;
        break;
      case "wave":
        rightArmLift = Math.sin(p * Math.PI) * 1.05;
        rightArmWave = pulse(p, 3) * 0.32;
        break;
      case "lean_forward":
        bodyRotation = Math.sin(p * Math.PI) * -0.14;
        bodyY += Math.sin(p * Math.PI) * 14;
        break;
      case "bounce":
        bodyY -= Math.abs(pulse(p, 2)) * 45;
        break;
    }
  }

  drawFloor(width, height, time);
  context.save();
  context.translate(bodyX, bodyY);
  context.rotate(bodyRotation);
  drawBody(time, headRotation, headOffsetY, rightArmLift, rightArmWave);
  context.restore();

  requestAnimationFrame(draw);
}

function drawFloor(width, height, time) {
  context.save();
  const gradient = context.createRadialGradient(
    width / 2, height * 0.82, 20,
    width / 2, height * 0.82, width * 0.34,
  );
  gradient.addColorStop(0, "rgba(148, 235, 255, 0.22)");
  gradient.addColorStop(1, "rgba(148, 235, 255, 0)");
  context.fillStyle = gradient;
  context.beginPath();
  context.ellipse(width / 2, height * 0.82, width * 0.28, 40 + Math.sin(time) * 2, 0, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function drawBody(time, headRotation, headOffsetY, rightArmLift, rightArmWave) {
  const ink = "#d8f7ff";
  const soft = "rgba(216, 247, 255, 0.72)";
  context.strokeStyle = ink;
  context.fillStyle = ink;
  context.lineWidth = 15;
  context.lineCap = "round";
  context.lineJoin = "round";

  const shoulderY = -58;
  const hipY = 95;
  const headY = -178 + headOffsetY;
  const breath = Math.sin(time * 1.55) * 3;

  context.beginPath();
  context.moveTo(0, shoulderY);
  context.quadraticCurveTo(breath * 0.35, 20, 0, hipY);
  context.stroke();

  drawLimb(0, shoulderY, -78, 15, -112, 92);
  if (rightArmLift > 0) {
    const elbowX = 55 + rightArmLift * 42;
    const elbowY = -78 - rightArmLift * 65;
    const handX = 90 + rightArmLift * 28 + Math.sin(rightArmWave) * 18;
    const handY = -125 - rightArmLift * 115;
    drawLimb(0, shoulderY, elbowX, elbowY, handX, handY);
    drawHand(handX, handY, rightArmWave);
  } else {
    drawLimb(0, shoulderY, 78, 15, 112, 92);
  }

  drawLimb(0, hipY, -50, 170, -72, 255);
  drawLimb(0, hipY, 50, 170, 72, 255);

  context.save();
  context.translate(0, headY);
  context.rotate(headRotation);
  context.lineWidth = 12;
  context.fillStyle = "rgba(7, 25, 36, 0.94)";
  context.strokeStyle = ink;
  context.beginPath();
  context.arc(0, 0, 74, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  drawFace(soft);
  context.restore();
}

function drawLimb(startX, startY, jointX, jointY, endX, endY) {
  context.beginPath();
  context.moveTo(startX, startY);
  context.quadraticCurveTo(jointX, jointY, endX, endY);
  context.stroke();
}

function drawHand(x, y, wave) {
  context.save();
  context.translate(x, y);
  context.rotate(wave);
  context.lineWidth = 7;
  for (let index = -1; index <= 1; index += 1) {
    context.beginPath();
    context.moveTo(0, 0);
    context.lineTo(index * 11, -25 - Math.abs(index) * 3);
    context.stroke();
  }
  context.restore();
}

function gazeOffset() {
  const intensity = Math.max(0, Math.min(1, Number(model.gaze.intensity ?? 1)));
  const amount = 10 * intensity;
  switch (model.gaze.target) {
    case "left": return { x: -amount, y: 0 };
    case "right": return { x: amount, y: 0 };
    case "up": return { x: 0, y: -amount };
    case "down": return { x: 0, y: amount };
    case "away": return { x: -amount * 0.8, y: amount * 0.35 };
    default: return { x: 0, y: 0 };
  }
}

function drawFace(soft) {
  const gaze = gazeOffset();
  const eyeY = -13;
  const eyeSpread = 27;
  context.fillStyle = soft;

  if (model.expression === "happy") {
    context.strokeStyle = soft;
    context.lineWidth = 7;
    for (const direction of [-1, 1]) {
      context.beginPath();
      context.arc(direction * eyeSpread, eyeY + 5, 11, Math.PI * 1.1, Math.PI * 1.9);
      context.stroke();
    }
  } else if (model.expression === "surprised") {
    for (const direction of [-1, 1]) {
      context.beginPath();
      context.arc(direction * eyeSpread + gaze.x, eyeY + gaze.y, 8, 0, Math.PI * 2);
      context.fill();
    }
  } else {
    for (const direction of [-1, 1]) {
      context.beginPath();
      context.arc(direction * eyeSpread + gaze.x, eyeY + gaze.y, model.expression === "sad" ? 5 : 7, 0, Math.PI * 2);
      context.fill();
    }
  }

  context.strokeStyle = soft;
  context.lineWidth = 7;
  context.beginPath();
  switch (model.expression) {
    case "happy":
      context.arc(0, 12, 25, 0.12 * Math.PI, 0.88 * Math.PI);
      break;
    case "sad":
      context.arc(0, 42, 23, 1.15 * Math.PI, 1.85 * Math.PI);
      break;
    case "surprised":
      context.arc(0, 25, 12, 0, Math.PI * 2);
      break;
    case "angry":
      context.moveTo(-24, 26);
      context.lineTo(24, 26);
      break;
    case "curious":
      context.arc(5, 18, 18, 0.08 * Math.PI, 0.75 * Math.PI);
      break;
    default:
      context.moveTo(-20, 25);
      context.quadraticCurveTo(0, 31, 20, 25);
  }
  context.stroke();

  if (model.expression === "angry" || model.expression === "curious") {
    context.lineWidth = 6;
    context.beginPath();
    if (model.expression === "angry") {
      context.moveTo(-39, -38);
      context.lineTo(-15, -29);
      context.moveTo(39, -38);
      context.lineTo(15, -29);
    } else {
      context.moveTo(-38, -31);
      context.lineTo(-17, -33);
      context.moveTo(15, -38);
      context.lineTo(39, -27);
    }
    context.stroke();
  }
}

loadInitialState();
connectEvents();
requestAnimationFrame(draw);

const canvas = document.getElementById("avatarCanvas");
const ctx = canvas.getContext("2d");
const elements = {
  connection: document.getElementById("connection"),
  connectionText: document.getElementById("connectionText"),
  expression: document.getElementById("expressionValue"),
  gesture: document.getElementById("gestureValue"),
  gaze: document.getElementById("gazeValue"),
  received: document.getElementById("receivedValue"),
  sequence: document.getElementById("sequenceLabel"),
  performance: document.getElementById("performanceLabel"),
  payload: document.getElementById("payloadView"),
  history: document.getElementById("historyList"),
  historyCount: document.getElementById("historyCount"),
};

const state = {
  expression: "neutral",
  gesture: null,
  gaze: { target: "neutral", behavior: "maintain", intensity: 1 },
  sequence: 0,
  gestureStartedAt: 0,
  gestureDuration: 1400,
};

const gestureDurations = {
  small_nod: 900,
  head_tilt: 1400,
  wave: 1900,
  lean_forward: 1400,
  bounce: 1200,
};

function setConnection(status, text) {
  elements.connection.dataset.state = status;
  elements.connectionText.textContent = text;
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

function applyRuntimeState(runtimeState) {
  if (!runtimeState || typeof runtimeState !== "object") return;
  const sequence = Number(runtimeState.sequence || 0);
  const action = runtimeState.latest_action || {};
  const isNewAction = sequence > state.sequence;

  state.expression = runtimeState.expression || "neutral";
  state.gaze = runtimeState.gaze || state.gaze;
  if (isNewAction && action.action === "gesture" && runtimeState.gesture) {
    state.gesture = runtimeState.gesture;
    state.gestureStartedAt = performance.now();
    state.gestureDuration = gestureDurations[state.gesture] || 1400;
  }
  state.sequence = sequence;

  elements.expression.textContent = state.expression;
  elements.gesture.textContent = state.gesture || "idle";
  elements.gaze.textContent = state.gaze.target || "neutral";
  elements.received.textContent = runtimeState.received_at
    ? formatTime(runtimeState.received_at)
    : "未受信";
  elements.sequence.textContent = `#${state.sequence}`;
  elements.performance.textContent = `${state.expression} / ${state.gesture || "idle"} / ${state.gaze.target || "neutral"}`;
  elements.payload.textContent = JSON.stringify(
    action.action ? action : { status: "waiting" },
    null,
    2,
  );
  renderHistory(Array.isArray(runtimeState.history) ? runtimeState.history : []);
}

function renderHistory(items) {
  elements.historyCount.textContent = `${items.length} actions`;
  if (!items.length) {
    elements.history.innerHTML = '<p class="empty-state">CoreまたはプリセットからActionが届くと、ここに表示されます。</p>';
    return;
  }

  elements.history.replaceChildren(...items.map((item) => {
    const action = item.action || {};
    const row = document.createElement("div");
    row.className = "history-item";

    const sequence = document.createElement("span");
    sequence.className = "history-sequence";
    sequence.textContent = `#${item.sequence}`;

    const type = document.createElement("span");
    type.className = "history-type";
    type.textContent = action.action || "unknown";

    const summary = document.createElement("code");
    summary.textContent = action.action === "gaze"
      ? `${action.target} / ${action.behavior}`
      : action.name || "-";

    const time = document.createElement("span");
    time.className = "history-time";
    time.textContent = formatTime(item.received_at);

    row.append(sequence, type, summary, time);
    return row;
  }));
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
    throw new Error(`Action rejected: HTTP ${response.status}`);
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
  const choose = (values) => values[Math.floor(Math.random() * values.length)];
  try {
    await sendAction("expression", choose([
      "neutral", "happy", "sad", "surprised", "angry", "curious",
    ]));
    await sendAction("gesture", choose([
      "small_nod", "head_tilt", "wave", "lean_forward", "bounce",
    ]));
    await sendAction("gaze", choose([
      "viewer", "left", "right", "up", "down", "away",
    ]));
  } catch (error) {
    console.error(error);
    setConnection("error", "送信失敗");
  }
});

async function loadInitialState() {
  try {
    const response = await fetch("/api/avatar/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    applyRuntimeState(await response.json());
  } catch (error) {
    console.error(error);
    setConnection("error", "状態取得失敗");
  }
}

function connectEvents() {
  setConnection("connecting", "接続中");
  const source = new EventSource("/api/avatar/events");
  source.addEventListener("open", () => setConnection("connected", "接続済み"));
  source.addEventListener("avatar-state", (event) => {
    try {
      applyRuntimeState(JSON.parse(event.data));
      setConnection("connected", "接続済み");
    } catch (error) {
      console.error(error);
    }
  });
  source.addEventListener("error", () => setConnection("error", "再接続中"));
}

function gestureProgress(now) {
  if (!state.gesture) return null;
  const progress = Math.min(
    1,
    Math.max(0, (now - state.gestureStartedAt) / state.gestureDuration),
  );
  if (progress >= 1) {
    state.gesture = null;
    elements.gesture.textContent = "idle";
    elements.performance.textContent = `${state.expression} / idle / ${state.gaze.target || "neutral"}`;
    return null;
  }
  return progress;
}

function gazeOffset() {
  const amount = 10 * Math.max(0, Math.min(1, Number(state.gaze.intensity ?? 1)));
  switch (state.gaze.target) {
    case "left": return { x: -amount, y: 0 };
    case "right": return { x: amount, y: 0 };
    case "up": return { x: 0, y: -amount };
    case "down": return { x: 0, y: amount };
    case "away": return { x: -amount * 0.8, y: amount * 0.35 };
    default: return { x: 0, y: 0 };
  }
}

function drawLimb(startX, startY, controlX, controlY, endX, endY) {
  ctx.beginPath();
  ctx.moveTo(startX, startY);
  ctx.quadraticCurveTo(controlX, controlY, endX, endY);
  ctx.stroke();
}

function drawFace() {
  const gaze = gazeOffset();
  const eyeY = -13;
  const eyeSpread = 27;
  ctx.strokeStyle = "rgba(216, 247, 255, 0.76)";
  ctx.fillStyle = "rgba(216, 247, 255, 0.76)";
  ctx.lineWidth = 7;

  if (state.expression === "happy") {
    for (const direction of [-1, 1]) {
      ctx.beginPath();
      ctx.arc(direction * eyeSpread, eyeY + 5, 11, Math.PI * 1.1, Math.PI * 1.9);
      ctx.stroke();
    }
  } else {
    for (const direction of [-1, 1]) {
      ctx.beginPath();
      ctx.arc(
        direction * eyeSpread + gaze.x,
        eyeY + gaze.y,
        state.expression === "surprised" ? 8 : 6,
        0,
        Math.PI * 2,
      );
      ctx.fill();
    }
  }

  ctx.beginPath();
  switch (state.expression) {
    case "happy":
      ctx.arc(0, 12, 25, 0.12 * Math.PI, 0.88 * Math.PI);
      break;
    case "sad":
      ctx.arc(0, 42, 23, 1.15 * Math.PI, 1.85 * Math.PI);
      break;
    case "surprised":
      ctx.arc(0, 25, 12, 0, Math.PI * 2);
      break;
    case "angry":
      ctx.moveTo(-24, 26);
      ctx.lineTo(24, 26);
      break;
    case "curious":
      ctx.arc(5, 18, 18, 0.08 * Math.PI, 0.75 * Math.PI);
      break;
    default:
      ctx.moveTo(-20, 25);
      ctx.quadraticCurveTo(0, 31, 20, 25);
  }
  ctx.stroke();

  if (["angry", "curious"].includes(state.expression)) {
    ctx.beginPath();
    if (state.expression === "angry") {
      ctx.moveTo(-39, -38);
      ctx.lineTo(-15, -29);
      ctx.moveTo(39, -38);
      ctx.lineTo(15, -29);
    } else {
      ctx.moveTo(-38, -31);
      ctx.lineTo(-17, -33);
      ctx.moveTo(15, -38);
      ctx.lineTo(39, -27);
    }
    ctx.stroke();
  }
}

function drawAvatar(now) {
  const width = canvas.width;
  const height = canvas.height;
  const time = now / 1000;
  const progress = gestureProgress(now);
  const pulse = progress === null ? 0 : Math.sin(progress * Math.PI);
  let bodyY = height * 0.55 + Math.sin(time * 1.55) * 4;
  let bodyRotation = 0;
  let headRotation = 0;
  let headOffsetY = 0;
  let armLift = 0;
  let armWave = 0;

  if (progress !== null) {
    switch (state.gesture) {
      case "small_nod":
        headOffsetY = Math.sin(progress * Math.PI * 2) * 18;
        break;
      case "head_tilt":
        headRotation = pulse * -0.28;
        break;
      case "wave":
        armLift = pulse;
        armWave = Math.sin(progress * Math.PI * 6) * 0.3;
        break;
      case "lean_forward":
        bodyRotation = pulse * -0.14;
        bodyY += pulse * 14;
        break;
      case "bounce":
        bodyY -= Math.abs(Math.sin(progress * Math.PI * 4)) * 45;
        break;
    }
  }

  ctx.clearRect(0, 0, width, height);
  const floor = ctx.createRadialGradient(
    width / 2,
    height * 0.82,
    20,
    width / 2,
    height * 0.82,
    width * 0.34,
  );
  floor.addColorStop(0, "rgba(148, 235, 255, 0.22)");
  floor.addColorStop(1, "rgba(148, 235, 255, 0)");
  ctx.fillStyle = floor;
  ctx.beginPath();
  ctx.ellipse(width / 2, height * 0.82, width * 0.28, 40, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.save();
  ctx.translate(width / 2, bodyY);
  ctx.rotate(bodyRotation);
  ctx.strokeStyle = "#d8f7ff";
  ctx.lineWidth = 15;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  const shoulderY = -58;
  const hipY = 95;
  ctx.beginPath();
  ctx.moveTo(0, shoulderY);
  ctx.quadraticCurveTo(Math.sin(time * 1.55), 20, 0, hipY);
  ctx.stroke();

  drawLimb(0, shoulderY, -78, 15, -112, 92);
  if (armLift > 0) {
    const handX = 90 + armLift * 28 + Math.sin(armWave) * 18;
    const handY = -125 - armLift * 115;
    drawLimb(0, shoulderY, 55 + armLift * 42, -78 - armLift * 65, handX, handY);
  } else {
    drawLimb(0, shoulderY, 78, 15, 112, 92);
  }
  drawLimb(0, hipY, -50, 170, -72, 255);
  drawLimb(0, hipY, 50, 170, 72, 255);

  ctx.save();
  ctx.translate(0, -178 + headOffsetY);
  ctx.rotate(headRotation);
  ctx.fillStyle = "rgba(7, 25, 36, 0.94)";
  ctx.lineWidth = 12;
  ctx.beginPath();
  ctx.arc(0, 0, 74, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  drawFace();
  ctx.restore();
  ctx.restore();

  requestAnimationFrame(drawAvatar);
}

loadInitialState();
connectEvents();
requestAnimationFrame(drawAvatar);

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

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
const lerp = (from, to, amount) => from + (to - from) * amount;
const ease = (value) => {
  const t = clamp(value, 0, 1);
  return t * t * (3 - 2 * t);
};

const state = {
  expression: { name: "neutral", intensity: 1 },
  attention: {
    target: "neutral",
    behavior: "maintain",
    intensity: 1,
    eye_follow: 1,
    head_follow: 0.55,
    body_follow: 0.15,
  },
  sequence: 0,
  activePerformance: null,
  queuedPerformances: [],
  heldTracks: new Map(),
  legacyMotion: null,
  lastPerformanceSequence: 0,
  cursor: { x: 0, y: 0, valid: false },
  attentionTarget: { x: 0, y: 0 },
  attentionSmooth: {
    eyesX: 0,
    eyesY: 0,
    headX: 0,
    headY: 0,
    bodyX: 0,
    bodyY: 0,
  },
  pose: null,
  transition: null,
  previousFrameAt: performance.now(),
};

function neutralPose() {
  return {
    headYaw: 0,
    headPitch: 0,
    headRoll: 0,
    torsoLeanX: 0,
    torsoLeanY: 0,
    bodyBounce: 0,
    leftArmRaise: 0,
    rightArmRaise: 0,
    leftArmIn: 0,
    rightArmIn: 0,
    leftArmWave: 0,
    rightArmWave: 0,
    gazeX: 0,
    gazeY: 0,
  };
}
state.pose = neutralPose();

window.addEventListener("pointermove", (event) => {
  state.cursor.x = clamp(event.clientX / Math.max(1, window.innerWidth) * 2 - 1, -1, 1);
  state.cursor.y = clamp(event.clientY / Math.max(1, window.innerHeight) * 2 - 1, -1, 1);
  state.cursor.valid = true;
}, { passive: true });

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

function renderHistory(items) {
  elements.historyCount.textContent = `${items.length} events`;
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
    type.textContent = item.kind || action.action || "unknown";
    const summary = document.createElement("code");
    summary.textContent = item.kind === "performance"
      ? `${item.performance?.performance_id || "-"} / ${item.performance?.tracks?.length || 0} tracks`
      : action.action === "gaze"
        ? `${action.target} / ${action.behavior}`
        : action.name || "-";
    const time = document.createElement("span");
    time.className = "history-time";
    time.textContent = formatTime(item.received_at);
    row.append(sequence, type, summary, time);
    return row;
  }));
}

function legacyGestureTrack(name, intensity = 1) {
  const channel = ["small_nod", "nod", "head_tilt", "head_shake"].includes(name)
    ? "head"
    : ["wave", "raise_hand"].includes(name)
      ? "right_arm"
      : "torso";
  return {
    track_id: `legacy-${Date.now()}`,
    channel,
    start_offset_ms: 0,
    duration_ms: name === "wave" ? 1900 : 1300,
    fade_in_ms: 120,
    fade_out_ms: 220,
    blend_mode: "additive",
    continuity: "current",
    hold: false,
    layer_priority: 200,
    intent: {
      type: "motion",
      name,
      intensity,
      amplitude: Math.max(0.2, intensity),
      tempo: 1,
      repetitions: name === "wave" ? 3 : name === "small_nod" ? 2 : 1,
      body_participation: 0,
      direction: null,
    },
  };
}

function applyRuntimeState(runtimeState) {
  if (!runtimeState || typeof runtimeState !== "object") return;
  const sequence = Number(runtimeState.sequence || 0);
  const isNew = sequence > state.sequence;
  state.sequence = sequence;

  if (isNew && runtimeState.latest_event_kind === "performance") {
    const plan = runtimeState.latest_performance;
    if (plan && sequence > state.lastPerformanceSequence) {
      state.lastPerformanceSequence = sequence;
      receivePerformance(plan);
    }
  } else if (isNew && runtimeState.latest_event_kind === "action") {
    const action = runtimeState.latest_action || {};
    if (action.action === "expression") {
      state.expression = { name: action.name, intensity: Number(action.intensity ?? 1) };
    } else if (action.action === "gaze") {
      state.attention = {
        target: action.target,
        behavior: action.behavior || "maintain",
        intensity: Number(action.intensity ?? 1),
        eye_follow: 1,
        head_follow: 0.55,
        body_follow: 0.15,
      };
    } else if (action.action === "gesture") {
      state.legacyMotion = {
        startedAt: performance.now(),
        track: legacyGestureTrack(action.name, Number(action.intensity ?? 1)),
      };
    }
  }

  elements.received.textContent = runtimeState.received_at
    ? formatTime(runtimeState.received_at)
    : "未受信";
  elements.sequence.textContent = `#${state.sequence}`;
  elements.payload.textContent = JSON.stringify(
    runtimeState.latest_performance || runtimeState.latest_action || { status: "waiting" },
    null,
    2,
  );
  renderHistory(Array.isArray(runtimeState.history) ? runtimeState.history : []);
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
    payload.behavior = name === "away" ? "avoid" : "maintain";
  } else {
    payload.name = name;
  }
  const response = await fetch("/api/avatar/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Action rejected: HTTP ${response.status}`);
}

async function sendPerformance(plan) {
  const response = await fetch("/api/avatar/performances", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(plan),
  });
  if (!response.ok) throw new Error(`Performance rejected: HTTP ${response.status}`);
}

function captureContinuity() {
  return {
    pose: { ...state.pose },
    expression: { ...state.expression },
    attention: { ...state.attention },
    heldTracks: new Map(state.heldTracks),
  };
}

function startPerformance(plan) {
  const now = performance.now();
  state.activePerformance = {
    plan,
    startedAt: now,
    previous: captureContinuity(),
  };
  state.transition = {
    startedAt: now,
    durationMs: 220,
    from: { ...state.pose },
  };
}

function receivePerformance(plan) {
  if (!plan || !Array.isArray(plan.tracks) || !plan.tracks.length) return;
  if (!state.activePerformance) {
    startPerformance(plan);
    return;
  }
  if (plan.interrupt_policy === "queue") {
    state.queuedPerformances.push(plan);
    return;
  }
  if (plan.interrupt_policy === "ignore_if_busy") return;
  if (Number(plan.priority) >= Number(state.activePerformance.plan.priority)) {
    startPerformance(plan);
  }
}

function commitHeldTracks(active) {
  const held = active.plan.tracks
    .filter((track) => track.hold)
    .sort((a, b) => Number(a.layer_priority) - Number(b.layer_priority));
  for (const track of held) state.heldTracks.set(track.channel, track);
  if (active.plan.return_behavior === "neutral") {
    state.heldTracks.clear();
    state.expression = { name: "neutral", intensity: 1 };
    state.attention = {
      target: "neutral", behavior: "maintain", intensity: 1,
      eye_follow: 1, head_follow: 0.55, body_follow: 0.15,
    };
  } else if (active.plan.return_behavior === "previous") {
    state.heldTracks = new Map(active.previous.heldTracks);
    state.expression = active.previous.expression;
    state.attention = active.previous.attention;
  }
}

function finishPerformance() {
  if (!state.activePerformance) return;
  const completed = state.activePerformance;
  state.activePerformance = null;
  commitHeldTracks(completed);
  const next = state.queuedPerformances.shift();
  if (next) startPerformance(next);
}

function trackWeight(track, elapsedMs) {
  const local = elapsedMs - Number(track.start_offset_ms);
  if (local < 0) return 0;
  const duration = Number(track.duration_ms);
  if (local > duration) return track.hold ? 1 : 0;
  const fadeIn = Math.max(0, Number(track.fade_in_ms || 0));
  const fadeOut = Math.max(0, Number(track.fade_out_ms || 0));
  const inWeight = fadeIn > 0 ? ease(local / fadeIn) : 1;
  const outWeight = !track.hold && fadeOut > 0
    ? ease((duration - local) / fadeOut)
    : 1;
  return Math.min(inWeight, outWeight);
}

function trackProgress(track, elapsedMs) {
  return clamp(
    (elapsedMs - Number(track.start_offset_ms)) / Number(track.duration_ms),
    0,
    1,
  );
}

function activeTracks(now) {
  const tracks = [...state.heldTracks.values()].map((track) => ({
    track,
    weight: 1,
    progress: 1,
  }));
  if (state.activePerformance) {
    const elapsed = now - state.activePerformance.startedAt;
    for (const track of state.activePerformance.plan.tracks) {
      const weight = trackWeight(track, elapsed);
      if (weight > 0) tracks.push({ track, weight, progress: trackProgress(track, elapsed) });
    }
    if (elapsed >= Number(state.activePerformance.plan.duration_ms)) finishPerformance();
  }
  if (state.legacyMotion) {
    const elapsed = now - state.legacyMotion.startedAt;
    const track = state.legacyMotion.track;
    const weight = trackWeight(track, elapsed);
    if (weight > 0) tracks.push({ track, weight, progress: trackProgress(track, elapsed) });
    if (elapsed > track.duration_ms) state.legacyMotion = null;
  }
  return tracks;
}

function strongestTrack(entries, channel) {
  return entries
    .filter((entry) => entry.track.channel === channel)
    .sort((a, b) => Number(b.track.layer_priority) - Number(a.track.layer_priority))[0] || null;
}

function resolveAttentionTarget(attention, now) {
  let target = { x: 0, y: 0 };
  switch (attention.target) {
    case "cursor":
      target = state.cursor.valid ? { x: state.cursor.x, y: state.cursor.y } : target;
      break;
    case "left": target = { x: -0.75, y: 0 }; break;
    case "right": target = { x: 0.75, y: 0 }; break;
    case "up": target = { x: 0, y: -0.7 }; break;
    case "down": target = { x: 0, y: 0.65 }; break;
    case "away": target = { x: -0.75, y: 0.25 }; break;
    default: target = { x: 0, y: 0 };
  }
  if (attention.behavior === "wander") {
    target.x += Math.sin(now / 1300) * 0.28;
    target.y += Math.sin(now / 1900 + 1.1) * 0.18;
  }
  const dx = target.x - state.attentionTarget.x;
  const dy = target.y - state.attentionTarget.y;
  const deadZone = 0.08;
  if (Math.hypot(dx, dy) > deadZone) {
    state.attentionTarget.x = clamp(target.x, -1, 1);
    state.attentionTarget.y = clamp(target.y, -1, 1);
  }
  return state.attentionTarget;
}

function updateAttention(attention, now, deltaMs) {
  const target = resolveAttentionTarget(attention, now);
  const frame = clamp(deltaMs / 16.67, 0.25, 4);
  const eyeRate = 1 - Math.pow(0.72, frame);
  const headRate = 1 - Math.pow(0.93, frame);
  const bodyRate = 1 - Math.pow(0.975, frame);
  state.attentionSmooth.eyesX = lerp(state.attentionSmooth.eyesX, target.x, eyeRate);
  state.attentionSmooth.eyesY = lerp(state.attentionSmooth.eyesY, target.y, eyeRate);
  state.attentionSmooth.headX = lerp(state.attentionSmooth.headX, target.x, headRate);
  state.attentionSmooth.headY = lerp(state.attentionSmooth.headY, target.y, headRate);
  state.attentionSmooth.bodyX = lerp(state.attentionSmooth.bodyX, target.x, bodyRate);
  state.attentionSmooth.bodyY = lerp(state.attentionSmooth.bodyY, target.y, bodyRate);
}

function applyMotion(pose, track, weight, progress) {
  const intent = track.intent;
  const strength = Number(intent.intensity ?? 1) * Number(intent.amplitude ?? 1) * weight;
  const repetitions = Number(intent.repetitions ?? 1);
  const tempo = Number(intent.tempo ?? 1);
  const phase = progress * Math.PI * 2 * repetitions * tempo;
  const bodyParticipation = Number(intent.body_participation ?? 0);
  switch (intent.name) {
    case "head_shake":
      pose.headYaw += Math.sin(phase) * 0.72 * strength;
      pose.torsoLeanX -= Math.sin(phase) * 0.16 * strength * bodyParticipation;
      break;
    case "small_nod":
    case "nod":
      pose.headPitch += Math.sin(phase) * 0.55 * strength;
      pose.bodyBounce += Math.max(0, Math.sin(phase)) * 5 * bodyParticipation;
      break;
    case "head_tilt":
      pose.headRoll -= Math.sin(progress * Math.PI) * 0.38 * strength;
      break;
    case "lean_forward":
      pose.torsoLeanY -= Math.sin(progress * Math.PI) * 0.55 * strength;
      break;
    case "lean_back":
      pose.torsoLeanY += Math.sin(progress * Math.PI) * 0.6 * strength;
      break;
    case "lean_left":
      pose.torsoLeanX -= Math.sin(progress * Math.PI) * 0.5 * strength;
      break;
    case "lean_right":
      pose.torsoLeanX += Math.sin(progress * Math.PI) * 0.5 * strength;
      break;
    case "bounce":
      pose.bodyBounce -= Math.abs(Math.sin(phase)) * 42 * strength;
      break;
    case "wave": {
      const side = track.channel === "left_arm" ? "left" : "right";
      pose[`${side}ArmRaise`] = Math.max(pose[`${side}ArmRaise`], ease(Math.min(1, progress * 4)) * strength);
      pose[`${side}ArmWave`] += Math.sin(phase) * 0.55 * strength;
      break;
    }
    case "raise_hand": {
      const side = track.channel === "left_arm" ? "left" : "right";
      pose[`${side}ArmRaise`] = Math.max(pose[`${side}ArmRaise`], ease(progress) * strength);
      break;
    }
    case "draw_in": {
      const side = track.channel === "left_arm" ? "left" : "right";
      pose[`${side}ArmIn`] = Math.max(pose[`${side}ArmIn`], Math.sin(progress * Math.PI) * strength);
      break;
    }
  }
}

function evaluateTracks(now, deltaMs) {
  const entries = activeTracks(now);
  const expressionEntry = strongestTrack(entries, "expression");
  const attentionEntry = strongestTrack(entries, "attention");
  if (expressionEntry) state.expression = { ...expressionEntry.track.intent };
  if (attentionEntry) state.attention = { ...attentionEntry.track.intent };
  updateAttention(state.attention, now, deltaMs);

  const pose = neutralPose();
  const attentionStrength = Number(state.attention.intensity ?? 1);
  pose.gazeX = state.attentionSmooth.eyesX * Number(state.attention.eye_follow ?? 1) * attentionStrength;
  pose.gazeY = state.attentionSmooth.eyesY * Number(state.attention.eye_follow ?? 1) * attentionStrength;
  pose.headYaw = state.attentionSmooth.headX * Number(state.attention.head_follow ?? 0.55) * attentionStrength;
  pose.headPitch = state.attentionSmooth.headY * Number(state.attention.head_follow ?? 0.55) * attentionStrength;
  pose.torsoLeanX = state.attentionSmooth.bodyX * Number(state.attention.body_follow ?? 0.15) * attentionStrength;
  pose.torsoLeanY = state.attentionSmooth.bodyY * Number(state.attention.body_follow ?? 0.15) * attentionStrength;

  const motionEntries = entries.filter((entry) => !["expression", "attention"].includes(entry.track.channel));
  for (const entry of motionEntries) applyMotion(pose, entry.track, entry.weight, entry.progress);

  if (state.transition) {
    const amount = ease((now - state.transition.startedAt) / state.transition.durationMs);
    for (const key of Object.keys(pose)) pose[key] = lerp(state.transition.from[key] || 0, pose[key], amount);
    if (amount >= 1) state.transition = null;
  }
  state.pose = pose;
  return motionEntries.map((entry) => entry.track.intent.name);
}

function drawLimb(startX, startY, controlX, controlY, endX, endY) {
  ctx.beginPath();
  ctx.moveTo(startX, startY);
  ctx.quadraticCurveTo(controlX, controlY, endX, endY);
  ctx.stroke();
}

function drawFace(pose) {
  const gazeX = pose.gazeX * 11;
  const gazeY = pose.gazeY * 9;
  const eyeY = -13;
  const eyeSpread = 27;
  ctx.strokeStyle = "rgba(216, 247, 255, 0.78)";
  ctx.fillStyle = "rgba(216, 247, 255, 0.78)";
  ctx.lineWidth = 7;
  if (state.expression.name === "happy") {
    for (const direction of [-1, 1]) {
      ctx.beginPath();
      ctx.arc(direction * eyeSpread, eyeY + 5, 11, Math.PI * 1.1, Math.PI * 1.9);
      ctx.stroke();
    }
  } else {
    for (const direction of [-1, 1]) {
      ctx.beginPath();
      ctx.arc(direction * eyeSpread + gazeX, eyeY + gazeY, state.expression.name === "surprised" ? 8 : 6, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.beginPath();
  switch (state.expression.name) {
    case "happy": ctx.arc(0, 12, 25, 0.12 * Math.PI, 0.88 * Math.PI); break;
    case "sad": ctx.arc(0, 42, 23, 1.15 * Math.PI, 1.85 * Math.PI); break;
    case "surprised": ctx.arc(0, 25, 12, 0, Math.PI * 2); break;
    case "angry":
    case "disgusted": ctx.moveTo(-24, 26); ctx.lineTo(24, 26); break;
    case "curious": ctx.arc(5, 18, 18, 0.08 * Math.PI, 0.75 * Math.PI); break;
    default: ctx.moveTo(-20, 25); ctx.quadraticCurveTo(0, 31, 20, 25);
  }
  ctx.stroke();
  if (["angry", "disgusted", "curious"].includes(state.expression.name)) {
    ctx.beginPath();
    if (state.expression.name === "curious") {
      ctx.moveTo(-38, -31); ctx.lineTo(-17, -33);
      ctx.moveTo(15, -38); ctx.lineTo(39, -27);
    } else {
      ctx.moveTo(-39, -38); ctx.lineTo(-15, -29);
      ctx.moveTo(39, -38); ctx.lineTo(15, -29);
    }
    ctx.stroke();
  }
}

function drawArm(side, pose, shoulderY) {
  const sign = side === "left" ? -1 : 1;
  const raise = pose[`${side}ArmRaise`];
  const inward = pose[`${side}ArmIn`];
  const wave = pose[`${side}ArmWave`];
  const handX = sign * (112 - inward * 68 + raise * 10) + Math.sin(wave) * 15;
  const handY = 92 - raise * 240 - inward * 25;
  const controlX = sign * (78 - inward * 35 + raise * 20);
  const controlY = 15 - raise * 100;
  drawLimb(0, shoulderY, controlX, controlY, handX, handY);
}

function drawAvatar(now) {
  const deltaMs = now - state.previousFrameAt;
  state.previousFrameAt = now;
  const activeMotionNames = evaluateTracks(now, deltaMs);
  const pose = state.pose;
  const width = canvas.width;
  const height = canvas.height;
  const time = now / 1000;
  const breathing = Math.sin(time * 1.45) * 4;
  const bodyY = height * 0.55 + breathing + pose.bodyBounce + pose.torsoLeanY * 24;
  const bodyRotation = pose.torsoLeanX * 0.32;

  ctx.clearRect(0, 0, width, height);
  const floor = ctx.createRadialGradient(width / 2, height * 0.82, 20, width / 2, height * 0.82, width * 0.34);
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
  ctx.quadraticCurveTo(-pose.torsoLeanX * 18, 20, 0, hipY);
  ctx.stroke();
  drawArm("left", pose, shoulderY);
  drawArm("right", pose, shoulderY);
  drawLimb(0, hipY, -50, 170, -72, 255);
  drawLimb(0, hipY, 50, 170, 72, 255);

  ctx.save();
  ctx.translate(pose.headYaw * 19, -178 + pose.headPitch * 12);
  ctx.rotate(pose.headRoll + pose.headYaw * 0.05);
  ctx.fillStyle = "rgba(7, 25, 36, 0.94)";
  ctx.lineWidth = 12;
  ctx.beginPath();
  ctx.arc(0, 0, 74, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  drawFace(pose);
  ctx.restore();
  ctx.restore();

  elements.expression.textContent = `${state.expression.name} (${Number(state.expression.intensity ?? 1).toFixed(2)})`;
  elements.gesture.textContent = activeMotionNames.length ? activeMotionNames.join(" + ") : "idle / breathing";
  elements.gaze.textContent = `${state.attention.target} / ${state.attention.behavior}`;
  elements.performance.textContent = `${state.expression.name} / ${activeMotionNames.join(" + ") || "continuous idle"} / ${state.attention.target}`;
  requestAnimationFrame(drawAvatar);
}

function track(track_id, channel, start, duration, intent, options = {}) {
  return {
    track_id,
    channel,
    start_offset_ms: start,
    duration_ms: duration,
    fade_in_ms: options.fadeIn ?? 160,
    fade_out_ms: options.fadeOut ?? 260,
    blend_mode: options.blend ?? (channel === "expression" || channel === "attention" ? "override" : "additive"),
    continuity: "current",
    hold: options.hold ?? false,
    layer_priority: options.priority ?? 100,
    intent,
  };
}

function performancePlan(name, duration, tracks) {
  const id = `${name}-${Date.now()}`;
  return {
    schema_version: 2,
    type: "avatar.performance.submit",
    performance_id: id,
    source_activity_id: "manual-probe",
    output_unit_id: id,
    priority: 500,
    interrupt_policy: "replace_lower_priority",
    return_behavior: "hold",
    duration_ms: duration,
    tracks,
    segments: [],
  };
}

function rejectionDemo() {
  return performancePlan("biological-rejection", 3000, [
    track("reject-expression", "expression", 0, 3000, { type: "expression", name: "disgusted", intensity: 0.9 }, { hold: true, priority: 100 }),
    track("look-person", "attention", 0, 700, { type: "attention", target: "viewer", behavior: "maintain", intensity: 0.9, eye_follow: 1, head_follow: 0.55, body_follow: 0.12 }, { hold: false, priority: 100 }),
    track("avert-gaze", "attention", 620, 2380, { type: "attention", target: "away", behavior: "avoid", intensity: 0.85, eye_follow: 1, head_follow: 0.48, body_follow: 0.18 }, { hold: true, priority: 120 }),
    track("lean-back", "torso", 90, 1750, { type: "motion", name: "lean_back", intensity: 0.8, amplitude: 0.85, tempo: 1, repetitions: 1, body_participation: 1, direction: "back" }),
    track("strong-head-shake", "head", 180, 1450, { type: "motion", name: "head_shake", intensity: 1, amplitude: 1, tempo: 1.35, repetitions: 4, body_participation: 0.7, direction: "horizontal" }, { priority: 240 }),
    track("right-arm-in", "right_arm", 260, 1750, { type: "motion", name: "draw_in", intensity: 0.85, amplitude: 0.9, tempo: 1, repetitions: 1, body_participation: 0.2, direction: "in" }, { priority: 210 }),
    track("left-arm-in", "left_arm", 340, 1650, { type: "motion", name: "draw_in", intensity: 0.72, amplitude: 0.8, tempo: 1, repetitions: 1, body_participation: 0.15, direction: "in" }, { priority: 205 }),
  ]);
}

function cursorAttentionDemo() {
  return performancePlan("cursor-attention", 120000, [
    track("curious-expression", "expression", 0, 120000, { type: "expression", name: "curious", intensity: 0.65 }, { hold: true }),
    track("follow-cursor", "attention", 0, 120000, { type: "attention", target: "cursor", behavior: "maintain", intensity: 0.9, eye_follow: 1, head_follow: 0.62, body_follow: 0.18 }, { hold: true, priority: 130 }),
    track("slight-forward", "torso", 150, 2600, { type: "motion", name: "lean_forward", intensity: 0.35, amplitude: 0.35, tempo: 0.7, repetitions: 1, body_participation: 1, direction: "forward" }, { fadeOut: 800 }),
  ]);
}

function affirmationDemo() {
  return performancePlan("strong-affirmation", 2600, [
    track("affirm-expression", "expression", 0, 2600, { type: "expression", name: "happy", intensity: 0.8 }, { hold: true }),
    track("affirm-attention", "attention", 0, 2600, { type: "attention", target: "viewer", behavior: "maintain", intensity: 1, eye_follow: 1, head_follow: 0.6, body_follow: 0.15 }, { hold: true }),
    track("strong-nod", "head", 180, 1500, { type: "motion", name: "nod", intensity: 0.95, amplitude: 0.9, tempo: 1.2, repetitions: 3, body_participation: 0.45, direction: "vertical" }, { priority: 230 }),
    track("affirm-forward", "torso", 120, 1800, { type: "motion", name: "lean_forward", intensity: 0.48, amplitude: 0.5, tempo: 1, repetitions: 1, body_participation: 1, direction: "forward" }),
    track("raise-hand", "right_arm", 380, 1700, { type: "motion", name: "raise_hand", intensity: 0.62, amplitude: 0.65, tempo: 1, repetitions: 1, body_participation: 0.1, direction: "up" }),
  ]);
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

const demoButtons = [
  ["performanceDemoButton", rejectionDemo],
  ["attentionDemoButton", cursorAttentionDemo],
  ["affirmDemoButton", affirmationDemo],
];
for (const [id, factory] of demoButtons) {
  const button = document.getElementById(id);
  if (!button) continue;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await sendPerformance(factory());
    } catch (error) {
      console.error(error);
      setConnection("error", "Performance送信失敗");
    } finally {
      button.disabled = false;
    }
  });
}

document.getElementById("randomButton").addEventListener("click", async () => {
  const choose = (values) => values[Math.floor(Math.random() * values.length)];
  try {
    await sendAction("expression", choose(["neutral", "happy", "sad", "surprised", "angry", "curious"]));
    await sendAction("gesture", choose(["small_nod", "head_tilt", "wave", "lean_forward", "bounce"]));
    await sendAction("gaze", choose(["viewer", "left", "right", "up", "down", "away"]));
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

loadInitialState();
connectEvents();
requestAnimationFrame(drawAvatar);

const canvas = document.querySelector("#field");
const ctx = canvas.getContext("2d", { alpha: false });
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const helpDialog = document.querySelector("#helpDialog");

document.querySelector("#helpButton").addEventListener("click", () => helpDialog.showModal());
document.querySelector("#helpClose").addEventListener("click", () => helpDialog.close());
helpDialog.addEventListener("click", (event) => {
  if (event.target === helpDialog) helpDialog.close();
});

const state = {
  emotion: {
    mood: "unknown", arousal: 0, valence: 0, talkativeness: 0,
    reactive: {
      joy: 0, amusement: 0, anger: 0, sadness: 0,
      fear: 0, surprise: 0, discomfort: 0, emotional_pressure: 0,
    },
  },
  drive: { curiosity: 0, engagement: 0, boredom: 0, energy: 0 },
  activity: { type: null, active: false },
  attention: { engaged: false },
  observed_at: null,
};

const display = structuredClone(state);
let width = 0;
let height = 0;
let dpr = 1;
let lastFrame = performance.now();
let lastStateAt = 0;
let sourceAvailable = false;
let streamConnected = false;
let signalPresence = 0;
let presenceTransitionTarget = 0;
let presenceTransitionStart = 0;
let presenceTransitionElapsedMs = 0;
let presenceTransitionProgress = 1;
let presenceAcceleratedProgress = 1;
let centralParticlePresence = 0;
let innerDetailPresence = 0;
let rotationYAngle = 0;
let tiltPhase = 0;
let breathPhase = 0;
let surfaceWavePhase = 0;
let surfaceCurlPhase = 0;
let talkFlowPhase = 0;
let pressurePulsePhase = 0;
const visualPalette = { hue: 202, saturation: 84, lightness: 72 };
const pendingStateSnapshots = [];
let stateTransition = null;
let lastSnapshotReceivedAt = 0;
let lastFrameAppearance = {
  hue: 202, saturation: 84, lightness: 72, energy: 0, engagement: 0,
  baseRadius: 0,
};
let scatterAppearance = { ...lastFrameAppearance };
let nextBubbleAt = 0;
const bubbles = [];
const emotionWaves = [];
const stimulusRipples = [];
const lastStimulusAtByKind = new Map();
let activePointerGesture = null;
let pendingTapGesture = null;
const STATE_TIMEOUT_MS = 45000;
const PRESENCE_GATHER_DURATION_MS = 7000;
const PRESENCE_SCATTER_DURATION_MS = 4200;
const CENTRIFUGAL_ACCELERATION_MIN = .12;
const CENTRIFUGAL_ACCELERATION_GAIN = .08;
const ROTATION_DIRECTION = -1;
const MAX_PARTICLE_TRACKING_SPEED = 360;
const MAX_VISUAL_FRAME_SECONDS = 1 / 60;
const MAX_PARTICLE_FRAME_DISTANCE = 4;
const PARTICLE_SIZE_REFERENCE_VIEWPORT = 720;
const MAX_PARTICLE_VIEWPORT_SCALE = 1.5;
const STATE_TRANSITION_INTERVAL_RATIO = .82;
const STATE_TRANSITION_MIN_SECONDS = .6;
const STATE_TRANSITION_MAX_SECONDS = 4;
const STIMULUS_INTERVAL_MS = 850;
const DRAG_SAMPLE_INTERVAL_MS = 140;
const DRAG_SAMPLE_DISTANCE_PX = 5;
const DOUBLE_TAP_INTERVAL_MS = 300;
const DOUBLE_TAP_DISTANCE_PX = 28;
const LONG_PRESS_DURATION_MS = 600;
const DRAG_START_DISTANCE_PX = 5;
const DRAG_TRAIL_LIFETIME_MS = 520;

function balancedEmotionGroup(index) {
  const pairIndex = Math.floor(index / 2);
  const randomValue = Math.sin((pairIndex + 1) * 12.9898) * 43758.5453;
  const pairFlip = randomValue - Math.floor(randomValue) >= .5 ? 1 : 0;
  return (index % 2) ^ pairFlip;
}

const particles = Array.from({ length: 820 }, (_, index) => {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (index / 819) * 2;
  const radius = Math.sqrt(1 - y * y);
  const theta = golden * index;
  return {
    x: Math.cos(theta) * radius,
    y,
    z: Math.sin(theta) * radius,
    seed: Math.random() * Math.PI * 2,
    weight: 0.35 + Math.random() * 0.9,
    emotionGroup: balancedEmotionGroup(index),
    scatterAngle: Math.random() * Math.PI * 2,
    scatterSpeed: .72 + Math.random() * .55,
  };
});

const dust = Array.from({ length: 150 }, () => ({
  x: Math.random(), y: Math.random(), z: Math.random(), phase: Math.random() * 9,
}));

const palettes = {
  neutral: [202, 84, 72],
  happy: [42, 92, 72],
  excited: [326, 88, 70],
  angry: [7, 92, 64],
  sad: [224, 76, 67],
  tired: [267, 46, 64],
};

const moodLabels = {
  unknown: "不明な状態",
  neutral: "静かなゆらぎ", happy: "ひらく光", excited: "弾むきらめき",
  angry: "鋭い熱", sad: "沈む青", tired: "ほどける輪郭",
};

const reactiveHues = {
  joy: 44,
  amusement: 322,
  anger: 7,
  sadness: 224,
  fear: 274,
  surprise: 184,
  discomfort: 104,
};

const reactiveMotionSpeedScales = {
  joy: 1.03,
  amusement: 1.07,
  anger: 1.08,
  sadness: .94,
  fear: 1.05,
  surprise: 1.07,
  discomfort: .97,
};

const reactiveLabels = {
  joy: "喜び",
  amusement: "愉快",
  anger: "怒り",
  sadness: "悲しみ",
  fear: "恐れ",
  surprise: "驚き",
  discomfort: "不快",
};

const emotionParticleGroups = Array.from({ length: 2 }, () => ({
  name: null,
  hue: 202,
  visibility: 0,
  sizeScale: 1,
  motionSpeedScale: 1,
  rotationOffset: 0,
  strength: 0,
}));

function resize() {
  dpr = Math.min(devicePixelRatio || 1, 2);
  width = innerWidth;
  height = innerHeight;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function mix(current, target, rate) { return current + (target - current) * rate; }
function clamp(value, min = 0, max = 1) { return Math.max(min, Math.min(max, value)); }
function smoothstep(edge0, edge1, value) {
  const normalized = clamp((value - edge0) / (edge1 - edge0));
  return normalized * normalized * (3 - 2 * normalized);
}
function smootherstep(value) {
  const normalized = clamp(value);
  return normalized ** 3
    * (normalized * (normalized * 6 - 15) + 10);
}
function mixHue(current, target, rate) {
  const delta = ((target - current + 540) % 360) - 180;
  return (current + delta * rate + 360) % 360;
}
function finiteNumber(value, fallback, min = 0, max = 1) {
  return typeof value === "number" && Number.isFinite(value)
    ? clamp(value, min, max)
    : fallback;
}

function beginParticleTransition(target) {
  const centerX = width * .5;
  const centerY = height * .49;
  const viewportSize = Math.max(width, height);
  if (!target) scatterAppearance = { ...lastFrameAppearance };
  for (const particle of particles) {
    if (particle.screenX === undefined || particle.screenY === undefined) continue;
    particle.motionStartX = particle.screenX;
    particle.motionStartY = particle.screenY;
    particle.motionStartVX = particle.screenVX || 0;
    particle.motionStartVY = particle.screenVY || 0;
    particle.motionSize = particle.screenSize;
    particle.motionAlpha = particle.screenAlpha;
    particle.motionHue = particle.screenHue;
    particle.motionSaturation = particle.screenSaturation;
    particle.motionLightness = particle.screenLightness;
    particle.motionShadowBlur = particle.screenShadowBlur;
    particle.motionShadowAlpha = particle.screenShadowAlpha;
    particle.motionZ = particle.screenZ;
    if (target) continue;

    const dx = particle.screenX - centerX;
    const dy = particle.screenY - centerY;
    const radius = Math.hypot(dx, dy);
    const directionX = radius ? dx / radius : Math.cos(particle.scatterAngle);
    const directionY = radius ? dy / radius : Math.sin(particle.scatterAngle);
    const rotationalSpeed = Math.hypot(
      particle.motionStartVX,
      particle.motionStartVY,
    );
    const rotationFactor = clamp(rotationalSpeed / 90);
    const acceleration = viewportSize
      * (CENTRIFUGAL_ACCELERATION_MIN
        + rotationFactor * CENTRIFUGAL_ACCELERATION_GAIN)
      * particle.scatterSpeed;
    // 回転の接線速度を初速として残し、中心から外向きの一定加速度を加える。
    particle.motionAccelerationX = directionX * acceleration;
    particle.motionAccelerationY = directionY * acceleration;
  }
}

function updateSignalPresence(dt) {
  const target = sourceAvailable ? 1 : 0;
  if (target !== presenceTransitionTarget) {
    presenceTransitionTarget = target;
    presenceTransitionStart = signalPresence;
    presenceTransitionElapsedMs = 0;
    beginParticleTransition(target);
  } else if (presenceTransitionProgress < 1) {
    presenceTransitionElapsedMs += dt * 1000;
  }

  const duration = target ? PRESENCE_GATHER_DURATION_MS : PRESENCE_SCATTER_DURATION_MS;
  presenceTransitionProgress = clamp(presenceTransitionElapsedMs / duration);
  presenceAcceleratedProgress = presenceTransitionProgress * presenceTransitionProgress;
  signalPresence = mix(
    presenceTransitionStart,
    target,
    presenceAcceleratedProgress,
  );
}

function resolveParticlePosition(
  particle,
  sphereX,
  sphereY,
  centerX,
  centerY,
  dt,
) {
  if (
    presenceTransitionTarget === 0
    && particle.motionStartX !== undefined
    && particle.motionStartY !== undefined
  ) {
    const elapsed = Math.min(
      presenceTransitionElapsedMs / 1000,
      PRESENCE_SCATTER_DURATION_MS / 1000,
    );
    const accelerationX = particle.motionAccelerationX || 0;
    const accelerationY = particle.motionAccelerationY || 0;
    return {
      x: particle.motionStartX
        + particle.motionStartVX * elapsed
        + .5 * accelerationX * elapsed * elapsed,
      y: particle.motionStartY
        + particle.motionStartVY * elapsed
        + .5 * accelerationY * elapsed * elapsed,
      vx: particle.motionStartVX + accelerationX * elapsed,
      vy: particle.motionStartVY + accelerationY * elapsed,
    };
  }

  if (
    presenceTransitionTarget === 1
    && presenceTransitionProgress < 1
    && particle.motionStartX !== undefined
    && particle.motionStartY !== undefined
  ) {
    const elapsed = presenceTransitionElapsedMs / 1000;
    const inertiaDuration = .45;
    const inertiaDistanceScale = inertiaDuration
      * (1 - Math.exp(-elapsed / inertiaDuration));
    const inertialX = particle.motionStartX
      + (particle.motionStartVX || 0) * inertiaDistanceScale;
    const inertialY = particle.motionStartY
      + (particle.motionStartVY || 0) * inertiaDistanceScale;
    const blend = smootherstep(presenceTransitionProgress);
    return {
      x: mix(inertialX, sphereX, blend),
      y: mix(inertialY, sphereY, blend),
      vx: null,
      vy: null,
    };
  }

  if (presenceTransitionTarget === 0) {
    const scatterDistance = Math.max(width, height) * 1.15 * particle.scatterSpeed;
    return {
      x: centerX + Math.cos(particle.scatterAngle) * scatterDistance,
      y: centerY + Math.sin(particle.scatterAngle) * scatterDistance,
      vx: 0,
      vy: 0,
    };
  }

  if (particle.screenX === undefined || particle.screenY === undefined) {
    return { x: sphereX, y: sphereY, vx: null, vy: null };
  }
  const dx = sphereX - particle.screenX;
  const dy = sphereY - particle.screenY;
  const distance = Math.hypot(dx, dy);
  // A delayed render must not consume the whole wall-clock gap in one frame.
  // Advancing that gap at once makes the stable particle population look as if
  // it were replaced, especially when a state event and a missed frame coincide.
  const maximumStep = Math.min(
    MAX_PARTICLE_TRACKING_SPEED * dt,
    MAX_PARTICLE_FRAME_DISTANCE,
  );
  if (!distance || distance <= maximumStep) {
    return { x: sphereX, y: sphereY, vx: null, vy: null };
  }
  const stepRatio = maximumStep / distance;
  return {
    x: particle.screenX + dx * stepRatio,
    y: particle.screenY + dy * stepRatio,
    vx: null,
    vy: null,
  };
}

function assignStateSnapshot(target, snapshot) {
  target.emotion.mood = snapshot.emotion.mood;
  target.emotion.arousal = snapshot.emotion.arousal;
  target.emotion.valence = snapshot.emotion.valence;
  target.emotion.talkativeness = snapshot.emotion.talkativeness;
  Object.assign(target.emotion.reactive, snapshot.emotion.reactive);
  Object.assign(target.drive, snapshot.drive);
  target.activity = snapshot.activity;
  target.attention = snapshot.attention;
  target.observed_at = snapshot.observed_at;
}

function averageStateSnapshots(entries) {
  const result = structuredClone(entries[entries.length - 1].snapshot);
  const numericGroups = [
    ["emotion", ["arousal", "valence", "talkativeness"]],
    ["drive", Object.keys(result.drive)],
  ];
  for (const [group, keys] of numericGroups) {
    for (const key of keys) {
      result[group][key] = entries.reduce(
        (sum, entry) => sum + entry.snapshot[group][key],
        0,
      ) / entries.length;
    }
  }
  for (const key of Object.keys(result.emotion.reactive)) {
    result.emotion.reactive[key] = entries.reduce(
      (sum, entry) => sum + entry.snapshot.emotion.reactive[key],
      0,
    ) / entries.length;
  }
  return result;
}

function interpolateStateSnapshot(from, to, progress) {
  display.emotion.mood = to.emotion.mood;
  for (const key of ["arousal", "valence", "talkativeness"]) {
    display.emotion[key] = mix(from.emotion[key], to.emotion[key], progress);
  }
  for (const key of Object.keys(display.emotion.reactive)) {
    display.emotion.reactive[key] = mix(
      from.emotion.reactive[key],
      to.emotion.reactive[key],
      progress,
    );
  }
  for (const key of Object.keys(display.drive)) {
    display.drive[key] = mix(from.drive[key], to.drive[key], progress);
  }
  display.activity = to.activity;
  display.attention = to.attention;
  display.observed_at = to.observed_at;
}

function advanceStateTrajectory(dt) {
  if (!stateTransition && pendingStateSnapshots.length) {
    const entries = pendingStateSnapshots.splice(0);
    const target = averageStateSnapshots(entries);
    const receivedAt = entries[entries.length - 1].receivedAt;
    const observedInterval = lastSnapshotReceivedAt
      ? (receivedAt - lastSnapshotReceivedAt) / 1000
      : 1.2;
    const duration = clamp(
      observedInterval * STATE_TRANSITION_INTERVAL_RATIO,
      STATE_TRANSITION_MIN_SECONDS,
      STATE_TRANSITION_MAX_SECONDS,
    );
    const previousReactive = { ...state.emotion.reactive };
    assignStateSnapshot(state, target);
    if (lastSnapshotReceivedAt) {
      createEmotionWave(previousReactive, target.emotion.reactive, receivedAt);
    }
    stateTransition = {
      from: structuredClone(display),
      to: structuredClone(target),
      elapsed: 0,
      duration,
    };
    lastSnapshotReceivedAt = receivedAt;
  }

  if (!stateTransition) return;
  stateTransition.elapsed = Math.min(
    stateTransition.elapsed + dt,
    stateTransition.duration,
  );
  const progress = smootherstep(
    stateTransition.elapsed / stateTransition.duration,
  );
  interpolateStateSnapshot(
    stateTransition.from,
    stateTransition.to,
    progress,
  );
  if (stateTransition.elapsed >= stateTransition.duration) {
    assignStateSnapshot(display, stateTransition.to);
    stateTransition = null;
  }
}

function dominantReactiveEmotions() {
  return Object.entries(display.emotion.reactive)
    .filter(([name]) => name !== "emotional_pressure")
    .map(([name, value]) => ({ name, value, hue: reactiveHues[name] }))
    .filter((item) => item.value >= .12)
    .sort((a, b) => b.value - a.value)
    .slice(0, 2);
}

function updateEmotionParticleGroups(dt) {
  const reactive = display.emotion.reactive;
  for (const group of emotionParticleGroups) {
    if (group.name && reactive[group.name] < .09) group.name = null;
  }
  const activeNames = emotionParticleGroups
    .map((group) => group.name)
    .filter(Boolean);
  const candidates = Object.keys(reactiveHues)
    .filter((name) => !activeNames.includes(name))
    .map((name) => ({ name, value: reactive[name] }))
    .sort((a, b) => b.value - a.value);

  for (const group of emotionParticleGroups) {
    if (group.name || candidates[0]?.value < .14) continue;
    group.name = candidates.shift().name;
  }
  if (
    emotionParticleGroups.every((group) => group.name)
    && candidates[0]?.value >= .14
  ) {
    const weakestGroup = [...emotionParticleGroups].sort(
      (a, b) => reactive[a.name] - reactive[b.name],
    )[0];
    if (candidates[0].value >= reactive[weakestGroup.name] + .07) {
      weakestGroup.name = candidates[0].name;
    }
  }

  const rankedGroups = emotionParticleGroups
    .filter((group) => group.name)
    .sort((a, b) => reactive[b.name] - reactive[a.name]);
  const transitionRate = 1 - Math.exp(-dt * 2.4);
  for (const group of emotionParticleGroups) {
    const rank = rankedGroups.indexOf(group);
    const active = rank >= 0;
    const strength = active ? reactive[group.name] : 0;
    group.visibility = mix(
      group.visibility,
      active ? 1 : 0,
      transitionRate,
    );
    group.sizeScale = mix(
      group.sizeScale,
      active ? .68 + strength * .9 : 1,
      transitionRate,
    );
    group.motionSpeedScale = mix(
      group.motionSpeedScale,
      active ? reactiveMotionSpeedScales[group.name] : 1,
      transitionRate,
    );
    if (active) {
      group.hue = mixHue(
        group.hue,
        reactiveHues[group.name],
        transitionRate,
      );
      group.strength = strength;
    } else {
      group.strength = mix(group.strength, 0, transitionRate);
    }
  }
  return emotionParticleGroups;
}

function emotionVisualProfile() {
  const reactive = display.emotion.reactive;
  return {
    activation: smoothstep(.45, .85, display.emotion.arousal),
    joy: reactive.joy,
    amusement: reactive.amusement,
    anger: reactive.anger,
    sadness: reactive.sadness,
    fear: reactive.fear,
    surprise: reactive.surprise,
    discomfort: reactive.discomfort,
    pressure: reactive.emotional_pressure,
    pressureLeak: Math.max(reactive.anger, reactive.fear)
      * reactive.emotional_pressure,
  };
}

function palette() {
  const base = palettes[display.emotion.mood] || palettes.neutral;
  const emotionalHue = display.emotion.valence < 0
    ? 222 + display.emotion.valence * -20
    : 198 - display.emotion.valence * 156;
  return [
    mixHue(emotionalHue, base[0], .18),
    mix(78, base[1], .25),
    mix(70, base[2], .25),
  ];
}

function rotate(point, ax, ay) {
  const cy = Math.cos(ay), sy = Math.sin(ay);
  const cx = Math.cos(ax), sx = Math.sin(ax);
  const x = point.x * cy - point.z * sy;
  const z1 = point.x * sy + point.z * cy;
  return { x, y: point.y * cx - z1 * sx, z: point.y * sx + z1 * cx };
}

function createBubble(now) {
  const radius = 1.8 + Math.random() * 4.7;
  bubbles.push({
    x: width * (.06 + Math.random() * .88),
    y: height + radius + Math.random() * 20,
    radius,
    speed: 13 + Math.random() * 25,
    sway: 4 + Math.random() * 13,
    phase: Math.random() * Math.PI * 2,
    bornAt: now,
    opacity: .16 + Math.random() * .25,
    vx: 0,
    vy: 0,
    tilt: (Math.random() - .5) * .38,
    stretch: 1.08 + Math.random() * .42,
    shape: Array.from({ length: 8 }, () => .78 + Math.random() * .38),
  });
}

function particleFlowAt(bubble, projected, reach, centerX, centerY, baseRadius, rotationForce) {
  let flowX = 0;
  let flowY = 0;
  let totalWeight = 0;

  for (const particle of projected) {
    const distance = Math.hypot(bubble.x - particle.x, bubble.y - particle.y);
    if (distance >= reach) continue;
    const weight = (1 - distance / reach) ** 2 * particle.alpha;
    flowX += particle.vx * weight;
    flowY += particle.vy * weight;
    totalWeight += weight;
  }

  if (totalWeight) {
    flowX /= totalWeight;
    flowY /= totalWeight;
  }

  const dx = bubble.x - centerX;
  const dy = bubble.y - centerY;
  const centerDistance = Math.hypot(dx, dy);
  const coreInfluence = clamp(1 - centerDistance / (baseRadius * 1.65));
  if (centerDistance && coreInfluence) {
    // The projected velocities cancel when opposite sides of the sphere overlap.
    // Preserve the visible rotational current as a tangential force around the core.
    flowX += -dy / centerDistance * rotationForce * coreInfluence;
    flowY += dx / centerDistance * rotationForce * coreInfluence * .58;
  }

  return {
    x: flowX,
    y: flowY,
    influence: Math.max(coreInfluence, Math.min(1, totalWeight * .5)),
  };
}

function traceBubble(bubble, age) {
  const points = bubble.shape.map((shape, index) => {
    const angle = index / bubble.shape.length * Math.PI * 2;
    const wobble = shape + Math.sin(age * 1.8 + bubble.phase + index * 1.7) * .055;
    return {
      x: Math.cos(angle) * bubble.radius * wobble,
      y: Math.sin(angle) * bubble.radius * bubble.stretch * wobble,
    };
  });
  ctx.beginPath();
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    const next = points[(index + 1) % points.length];
    const midX = (point.x + next.x) * .5;
    const midY = (point.y + next.y) * .5;
    if (index === 0) ctx.moveTo(midX, midY);
    ctx.quadraticCurveTo(next.x, next.y, midX, midY);
  }
  ctx.closePath();
}

function drawBubble(bubble, x, age, alpha, hue, saturation) {
  ctx.save();
  ctx.translate(x, bubble.y);
  ctx.rotate(bubble.tilt + Math.sin(age * .7 + bubble.phase) * .08);
  traceBubble(bubble, age);
  ctx.fillStyle = `hsla(${hue}, ${Math.min(76, saturation)}%, 78%, ${alpha * .1})`;
  ctx.fill();
  ctx.strokeStyle = `hsla(${hue}, ${Math.min(82, saturation)}%, 86%, ${alpha * .72})`;
  ctx.lineWidth = .7;
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(-bubble.radius * .55, -bubble.radius * .08);
  ctx.quadraticCurveTo(
    -bubble.radius * .42,
    -bubble.radius * bubble.stretch * .68,
    bubble.radius * .12,
    -bubble.radius * bubble.stretch * .72,
  );
  ctx.strokeStyle = `hsla(${hue}, ${Math.min(88, saturation)}%, 96%, ${alpha * 1.35})`;
  ctx.lineWidth = Math.max(.75, bubble.radius * .16);
  ctx.lineCap = "round";
  ctx.stroke();
  ctx.restore();
}

function renderBubbles(now, dt, projected, baseRadius, centerX, centerY, rotationForce, hue, saturation) {
  if (sourceAvailable && !reduceMotion && now >= nextBubbleAt) {
    createBubble(now);
    if (Math.random() < .2) createBubble(now);
    nextBubbleAt = now + 260 + Math.random() * 950;
  }

  const t = now / 1000;
  const reach = Math.max(30, baseRadius * .26);
  ctx.shadowBlur = 0;
  for (let index = bubbles.length - 1; index >= 0; index -= 1) {
    const bubble = bubbles[index];
    const age = (now - bubble.bornAt) / 1000;
    const flow = particleFlowAt(bubble, projected, reach, centerX, centerY, baseRadius, rotationForce);
    const response = 1 - Math.exp(-dt * (1.5 + flow.influence * 3));
    const ambient = Math.sin(t * .32 + bubble.phase) * 2.2;
    bubble.vx += (ambient + flow.x * .7 - bubble.vx) * response;
    bubble.vy += (flow.y * .45 - bubble.vy) * response;
    bubble.x += bubble.vx * dt;
    bubble.y += (-bubble.speed + bubble.vy) * dt;
    const x = bubble.x + Math.sin(age * 1.3 + bubble.phase) * bubble.sway;
    const fade = Math.min(1, age * 2) * Math.min(1, (bubble.y + 30) / 90);
    const alpha = bubble.opacity * Math.max(0, fade);

    drawBubble(bubble, x, age, alpha, hue, saturation);
    if (bubble.y < -bubble.radius - 8) bubbles.splice(index, 1);
  }
}

function drawPressureCore(
  pressure,
  centerX,
  centerY,
  baseRadius,
  hue,
  reveal,
) {
  if (!sourceAvailable || pressure <= .01 || reveal <= .01) return;
  const pulse = 1 + Math.sin(pressurePulsePhase) * (.025 + pressure * .045);
  const radius = baseRadius * (.19 - pressure * .045) * pulse;
  const glow = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius * 2.4);
  glow.addColorStop(0, `hsla(${hue + 22}, 82%, 82%, ${pressure * .2 * reveal})`);
  glow.addColorStop(.3, `hsla(${hue + 8}, 76%, 58%, ${pressure * .09 * reveal})`);
  glow.addColorStop(1, "transparent");
  ctx.fillStyle = glow;
  ctx.fillRect(centerX - radius * 2.5, centerY - radius * 2.5, radius * 5, radius * 5);

  ctx.beginPath();
  ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
  ctx.strokeStyle = `hsla(${hue + 18}, 86%, 80%, ${pressure * .5 * reveal})`;
  ctx.lineWidth = .7 + pressure * 1.4;
  ctx.shadowColor = `hsla(${hue}, 90%, 70%, ${pressure * .7})`;
  ctx.shadowBlur = 10 + pressure * 18;
  ctx.stroke();
  ctx.shadowBlur = 0;
}

function createEmotionWave(previous, next, now) {
  let strongest = null;
  for (const [name, value] of Object.entries(next)) {
    if (name === "emotional_pressure") continue;
    const delta = value - (previous[name] || 0);
    if (delta >= .035 && (!strongest || delta > strongest.delta)) {
      strongest = { name, delta };
    }
  }
  if (!strongest) return;
  emotionWaves.push({
    bornAt: now,
    hue: reactiveHues[strongest.name] ?? 202,
    strength: clamp(strongest.delta * 3.2, .16, 1),
  });
  if (emotionWaves.length > 6) emotionWaves.shift();
}

function renderEmotionWaves(now, centerX, centerY, baseRadius) {
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let index = emotionWaves.length - 1; index >= 0; index -= 1) {
    const wave = emotionWaves[index];
    const age = (now - wave.bornAt) / 1000;
    const duration = reduceMotion ? .45 : 2.4;
    const progress = clamp(age / duration);
    const radius = baseRadius * (.45 + progress * 1.45);
    const alpha = (1 - progress) * wave.strength * signalPresence;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
    ctx.strokeStyle = `hsla(${wave.hue}, 90%, 76%, ${alpha * .5})`;
    ctx.lineWidth = 1 + (1 - progress) * 2.5;
    ctx.shadowColor = `hsla(${wave.hue}, 94%, 72%, ${alpha})`;
    ctx.shadowBlur = 8 + wave.strength * 14;
    ctx.stroke();
    if (progress >= 1) emotionWaves.splice(index, 1);
  }
  ctx.restore();
}

function drawStimulusTrail(path, now, hue, opacity = 1) {
  if (!path?.length) return false;
  let visible = false;
  for (let index = 1; index < path.length; index += 1) {
    const previous = path[index - 1];
    const point = path[index];
    const age = now - point.bornAt;
    if (age >= DRAG_TRAIL_LIFETIME_MS) continue;
    const alpha = (1 - age / DRAG_TRAIL_LIFETIME_MS) ** 2 * opacity;
    ctx.beginPath();
    ctx.moveTo(previous.x, previous.y);
    ctx.lineTo(point.x, point.y);
    ctx.strokeStyle = `hsla(${hue + 32}, 94%, 82%, ${alpha * .72})`;
    ctx.lineWidth = 1.2 + alpha * 2.1;
    ctx.shadowColor = `hsla(${hue + 22}, 96%, 72%, ${alpha * .85})`;
    ctx.shadowBlur = 7 + alpha * 13;
    ctx.lineCap = "round";
    ctx.stroke();
    visible = true;
  }
  return visible;
}

function drawStimulusRing(x, y, radius, alpha, hue, lineWidth = 2) {
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.strokeStyle = `hsla(${hue}, 92%, 86%, ${alpha * .72})`;
  ctx.lineWidth = lineWidth;
  ctx.shadowColor = `hsla(${hue}, 96%, 78%, ${alpha})`;
  ctx.shadowBlur = 8 + alpha * 14;
  ctx.stroke();
}

function renderActivePointerEffect(now, hue) {
  if (!sourceAvailable || !activePointerGesture) return;
  const gesture = activePointerGesture;
  const heldFor = now - gesture.startedAt;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  if (gesture.dragging) {
    drawStimulusTrail(gesture.path, now, hue);
  } else if (heldFor >= LONG_PRESS_DURATION_MS) {
    const holdProgress = clamp(
      (heldFor - LONG_PRESS_DURATION_MS) / 1200,
    );
    const pulse = (Math.sin(now * .01) + 1) * .5;
    const radius = 26 - holdProgress * 9 + pulse * 3;
    const glow = ctx.createRadialGradient(
      gesture.currentX,
      gesture.currentY,
      0,
      gesture.currentX,
      gesture.currentY,
      radius * 2.4,
    );
    glow.addColorStop(0, `hsla(${hue + 18}, 96%, 88%, .32)`);
    glow.addColorStop(.35, `hsla(${hue}, 92%, 70%, .14)`);
    glow.addColorStop(1, "transparent");
    ctx.fillStyle = glow;
    ctx.fillRect(
      gesture.currentX - radius * 2.5,
      gesture.currentY - radius * 2.5,
      radius * 5,
      radius * 5,
    );
    drawStimulusRing(
      gesture.currentX,
      gesture.currentY,
      radius,
      .82,
      hue + 18,
      1.5,
    );
  }
  ctx.restore();
}

function renderStimulusRipples(now, hue) {
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let index = stimulusRipples.length - 1; index >= 0; index -= 1) {
    const ripple = stimulusRipples[index];
    const age = (now - ripple.bornAt) / 1000;
    const durations = {
      tap: 1.15,
      double_tap: 1.55,
      long_press: 1.8,
      drag: 1.15,
    };
    const duration = reduceMotion ? .4 : (durations[ripple.kind] || 1.15);
    const progress = clamp(age / duration);
    const alpha = 1 - progress;
    if (ripple.kind === "drag") {
      const trailVisible = drawStimulusTrail(ripple.path, now, hue, .9);
      if (progress < 1) {
        drawStimulusRing(
          ripple.x,
          ripple.y,
          12 + progress * Math.min(width, height) * .1,
          alpha,
          hue + 32,
          1.4,
        );
      }
      if (progress >= 1 && !trailVisible) stimulusRipples.splice(index, 1);
      continue;
    } else if (ripple.kind === "long_press") {
      const radius = 18 + progress * Math.min(width, height) * .085;
      drawStimulusRing(ripple.x, ripple.y, radius, alpha, hue + 18, 1.4 + alpha);
      drawStimulusRing(
        ripple.x,
        ripple.y,
        radius * .62,
        alpha * .55,
        hue + 18,
        1,
      );
    } else {
      const count = ripple.kind === "double_tap" ? 2 : 1;
      for (let ringIndex = 0; ringIndex < count; ringIndex += 1) {
        const ringProgress = clamp(progress - ringIndex * .13);
        const ringAlpha = (1 - ringProgress) * (ringIndex ? .65 : 1);
        const radius = 12 + ringProgress * Math.min(width, height) * .12;
        drawStimulusRing(
          ripple.x,
          ripple.y,
          radius,
          ringAlpha,
          hue + ringIndex * 28,
          1.2 + ringAlpha * 1.8,
        );
      }
    }
    if (progress >= 1) stimulusRipples.splice(index, 1);
  }
  ctx.restore();
}

function drawParticles(projected) {
  const glowBuckets = Array.from({ length: 4 }, () => []);
  for (const particle of projected) {
    const bucketIndex = Math.min(
      glowBuckets.length - 1,
      Math.floor(clamp(particle.alpha) * glowBuckets.length),
    );
    glowBuckets[bucketIndex].push(particle);
  }

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const bucket of glowBuckets) {
    if (!bucket.length) continue;
    let hueX = 0;
    let hueY = 0;
    let saturation = 0;
    let lightness = 0;
    let alpha = 0;
    let shadowAlpha = 0;
    let shadowBlur = 0;
    ctx.beginPath();
    for (const particle of bucket) {
      const hueRadians = particle.hue * Math.PI / 180;
      hueX += Math.cos(hueRadians);
      hueY += Math.sin(hueRadians);
      saturation += particle.saturation;
      lightness += particle.lightness;
      alpha += particle.alpha;
      shadowAlpha += particle.shadowAlpha;
      shadowBlur += particle.shadowBlur;
      ctx.moveTo(particle.x + particle.size, particle.y);
      ctx.arc(
        particle.x,
        particle.y,
        particle.size,
        0,
        Math.PI * 2,
      );
    }
    const count = bucket.length;
    const hue = (
      Math.atan2(hueY / count, hueX / count) * 180 / Math.PI
      + 360
    ) % 360;
    const averageSaturation = saturation / count;
    const averageLightness = lightness / count;
    const averageAlpha = alpha / count;
    ctx.fillStyle = `hsla(${hue}, ${averageSaturation}%, ${
      averageLightness
    }%, ${averageAlpha * .2})`;
    ctx.shadowColor = `hsla(${hue}, ${averageSaturation}%, ${
      averageLightness
    }%, ${(shadowAlpha / count) * .72})`;
    ctx.shadowBlur = shadowBlur / count;
    ctx.fill();
  }

  ctx.shadowBlur = 0;
  for (const particle of projected) {
    ctx.beginPath();
    ctx.fillStyle = `hsla(${particle.hue}, ${particle.saturation}%, ${
      particle.lightness
    }%, ${particle.alpha})`;
    ctx.arc(
      particle.x,
      particle.y,
      particle.size,
      0,
      Math.PI * 2,
    );
    ctx.fill();
  }
  ctx.restore();
}

function render(now) {
  // Keep visual time continuous after a dropped frame. It is less noticeable
  // for the animation to run briefly behind real time than to jump ahead.
  const dt = Math.min(
    Math.max((now - lastFrame) / 1000, 0),
    MAX_VISUAL_FRAME_SECONDS,
  );
  lastFrame = now;
  if (sourceAvailable && now - lastStateAt > STATE_TIMEOUT_MS) {
    markUnavailable(streamConnected ? "ゆらを待っています" : "再接続しています");
  }
  updateSignalPresence(dt);
  advanceStateTrajectory(dt);
  const t = now / 1000;
  const [targetHue, targetSaturation, targetLightness] = palette();
  const paletteRate = 1 - Math.exp(-dt * (reduceMotion ? 3 : 1.25));
  visualPalette.hue = mixHue(visualPalette.hue, targetHue, paletteRate);
  visualPalette.saturation = mix(
    visualPalette.saturation,
    targetSaturation,
    paletteRate,
  );
  visualPalette.lightness = mix(
    visualPalette.lightness,
    targetLightness,
    paletteRate,
  );
  const { hue, saturation, lightness } = visualPalette;
  const sceneAppearance = !sourceAvailable && presenceTransitionTarget === 0
    ? scatterAppearance
    : { hue, saturation, lightness };
  const sceneHue = sceneAppearance.hue;
  document.documentElement.style.setProperty("--accent", `hsl(${hue} ${saturation}% ${lightness}%)`);
  document.documentElement.style.setProperty("--accent-soft", `hsla(${hue} ${saturation}% ${lightness}% / .2)`);

  const bg = ctx.createRadialGradient(width * .5, height * .48, 0, width * .5, height * .48, Math.max(width, height) * .72);
  bg.addColorStop(
    0,
    `hsla(${sceneHue}, 42%, ${4 + centralParticlePresence * 6}%, .96)`,
  );
  bg.addColorStop(.45, "#070a14");
  bg.addColorStop(1, "#020309");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  const surfaceGlow = ctx.createLinearGradient(0, 0, 0, height * .28);
  surfaceGlow.addColorStop(
    0,
    `hsla(${sceneHue}, 72%, 72%, ${centralParticlePresence * .07})`,
  );
  surfaceGlow.addColorStop(1, `hsla(${sceneHue}, 72%, 72%, 0)`);
  ctx.fillStyle = surfaceGlow;
  ctx.fillRect(0, 0, width, height * .28);

  for (const mote of dust) {
    const alpha = .05 + .08 * (Math.sin(t * .25 + mote.phase) + 1);
    ctx.fillStyle = `hsla(${hue}, 70%, 76%, ${alpha})`;
    ctx.fillRect(mote.x * width, mote.y * height, mote.z * 1.5 + .25, mote.z * 1.5 + .25);
  }

  const arousal = display.emotion.arousal;
  const energy = display.drive.energy;
  const curiosity = display.drive.curiosity;
  const engagement = display.drive.engagement;
  const boredom = display.drive.boredom;
  const talking = display.emotion.talkativeness;
  const emotionShape = emotionVisualProfile();
  const pressure = emotionShape.pressure;
  const particleEmotionGroups = updateEmotionParticleGroups(dt);
  const baseRadius = Math.min(width, height) * (.18 + curiosity * .09 + energy * .025);
  const particleViewportScale = clamp(
    Math.min(width, height) / PARTICLE_SIZE_REFERENCE_VIEWPORT,
    1,
    MAX_PARTICLE_VIEWPORT_SCALE,
  );
  if (sourceAvailable) {
    lastFrameAppearance = {
      hue, saturation, lightness, energy, engagement, baseRadius,
    };
  }
  const speed = reduceMotion ? .025 : .045 + arousal * .23;
  rotationYAngle = (
    rotationYAngle
    + ROTATION_DIRECTION * speed * dt
    + Math.PI * 2
  ) % (Math.PI * 2);
  for (const group of particleEmotionGroups) {
    const speedReveal = group.visibility * innerDetailPresence;
    group.rotationOffset = (
      group.rotationOffset
      + ROTATION_DIRECTION
        * speed
        * (group.motionSpeedScale - 1)
        * speedReveal
        * dt
      + Math.PI * 2
    ) % (Math.PI * 2);
  }
  const rotationY = rotationYAngle;
  tiltPhase = (tiltPhase + .12 * dt) % (Math.PI * 2);
  const motionScale = reduceMotion ? .25 : 1;
  breathPhase = (
    breathPhase + (.3 + emotionShape.activation * 1.15) * dt
  ) % (Math.PI * 2);
  surfaceWavePhase = (
    surfaceWavePhase
    + (
      .2
      + emotionShape.activation * .75
      + emotionShape.amusement * .35
      + emotionShape.anger * .25
    ) * dt
  ) % (Math.PI * 2);
  surfaceCurlPhase = (
    surfaceCurlPhase
    + (.16 + emotionShape.activation * .62) * dt
  ) % (Math.PI * 2);
  talkFlowPhase = (
    talkFlowPhase + (.12 + talking * .45) * dt
  ) % (Math.PI * 2);
  pressurePulsePhase = (
    pressurePulsePhase + (1.4 + pressure * 2.8) * dt
  ) % (Math.PI * 2);

  const tiltAmplitude = (
    .025
    + emotionShape.activation * .05
    + emotionShape.amusement * .04
    + emotionShape.anger * .025
  ) * motionScale;
  const rotationX = Math.sin(tiltPhase) * tiltAmplitude;
  const flatten = 1
    - boredom * .07
    - emotionShape.sadness * (.035 + (1 - emotionShape.activation) * .04);
  const breathAmplitude = (
    .006
    + emotionShape.activation * .015
    + emotionShape.joy * .025
    + emotionShape.amusement * .015
    + emotionShape.surprise * .018
  ) * motionScale;
  const pulse = 1 + Math.sin(breathPhase) * breathAmplitude;
  const emotionScale = 1
    + emotionShape.joy * .03
    + emotionShape.amusement * .01
    + emotionShape.surprise * .02
    - emotionShape.anger * .012
    - emotionShape.sadness * .012
    - emotionShape.fear * .018
    - pressure * .07;
  const centerX = width * .5;
  const centerY = height * .49;

  const projected = particles.map((particle) => {
    const longitude = Math.atan2(particle.z, particle.x);
    const wave = Math.sin(
      surfaceWavePhase + particle.seed + particle.y * 4.5,
    );
    const curl = Math.cos(
      surfaceCurlPhase + particle.seed * 1.7 + particle.z * 5,
    );
    const sharpWave = Math.tanh(wave * 1.8) / Math.tanh(1.8);
    const joyWave = Math.sin(
      surfaceWavePhase * .7 + longitude * 2 + particle.y * 2.5,
    );
    const amusementWave = Math.sin(
      surfaceWavePhase * 1.35 + longitude * 3 + particle.seed,
    );
    const fearNoise = Math.sin(
      surfaceWavePhase * 2.8
      + particle.seed * 4.1
      + particle.y * 8,
    );
    const dynamicDeformation = (
      joyWave
        * emotionShape.joy
        * (.012 + emotionShape.activation * .04)
      + amusementWave
        * emotionShape.amusement
        * (.02 + emotionShape.activation * .05)
      + sharpWave
        * emotionShape.anger
        * (.025 + emotionShape.activation * .075)
      + curl
        * emotionShape.sadness
        * (.008 + emotionShape.activation * .012)
      + fearNoise
        * emotionShape.fear
        * (.01 + emotionShape.activation * .06)
      + wave
        * emotionShape.surprise
        * (.008 + emotionShape.activation * .02)
      + curl
        * emotionShape.discomfort
        * (.02 + emotionShape.activation * .035)
      + curl * emotionShape.pressureLeak * .045
    ) * motionScale;
    const driveLooseness = curl
      * (1 - engagement)
      * (.004 + boredom * .01)
      * motionScale;
    const radial = pulse
      * emotionScale
      * (1 + dynamicDeformation + driveLooseness);
    const source = {
      x: particle.x * radial,
      y: particle.y * radial * flatten,
      z: particle.z * radial,
    };
    const talkFlow = Math.sin(
      talkFlowPhase + particle.y * 4 + particle.seed,
    ) * talking * .02 * motionScale;
    const emotionGroup = particleEmotionGroups[particle.emotionGroup];
    const emotionReveal = emotionGroup.visibility * innerDetailPresence;
    const p = rotate(
      source,
      rotationX,
      rotationY + emotionGroup.rotationOffset + talkFlow,
    );
    const perspective = 1 / (2.7 - p.z * .75);
    const sphereX = centerX + p.x * baseRadius * perspective * 2.2;
    const sphereY = centerY + p.y * baseRadius * perspective * 2.2;
    const position = resolveParticlePosition(
      particle,
      sphereX,
      sphereY,
      centerX,
      centerY,
      dt,
    );
    const x = position.x;
    const y = position.y;
    const measuredVX = dt && particle.screenX !== undefined
      ? (x - particle.screenX) / dt : 0;
    const measuredVY = dt && particle.screenY !== undefined
      ? (y - particle.screenY) / dt : 0;
    const vx = position.vx ?? measuredVX;
    const vy = position.vy ?? measuredVY;
    const scattering = presenceTransitionTarget === 0
      && particle.motionStartX !== undefined;
    const gathering = presenceTransitionTarget === 1
      && presenceTransitionProgress < 1
      && particle.motionStartX !== undefined;
    const gatheringBlend = gathering
      ? smootherstep(presenceTransitionProgress)
      : (scattering ? 0 : 1);
    const largeParticleBoost = 1
      + smoothstep(.82, 1.25, particle.weight) * .35;
    const randomSizeWeight = particle.weight * largeParticleBoost;
    const organicSizeVariation = mix(
      .82,
      1.18,
      (particle.weight - .35) / .9,
    );
    const sizeWeight = mix(
      randomSizeWeight,
      emotionGroup.sizeScale * organicSizeVariation,
      emotionReveal,
    );
    const connectedSize = (.55 + perspective * 1.8)
      * (.75 + energy * .7)
      * particleViewportScale
      * sizeWeight;
    const depthVisibility = mix(.28, 1, clamp((p.z + 1) * .5));
    const connectedAlpha = clamp(.12 + perspective * .48 + p.z * .1)
      * depthVisibility
      * clamp(signalPresence * 1.6);
    const connectedSaturation = mix(saturation, 92, emotionReveal);
    const connectedLightness = lightness - (1 - depthVisibility) * 18 + p.z * 4;
    const connectedShadowAlpha = mix(.16, .65, depthVisibility);
    const connectedHue = mixHue(hue, emotionGroup.hue, emotionReveal)
      + p.z * 18;
    const connectedShadowBlur = (4 + arousal * 9) * particleViewportScale;
    const holdsMotionAppearance = scattering || gathering;
    const transitionNumber = (snapshot, connected) => (
      holdsMotionAppearance && snapshot !== undefined
        ? mix(snapshot, connected, gatheringBlend)
        : connected
    );
    const visualSize = transitionNumber(particle.motionSize, connectedSize);
    const visualAlpha = transitionNumber(particle.motionAlpha, connectedAlpha);
    const visualHue = holdsMotionAppearance && particle.motionHue !== undefined
      ? mixHue(particle.motionHue, connectedHue, gatheringBlend)
      : connectedHue;
    const visualSaturation = transitionNumber(
      particle.motionSaturation,
      connectedSaturation,
    );
    const visualLightness = transitionNumber(
      particle.motionLightness,
      connectedLightness,
    );
    const visualShadowBlur = transitionNumber(
      particle.motionShadowBlur,
      connectedShadowBlur,
    );
    const visualShadowAlpha = transitionNumber(
      particle.motionShadowAlpha,
      connectedShadowAlpha,
    );
    const visualZ = transitionNumber(particle.motionZ, p.z);
    particle.screenX = x;
    particle.screenY = y;
    particle.screenVX = Number.isFinite(vx) ? vx : 0;
    particle.screenVY = Number.isFinite(vy) ? vy : 0;
    particle.screenSize = visualSize;
    particle.screenAlpha = visualAlpha;
    particle.screenHue = visualHue;
    particle.screenSaturation = visualSaturation;
    particle.screenLightness = visualLightness;
    particle.screenShadowBlur = visualShadowBlur;
    particle.screenShadowAlpha = visualShadowAlpha;
    particle.screenZ = visualZ;
    return {
      x,
      y,
      vx: clamp(particle.screenVX, -260, 260),
      vy: clamp(particle.screenVY, -260, 260),
      z: visualZ,
      size: visualSize,
      alpha: visualAlpha,
      hue: visualHue,
      saturation: visualSaturation,
      lightness: visualLightness,
      shadowBlur: visualShadowBlur,
      shadowAlpha: visualShadowAlpha,
    };
  }).sort((a, b) => a.z - b.z);

  const haloBaseRadius = !sourceAvailable && presenceTransitionTarget === 0
    ? scatterAppearance.baseRadius || baseRadius
    : baseRadius;
  const glowRadius = haloBaseRadius * 1.35;
  const particlesNearCenter = projected.filter(
    (particle) => Math.hypot(
      particle.x - centerX,
      particle.y - centerY,
    ) <= glowRadius,
  ).length;
  const centerPresenceTarget = particlesNearCenter / projected.length;
  const centerPresenceRate = 1 - Math.exp(-dt * 6);
  centralParticlePresence = mix(
    centralParticlePresence,
    centerPresenceTarget,
    centerPresenceRate,
  );
  const detailsReady = sourceAvailable
    && presenceTransitionTarget === 1
    && presenceTransitionProgress >= 1;
  const detailPresenceRate = 1 - Math.exp(-dt * (detailsReady ? 1.6 : 5));
  innerDetailPresence = mix(
    innerDetailPresence,
    detailsReady ? 1 : 0,
    detailPresenceRate,
  );

  drawParticles(projected);

  ctx.globalCompositeOperation = "lighter";
  const haloAppearance = !sourceAvailable && presenceTransitionTarget === 0
    ? scatterAppearance
    : { hue, saturation, lightness, energy, engagement };
  const halo = ctx.createRadialGradient(
    centerX,
    centerY,
    0,
    centerX,
    centerY,
    haloBaseRadius * 1.55,
  );
  halo.addColorStop(
    0,
    `hsla(${haloAppearance.hue}, ${haloAppearance.saturation}%, 72%, ${
      (0.075 + haloAppearance.energy * .06) * centralParticlePresence
    })`,
  );
  halo.addColorStop(
    .35,
    `hsla(${haloAppearance.hue}, ${haloAppearance.saturation}%, 50%, ${
      (0.035 + haloAppearance.engagement * .045) * centralParticlePresence
    })`,
  );
  halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.fillRect(
    centerX - haloBaseRadius * 1.6,
    centerY - haloBaseRadius * 1.6,
    haloBaseRadius * 3.2,
    haloBaseRadius * 3.2,
  );
  ctx.globalCompositeOperation = "source-over";

  drawPressureCore(
    pressure,
    centerX,
    centerY,
    baseRadius,
    hue,
    innerDetailPresence,
  );
  renderEmotionWaves(now, centerX, centerY, baseRadius);

  const rotationForce = (28 + arousal * 88 + talking * 18) * signalPresence;
  renderBubbles(now, dt, projected, baseRadius, centerX, centerY, rotationForce, hue, saturation);
  renderStimulusRipples(now, hue);
  renderActivePointerEffect(now, hue);

  updateLabels();
  requestAnimationFrame(render);
}

function updateMetric(id, value, signed = false) {
  const node = document.querySelector(`#${id}`);
  node.textContent = `${sourceAvailable && value >= 0 && signed ? "+" : ""}${value.toFixed(2)}`;
  const normalized = sourceAvailable ? (signed ? (value + 1) / 2 : value) : 0;
  node.parentElement.querySelector("i").style.setProperty("--level", `${clamp(normalized) * 100}%`);
}

function updateLabels() {
  updateMetric("valence", display.emotion.valence, true);
  updateMetric("arousal", display.emotion.arousal);
  updateMetric("talkativeness", display.emotion.talkativeness);
  updateMetric("curiosity", display.drive.curiosity);
  updateMetric("energy", display.drive.energy);
  const moodNode = document.querySelector("#moodLabel");
  moodNode.textContent = moodLabels[display.emotion.mood] || display.emotion.mood;
  moodNode.title = dominantReactiveEmotions()
    .map((item) => `${reactiveLabels[item.name]} ${item.value.toFixed(2)}`)
    .join(" / ");
  const activity = display.activity?.type || (sourceAvailable ? "IDLE" : "UNKNOWN");
  document.querySelector("#activity").textContent = activity.replaceAll("_", " ").toUpperCase();
}

function markUnavailable(connectionText) {
  sourceAvailable = false;
  pendingStateSnapshots.length = 0;
  stateTransition = null;
  lastSnapshotReceivedAt = 0;
  Object.assign(state.emotion, { mood: "unknown", arousal: 0, valence: 0, talkativeness: 0 });
  Object.keys(state.emotion.reactive).forEach((key) => { state.emotion.reactive[key] = 0; });
  Object.assign(state.drive, { curiosity: 0, engagement: 0, boredom: 0, energy: 0 });
  state.activity = { type: null, active: false };
  state.attention = { engaged: false };
  display.activity = state.activity;
  display.attention = state.attention;
  document.querySelector("#connection").classList.remove("live");
  document.querySelector("#connectionText").textContent = connectionText;
  document.querySelector("#observedAt").textContent = "--:--:--";
}

function receive(next) {
  if (!next?.emotion || !next?.drive) return;
  const incomingReactive = next.emotion.reactive;
  const normalizedReactive = {};
  for (const key of Object.keys(state.emotion.reactive)) {
    normalizedReactive[key] = finiteNumber(incomingReactive?.[key], 0);
  }
  const snapshot = structuredClone(state);
  snapshot.emotion.mood = typeof next.emotion.mood === "string"
    ? next.emotion.mood : state.emotion.mood;
  snapshot.emotion.arousal = finiteNumber(
    next.emotion.arousal,
    state.emotion.arousal,
  );
  snapshot.emotion.valence = finiteNumber(
    next.emotion.valence,
    state.emotion.valence,
    -1,
    1,
  );
  snapshot.emotion.talkativeness = finiteNumber(
    next.emotion.talkativeness,
    state.emotion.talkativeness,
  );
  Object.assign(snapshot.emotion.reactive, normalizedReactive);
  for (const key of Object.keys(state.drive)) {
    snapshot.drive[key] = finiteNumber(next.drive[key], state.drive[key]);
  }
  snapshot.activity = next.activity || state.activity;
  snapshot.attention = next.attention || state.attention;
  snapshot.observed_at = next.observed_at;
  const receivedAt = performance.now();
  pendingStateSnapshots.push({ snapshot, receivedAt });
  lastStateAt = receivedAt;
  sourceAvailable = true;
  const connection = document.querySelector("#connection");
  connection.classList.add("live");
  document.querySelector("#connectionText").textContent = "LIVE STATE";
  const date = new Date(next.observed_at);
  document.querySelector("#observedAt").textContent = Number.isNaN(date.valueOf())
    ? "--:--:--" : date.toLocaleTimeString("ja-JP", { hour12: false });
}

let stimulusStatusTimer = null;
function setStimulusStatus(message) {
  const node = document.querySelector("#stimulusStatus");
  if (!node) return;
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(stimulusStatusTimer);
  stimulusStatusTimer = setTimeout(() => node.classList.remove("visible"), 1800);
}

function normalizedCanvasPosition(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: clamp((clientX - rect.left) / rect.width),
    y: clamp((clientY - rect.top) / rect.height),
  };
}

function currentParticleZone() {
  const rect = canvas.getBoundingClientRect();
  const radius = lastFrameAppearance.baseRadius * 1.18;
  return {
    center: normalizedCanvasPosition(
      rect.left + width * .5,
      rect.top + height * .49,
    ),
    radius_x: clamp(radius / rect.width),
    radius_y: clamp(radius / rect.height),
  };
}

function createDragGestureId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return `drag-${globalThis.crypto.randomUUID()}`;
  }
  return `drag-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function sendStimulus(kind, clientX, clientY, details = {}) {
  if (!sourceAvailable) {
    setStimulusStatus("ゆらとの接続を待っています");
    return;
  }
  const now = performance.now();
  const rateLimitKey = details.rateLimitKey || kind;
  const minimumIntervalMs = details.minimumIntervalMs
    ?? STIMULUS_INTERVAL_MS;
  const lastStimulusAt = lastStimulusAtByKind.get(rateLimitKey) ?? -Infinity;
  if (!details.force && now - lastStimulusAt < minimumIntervalMs) {
    if (details.showStatus !== false) {
      setStimulusStatus("刺激は少し間をあけて届けられます");
    }
    return;
  }
  if (details.clearRateLimit) {
    lastStimulusAtByKind.delete(rateLimitKey);
  } else {
    lastStimulusAtByKind.set(rateLimitKey, now);
  }
  const position = normalizedCanvasPosition(clientX, clientY);
  const payload = { kind, ...position };
  if (details.startPosition) {
    payload.start_position = normalizedCanvasPosition(
      details.startPosition.x,
      details.startPosition.y,
    );
  }
  if (details.durationMs !== undefined) {
    const maximumDurationMs = kind === "drag" ? 60_000 : 10_000;
    payload.duration_ms = Math.min(
      maximumDurationMs,
      Math.max(0, details.durationMs),
    );
  }
  if (details.gestureId) {
    payload.gesture_id = details.gestureId;
    payload.gesture_phase = details.gesturePhase;
    payload.gesture_sequence = details.gestureSequence;
  }
  if (details.particleZone) {
    payload.particle_zone = details.particleZone;
  }
  if (details.renderRipple !== false) {
    stimulusRipples.push({
      kind,
      x: clientX,
      y: clientY,
      path: details.path || [{ x: clientX, y: clientY }],
      bornAt: now,
    });
    if (stimulusRipples.length > 12) stimulusRipples.shift();
  }
  const messages = {
    tap: "ゆらへ、そっと触れました",
    double_tap: "ゆらへ、二度触れました",
    long_press: "ゆらへ、しばらく触れました",
    drag: "ゆらの粒子を、そっとなぞりました",
  };
  if (details.showStatus !== false) {
    setStimulusStatus(messages[kind] || "ゆらへ刺激を届けました");
  }
  try {
    const response = await fetch("/api/stimuli", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.status === 429) {
      if (details.showStatus !== false) {
        setStimulusStatus("刺激は少し間をあけて届けられます");
      }
    } else if (!response.ok) {
      setStimulusStatus("今は刺激を届けられません");
    }
  } catch {
    setStimulusStatus("今は刺激を届けられません");
  }
}

function sendDragSample(gesture, phase, clientX, clientY, occurredAt) {
  const previousX = gesture.lastDragSampleX ?? gesture.startX;
  const previousY = gesture.lastDragSampleY ?? gesture.startY;
  const sequence = gesture.dragSequence;
  gesture.dragSequence += 1;
  gesture.lastDragSampleX = clientX;
  gesture.lastDragSampleY = clientY;
  gesture.lastDragSampleAt = occurredAt;
  if (phase === "end") gesture.dragStreamEnded = true;
  sendStimulus("drag", clientX, clientY, {
    startPosition: { x: previousX, y: previousY },
    durationMs: occurredAt - gesture.startedAt,
    path: gesture.path,
    gestureId: gesture.dragGestureId,
    gesturePhase: phase,
    gestureSequence: sequence,
    particleZone: currentParticleZone(),
    rateLimitKey: gesture.dragGestureId,
    minimumIntervalMs: DRAG_SAMPLE_INTERVAL_MS,
    force: phase === "end",
    clearRateLimit: phase === "end",
    renderRipple: phase === "end",
    showStatus: phase === "start",
  });
}

function queueTapGesture(clientX, clientY, occurredAt) {
  if (
    pendingTapGesture
    && occurredAt - pendingTapGesture.occurredAt <= DOUBLE_TAP_INTERVAL_MS
    && Math.hypot(
      clientX - pendingTapGesture.x,
      clientY - pendingTapGesture.y,
    ) <= DOUBLE_TAP_DISTANCE_PX
  ) {
    clearTimeout(pendingTapGesture.timer);
    pendingTapGesture = null;
    sendStimulus("double_tap", clientX, clientY);
    return;
  }
  if (pendingTapGesture) {
    clearTimeout(pendingTapGesture.timer);
    sendStimulus("tap", pendingTapGesture.x, pendingTapGesture.y);
  }
  const gesture = {
    x: clientX,
    y: clientY,
    occurredAt,
    timer: null,
  };
  gesture.timer = setTimeout(() => {
    if (pendingTapGesture !== gesture) return;
    pendingTapGesture = null;
    sendStimulus("tap", gesture.x, gesture.y);
  }, DOUBLE_TAP_INTERVAL_MS);
  pendingTapGesture = gesture;
}

const stream = new EventSource("/events");
stream.addEventListener("open", () => {
  streamConnected = true;
  if (!sourceAvailable) document.querySelector("#connectionText").textContent = "ゆらを待っています";
});
stream.addEventListener("state", (event) => receive(JSON.parse(event.data)));
stream.onerror = () => {
  streamConnected = false;
  markUnavailable("再接続しています");
};

canvas.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || event.ctrlKey) return;
  canvas.setPointerCapture(event.pointerId);
  activePointerGesture = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    currentX: event.clientX,
    currentY: event.clientY,
    startedAt: performance.now(),
    dragging: false,
    movedBeyondDragDistance: false,
    dragGestureId: createDragGestureId(),
    dragSequence: 0,
    lastDragSampleX: null,
    lastDragSampleY: null,
    lastDragSampleAt: null,
    dragStreamEnded: false,
    path: [{
      x: event.clientX,
      y: event.clientY,
      bornAt: performance.now(),
    }],
  };
});
function handlePointerMove(event) {
  if (activePointerGesture?.pointerId !== event.pointerId) return;
  if ((event.buttons & 1) === 0) return;
  const now = performance.now();
  const previousPoint = activePointerGesture.path[
    activePointerGesture.path.length - 1
  ];
  activePointerGesture.currentX = event.clientX;
  activePointerGesture.currentY = event.clientY;
  const exceedsDragDistance = Math.hypot(
    event.clientX - activePointerGesture.startX,
    event.clientY - activePointerGesture.startY,
  ) >= DRAG_START_DISTANCE_PX;
  if (exceedsDragDistance) {
    activePointerGesture.movedBeyondDragDistance = true;
  }
  if (!activePointerGesture.dragging && exceedsDragDistance) {
    activePointerGesture.dragging = true;
    sendDragSample(
      activePointerGesture,
      "start",
      event.clientX,
      event.clientY,
      now,
    );
  }
  if (
    activePointerGesture.dragging
    && !activePointerGesture.dragStreamEnded
    && Math.hypot(
      event.clientX - previousPoint.x,
      event.clientY - previousPoint.y,
    ) >= 4
  ) {
    activePointerGesture.path.push({
      x: event.clientX,
      y: event.clientY,
      bornAt: now,
    });
    while (
      activePointerGesture.path.length > 1
      && now - activePointerGesture.path[0].bornAt
        >= DRAG_TRAIL_LIFETIME_MS
    ) {
      activePointerGesture.path.shift();
    }
    if (activePointerGesture.path.length > 96) {
      activePointerGesture.path.shift();
    }
    if (
      now - activePointerGesture.lastDragSampleAt
        >= DRAG_SAMPLE_INTERVAL_MS
      && Math.hypot(
        event.clientX - activePointerGesture.lastDragSampleX,
        event.clientY - activePointerGesture.lastDragSampleY,
      ) >= DRAG_SAMPLE_DISTANCE_PX
    ) {
      sendDragSample(
        activePointerGesture,
        "update",
        event.clientX,
        event.clientY,
        now,
      );
    }
  }
}

function handlePointerUp(event) {
  if (activePointerGesture?.pointerId !== event.pointerId) return;
  const gesture = activePointerGesture;
  activePointerGesture = null;
  if (canvas.hasPointerCapture(event.pointerId)) {
    canvas.releasePointerCapture(event.pointerId);
  }
  const durationMs = performance.now() - gesture.startedAt;
  if (gesture.dragging) {
    const releasedAt = performance.now();
    gesture.path.push({
      x: event.clientX,
      y: event.clientY,
      bornAt: releasedAt,
    });
    while (
      gesture.path.length > 1
      && releasedAt - gesture.path[0].bornAt >= DRAG_TRAIL_LIFETIME_MS
    ) {
      gesture.path.shift();
    }
    if (!gesture.dragStreamEnded) {
      sendDragSample(
        gesture,
        "end",
        event.clientX,
        event.clientY,
        performance.now(),
      );
    }
  } else if (gesture.movedBeyondDragDistance) {
    return;
  } else if (durationMs >= LONG_PRESS_DURATION_MS) {
    sendStimulus("long_press", event.clientX, event.clientY, { durationMs });
  } else {
    queueTapGesture(event.clientX, event.clientY, performance.now());
  }
}

function handlePointerCancel(event) {
  if (activePointerGesture?.pointerId === event.pointerId) {
    if (
      activePointerGesture.dragging
      && !activePointerGesture.dragStreamEnded
    ) {
      sendDragSample(
        activePointerGesture,
        "end",
        activePointerGesture.lastDragSampleX,
        activePointerGesture.lastDragSampleY,
        performance.now(),
      );
    }
    activePointerGesture = null;
  }
}

// Pointer capture normally keeps delivery on the canvas, but window-level capture
// also covers browser/overlay boundary transitions and lost canvas targeting.
window.addEventListener("pointermove", handlePointerMove, true);
window.addEventListener("pointerup", handlePointerUp, true);
window.addEventListener("pointercancel", handlePointerCancel, true);
canvas.addEventListener("dblclick", (event) => event.preventDefault());
canvas.addEventListener("keydown", (event) => {
  if (!["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  sendStimulus("tap", width * .5, height * .49);
});
addEventListener("resize", resize);
resize();
requestAnimationFrame(render);

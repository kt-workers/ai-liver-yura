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
let presenceTransitionStartedAt = performance.now();
let presenceTransitionProgress = 1;
let presenceAcceleratedProgress = 1;
let centralParticlePresence = 0;
let innerDetailPresence = 0;
let rotationYAngle = 0;
const visualPalette = { hue: 202, saturation: 84, lightness: 72 };
let lastFrameAppearance = {
  hue: 202, saturation: 84, lightness: 72, energy: 0, engagement: 0,
  baseRadius: 0,
};
let scatterAppearance = { ...lastFrameAppearance };
let nextBubbleAt = 0;
const bubbles = [];
const emotionWaves = [];
const stimulusRipples = [];
let lastStimulusAt = -Infinity;
const STATE_TIMEOUT_MS = 45000;
const PRESENCE_GATHER_DURATION_MS = 7000;
const PRESENCE_SCATTER_DURATION_MS = 4200;
const CENTRIFUGAL_ACCELERATION_MIN = .12;
const CENTRIFUGAL_ACCELERATION_GAIN = .08;
const ROTATION_DIRECTION = -1;
const STIMULUS_INTERVAL_MS = 850;

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

const reactiveLabels = {
  joy: "喜び",
  amusement: "愉快",
  anger: "怒り",
  sadness: "悲しみ",
  fear: "恐れ",
  surprise: "驚き",
  discomfort: "不快",
};

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

function updateSignalPresence(now) {
  const target = sourceAvailable ? 1 : 0;
  if (target !== presenceTransitionTarget) {
    presenceTransitionTarget = target;
    presenceTransitionStart = signalPresence;
    presenceTransitionStartedAt = now;
    beginParticleTransition(target);
  }

  const duration = target ? PRESENCE_GATHER_DURATION_MS : PRESENCE_SCATTER_DURATION_MS;
  presenceTransitionProgress = clamp((now - presenceTransitionStartedAt) / duration);
  presenceAcceleratedProgress = presenceTransitionProgress * presenceTransitionProgress;
  signalPresence = mix(
    presenceTransitionStart,
    target,
    presenceAcceleratedProgress,
  );
}

function resolveParticlePosition(particle, sphereX, sphereY, now, centerX, centerY) {
  if (
    presenceTransitionTarget === 0
    && particle.motionStartX !== undefined
    && particle.motionStartY !== undefined
  ) {
    const elapsed = Math.min(
      (now - presenceTransitionStartedAt) / 1000,
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
    return {
      x: mix(particle.motionStartX, sphereX, presenceAcceleratedProgress),
      y: mix(particle.motionStartY, sphereY, presenceAcceleratedProgress),
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

  return { x: sphereX, y: sphereY, vx: null, vy: null };
}

function smoothState(dt) {
  const rate = 1 - Math.exp(-dt * 2.2);
  for (const group of ["emotion", "drive"]) {
    for (const [key, value] of Object.entries(state[group])) {
      if (typeof value === "number") display[group][key] = mix(display[group][key], value, rate);
      else if (key !== "reactive") display[group][key] = value;
    }
  }
  for (const [key, value] of Object.entries(state.emotion.reactive)) {
    display.emotion.reactive[key] = mix(display.emotion.reactive[key], value, rate);
  }
  display.activity = state.activity;
  display.attention = state.attention;
}

function dominantReactiveEmotions() {
  return Object.entries(display.emotion.reactive)
    .filter(([name]) => name !== "emotional_pressure")
    .map(([name, value]) => ({ name, value, hue: reactiveHues[name] }))
    .filter((item) => item.value >= .04)
    .sort((a, b) => b.value - a.value)
    .slice(0, 2);
}

function emotionalTurbulence() {
  const reactiveIntensity = Math.max(
    0,
    ...Object.entries(display.emotion.reactive)
      .filter(([name]) => name !== "emotional_pressure")
      .map(([, value]) => value),
  );
  const arousalIntensity = clamp((display.emotion.arousal - .45) / .55);
  const valenceIntensity = clamp((Math.abs(display.emotion.valence) - .25) / .75);
  return clamp(
    arousalIntensity * .45
    + display.emotion.reactive.emotional_pressure * .4
    + reactiveIntensity * .45
    + valenceIntensity * .15,
  );
}

function palette() {
  const base = palettes[display.emotion.mood] || palettes.neutral;
  const emotionalHue = display.emotion.valence < 0
    ? 222 + display.emotion.valence * -20
    : 198 - display.emotion.valence * 156;
  return [mix(emotionalHue, base[0], 0.48), base[1], base[2]];
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

function drawEmotionCurrents(
  t,
  currents,
  centerX,
  centerY,
  baseRadius,
  rotationX,
  rotationY,
  reveal,
) {
  if (!sourceAvailable || !currents.length || reveal <= .01) return;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let currentIndex = 0; currentIndex < currents.length; currentIndex += 1) {
    const current = currents[currentIndex];
    const phaseOffset = currentIndex * Math.PI + t * (.08 + current.value * .09);
    ctx.beginPath();
    for (let index = 0; index <= 96; index += 1) {
      const progress = index / 96;
      const angle = progress * Math.PI * 4 + phaseOffset;
      const y = (progress * 2 - 1) * .82;
      const ringRadius = Math.sqrt(Math.max(0, 1 - y * y));
      const source = {
        x: Math.cos(angle) * ringRadius * 1.035,
        y,
        z: Math.sin(angle) * ringRadius * 1.035,
      };
      const point = rotate(source, rotationX, rotationY);
      const perspective = 1 / (2.7 - point.z * .75);
      const x = centerX + point.x * baseRadius * perspective * 2.2;
      const projectedY = centerY + point.y * baseRadius * perspective * 2.2;
      if (index === 0) ctx.moveTo(x, projectedY);
      else ctx.lineTo(x, projectedY);
    }
    const alpha = clamp((.12 + current.value * .55) * reveal);
    ctx.strokeStyle = `hsla(${current.hue}, 88%, 72%, ${alpha})`;
    ctx.lineWidth = 1 + current.value * 2.2;
    ctx.shadowColor = `hsla(${current.hue}, 92%, 68%, ${alpha})`;
    ctx.shadowBlur = 7 + current.value * 13;
    ctx.stroke();
  }
  ctx.restore();
}

function drawPressureCore(t, pressure, centerX, centerY, baseRadius, hue, reveal) {
  if (!sourceAvailable || pressure <= .01 || reveal <= .01) return;
  const pulse = 1 + Math.sin(t * (1.4 + pressure * 2.8)) * (.025 + pressure * .045);
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

function renderStimulusRipples(now, hue) {
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let index = stimulusRipples.length - 1; index >= 0; index -= 1) {
    const ripple = stimulusRipples[index];
    const age = (now - ripple.bornAt) / 1000;
    const duration = reduceMotion ? .35 : 1.15;
    const progress = clamp(age / duration);
    const radius = 12 + progress * Math.min(width, height) * .12;
    const alpha = 1 - progress;
    ctx.beginPath();
    ctx.arc(ripple.x, ripple.y, radius, 0, Math.PI * 2);
    ctx.strokeStyle = `hsla(${hue}, 92%, 86%, ${alpha * .7})`;
    ctx.lineWidth = 1.2 + alpha * 1.8;
    ctx.shadowColor = `hsla(${hue}, 96%, 78%, ${alpha})`;
    ctx.shadowBlur = 8 + alpha * 14;
    ctx.stroke();
    if (progress >= 1) stimulusRipples.splice(index, 1);
  }
  ctx.restore();
}

function render(now) {
  const dt = Math.min((now - lastFrame) / 1000, 0.05);
  lastFrame = now;
  if (sourceAvailable && now - lastStateAt > STATE_TIMEOUT_MS) {
    markUnavailable(streamConnected ? "ゆらを待っています" : "再接続しています");
  }
  updateSignalPresence(now);
  smoothState(dt);
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
  const pressure = display.emotion.reactive.emotional_pressure;
  const turbulence = emotionalTurbulence();
  const reactiveCurrents = dominantReactiveEmotions();
  const baseRadius = Math.min(width, height) * (.18 + curiosity * .09 + energy * .025);
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
  const rotationY = rotationYAngle;
  const rotationX = Math.sin(t * .12) * (.035 + turbulence * .13);
  const flatten = 1 - boredom * turbulence * .18;
  const pulse = 1
    + Math.sin(t * (.35 + turbulence * 1.2)) * (.008 + turbulence * .075);
  const centerX = width * .5;
  const centerY = height * .49;

  const projected = particles.map((particle) => {
    const wave = Math.sin(
      t * (.22 + turbulence * .9) + particle.seed + particle.y * 4.5,
    );
    const curl = Math.cos(
      t * (.18 + turbulence * .72) + particle.seed * 1.7 + particle.z * 5,
    );
    const looseness = turbulence
      * (.055 + (1 - engagement) * .055 + boredom * .045);
    const pressureCompression = 1 - pressure * .12;
    const radial = pulse * pressureCompression
      * (1 + wave * (.003 + turbulence * .09) + looseness * curl);
    const source = {
      x: particle.x * radial,
      y: particle.y * radial * flatten,
      z: particle.z * radial,
    };
    const p = rotate(source, rotationX, rotationY + particle.seed * talking * .015);
    const perspective = 1 / (2.7 - p.z * .75);
    const sphereX = centerX + p.x * baseRadius * perspective * 2.2;
    const sphereY = centerY + p.y * baseRadius * perspective * 2.2;
    const position = resolveParticlePosition(
      particle,
      sphereX,
      sphereY,
      now,
      centerX,
      centerY,
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
    const connectedSize = (.55 + perspective * 1.8)
      * particle.weight
      * (.75 + energy * .7);
    const depthVisibility = mix(.28, 1, clamp((p.z + 1) * .5));
    const connectedAlpha = clamp(.12 + perspective * .48 + p.z * .1)
      * depthVisibility
      * clamp(signalPresence * 1.6);
    const connectedLightness = lightness - (1 - depthVisibility) * 18 + p.z * 4;
    const connectedShadowAlpha = mix(.16, .65, depthVisibility);
    const visualSize = scattering && particle.motionSize !== undefined
      ? particle.motionSize : connectedSize;
    const visualAlpha = scattering && particle.motionAlpha !== undefined
      ? particle.motionAlpha : connectedAlpha;
    const visualHue = scattering && particle.motionHue !== undefined
      ? particle.motionHue : hue + p.z * 18;
    const visualSaturation = scattering && particle.motionSaturation !== undefined
      ? particle.motionSaturation : saturation;
    const visualLightness = scattering && particle.motionLightness !== undefined
      ? particle.motionLightness : connectedLightness;
    const visualShadowBlur = scattering && particle.motionShadowBlur !== undefined
      ? particle.motionShadowBlur : 4 + arousal * 9;
    const visualShadowAlpha = scattering && particle.motionShadowAlpha !== undefined
      ? particle.motionShadowAlpha : connectedShadowAlpha;
    const visualZ = scattering && particle.motionZ !== undefined
      ? particle.motionZ : p.z;
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

  drawEmotionCurrents(
    t,
    reactiveCurrents,
    centerX,
    centerY,
    baseRadius * (1 - pressure * .08),
    rotationX,
    rotationY,
    innerDetailPresence,
  );

  ctx.globalCompositeOperation = "lighter";
  for (const p of projected) {
    ctx.beginPath();
    ctx.fillStyle = `hsla(${p.hue}, ${p.saturation}%, ${p.lightness}%, ${p.alpha})`;
    ctx.shadowColor = `hsla(${p.hue}, ${p.saturation}%, ${p.lightness}%, ${p.shadowAlpha})`;
    ctx.shadowBlur = p.shadowBlur;
    ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
    ctx.fill();
  }

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
    t,
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
  const previousReactive = { ...state.emotion.reactive };
  const incomingReactive = next.emotion.reactive;
  const normalizedReactive = {};
  for (const key of Object.keys(state.emotion.reactive)) {
    normalizedReactive[key] = finiteNumber(incomingReactive?.[key], 0);
  }
  if (sourceAvailable) {
    createEmotionWave(previousReactive, normalizedReactive, performance.now());
  }
  state.emotion.mood = typeof next.emotion.mood === "string"
    ? next.emotion.mood : state.emotion.mood;
  state.emotion.arousal = finiteNumber(next.emotion.arousal, state.emotion.arousal);
  state.emotion.valence = finiteNumber(next.emotion.valence, state.emotion.valence, -1, 1);
  state.emotion.talkativeness = finiteNumber(
    next.emotion.talkativeness,
    state.emotion.talkativeness,
  );
  Object.assign(state.emotion.reactive, normalizedReactive);
  for (const key of Object.keys(state.drive)) {
    state.drive[key] = finiteNumber(next.drive[key], state.drive[key]);
  }
  state.activity = next.activity || state.activity;
  state.attention = next.attention || state.attention;
  state.observed_at = next.observed_at;
  lastStateAt = performance.now();
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

async function sendStimulus(clientX, clientY) {
  if (!sourceAvailable) {
    setStimulusStatus("ゆらとの接続を待っています");
    return;
  }
  const now = performance.now();
  if (now - lastStimulusAt < STIMULUS_INTERVAL_MS) {
    setStimulusStatus("刺激は少し間をあけて届けられます");
    return;
  }
  lastStimulusAt = now;
  const rect = canvas.getBoundingClientRect();
  const x = clamp((clientX - rect.left) / rect.width);
  const y = clamp((clientY - rect.top) / rect.height);
  stimulusRipples.push({ x: clientX, y: clientY, bornAt: now });
  setStimulusStatus("ゆらへ、そっと触れました");
  try {
    const response = await fetch("/api/stimuli", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "tap", x, y }),
    });
    if (response.status === 429) {
      setStimulusStatus("刺激は少し間をあけて届けられます");
    } else if (!response.ok) {
      setStimulusStatus("今は刺激を届けられません");
    }
  } catch {
    setStimulusStatus("今は刺激を届けられません");
  }
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
  if (event.button !== 0) return;
  sendStimulus(event.clientX, event.clientY);
});
canvas.addEventListener("keydown", (event) => {
  if (!["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  sendStimulus(width * .5, height * .49);
});
addEventListener("resize", resize);
resize();
requestAnimationFrame(render);

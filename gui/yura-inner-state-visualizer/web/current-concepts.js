const canvases = [...document.querySelectorAll(".concept-canvas")];
const controls = {
  emotionA: document.querySelector("#emotionA"),
  strengthA: document.querySelector("#strengthA"),
  emotionB: document.querySelector("#emotionB"),
  strengthB: document.querySelector("#strengthB"),
  arousal: document.querySelector("#arousal"),
};

const emotionStyles = {
  joy: { hue: 44, phase: .22, tilt: -.46, speedScale: 1.03 },
  amusement: { hue: 322, phase: 1.18, tilt: .56, speedScale: 1.07 },
  anger: { hue: 7, phase: 2.08, tilt: -.72, speedScale: 1.08 },
  sadness: { hue: 224, phase: 2.92, tilt: .34, speedScale: .94 },
  fear: { hue: 274, phase: 3.72, tilt: -.18, speedScale: 1.05 },
  surprise: { hue: 184, phase: 4.54, tilt: .76, speedScale: 1.07 },
  discomfort: { hue: 104, phase: 5.38, tilt: -.58, speedScale: .97 },
};

const goldenAngle = Math.PI * (3 - Math.sqrt(5));
function balancedEmotionGroup(index) {
  const pairIndex = Math.floor(index / 2);
  const randomValue = Math.sin((pairIndex + 1) * 12.9898) * 43758.5453;
  const pairFlip = randomValue - Math.floor(randomValue) >= .5 ? 1 : 0;
  return (index % 2) ^ pairFlip;
}

const spherePoints = Array.from({ length: 380 }, (_, index) => {
  const y = 1 - index / 379 * 2;
  const radius = Math.sqrt(1 - y * y);
  const theta = goldenAngle * index;
  return {
    x: Math.cos(theta) * radius,
    y,
    z: Math.sin(theta) * radius,
    weight: .5 + ((Math.sin(index * 91.17) + 1) * .5) ** 3 * 1.1,
    emotionGroup: balancedEmotionGroup(index),
  };
});

function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, value));
}

function rotateX(point, angle) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return {
    x: point.x,
    y: point.y * cosine - point.z * sine,
    z: point.y * sine + point.z * cosine,
  };
}

function rotateY(point, angle) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return {
    x: point.x * cosine - point.z * sine,
    y: point.y,
    z: point.x * sine + point.z * cosine,
  };
}

function rotateZ(point, angle) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return {
    x: point.x * cosine - point.y * sine,
    y: point.x * sine + point.y * cosine,
    z: point.z,
  };
}

function rotateScene(point, rotation) {
  return rotateX(rotateY(point, rotation), -.08);
}

function project(point, scene) {
  const perspective = 1 / (2.8 - point.z * .72);
  return {
    x: scene.cx + point.x * scene.radius * perspective * 2.15,
    y: scene.cy + point.y * scene.radius * perspective * 2.15,
    z: point.z,
    perspective,
  };
}

function normalize(point) {
  const length = Math.hypot(point.x, point.y, point.z) || 1;
  return { x: point.x / length, y: point.y / length, z: point.z / length };
}

function cross(a, b) {
  return {
    x: a.y * b.z - a.z * b.y,
    y: a.z * b.x - a.x * b.z,
    z: a.x * b.y - a.y * b.x,
  };
}

function addScaled(a, b, scale) {
  return {
    x: a.x + b.x * scale,
    y: a.y + b.y * scale,
    z: a.z + b.z * scale,
  };
}

function stateFromControls() {
  return {
    emotions: [
      {
        name: controls.emotionA.value,
        strength: Number(controls.strengthA.value),
      },
      {
        name: controls.emotionB.value,
        strength: Number(controls.strengthB.value),
      },
    ],
    arousal: Number(controls.arousal.value),
  };
}

function sizeCanvas(canvas) {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const pixelWidth = Math.floor(width * dpr);
  const pixelHeight = Math.floor(height * dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {
    ctx,
    width,
    height,
    cx: width * .5,
    cy: height * .51,
    radius: Math.min(width, height) * .33,
  };
}

function clearScene(scene) {
  const { ctx, width, height, cx, cy, radius } = scene;
  const background = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * 2.7);
  background.addColorStop(0, "rgba(18, 42, 61, .62)");
  background.addColorStop(.42, "rgba(6, 12, 25, .96)");
  background.addColorStop(1, "#02040a");
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, width, height);

  const halo = ctx.createRadialGradient(cx, cy, radius * .1, cx, cy, radius * 1.55);
  halo.addColorStop(0, "rgba(100, 205, 238, .09)");
  halo.addColorStop(.55, "rgba(65, 127, 170, .035)");
  halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.fillRect(cx - radius * 1.7, cy - radius * 1.7, radius * 3.4, radius * 3.4);
}

function drawSphere(
  scene,
  rotation,
  arousal,
  emotions = null,
  groupRotationOffsets = [0, 0],
) {
  const rankedEmotions = emotions
    ? [...emotions].sort((a, b) => b.strength - a.strength)
    : null;
  const projected = spherePoints.map((point, index) => {
    const wave = 1 + Math.sin(index * .37 + rotation * 2.1) * arousal * .012;
    const rotated = rotateScene(
      {
        x: point.x * wave,
        y: point.y * wave,
        z: point.z * wave,
      },
      rotation + groupRotationOffsets[point.emotionGroup],
    );
    return {
      ...project(rotated, scene),
      weight: point.weight,
      emotionGroup: point.emotionGroup,
    };
  }).sort((a, b) => a.z - b.z);

  const { ctx } = scene;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const point of projected) {
    const depth = clamp((point.z + 1) * .5);
    const alpha = (.1 + depth * .58) * (.72 + arousal * .25);
    const emotion = rankedEmotions?.[point.emotionGroup];
    const emotionStyle = emotion ? emotionStyles[emotion.name] : null;
    const sizeScale = emotion
      ? .68 + emotion.strength * .9
      : 1;
    const organicSizeVariation = .82
      + clamp((point.weight - .5) / 1.1) * .36;
    const sizeWeight = emotion
      ? sizeScale * organicSizeVariation
      : point.weight;
    const size = (.55 + point.perspective * 1.9)
      * sizeWeight;
    const hue = emotionStyle?.hue ?? 194;
    const saturation = emotionStyle ? 92 : 78;
    ctx.beginPath();
    ctx.fillStyle = `hsla(${hue + point.z * 18}, ${
      saturation
    }%, ${58 + depth * 22}%, ${alpha})`;
    ctx.arc(point.x, point.y, size, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function segmentVisibleForPass(z, pass) {
  return pass === "front" ? z >= 0 : z < 0;
}

function drawMembrane(scene, state, rotation, pass) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    const offset = emotionIndex ? .12 : -.12;
    const segments = 72;
    for (let index = 0; index < segments; index += 1) {
      const angleA = index / segments * Math.PI * 2 + style.phase;
      const angleB = (index + 1) / segments * Math.PI * 2 + style.phase;
      const pointAt = (angle, widthOffset) => {
        const y = clamp(
          offset + Math.sin(angle * 2 + style.phase) * .2 + widthOffset,
          -.92,
          .92,
        );
        const ring = Math.sqrt(1 - y * y) * 1.035;
        return rotateScene({
          x: Math.cos(angle) * ring,
          y,
          z: Math.sin(angle) * ring,
        }, rotation);
      };
      const halfWidth = .025 + emotion.strength * .035;
      const corners = [
        pointAt(angleA, -halfWidth),
        pointAt(angleB, -halfWidth),
        pointAt(angleB, halfWidth),
        pointAt(angleA, halfWidth),
      ];
      const averageZ = corners.reduce((sum, point) => sum + point.z, 0) / 4;
      if (!segmentVisibleForPass(averageZ, pass)) continue;
      const projected = corners.map((point) => project(point, scene));
      const depth = clamp((averageZ + 1) * .5);
      ctx.beginPath();
      ctx.moveTo(projected[0].x, projected[0].y);
      projected.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
      ctx.closePath();
      ctx.fillStyle = `hsla(${style.hue}, 88%, 68%, ${
        emotion.strength * (.045 + depth * .12)
      })`;
      ctx.fill();
    }
  });
}

function orbitPoint(angle, style, emotionIndex, radius = 1.055) {
  let point = { x: Math.cos(angle) * radius, y: 0, z: Math.sin(angle) * radius };
  point = rotateX(point, style.tilt);
  point = rotateZ(point, emotionIndex ? .36 : -.32);
  return point;
}

function drawStream(scene, state, rotation, pass, elapsed) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    const count = 18 + Math.round(emotion.strength * 14);
    for (let index = 0; index < count; index += 1) {
      const trail = index / count;
      const angle = style.phase
        + trail * Math.PI * 2
        - elapsed * (.34 + state.arousal * .34);
      const point = rotateScene(
        orbitPoint(angle, style, emotionIndex),
        rotation,
      );
      if (!segmentVisibleForPass(point.z, pass)) continue;
      const projected = project(point, scene);
      const depth = clamp((point.z + 1) * .5);
      const pulse = .45 + .55 * Math.sin(trail * Math.PI) ** 2;
      const alpha = emotion.strength * pulse * (.16 + depth * .62);
      ctx.beginPath();
      ctx.fillStyle = `hsla(${style.hue}, 92%, 76%, ${alpha})`;
      ctx.shadowColor = `hsla(${style.hue}, 94%, 68%, ${alpha})`;
      ctx.shadowBlur = 4 + emotion.strength * 10;
      ctx.arc(
        projected.x,
        projected.y,
        .8 + pulse * (1.2 + emotion.strength * 1.5),
        0,
        Math.PI * 2,
      );
      ctx.fill();
    }
  });
  ctx.shadowBlur = 0;
}

function drawOrbit(scene, state, rotation, pass) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    const segments = 42;
    const visibleRatio = .28 + emotion.strength * .62;
    for (let index = 0; index < segments; index += 1) {
      const pattern = ((index * 13 + Math.round(style.phase * 10)) % segments) / segments;
      if (pattern > visibleRatio) continue;
      const angleA = index / segments * Math.PI * 2 + style.phase;
      const angleB = (index + .62) / segments * Math.PI * 2 + style.phase;
      const pointA = rotateScene(orbitPoint(angleA, style, emotionIndex, 1.075), rotation);
      const pointB = rotateScene(orbitPoint(angleB, style, emotionIndex, 1.075), rotation);
      const averageZ = (pointA.z + pointB.z) * .5;
      if (!segmentVisibleForPass(averageZ, pass)) continue;
      const a = project(pointA, scene);
      const b = project(pointB, scene);
      const depth = clamp((averageZ + 1) * .5);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = `hsla(${style.hue}, 90%, 75%, ${
        emotion.strength * (.12 + depth * .6)
      })`;
      ctx.lineWidth = .8 + emotion.strength * 2.2;
      ctx.lineCap = "round";
      ctx.shadowColor = `hsla(${style.hue}, 94%, 66%, ${depth * emotion.strength})`;
      ctx.shadowBlur = 3 + emotion.strength * 9;
      ctx.stroke();
    }
  });
  ctx.shadowBlur = 0;
}

function smallCirclePoint(anchor, tangent, bitangent, radius, angle) {
  const radial = {
    x: tangent.x * Math.cos(angle) + bitangent.x * Math.sin(angle),
    y: tangent.y * Math.cos(angle) + bitangent.y * Math.sin(angle),
    z: tangent.z * Math.cos(angle) + bitangent.z * Math.sin(angle),
  };
  return normalize(addScaled(
    {
      x: anchor.x * Math.cos(radius),
      y: anchor.y * Math.cos(radius),
      z: anchor.z * Math.cos(radius),
    },
    radial,
    Math.sin(radius),
  ));
}

function drawPulse(scene, state, rotation, pass, elapsed) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    const anchor = normalize({
      x: Math.cos(style.phase),
      y: emotionIndex ? .28 : -.22,
      z: Math.sin(style.phase),
    });
    const tangent = normalize(cross({ x: 0, y: 1, z: 0 }, anchor));
    const bitangent = normalize(cross(anchor, tangent));
    for (let ringIndex = 0; ringIndex < 3; ringIndex += 1) {
      const pulse = (elapsed * (.18 + state.arousal * .14) + ringIndex / 3) % 1;
      const angularRadius = .12 + pulse * (.28 + emotion.strength * .2);
      const segments = 48;
      for (let index = 0; index < segments; index += 1) {
        const angleA = index / segments * Math.PI * 2;
        const angleB = (index + 1) / segments * Math.PI * 2;
        const pointA = rotateScene(
          smallCirclePoint(anchor, tangent, bitangent, angularRadius, angleA),
          rotation,
        );
        const pointB = rotateScene(
          smallCirclePoint(anchor, tangent, bitangent, angularRadius, angleB),
          rotation,
        );
        const averageZ = (pointA.z + pointB.z) * .5;
        if (!segmentVisibleForPass(averageZ, pass)) continue;
        const a = project(pointA, scene);
        const b = project(pointB, scene);
        const depth = clamp((averageZ + 1) * .5);
        const alpha = (1 - pulse) * emotion.strength * (.1 + depth * .52);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = `hsla(${style.hue}, 92%, 77%, ${alpha})`;
        ctx.lineWidth = .7 + emotion.strength * 1.4;
        ctx.shadowColor = `hsla(${style.hue}, 96%, 70%, ${alpha})`;
        ctx.shadowBlur = 4 + emotion.strength * 8;
        ctx.stroke();
      }
    }
  });
  ctx.shadowBlur = 0;
}

function emotionAnchor(style, emotionIndex, radius = 1) {
  return normalize({
    x: Math.cos(style.phase) * radius,
    y: emotionIndex ? .3 : -.24,
    z: Math.sin(style.phase) * radius,
  });
}

function drawCloud(scene, state, rotation, pass, elapsed) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    for (let cloudIndex = 0; cloudIndex < 5; cloudIndex += 1) {
      const angle = style.phase + cloudIndex * 2.17 + elapsed * .035;
      const source = {
        x: Math.cos(angle) * (.16 + cloudIndex * .035),
        y: (emotionIndex ? .16 : -.14) + Math.sin(angle * 1.7) * .12,
        z: Math.sin(angle) * (.16 + cloudIndex * .035),
      };
      const point = rotateScene(source, rotation);
      if (!segmentVisibleForPass(point.z, pass)) continue;
      const projected = project(point, scene);
      const depth = clamp((point.z + .45) / .9);
      const radius = scene.radius
        * (.28 + emotion.strength * .25)
        * (1 + Math.sin(elapsed * .55 + cloudIndex) * .06);
      const alpha = emotion.strength * (.025 + depth * .07);
      const gradient = ctx.createRadialGradient(
        projected.x,
        projected.y,
        0,
        projected.x,
        projected.y,
        radius,
      );
      gradient.addColorStop(0, `hsla(${style.hue}, 88%, 68%, ${alpha})`);
      gradient.addColorStop(.42, `hsla(${style.hue}, 82%, 54%, ${alpha * .55})`);
      gradient.addColorStop(1, "transparent");
      ctx.fillStyle = gradient;
      ctx.fillRect(
        projected.x - radius,
        projected.y - radius,
        radius * 2,
        radius * 2,
      );
    }
  });
}

function drawCluster(scene, state, rotation, pass, elapsed) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    const anchor = emotionAnchor(style, emotionIndex);
    const tangent = normalize(cross({ x: 0, y: 1, z: 0 }, anchor));
    const bitangent = normalize(cross(anchor, tangent));
    const count = 22 + Math.round(emotion.strength * 28);
    for (let index = 0; index < count; index += 1) {
      const seed = (Math.sin(index * 78.233 + style.phase * 19) + 1) * .5;
      const angle = index * goldenAngle + style.phase;
      const spread = (.04 + Math.sqrt(seed) * (.22 + emotion.strength * .13))
        * (1 + Math.sin(elapsed * .42 + index * .2) * .035);
      const point = rotateScene(
        smallCirclePoint(anchor, tangent, bitangent, spread, angle),
        rotation,
      );
      if (!segmentVisibleForPass(point.z, pass)) continue;
      const projected = project(point, scene);
      const depth = clamp((point.z + 1) * .5);
      const alpha = emotion.strength * (.12 + depth * .7);
      const size = .65 + seed * (1.5 + emotion.strength * 2);
      ctx.beginPath();
      ctx.fillStyle = `hsla(${style.hue}, 92%, 76%, ${alpha})`;
      ctx.shadowColor = `hsla(${style.hue}, 96%, 68%, ${alpha})`;
      ctx.shadowBlur = 3 + emotion.strength * 8;
      ctx.arc(projected.x, projected.y, size, 0, Math.PI * 2);
      ctx.fill();
    }
  });
  ctx.shadowBlur = 0;
}

function drawCore(scene, state, rotation, pass, elapsed) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    const orbitAngle = style.phase - elapsed * (.035 + state.arousal * .025);
    const source = {
      x: Math.cos(orbitAngle) * .35,
      y: emotionIndex ? .2 : -.18,
      z: Math.sin(orbitAngle) * .35,
    };
    const point = rotateScene(source, rotation);
    if (!segmentVisibleForPass(point.z, pass)) return;
    const projected = project(point, scene);
    const depth = clamp((point.z + .45) / .9);
    const pulse = 1 + Math.sin(elapsed * (1.1 + state.arousal) + style.phase) * .08;
    const radius = scene.radius * (.055 + emotion.strength * .055) * pulse;
    const alpha = emotion.strength * (.18 + depth * .48);
    const glow = ctx.createRadialGradient(
      projected.x,
      projected.y,
      0,
      projected.x,
      projected.y,
      radius * 3,
    );
    glow.addColorStop(0, `hsla(${style.hue}, 96%, 92%, ${alpha})`);
    glow.addColorStop(.18, `hsla(${style.hue}, 94%, 72%, ${alpha * .75})`);
    glow.addColorStop(.5, `hsla(${style.hue}, 88%, 52%, ${alpha * .22})`);
    glow.addColorStop(1, "transparent");
    ctx.fillStyle = glow;
    ctx.fillRect(
      projected.x - radius * 3,
      projected.y - radius * 3,
      radius * 6,
      radius * 6,
    );
    ctx.beginPath();
    ctx.arc(projected.x, projected.y, radius, 0, Math.PI * 2);
    ctx.strokeStyle = `hsla(${style.hue}, 96%, 84%, ${alpha * .78})`;
    ctx.lineWidth = .8 + emotion.strength * 1.4;
    ctx.shadowColor = `hsla(${style.hue}, 96%, 70%, ${alpha})`;
    ctx.shadowBlur = 7 + emotion.strength * 12;
    ctx.stroke();
  });
  ctx.shadowBlur = 0;
}

function drawPatch(scene, state, rotation, pass, elapsed) {
  const { ctx } = scene;
  state.emotions.forEach((emotion, emotionIndex) => {
    const style = emotionStyles[emotion.name];
    const anchor = emotionAnchor(style, emotionIndex);
    const point = rotateScene(anchor, rotation);
    if (!segmentVisibleForPass(point.z, pass)) return;
    const projected = project(point, scene);
    const depth = clamp((point.z + 1) * .5);
    const breathing = 1 + Math.sin(elapsed * (.7 + state.arousal * .55) + style.phase) * .08;
    const radius = scene.radius
      * (.22 + emotion.strength * .2)
      * projected.perspective
      * 2.15
      * breathing;
    const alpha = emotion.strength * (.035 + depth * .14);
    ctx.save();
    ctx.translate(projected.x, projected.y);
    ctx.rotate(style.tilt * .4);
    ctx.scale(.72 + depth * .28, 1);
    const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
    glow.addColorStop(0, `hsla(${style.hue}, 92%, 72%, ${alpha})`);
    glow.addColorStop(.5, `hsla(${style.hue}, 88%, 58%, ${alpha * .58})`);
    glow.addColorStop(.82, `hsla(${style.hue}, 82%, 48%, ${alpha * .15})`);
    glow.addColorStop(1, "transparent");
    ctx.fillStyle = glow;
    ctx.fillRect(-radius, -radius, radius * 2, radius * 2);
    ctx.restore();
  });
}

function drawCandidate(scene, type, state, rotation, pass, elapsed) {
  scene.ctx.save();
  scene.ctx.globalCompositeOperation = "lighter";
  if (type === "membrane") drawMembrane(scene, state, rotation, pass);
  if (type === "stream") drawStream(scene, state, rotation, pass, elapsed);
  if (type === "orbit") drawOrbit(scene, state, rotation, pass);
  if (type === "pulse") drawPulse(scene, state, rotation, pass, elapsed);
  if (type === "cloud") drawCloud(scene, state, rotation, pass, elapsed);
  if (type === "cluster") drawCluster(scene, state, rotation, pass, elapsed);
  if (type === "core") drawCore(scene, state, rotation, pass, elapsed);
  if (type === "patch") drawPatch(scene, state, rotation, pass, elapsed);
  scene.ctx.restore();
}

let lastFrame = performance.now();
let rotation = 0;
const particleGroupRotationOffsets = [0, 0];
function render(now) {
  const dt = Math.min(Math.max((now - lastFrame) / 1000, 0), 1 / 30);
  lastFrame = now;
  const state = stateFromControls();
  const baseSpeed = .08 + state.arousal * .16;
  rotation = (rotation - baseSpeed * dt + Math.PI * 2) % (Math.PI * 2);
  const rankedEmotions = [...state.emotions]
    .sort((a, b) => b.strength - a.strength);
  rankedEmotions.forEach((emotion, groupIndex) => {
    particleGroupRotationOffsets[groupIndex] = (
      particleGroupRotationOffsets[groupIndex]
      - baseSpeed
        * (emotionStyles[emotion.name].speedScale - 1)
        * dt
      + Math.PI * 2
    ) % (Math.PI * 2);
  });
  const elapsed = now / 1000;
  for (const canvas of canvases) {
    const scene = sizeCanvas(canvas);
    clearScene(scene);
    drawCandidate(scene, canvas.dataset.concept, state, rotation, "back", elapsed);
    drawSphere(
      scene,
      rotation,
      state.arousal,
      canvas.dataset.concept === "particle-split" ? state.emotions : null,
      canvas.dataset.concept === "particle-split"
        ? particleGroupRotationOffsets
        : undefined,
    );
    drawCandidate(scene, canvas.dataset.concept, state, rotation, "front", elapsed);
  }
  requestAnimationFrame(render);
}

for (const name of ["strengthA", "strengthB", "arousal"]) {
  const control = controls[name];
  const output = document.querySelector(`#${name}Value`);
  const update = () => { output.value = Number(control.value).toFixed(2); };
  control.addEventListener("input", update);
  update();
}

requestAnimationFrame(render);

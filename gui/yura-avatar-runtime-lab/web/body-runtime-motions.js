(() => {
  const applyBaseMotion = applyMotion;
  const resolveBaseAttentionTarget = resolveAttentionTarget;

  const spatialTargets = {
    left: { x: -0.82, y: 0 },
    right: { x: 0.82, y: 0 },
    up: { x: 0, y: -0.75 },
    down: { x: 0, y: 0.7 },
    up_left: { x: -0.72, y: -0.65 },
    left_up: { x: -0.72, y: -0.65 },
    up_right: { x: 0.72, y: -0.65 },
    right_up: { x: 0.72, y: -0.65 },
    down_left: { x: -0.72, y: 0.62 },
    left_down: { x: -0.72, y: 0.62 },
    down_right: { x: 0.72, y: 0.62 },
    right_down: { x: 0.72, y: 0.62 },
    center: { x: 0, y: 0 },
    front: { x: 0, y: 0 },
  };

  const poseAxes = {
    head_yaw: ["headYaw", 1],
    head_pitch: ["headPitch", 1],
    head_roll: ["headRoll", 1],
    torso_lean_x: ["torsoLeanX", 1],
    torso_lean_y: ["torsoLeanY", 1],
    body_height: ["bodyBounce", -90],
    gaze_x: ["gazeX", 1],
    gaze_y: ["gazeY", 1],
    eye_closure: ["eyeClosure", 1],
    mouth_open: ["mouthOpen", 1],
    left_arm_raise: ["leftArmRaise", 1],
    right_arm_raise: ["rightArmRaise", 1],
    left_arm_in: ["leftArmIn", 1],
    right_arm_in: ["rightArmIn", 1],
  };

  resolveAttentionTarget = function resolveBodyRuntimeAttentionTarget(attention, now) {
    const spatial = spatialTargets[String(attention.target || "").toLowerCase()];
    if (!spatial) return resolveBaseAttentionTarget(attention, now);

    const target = { ...spatial };
    if (attention.behavior === "wander") {
      target.x += Math.sin(now / 1300) * 0.28;
      target.y += Math.sin(now / 1900 + 1.1) * 0.18;
    }
    const dx = target.x - state.attentionTarget.x;
    const dy = target.y - state.attentionTarget.y;
    if (Math.hypot(dx, dy) > 0.08) {
      state.attentionTarget.x = clamp(target.x, -1, 1);
      state.attentionTarget.y = clamp(target.y, -1, 1);
    }
    return state.attentionTarget;
  };

  drawFace = function drawBodyRuntimeFace(pose) {
    const yaw = clamp(Number(pose.headYaw || 0), -1, 1);
    const expression = String(state.expression.name || "neutral");
    const commandedEyeClosure = expression === "eyes_close" ? 1 : 0;
    const commandedEyeOpen = expression === "eyes_open" ? 1 : 0;
    const eyeClosure = clamp(
      Math.max(Number(pose.eyeClosure || 0), commandedEyeClosure) - commandedEyeOpen,
      0,
      1,
    );
    const poseMouthOpen = clamp(Number(pose.mouthOpen || 0), 0, 1);
    const mouthOpen = Math.max(
      poseMouthOpen,
      expression === "mouth_open" ? 1 : 0,
    );
    const mouthClosed = expression === "mouth_close" && mouthOpen < 0.08;
    const gazeX = (Number(pose.gazeX || 0) + yaw * 0.24) * 11;
    const gazeY = Number(pose.gazeY || 0) * 9;
    const eyeY = -13;
    const eyeSpread = 27;

    ctx.save();
    ctx.translate(yaw * 22, 0);
    ctx.scale(1 - Math.abs(yaw) * 0.28, 1);
    ctx.strokeStyle = "rgba(216, 247, 255, 0.78)";
    ctx.fillStyle = "rgba(216, 247, 255, 0.78)";
    ctx.lineWidth = 7;

    for (const direction of [-1, 1]) {
      ctx.beginPath();
      const x = direction * eyeSpread + gazeX;
      const y = eyeY + gazeY;
      if (eyeClosure >= 0.55) {
        ctx.moveTo(x - 9, y);
        ctx.quadraticCurveTo(x, y + 5, x + 9, y);
        ctx.stroke();
      } else if (expression === "happy") {
        ctx.arc(direction * eyeSpread, eyeY + 5, 11, Math.PI * 1.1, Math.PI * 1.9);
        ctx.stroke();
      } else {
        const radius = expression === "surprised" ? 8 : 6;
        ctx.arc(x, y, Math.max(2, radius * (1 - eyeClosure)), 0, Math.PI * 2);
        ctx.fill();
      }
    }

    ctx.beginPath();
    if (mouthOpen > 0.08) {
      ctx.ellipse(
        0,
        24,
        10 + mouthOpen * 5,
        5 + mouthOpen * 16,
        0,
        0,
        Math.PI * 2,
      );
    } else if (mouthClosed) {
      ctx.moveTo(-18, 25);
      ctx.lineTo(18, 25);
    } else {
      switch (expression) {
        case "happy": ctx.arc(0, 12, 25, 0.12 * Math.PI, 0.88 * Math.PI); break;
        case "sad": ctx.arc(0, 42, 23, 1.15 * Math.PI, 1.85 * Math.PI); break;
        case "surprised": ctx.arc(0, 25, 12, 0, Math.PI * 2); break;
        case "angry":
        case "disgusted": ctx.moveTo(-24, 26); ctx.lineTo(24, 26); break;
        case "curious": ctx.arc(5, 18, 18, 0.08 * Math.PI, 0.75 * Math.PI); break;
        default: ctx.moveTo(-20, 25); ctx.quadraticCurveTo(0, 31, 20, 25);
      }
    }
    ctx.stroke();

    if (["angry", "disgusted", "curious"].includes(expression)) {
      ctx.beginPath();
      if (expression === "curious") {
        ctx.moveTo(-38, -31); ctx.lineTo(-17, -33);
        ctx.moveTo(15, -38); ctx.lineTo(39, -27);
      } else {
        ctx.moveTo(-39, -38); ctx.lineTo(-15, -29);
        ctx.moveTo(39, -38); ctx.lineTo(15, -29);
      }
      ctx.stroke();
    }
    ctx.restore();
  };

  function applyPoseTarget(pose, intent, weight, progress) {
    const responsiveness = clamp(Number(intent.responsiveness ?? 0.72), 0.05, 1);
    const easedProgress = ease(clamp(progress, 0, 1));
    const responseCurve = 1 - Math.pow(
      1 - easedProgress,
      0.45 + responsiveness * 2.4,
    );
    const alpha = clamp(responseCurve * weight, 0, 1);

    for (const [intentKey, [poseKey, scale]] of Object.entries(poseAxes)) {
      if (intent[intentKey] === undefined || intent[intentKey] === null) continue;
      const target = Number(intent[intentKey]) * scale;
      pose[poseKey] = lerp(Number(pose[poseKey] || 0), target, alpha);
    }
  }

  applyMotion = function applyBodyRuntimeMotion(pose, track, weight, progress) {
    const intent = track.intent || {};
    if (intent.type === "pose") {
      applyPoseTarget(pose, intent, weight, progress);
      return;
    }

    const intensity = Number(intent.intensity ?? 1);
    const amplitude = Number(intent.amplitude ?? 1);
    const repetitions = Number(intent.repetitions ?? 1);
    const tempo = Number(intent.tempo ?? 1);
    const bodyParticipation = Number(intent.body_participation ?? 0);
    const direction = intent.direction === "right" ? 1 : -1;
    const strength = intensity * amplitude * weight;
    const phase = progress * Math.PI * 2 * repetitions * tempo;
    const arc = Math.sin(progress * Math.PI);

    switch (intent.name) {
      case "breathing":
        pose.bodyBounce += Math.sin(phase) * 18 * strength;
        pose.torsoLeanY += Math.sin(phase) * 0.12 * strength;
        return;
      case "micro_sway":
        pose.torsoLeanX += direction * Math.sin(phase) * 0.72 * strength;
        pose.headRoll -= direction * Math.sin(phase * 0.85) * 0.14 * strength;
        return;
      case "idle_blink":
      case "blink":
        pose.eyeClosure = Math.max(Number(pose.eyeClosure || 0), arc * strength);
        return;
      case "idle_gaze_shift": {
        const drift = Math.sin(progress * Math.PI) * direction * strength;
        pose.gazeX += drift * 0.42;
        pose.gazeY += Math.sin(progress * Math.PI * 2) * 0.08 * strength;
        pose.headYaw += drift * 0.12;
        return;
      }
      case "idle_posture_adjust":
        pose.torsoLeanX += direction * Math.sin(progress * Math.PI) * 0.32 * strength;
        pose.headRoll -= direction * Math.sin(progress * Math.PI) * 0.07 * strength;
        return;
      case "speech_cadence": {
        const primary = Math.sin(phase);
        const secondary = Math.sin(phase * 0.47 + 1.1);
        pose.headPitch += (primary * 0.42 + secondary * 0.16) * strength;
        pose.headRoll += direction * secondary * 0.19 * strength;
        pose.bodyBounce += Math.max(0, primary) * 7 * strength;
        return;
      }
      case "speech_sway": {
        const primary = Math.sin(phase * 0.68);
        const secondary = Math.sin(phase * 1.31 + 0.8);
        pose.torsoLeanX += direction * (primary * 0.62 + secondary * 0.16) * strength;
        pose.torsoLeanY -= Math.max(0, secondary) * 0.12 * strength;
        pose.headRoll -= direction * primary * 0.1 * strength;
        return;
      }
      case "question_tilt":
        pose.headRoll += direction * arc * 0.5 * strength;
        pose.headPitch -= arc * 0.16 * strength;
        pose.torsoLeanY -= arc * 0.18 * strength * bodyParticipation;
        return;
      case "head_circle":
        pose.headYaw += Math.sin(phase) * 0.75 * strength;
        pose.headPitch += Math.cos(phase) * 0.52 * strength;
        pose.headRoll += Math.sin(phase) * 0.24 * strength;
        return;
      case "bow":
        pose.headPitch += arc * 0.95 * strength;
        pose.torsoLeanY += arc * 0.95 * strength;
        pose.bodyBounce += arc * 20 * strength;
        return;
      case "jump":
        pose.bodyBounce -= arc * 115 * strength;
        pose.leftArmRaise = Math.max(pose.leftArmRaise, arc * 0.35 * strength);
        pose.rightArmRaise = Math.max(pose.rightArmRaise, arc * 0.35 * strength);
        return;
      case "body_sway":
        pose.torsoLeanX += Math.sin(phase) * 0.92 * strength;
        pose.headRoll -= Math.sin(phase) * 0.18 * strength;
        return;
      case "body_twist":
        pose.torsoLeanX += Math.sin(phase) * 0.72 * strength;
        pose.headYaw -= Math.sin(phase) * 0.28 * strength;
        return;
      case "recoil":
        pose.torsoLeanY += arc * 0.72 * strength;
        pose.headPitch -= arc * 0.16 * strength;
        return;
      case "open_outward": {
        const side = track.channel === "left_arm" ? "left" : "right";
        pose[`${side}ArmIn`] = Math.min(
          pose[`${side}ArmIn`],
          -arc * 0.72 * strength,
        );
        pose[`${side}ArmRaise`] = Math.max(
          pose[`${side}ArmRaise`],
          arc * 0.18 * strength,
        );
        return;
      }
      case "straighten":
        pose.torsoLeanY -= arc * 0.24 * strength;
        pose.bodyBounce -= arc * 8 * strength;
        return;
      case "posture_open":
        pose.leftArmIn = Math.min(pose.leftArmIn, -0.62 * strength);
        pose.rightArmIn = Math.min(pose.rightArmIn, -0.62 * strength);
        pose.torsoLeanY -= 0.16 * strength;
        return;
      case "posture_closed":
        pose.leftArmIn = Math.max(pose.leftArmIn, 0.72 * strength);
        pose.rightArmIn = Math.max(pose.rightArmIn, 0.72 * strength);
        pose.torsoLeanY += 0.12 * strength;
        return;
      case "posture_forward":
        pose.torsoLeanY -= 0.42 * strength;
        return;
      case "posture_withdrawn":
        pose.torsoLeanY += 0.48 * strength;
        pose.leftArmIn = Math.max(pose.leftArmIn, 0.42 * strength);
        pose.rightArmIn = Math.max(pose.rightArmIn, 0.42 * strength);
        return;
      default:
        applyBaseMotion(pose, track, weight, progress);
    }
  };
})();

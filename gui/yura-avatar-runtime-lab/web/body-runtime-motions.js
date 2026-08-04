(() => {
  const applyBaseMotion = applyMotion;

  applyMotion = function applyBodyRuntimeMotion(pose, track, weight, progress) {
    const intent = track.intent || {};
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
        pose.bodyBounce += Math.sin(phase) * 13 * strength;
        pose.torsoLeanY += Math.sin(phase) * 0.08 * strength;
        return;
      case "micro_sway":
        pose.torsoLeanX += Math.sin(phase) * 0.5 * strength;
        pose.headRoll -= Math.sin(phase * 0.85) * 0.08 * strength;
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

(() => {
  const applyBaseMotion = applyMotion;

  applyMotion = function applyBodyRuntimeMotion(pose, track, weight, progress) {
    const intent = track.intent || {};
    const intensity = Number(intent.intensity ?? 1);
    const amplitude = Number(intent.amplitude ?? 1);
    const repetitions = Number(intent.repetitions ?? 1);
    const tempo = Number(intent.tempo ?? 1);
    const strength = intensity * amplitude * weight;
    const phase = progress * Math.PI * 2 * repetitions * tempo;
    const arc = Math.sin(progress * Math.PI);

    switch (intent.name) {
      case "breathing":
        pose.bodyBounce += Math.sin(phase) * 7 * strength;
        pose.torsoLeanY += Math.sin(phase) * 0.035 * strength;
        return;
      case "micro_sway":
        pose.torsoLeanX += Math.sin(phase) * 0.2 * strength;
        pose.headRoll -= Math.sin(phase * 0.85) * 0.035 * strength;
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
        pose.leftArmIn = Math.min(pose.leftArmIn, -0.22 * strength);
        pose.rightArmIn = Math.min(pose.rightArmIn, -0.22 * strength);
        pose.torsoLeanY -= 0.07 * strength;
        return;
      case "posture_closed":
        pose.leftArmIn = Math.max(pose.leftArmIn, 0.42 * strength);
        pose.rightArmIn = Math.max(pose.rightArmIn, 0.42 * strength);
        pose.torsoLeanY += 0.05 * strength;
        return;
      case "posture_forward":
        pose.torsoLeanY -= 0.25 * strength;
        return;
      case "posture_withdrawn":
        pose.torsoLeanY += 0.32 * strength;
        pose.leftArmIn = Math.max(pose.leftArmIn, 0.2 * strength);
        pose.rightArmIn = Math.max(pose.rightArmIn, 0.2 * strength);
        return;
      default:
        applyBaseMotion(pose, track, weight, progress);
    }
  };
})();

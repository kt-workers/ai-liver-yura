(() => {
  const receiveLayeredPerformance = receivePerformance;
  const startBasePerformance = startPerformance;
  const activeLayeredTracks = activeTracks;
  const applyLayeredMotion = applyMotion;

  const channelPoseKeys = {
    head: ["headYaw", "headPitch", "headRoll", "gazeX", "gazeY", "eyeClosure"],
    torso: ["torsoLeanX", "torsoLeanY", "bodyBounce"],
    left_arm: ["leftArmRaise", "leftArmIn", "leftArmWave"],
    right_arm: ["rightArmRaise", "rightArmIn", "rightArmWave"],
    full_body: [
      "headYaw", "headPitch", "headRoll", "gazeX", "gazeY", "eyeClosure",
      "torsoLeanX", "torsoLeanY", "bodyBounce",
      "leftArmRaise", "leftArmIn", "leftArmWave",
      "rightArmRaise", "rightArmIn", "rightArmWave",
    ],
  };

  function poseSnapshot() {
    return {
      ...neutralPose(),
      ...(state.pose || {}),
    };
  }

  function attachContinuityOrigins(plan) {
    if (!plan || !Array.isArray(plan.tracks)) return;
    const origin = poseSnapshot();
    for (const track of plan.tracks) {
      if (track.continuity !== "current") continue;
      track.__continuityOrigin = { ...origin };
    }
  }

  function continuityOriginWeight(track, progress) {
    if (!track.__continuityOrigin) return 0;
    const duration = Math.max(1, Number(track.duration_ms || 1));
    const fadeOut = Math.max(0, Number(track.fade_out_ms || 0));
    if (fadeOut <= 0) return progress < 1 ? 1 : 0;
    const remaining = duration * (1 - clamp(progress, 0, 1));
    return clamp(remaining / fadeOut, 0, 1);
  }

  function applyContinuityOrigin(pose, track, progress) {
    const origin = track.__continuityOrigin;
    const keys = channelPoseKeys[track.channel];
    if (!origin || !keys || state.__continuityChannels.has(track.channel)) return;

    const weight = continuityOriginWeight(track, progress);
    for (const key of keys) {
      const current = Number(pose[key] || 0);
      const start = Number(origin[key] || 0);
      pose[key] = lerp(current, start, weight);
    }
    state.__continuityChannels.add(track.channel);
  }

  startPerformance = function startContinuousPerformance(plan) {
    attachContinuityOrigins(plan);
    startBasePerformance(plan);
    // Trackごとのcontinuity=currentで開始姿勢を保持するため、
    // neutralへ向かう一括Transitionは使用しない。
    state.transition = null;
  };

  receivePerformance = function receiveContinuousPerformance(plan, sequence) {
    attachContinuityOrigins(plan);
    receiveLayeredPerformance(plan, sequence);
  };

  activeTracks = function activeContinuousTracks(now) {
    return activeLayeredTracks(now).sort((left, right) => {
      const priorityDifference =
        Number(left.track.layer_priority || 0) - Number(right.track.layer_priority || 0);
      if (priorityDifference !== 0) return priorityDifference;
      return String(left.track.track_id || "").localeCompare(
        String(right.track.track_id || ""),
      );
    });
  };

  applyMotion = function applyContinuousMotion(pose, track, weight, progress) {
    state.__continuityChannels ||= new Set();
    applyContinuityOrigin(pose, track, progress);
    applyLayeredMotion(pose, track, weight, progress);
  };

  const evaluateLayeredTracks = evaluateTracks;
  evaluateTracks = function evaluateContinuousTracks(now, deltaMs) {
    state.__continuityChannels = new Set();
    return evaluateLayeredTracks(now, deltaMs);
  };
})();

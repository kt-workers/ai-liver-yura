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
    const origin = track.__continuityOriginOverride || track.__continuityOrigin;
    if (!origin) return 0;
    const duration = Math.max(1, Number(track.duration_ms || 1));
    const fadeOut = Math.max(0, Number(track.fade_out_ms || 0));
    if (fadeOut <= 0) return progress < 1 ? 1 : 0;
    const remaining = duration * (1 - clamp(progress, 0, 1));
    return clamp(remaining / fadeOut, 0, 1);
  }

  function applyContinuityOrigin(pose, track, progress) {
    const origin = track.__continuityOriginOverride || track.__continuityOrigin;
    const keys = channelPoseKeys[track.channel];
    if (!origin || !keys || !track.__applyContinuityOrigin) return;

    const weight = continuityOriginWeight(track, progress);
    for (const key of keys) {
      const current = Number(pose[key] || 0);
      const start = Number(origin[key] || 0);
      pose[key] = lerp(current, start, weight);
    }
  }

  function assignChannelContinuityOrigins(entries) {
    const ownerByChannel = new Map();
    const firstEntryByChannel = new Map();

    for (const entry of entries) {
      const track = entry.track;
      track.__applyContinuityOrigin = false;
      delete track.__continuityOriginOverride;
      if (!firstEntryByChannel.has(track.channel)) {
        firstEntryByChannel.set(track.channel, entry);
      }
      if (track.__continuityOrigin) {
        ownerByChannel.set(track.channel, track);
      }
    }

    for (const [channel, owner] of ownerByChannel.entries()) {
      const firstEntry = firstEntryByChannel.get(channel);
      if (!firstEntry) continue;
      firstEntry.track.__applyContinuityOrigin = true;
      firstEntry.track.__continuityOriginOverride = owner.__continuityOrigin;
    }
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
    const entries = activeLayeredTracks(now).sort((left, right) => {
      const priorityDifference =
        Number(left.track.layer_priority || 0) - Number(right.track.layer_priority || 0);
      if (priorityDifference !== 0) return priorityDifference;
      return String(left.track.track_id || "").localeCompare(
        String(right.track.track_id || ""),
      );
    });
    assignChannelContinuityOrigins(entries);
    return entries;
  };

  applyMotion = function applyContinuousMotion(pose, track, weight, progress) {
    applyContinuityOrigin(pose, track, progress);
    applyLayeredMotion(pose, track, weight, progress);
  };
})();

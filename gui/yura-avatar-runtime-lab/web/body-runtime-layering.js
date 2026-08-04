(() => {
  const receiveBasePerformance = receivePerformance;
  const activeBaseTracks = activeTracks;
  const persistentOutputUnits = new Set([
    "body-autonomous",
    "body-activity-context",
  ]);

  state.bodyLayerPerformances = new Map();

  receivePerformance = function receiveLayeredBodyPerformance(plan, sequence) {
    if (!persistentOutputUnits.has(plan.output_unit_id)) {
      receiveBasePerformance(plan, sequence);
      return;
    }

    state.bodyLayerPerformances.set(plan.output_unit_id, {
      plan,
      sequence,
      startedAt: performance.now(),
    });
    state.lastPerformanceSequence = Math.max(
      Number(state.lastPerformanceSequence || 0),
      Number(sequence || 0),
    );
  };

  activeTracks = function activeLayeredBodyTracks(now) {
    const entries = activeBaseTracks(now);
    for (const [key, active] of state.bodyLayerPerformances.entries()) {
      const elapsed = now - active.startedAt;
      if (elapsed > active.plan.duration_ms) {
        state.bodyLayerPerformances.delete(key);
        continue;
      }
      for (const track of active.plan.tracks || []) {
        const localTime = elapsed - track.start_offset_ms;
        if (localTime < 0 || localTime > track.duration_ms) continue;
        const weight = trackWeight(track, localTime);
        if (weight <= 0) continue;
        entries.push({
          track,
          weight,
          progress: clamp(localTime / Math.max(1, track.duration_ms), 0, 1),
          source: key,
        });
      }
    }
    return entries;
  };
})();

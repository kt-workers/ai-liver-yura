(() => {
  const originalApplyRuntimeState = applyRuntimeState;
  let activePerformance = null;
  let segmentTimer = null;
  let lastPerformanceSequence = 0;
  const queuedPerformances = [];

  function cloneGaze(gaze) {
    return {
      target: gaze?.target || "neutral",
      behavior: gaze?.behavior || "maintain",
      intensity: Number(gaze?.intensity ?? 1),
    };
  }

  function performanceSummary(plan, segmentIndex) {
    const segment = plan.segments[segmentIndex];
    const expression = segment.expression?.name || "neutral";
    const gesture = segment.gesture?.name || "idle";
    const gaze = segment.gaze?.target || state.gaze.target || "neutral";
    return `${expression} / ${gesture} / ${gaze} · ${segmentIndex + 1}/${plan.segments.length}`;
  }

  function updatePresentation(plan, segmentIndex) {
    const segment = plan.segments[segmentIndex];
    state.expression = segment.expression?.name || "neutral";
    if (segment.gesture) {
      state.gesture = segment.gesture.name;
      state.gestureStartedAt = performance.now();
      state.gestureDuration = segment.duration_ms;
    } else {
      state.gesture = null;
    }
    if (segment.gaze) {
      state.gaze = cloneGaze(segment.gaze);
    }

    elements.expression.textContent = `${state.expression} (${Number(segment.expression?.intensity ?? 1).toFixed(2)})`;
    elements.gesture.textContent = segment.gesture
      ? `${segment.gesture.name} (${Number(segment.gesture.intensity ?? 1).toFixed(2)})`
      : "idle";
    elements.gaze.textContent = segment.gaze
      ? `${segment.gaze.target} (${Number(segment.gaze.intensity ?? 1).toFixed(2)})`
      : state.gaze.target || "neutral";
    elements.performance.textContent = performanceSummary(plan, segmentIndex);
    elements.payload.textContent = JSON.stringify(plan, null, 2);
  }

  function restoreAfterPerformance(active) {
    const behavior = active.plan.return_behavior;
    if (behavior === "previous") {
      state.expression = active.previous.expression;
      state.gesture = active.previous.gesture;
      state.gaze = cloneGaze(active.previous.gaze);
    } else if (behavior === "neutral") {
      state.expression = "neutral";
      state.gesture = null;
      state.gaze = { target: "neutral", behavior: "maintain", intensity: 1 };
    } else {
      state.gesture = null;
    }

    elements.expression.textContent = state.expression;
    elements.gesture.textContent = state.gesture || "idle";
    elements.gaze.textContent = state.gaze.target || "neutral";
    elements.performance.textContent = `${state.expression} / ${state.gesture || "idle"} / ${state.gaze.target || "neutral"}`;
  }

  function finishPerformance() {
    if (!activePerformance) return;
    const completed = activePerformance;
    activePerformance = null;
    segmentTimer = null;
    restoreAfterPerformance(completed);
    const next = queuedPerformances.shift();
    if (next) startPerformance(next);
  }

  function playSegment(index) {
    if (!activePerformance) return;
    if (index >= activePerformance.plan.segments.length) {
      finishPerformance();
      return;
    }
    activePerformance.segmentIndex = index;
    updatePresentation(activePerformance.plan, index);
    const duration = activePerformance.plan.segments[index].duration_ms;
    segmentTimer = window.setTimeout(() => playSegment(index + 1), duration);
  }

  function startPerformance(plan) {
    if (segmentTimer !== null) {
      window.clearTimeout(segmentTimer);
      segmentTimer = null;
    }
    activePerformance = {
      plan,
      segmentIndex: 0,
      previous: {
        expression: state.expression,
        gesture: state.gesture,
        gaze: cloneGaze(state.gaze),
      },
    };
    playSegment(0);
  }

  function receivePerformance(plan) {
    if (!plan || !Array.isArray(plan.segments) || !plan.segments.length) return;
    if (!activePerformance) {
      startPerformance(plan);
      return;
    }

    if (plan.interrupt_policy === "queue") {
      queuedPerformances.push(plan);
      return;
    }
    if (plan.interrupt_policy === "ignore_if_busy") {
      return;
    }
    if (Number(plan.priority) >= Number(activePerformance.plan.priority)) {
      startPerformance(plan);
    }
  }

  applyRuntimeState = function applyRuntimeStateWithPerformance(runtimeState) {
    originalApplyRuntimeState(runtimeState);
    const sequence = Number(runtimeState?.sequence || 0);
    const plan = runtimeState?.latest_performance;
    if (
      runtimeState?.latest_event_kind === "performance"
      && sequence > lastPerformanceSequence
      && plan
    ) {
      lastPerformanceSequence = sequence;
      receivePerformance(plan);
    }
  };

  async function sendPerformance(plan) {
    const response = await fetch("/api/avatar/performances", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(plan),
    });
    if (!response.ok) {
      throw new Error(`Performance rejected: HTTP ${response.status}`);
    }
  }

  const demoButton = document.getElementById("performanceDemoButton");
  if (demoButton) {
    demoButton.addEventListener("click", async () => {
      demoButton.disabled = true;
      const id = `manual-${Date.now()}`;
      try {
        await sendPerformance({
          schema_version: 1,
          type: "avatar.performance.submit",
          performance_id: id,
          source_activity_id: "manual-probe",
          output_unit_id: id,
          priority: 500,
          interrupt_policy: "replace_lower_priority",
          return_behavior: "neutral",
          segments: [
            {
              expression: { name: "curious", intensity: 0.65 },
              gesture: { name: "head_tilt", intensity: 0.55 },
              gaze: { target: "viewer", behavior: "maintain", intensity: 0.8 },
              duration_ms: 1200,
              fade_in_ms: 180,
              fade_out_ms: 220,
            },
            {
              expression: { name: "surprised", intensity: 0.85 },
              gesture: { name: "lean_forward", intensity: 0.75 },
              gaze: { target: "right", behavior: "glance", intensity: 0.9 },
              duration_ms: 1000,
              fade_in_ms: 120,
              fade_out_ms: 180,
            },
            {
              expression: { name: "happy", intensity: 0.9 },
              gesture: { name: "wave", intensity: 0.9 },
              gaze: { target: "viewer", behavior: "maintain", intensity: 1 },
              duration_ms: 1800,
              fade_in_ms: 180,
              fade_out_ms: 300,
            },
          ],
        });
      } catch (error) {
        console.error(error);
        setConnection("error", "Performance送信失敗");
      } finally {
        demoButton.disabled = false;
      }
    });
  }

  window.avatarPerformancePlayback = {
    receive: receivePerformance,
    send: sendPerformance,
  };
})();

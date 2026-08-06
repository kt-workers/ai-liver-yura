const metric = (label, value) => `<div class="metric"><small>${label}</small><strong>${value}</strong></div>`;
const format = (value, digits = 2) => Number(value ?? 0).toFixed(digits);

export class MetricsView {
  constructor(container, diagnosticList) {
    this.container = container;
    this.diagnosticList = diagnosticList;
    this.previousAt = 0;
    this.smoothedFps = 0;
  }

  render(frame) {
    const pose = frame.pose || {}, state = frame.inner_state || {};
    const now = performance.now();
    if (this.previousAt) {
      const instant = 1000 / Math.max(1, now - this.previousAt);
      this.smoothedFps = this.smoothedFps ? this.smoothedFps * .82 + instant * .18 : instant;
    }
    this.previousAt = now;
    this.container.innerHTML = [
      metric("覚醒度", format(state.arousal)),
      metric("緊張", format(state.tension)),
      metric("関与度", format(state.engagement)),
      metric("運動量", format(state.movement_energy)),
      metric("頭 Yaw", format(pose.head_yaw)),
      metric("胴体 Pitch", format(pose.torso_pitch)),
      metric("口の開き", format(pose.mouth_open)),
      metric("右腕", format(pose.right_arm_raise)),
    ].join("");
    this.diagnosticList.innerHTML = [
      ["Schema", frame.schema_version], ["Sequence", frame.sequence], ["Source", frame.source || "unknown"],
      ["Timestamp", frame.timestamp_ms], ["Attention", frame.attention_target_id || "ambient_scan"],
      ["Dwell", `${frame.attention_dwell_ms || 0} ms`], ["Joints", frame.joints?.length || 0],
      ["BlendShapes", frame.blend_shapes?.length || 0],
    ].map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`).join("");
    return this.smoothedFps;
  }
}

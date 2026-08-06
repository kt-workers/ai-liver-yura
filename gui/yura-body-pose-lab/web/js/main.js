import { BodyPoseLabApiClient } from "./api-client.js";
import { CandidateControls } from "./candidate-controls.js";
import { BodyPoseFrameStream } from "./frame-stream.js";
import { createLabState, applyEmotionPreset, emotionPayload, contextPayload, candidatesPayload } from "./lab-state.js";
import { MetricsView } from "./metrics-view.js";
import { PayloadView } from "./payload-view.js";
import { EMOTION_PRESETS } from "./presets.js";
import { StickFigureRenderer } from "./stick-figure-renderer.js";

const state = createLabState();
const api = new BodyPoseLabApiClient();
const renderer = new StickFigureRenderer(document.querySelector("#pose-canvas"));
const metrics = new MetricsView(document.querySelector("#metrics"), document.querySelector("#diagnostic-list"));
const payloadView = new PayloadView(document.querySelector("#payload-view"));
const toast = document.querySelector("#toast");
const controls = {
  arousal: document.querySelector("#arousal"), valence: document.querySelector("#valence"), joy: document.querySelector("#joy"),
  surprise: document.querySelector("#surprise"), fear: document.querySelector("#fear"), engagement: document.querySelector("#engagement"),
  movement: document.querySelector("#movement"), gaze: document.querySelector("#gaze"), posture: document.querySelector("#posture"),
};

const notify = (message) => { toast.textContent = message; toast.classList.add("visible"); clearTimeout(notify.timer); notify.timer = setTimeout(() => toast.classList.remove("visible"), 2200); };
const run = async (operation, success) => { try { await operation(); if (success) notify(success); } catch (error) { notify(error.message); console.error(error); } };

function syncControlsFromState() {
  const values = { arousal: state.emotion.arousal, valence: state.emotion.valence, joy: state.emotion.reactive.joy, surprise: state.emotion.reactive.surprise, fear: state.emotion.reactive.fear, engagement: state.context.engagement, movement: state.context.movement_energy, gaze: state.context.gaze_freedom };
  for (const [name, value] of Object.entries(values)) {
    controls[name].value = value;
    document.querySelector(`#${name}-value`).value = Number(value).toFixed(2);
  }
  controls.posture.value = state.context.posture_tendency;
}

function readEmotionControls() {
  state.emotion.arousal = Number(controls.arousal.value); state.emotion.valence = Number(controls.valence.value);
  state.emotion.reactive.joy = Number(controls.joy.value); state.emotion.reactive.surprise = Number(controls.surprise.value);
  state.emotion.reactive.fear = Number(controls.fear.value);
}
function readContextControls() {
  state.context.engagement = Number(controls.engagement.value); state.context.movement_energy = Number(controls.movement.value);
  state.context.gaze_freedom = Number(controls.gaze.value); state.context.posture_tendency = controls.posture.value;
}

function installPresets() {
  const list = document.querySelector("#preset-list");
  for (const preset of EMOTION_PRESETS) {
    const button = document.createElement("button"); button.type = "button"; button.textContent = preset.label;
    button.addEventListener("click", () => run(async () => { applyEmotionPreset(state, preset); syncControlsFromState(); await api.updateEmotion(emotionPayload(state)); }, `${preset.label}を反映しました`));
    list.append(button);
  }
}

function installControls() {
  for (const name of ["arousal", "valence", "joy", "surprise", "fear", "engagement", "movement", "gaze"]) {
    controls[name].addEventListener("input", () => { document.querySelector(`#${name}-value`).value = Number(controls[name].value).toFixed(2); });
  }
  for (const name of ["arousal", "valence", "joy", "surprise", "fear"]) {
    controls[name].addEventListener("change", () => run(async () => { readEmotionControls(); await api.updateEmotion(emotionPayload(state)); }));
  }
  for (const name of ["engagement", "movement", "gaze", "posture"]) {
    controls[name].addEventListener("change", () => run(async () => { readContextControls(); await api.updateActivityContext(contextPayload(state)); }));
  }
  document.querySelector('[data-action="blink"]').addEventListener("click", () => run(() => api.requestBlink(), "瞬きを要求しました"));
  document.querySelector('[data-action="speech"]').addEventListener("click", () => run(() => api.presentSpeech({ presentation_id: `lab-speech-${Date.now()}`, duration_ms: 1800, energy: Math.max(state.emotion.arousal, state.context.movement_energy) }), "発話口形を開始しました"));
  const constraints = {
    "right-arm": { constraint_id: "lab-right-arm", duration_ms: 1800, targets: [{ axis: "right_arm_raise", value: .92, weight: 1 }] },
    "left-arm": { constraint_id: "lab-left-arm", duration_ms: 1800, targets: [{ axis: "left_arm_raise", value: .92, weight: 1 }] },
    bow: { constraint_id: "lab-bow", duration_ms: 1600, targets: [{ axis: "torso_pitch", value: .72, weight: 1 }, { axis: "head_pitch", value: .48, weight: .8 }] },
    jump: { constraint_id: "lab-jump", duration_ms: 1100, attack_ratio: .16, release_ratio: .38, targets: [{ axis: "body_height", value: .78, weight: 1 }] },
  };
  document.querySelectorAll("[data-constraint]").forEach((button) => button.addEventListener("click", () => run(() => api.applyConstraint(constraints[button.dataset.constraint]), "一時制約を適用しました")));
  document.querySelector("#clear-constraint").addEventListener("click", () => run(() => api.clearConstraint(), "一時制約を解除しました"));
}

function updateConnection(status) {
  const dot = document.querySelector("#connection-dot"), label = document.querySelector("#connection-label");
  dot.className = `status-dot ${status}`; label.textContent = status === "online" ? "接続中" : status === "offline" ? "再接続中" : "接続準備中";
}

const candidates = new CandidateControls(document.querySelector("#candidate-layer"), state, () => run(() => api.updateCandidates(candidatesPayload(state))));
const stream = new BodyPoseFrameStream({
  onStatus: updateConnection,
  onFrame: (frame) => {
    state.latestFrame = frame; renderer.setFrame(frame); payloadView.render(frame);
    const fps = metrics.render(frame); document.querySelector("#fps").textContent = `${fps.toFixed(1)} fps`;
    document.querySelector("#attention-target").textContent = frame.attention_target_id || "ambient_scan";
    document.querySelector("#frame-source").textContent = frame.source || "unknown source";
  },
});

syncControlsFromState(); installPresets(); installControls(); candidates.render();
run(async () => { await api.updateEmotion(emotionPayload(state)); await api.updateActivityContext(contextPayload(state)); await api.updateCandidates(candidatesPayload(state)); });
stream.connect(); window.addEventListener("beforeunload", () => stream.close());

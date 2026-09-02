const $ = (id) => document.getElementById(id);
const canvas = $("stickCanvas");
const ctx = canvas.getContext("2d");
let latest = null;

function clamp(value, min, max) {
  const number = Number(value);
  return Math.max(min, Math.min(max, Number.isFinite(number) ? number : 0));
}

function qZAngle(rotation) {
  if (!rotation) return 0;
  return 2 * Math.atan2(Number(rotation.z) || 0, Number(rotation.w) || 1);
}

function projectionMap(command) {
  const joints = new Map();
  const channels = new Map();
  for (const item of command?.joint_projections || []) joints.set(item.canonical_joint_id, item);
  for (const item of command?.channel_projections || []) channels.set(item.canonical_channel, Number(item.value) || 0);
  return { joints, channels };
}

function line(a, b, color, width = 5) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

function draw() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const command = latest?.projection_command;
  const { joints, channels } = projectionMap(command);
  const scale = Math.min(rect.width, rect.height) / 5.2;
  const sway = clamp(channels.get("subtle_sway") || 0, -1, 1) * scale * 0.08;
  const breath = clamp(channels.get("breath_amplitude") || 0, 0, 1);
  const breathPhase = clamp(channels.get("breath_phase") || 0, 0, 1);
  const breathY = Math.sin(breathPhase * Math.PI * 2) * breath * scale * 0.025;

  const root = { x: rect.width * 0.5 + sway, y: rect.height * 0.72 + breathY };
  const chest = { x: root.x, y: root.y - scale * 0.9 };
  const neck = { x: chest.x, y: chest.y - scale * 0.14 };
  const head = { x: neck.x, y: neck.y - scale * 0.28 };
  const shoulderL = { x: chest.x - scale * 0.34, y: chest.y + scale * 0.04 };
  const shoulderR = { x: chest.x + scale * 0.34, y: chest.y + scale * 0.04 };
  const hipL = { x: root.x - scale * 0.18, y: root.y };
  const hipR = { x: root.x + scale * 0.18, y: root.y };

  const scaffold = "rgba(82,112,115,.65)";
  const physical = "rgba(153,247,237,.96)";
  line(root, chest, scaffold, 5);
  line(chest, neck, scaffold, 5);
  line(shoulderL, shoulderR, scaffold, 4);
  line(hipL, hipR, scaffold, 4);

  const leftElbow = { x: shoulderL.x - scale * 0.32, y: shoulderL.y + scale * 0.45 };
  const leftWrist = { x: leftElbow.x - scale * 0.08, y: leftElbow.y + scale * 0.42 };
  line(shoulderL, leftElbow, scaffold, 5);
  line(leftElbow, leftWrist, scaffold, 5);

  const armRotation = joints.get("arm")?.rotation;
  const angle = qZAngle(armRotation);
  const armCanvas = -angle;
  const elbow = {
    x: shoulderR.x + Math.cos(armCanvas) * scale * 0.52,
    y: shoulderR.y + Math.sin(armCanvas) * scale * 0.52,
  };
  const hand = {
    x: elbow.x + Math.cos(armCanvas) * scale * 0.42,
    y: elbow.y + Math.sin(armCanvas) * scale * 0.42,
  };
  line(shoulderR, elbow, physical, 7);
  line(elbow, hand, physical, 7);
  ctx.fillStyle = physical;
  ctx.beginPath(); ctx.arc(hand.x, hand.y, scale * 0.055, 0, Math.PI * 2); ctx.fill();

  const kneeL = { x: hipL.x - scale * 0.1, y: hipL.y + scale * 0.56 };
  const ankleL = { x: kneeL.x - scale * 0.04, y: kneeL.y + scale * 0.58 };
  const kneeR = { x: hipR.x + scale * 0.1, y: hipR.y + scale * 0.56 };
  const ankleR = { x: kneeR.x + scale * 0.04, y: kneeR.y + scale * 0.58 };
  line(hipL, kneeL, scaffold, 5); line(kneeL, ankleL, scaffold, 5);
  line(hipR, kneeR, scaffold, 5); line(kneeR, ankleR, scaffold, 5);

  ctx.strokeStyle = scaffold;
  ctx.fillStyle = "rgba(18,47,52,.95)";
  ctx.lineWidth = 4;
  ctx.beginPath(); ctx.ellipse(head.x, head.y, scale * .24, scale * .29, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

  const gazeX = clamp(channels.get("gaze_x") || 0, -1, 1) * scale * .05;
  const gazeY = clamp(channels.get("gaze_y") || 0, -1, 1) * scale * .04;
  const eyelid = clamp(channels.get("eyelid_openness") ?? 1, 0, 1);
  ctx.fillStyle = physical;
  if (eyelid < .18) {
    line({x:head.x-scale*.11,y:head.y-scale*.03},{x:head.x-scale*.04,y:head.y-scale*.03},physical,2);
    line({x:head.x+scale*.04,y:head.y-scale*.03},{x:head.x+scale*.11,y:head.y-scale*.03},physical,2);
  } else {
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(head.x + side * scale * .075 + gazeX, head.y - scale * .04 + gazeY, scale*.026, scale*.018*eyelid, 0, 0, Math.PI*2);
      ctx.fill();
    }
  }
  const mouth = clamp(channels.get("mouth_openness") || 0, 0, 1);
  ctx.strokeStyle = physical; ctx.lineWidth = 2;
  ctx.beginPath();
  if (mouth > .06) ctx.ellipse(head.x, head.y + scale*.1, scale*.06, scale*(.01 + mouth*.045), 0, 0, Math.PI*2);
  else { ctx.moveTo(head.x-scale*.055,head.y+scale*.1); ctx.lineTo(head.x+scale*.055,head.y+scale*.1); }
  ctx.stroke();

  const targetAngle = Number(latest?.controls?.target_angle ?? 0);
  const tx = shoulderR.x + Math.cos(-targetAngle) * scale * 1.15;
  const ty = shoulderR.y + Math.sin(-targetAngle) * scale * 1.15;
  ctx.strokeStyle = "rgba(255,207,117,.9)"; ctx.fillStyle = "rgba(255,207,117,.18)"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(tx, ty, scale*.09, 0, Math.PI*2); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(tx-scale*.13,ty); ctx.lineTo(tx+scale*.13,ty); ctx.moveTo(tx,ty-scale*.13); ctx.lineTo(tx,ty+scale*.13); ctx.stroke();

  ctx.fillStyle = "rgba(184,213,210,.7)"; ctx.font = "12px system-ui";
  ctx.fillText(`D10 arm angle: ${angle.toFixed(3)} rad`, 18, 26);
  ctx.fillText(`target input: ${targetAngle.toFixed(2)} rad`, 18, 44);
}

function text(id, value) { $(id).textContent = value ?? "—"; }
function pretty(value) { return JSON.stringify(value ?? null, null, 2); }

function update(snapshot) {
  latest = snapshot;
  $("connection").textContent = snapshot.fatal_error ? "Runtime FAIL" : "接続中";
  $("connection").className = snapshot.fatal_error ? "badge fail" : "badge";
  const avatar = snapshot.avatar || {};
  const realtime = snapshot.realtime || {};
  text("avatarStatus", avatar.status || "未投影");
  text("bodyRevision", snapshot.body_state_revision);
  text("frameCount", snapshot.frame_count);
  text("controllerStatus", snapshot.controller_status);
  text("sessionStatus", snapshot.session?.status || "—");
  text("activePlan", snapshot.session?.active_plan_id || snapshot.controller_plan_id || "—");
  text("plannerStatus", snapshot.planner?.status || "—");
  text("plannerLatency", snapshot.planner?.last_latency_ms == null ? "—" : `${snapshot.planner.last_latency_ms.toFixed(1)} ms`);
  text("pendingTasks", snapshot.pending_task_count);
  text("realtimeStatus", realtime.runtime || "—");
  text("realtimeLateTicks", realtime.late_tick_count ?? "—");
  text("projectionStatus", avatar.status || "—");
  text("droppedFrames", avatar.dropped_or_coalesced_frames ?? "—");
  $("channels").textContent = pretty(snapshot.frame?.channels || {});
  $("realtimeLayers").textContent = pretty(realtime.layer_statuses || {});
  $("plannerResult").textContent = pretty(snapshot.planner?.last_plan || {});
  $("diagnostics").textContent = pretty({
    fatal_error: snapshot.fatal_error,
    last_command_error: snapshot.last_command_error,
    planner_error: snapshot.planner?.last_error,
    avatar_diagnostics: avatar.diagnostics || [],
    avatar_degraded_items: avatar.degraded_items || [],
    realtime_overlay_bundle_id: realtime.overlay_bundle_id,
    realtime_based_on_body_state_revision: realtime.based_on_body_state_revision,
    realtime_speech_sample_active: realtime.speech_sample_active,
    browser_direct_channel_overlay: realtime.browser_direct_channel_overlay,
  });
  $("rendererAvailable").checked = Boolean(snapshot.renderer_available);
  const llm = snapshot.live_llm || {};
  $("liveLlmState").textContent = llm.ready
    ? `実LLM準備済み: model=${llm.model}`
    : "実LLMは OPENAI_API_KEY と YURA_VERIFY_OPENAI_MODEL の両方が必要です。";
  draw();
}

async function command(payload) {
  const response = await fetch("/api/command", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`command failed: ${response.status}`);
}

$("submitMotion").addEventListener("click", () => command({
  action: "submit_motion",
  mode: $("mode").value,
  delay_seconds: Number($("delay").value),
  target_angle: Number($("targetAngle").value),
}).catch(console.error));

function sendGazeTarget() {
  $("gazeXValue").value = Number($("gazeX").value).toFixed(2);
  $("gazeYValue").value = Number($("gazeY").value).toFixed(2);
  command({
    action: "channels",
    gaze_x: Number($("gazeX").value),
    gaze_y: Number($("gazeY").value),
  }).catch(console.error);
}
for (const id of ["gazeX", "gazeY"]) $(id).addEventListener("input", sendGazeTarget);
$("speechSample").addEventListener("click", () => command({action:"speech"}).catch(console.error));
$("rendererAvailable").addEventListener("change", () => command({
  action: "renderer",
  available: $("rendererAvailable").checked,
}).catch(console.error));

const source = new EventSource("/api/events");
source.addEventListener("snapshot", (event) => update(JSON.parse(event.data)));
source.onopen = () => { $("connection").textContent = "接続中"; $("connection").className = "badge"; };
source.onerror = () => { $("connection").textContent = "再接続中"; $("connection").className = "badge warn"; };
window.addEventListener("resize", draw);

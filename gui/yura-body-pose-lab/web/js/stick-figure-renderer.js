function clamp(value, min = -1, max = 1) { return Math.max(min, Math.min(max, Number(value) || 0)); }
function rotate(point, origin, angle) {
  const c = Math.cos(angle), s = Math.sin(angle), dx = point.x - origin.x, dy = point.y - origin.y;
  return { x: origin.x + dx * c - dy * s, y: origin.y + dx * s + dy * c };
}

export class StickFigureRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.frame = null;
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.resize();
  }

  setFrame(frame) { this.frame = frame; this.draw(); }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(rect.width * dpr));
    this.canvas.height = Math.max(1, Math.round(rect.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  draw() {
    const { ctx } = this;
    const rect = this.canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    if (!this.frame?.pose) return;
    const p = this.frame.pose;
    const scale = Math.min(rect.width, rect.height) / 5.1;
    const root = { x: rect.width * 0.5 + clamp(p.torso_yaw) * scale * .16, y: rect.height * .72 - clamp(p.body_height) * scale * .23 };
    const torsoRoll = clamp(p.torso_roll) * .23;
    const chest = rotate({ x: root.x, y: root.y - scale * .82 - clamp(p.torso_pitch) * scale * .09 }, root, torsoRoll);
    const neck = rotate({ x: chest.x, y: chest.y - scale * .14 }, chest, torsoRoll);
    const head = { x: neck.x + clamp(p.head_yaw) * scale * .16, y: neck.y - scale * .30 + clamp(p.head_pitch) * scale * .12 };
    const shoulderLeft = rotate({ x: chest.x - scale * .34, y: chest.y + scale * .04 }, chest, torsoRoll);
    const shoulderRight = rotate({ x: chest.x + scale * .34, y: chest.y + scale * .04 }, chest, torsoRoll);
    const hipLeft = rotate({ x: root.x - scale * .18, y: root.y }, root, torsoRoll * .35);
    const hipRight = rotate({ x: root.x + scale * .18, y: root.y }, root, torsoRoll * .35);

    ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "rgba(185,247,242,.94)"; ctx.fillStyle = "rgba(24,79,88,.92)"; ctx.lineWidth = Math.max(3, scale * .035); ctx.shadowColor = "rgba(111,232,222,.42)"; ctx.shadowBlur = 12;
    this.line(root, chest); this.line(chest, neck); this.line(shoulderLeft, shoulderRight); this.line(hipLeft, hipRight);
    this.arm(shoulderLeft, -1, clamp(p.left_arm_raise, 0, 1), clamp(p.left_arm_in));
    this.arm(shoulderRight, 1, clamp(p.right_arm_raise, 0, 1), clamp(p.right_arm_in));
    this.leg(hipLeft, -1, scale); this.leg(hipRight, 1, scale);

    ctx.save(); ctx.translate(head.x, head.y); ctx.rotate(clamp(p.head_roll) * .32); ctx.beginPath(); ctx.ellipse(0, 0, scale * .25, scale * .31, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
    const gazeX = clamp(p.gaze_x) * scale * .055, gazeY = clamp(p.gaze_y) * scale * .04;
    const leftOpen = clamp(p.eye_left_open, 0, 1), rightOpen = clamp(p.eye_right_open, 0, 1);
    this.eye(-scale * .09 + gazeX, -scale * .04 + gazeY, leftOpen, scale);
    this.eye(scale * .09 + gazeX, -scale * .04 + gazeY, rightOpen, scale);
    this.mouth(clamp(p.mouth_open, 0, 1), clamp(p.mouth_form), scale);
    ctx.restore();
  }

  arm(shoulder, side, raise, inward) {
    const scale = Math.min(this.canvas.getBoundingClientRect().width, this.canvas.getBoundingClientRect().height) / 5.1;
    const angle = side * (1.35 - raise * 2.05) - side * inward * .35;
    const elbow = { x: shoulder.x + Math.cos(angle) * scale * .48, y: shoulder.y + Math.sin(angle) * scale * .48 };
    const wristAngle = angle + side * (.18 - inward * .3);
    const wrist = { x: elbow.x + Math.cos(wristAngle) * scale * .42, y: elbow.y + Math.sin(wristAngle) * scale * .42 };
    this.line(shoulder, elbow); this.line(elbow, wrist); this.joint(wrist, scale * .04);
  }

  leg(hip, side, scale) {
    const knee = { x: hip.x + side * scale * .12, y: hip.y + scale * .55 };
    const ankle = { x: knee.x + side * scale * .05, y: knee.y + scale * .58 };
    this.line(hip, knee); this.line(knee, ankle); this.line(ankle, { x: ankle.x + side * scale * .16, y: ankle.y });
  }

  eye(x, y, open, scale) {
    const { ctx } = this; ctx.strokeStyle = "rgba(225,255,253,.96)"; ctx.fillStyle = "rgba(126,234,224,.95)"; ctx.lineWidth = Math.max(1.5, scale * .018);
    if (open < .18) { ctx.beginPath(); ctx.moveTo(x - scale * .045, y); ctx.lineTo(x + scale * .045, y); ctx.stroke(); return; }
    ctx.beginPath(); ctx.ellipse(x, y, scale * .04, scale * .025 * open, 0, 0, Math.PI * 2); ctx.fill();
  }

  mouth(open, form, scale) {
    const { ctx } = this; ctx.strokeStyle = "rgba(225,255,253,.95)"; ctx.lineWidth = Math.max(1.5, scale * .016); ctx.beginPath();
    const y = scale * .095, width = scale * .09, curve = form * scale * .045;
    if (open > .08) { ctx.ellipse(0, y, width * .55, scale * (.012 + open * .045), 0, 0, Math.PI * 2); }
    else { ctx.moveTo(-width, y); ctx.quadraticCurveTo(0, y + curve, width, y); }
    ctx.stroke();
  }

  line(a, b) { const { ctx } = this; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
  joint(point, radius) { const { ctx } = this; ctx.beginPath(); ctx.arc(point.x, point.y, radius, 0, Math.PI * 2); ctx.fill(); }
}

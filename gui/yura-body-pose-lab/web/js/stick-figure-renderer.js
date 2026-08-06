import { clamp, computeStickFigureGeometry } from "./stick-figure-geometry.js";
import { StickFigurePoseFilter } from "./stick-figure-pose-filter.js";

export class StickFigureRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.frame = null;
    this.poseFilter = new StickFigurePoseFilter();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.resize();
  }

  setFrame(frame) {
    if (!frame?.pose) {
      this.frame = frame;
      this.poseFilter.reset();
      this.draw();
      return;
    }
    this.frame = {
      ...frame,
      pose: this.poseFilter.apply(frame.pose),
    };
    this.draw();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (this.canvas.width !== width) this.canvas.width = width;
    if (this.canvas.height !== height) this.canvas.height = height;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  draw() {
    const { ctx } = this;
    const rect = this.canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    if (!this.frame?.pose) return;

    const pose = this.frame.pose;
    const geometry = computeStickFigureGeometry(pose, rect.width, rect.height);
    const { scale } = geometry;

    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "rgba(185,247,242,.94)";
    ctx.fillStyle = "rgba(24,79,88,.92)";
    ctx.lineWidth = Math.max(3, scale * 0.035);
    ctx.shadowColor = "rgba(111,232,222,.42)";
    ctx.shadowBlur = 12;

    this.drawLeg(geometry.leftLeg, scale);
    this.drawLeg(geometry.rightLeg, scale);
    this.drawTorso(geometry, scale);
    this.drawArm(geometry.leftArm, scale);
    this.drawArm(geometry.rightArm, scale);
    this.drawHead(geometry, pose);

    ctx.restore();
  }

  drawTorso(geometry, scale) {
    this.line(geometry.pelvis, geometry.chest);
    this.line(geometry.shoulderLeft, geometry.shoulderRight);
    this.line(geometry.hipLeft, geometry.hipRight);
    this.line(geometry.chest, geometry.neck);
    this.line(geometry.neck, geometry.headBottom);

    this.joint(geometry.chest, scale * 0.042);
    this.joint(geometry.pelvis, scale * 0.048);
    this.joint(geometry.shoulderLeft, scale * 0.038);
    this.joint(geometry.shoulderRight, scale * 0.038);
    this.joint(geometry.hipLeft, scale * 0.038);
    this.joint(geometry.hipRight, scale * 0.038);
  }

  drawArm(arm, scale) {
    this.line(arm.shoulder, arm.elbow);
    this.line(arm.elbow, arm.wrist);
    this.joint(arm.elbow, scale * 0.034);
    this.endPoint(arm.wrist, scale * 0.042);
  }

  drawLeg(leg, scale) {
    this.line(leg.hip, leg.knee);
    this.line(leg.knee, leg.ankle);
    this.line(leg.ankle, leg.toe);
    this.joint(leg.knee, scale * 0.036);
    this.joint(leg.ankle, scale * 0.030);
  }

  drawHead(geometry, pose) {
    const { ctx } = this;
    const { scale } = geometry;
    ctx.save();
    ctx.translate(geometry.head.x, geometry.head.y);
    ctx.rotate(geometry.headAngle);
    ctx.beginPath();
    ctx.ellipse(
      0,
      0,
      scale * 0.25 * (1 - Math.abs(clamp(pose.head_yaw)) * 0.12),
      scale * 0.31,
      0,
      0,
      Math.PI * 2,
    );
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;

    const gazeX = clamp(pose.gaze_x) * scale * 0.055;
    const gazeY = clamp(pose.gaze_y) * scale * 0.04;
    const leftOpen = clamp(pose.eye_left_open, 0, 1);
    const rightOpen = clamp(pose.eye_right_open, 0, 1);
    this.eye(-scale * 0.09 + gazeX, -scale * 0.04 + gazeY, leftOpen, scale);
    this.eye(scale * 0.09 + gazeX, -scale * 0.04 + gazeY, rightOpen, scale);
    this.mouth(clamp(pose.mouth_open, 0, 1), clamp(pose.mouth_form), scale);
    ctx.restore();
  }

  eye(x, y, open, scale) {
    const { ctx } = this;
    ctx.strokeStyle = "rgba(225,255,253,.96)";
    ctx.fillStyle = "rgba(126,234,224,.95)";
    ctx.lineWidth = Math.max(1.5, scale * 0.018);
    if (open < 0.18) {
      ctx.beginPath();
      ctx.moveTo(x - scale * 0.045, y);
      ctx.lineTo(x + scale * 0.045, y);
      ctx.stroke();
      return;
    }
    ctx.beginPath();
    ctx.ellipse(x, y, scale * 0.04, scale * 0.025 * open, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  mouth(open, form, scale) {
    const { ctx } = this;
    ctx.strokeStyle = "rgba(225,255,253,.95)";
    ctx.lineWidth = Math.max(1.5, scale * 0.016);
    ctx.beginPath();
    const y = scale * 0.095;
    const width = scale * 0.09;
    const curve = form * scale * 0.045;
    if (open > 0.08) {
      ctx.ellipse(0, y, width * 0.55, scale * (0.012 + open * 0.045), 0, 0, Math.PI * 2);
    } else {
      ctx.moveTo(-width, y);
      ctx.quadraticCurveTo(0, y + curve, width, y);
    }
    ctx.stroke();
  }

  line(a, b) {
    const { ctx } = this;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  joint(point, radius) {
    const { ctx } = this;
    ctx.save();
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  endPoint(point, radius) {
    const { ctx } = this;
    ctx.save();
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(185,247,242,.94)";
    ctx.fill();
    ctx.restore();
  }
}

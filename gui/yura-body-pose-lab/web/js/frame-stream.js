export class BodyPoseFrameStream {
  constructor({ onFrame, onStatus }) {
    this.onFrame = onFrame;
    this.onStatus = onStatus;
    this.source = null;
  }

  connect() {
    this.close();
    this.onStatus?.("connecting");
    this.source = new EventSource("/api/frames");
    this.source.addEventListener("open", () => this.onStatus?.("online"));
    this.source.addEventListener("body-pose-frame", (event) => {
      try { this.onFrame?.(JSON.parse(event.data)); }
      catch (error) { console.error("invalid body pose frame", error); }
    });
    this.source.addEventListener("error", () => this.onStatus?.("offline"));
  }

  close() {
    if (this.source) this.source.close();
    this.source = null;
  }
}

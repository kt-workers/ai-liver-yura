const clamp = (value) => Math.max(-1, Math.min(1, value));

export class CandidateControls {
  constructor(layer, state, onCommit) {
    this.layer = layer;
    this.state = state;
    this.onCommit = onCommit;
    this.render();
  }

  render() {
    this.layer.replaceChildren();
    for (const candidate of this.state.candidates) {
      const marker = document.createElement("button");
      marker.className = "candidate";
      marker.type = "button";
      marker.dataset.label = candidate.candidate_id;
      marker.style.left = `${(candidate.x + 1) * 50}%`;
      marker.style.top = `${(candidate.y + 1) * 50}%`;
      marker.addEventListener("pointerdown", (event) => this.#startDrag(event, candidate, marker));
      this.layer.append(marker);
    }
  }

  #startDrag(event, candidate, marker) {
    event.preventDefault(); marker.setPointerCapture(event.pointerId);
    const move = (moveEvent) => {
      const rect = this.layer.getBoundingClientRect();
      candidate.x = clamp(((moveEvent.clientX - rect.left) / rect.width) * 2 - 1);
      candidate.y = clamp(((moveEvent.clientY - rect.top) / rect.height) * 2 - 1);
      marker.style.left = `${(candidate.x + 1) * 50}%`;
      marker.style.top = `${(candidate.y + 1) * 50}%`;
    };
    const finish = async () => {
      marker.removeEventListener("pointermove", move);
      marker.removeEventListener("pointerup", finish);
      marker.removeEventListener("pointercancel", finish);
      await this.onCommit?.();
    };
    marker.addEventListener("pointermove", move);
    marker.addEventListener("pointerup", finish);
    marker.addEventListener("pointercancel", finish);
  }
}

export class PayloadView {
  constructor(element) { this.element = element; }
  render(frame) { this.element.textContent = JSON.stringify(frame, null, 2); }
}

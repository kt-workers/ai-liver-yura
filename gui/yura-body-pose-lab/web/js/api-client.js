export class BodyPoseLabApiClient {
  async getSnapshot() { return this.#request("GET", "/api/snapshot"); }
  async updateEmotion(payload) { return this.#request("POST", "/api/emotion", payload); }
  async updateActivityContext(payload) { return this.#request("POST", "/api/activity-context", payload); }
  async updateCandidates(payload) { return this.#request("POST", "/api/attention-candidates", payload); }
  async applyConstraint(payload) { return this.#request("POST", "/api/external-constraint", payload); }
  async clearConstraint() { return this.#request("DELETE", "/api/external-constraint"); }
  async requestBlink() { return this.#request("POST", "/api/blink", {}); }
  async presentSpeech(payload) { return this.#request("POST", "/api/speech", payload); }

  async #request(method, path, payload) {
    const init = { method, headers: { Accept: "application/json" } };
    if (payload !== undefined && method !== "GET") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(payload);
    }
    const response = await fetch(path, init);
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || `${method} ${path} failed`);
    return data;
  }
}

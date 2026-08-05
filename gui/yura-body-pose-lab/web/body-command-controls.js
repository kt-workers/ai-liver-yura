(() => {
  const status = document.getElementById("bodyCommandStatus");
  const buttons = document.querySelectorAll("[data-body-command]");

  async function sendBodyCommand(button) {
    const command = button.dataset.bodyCommand;
    if (!command) return;
    const durationValue = Number(button.dataset.durationMs || "0");
    const payload = { command };
    if (Number.isInteger(durationValue) && durationValue > 0) {
      payload.duration_ms = durationValue;
    }

    for (const candidate of buttons) candidate.disabled = true;
    status.dataset.state = "sending";
    status.textContent = `${button.textContent.trim()}を送信中…`;
    try {
      const response = await postJson("/api/body-command", payload);
      status.dataset.state = "active";
      status.textContent = `${button.textContent.trim()}を実行中`;
      window.setTimeout(() => {
        if (status.dataset.state === "active") {
          status.dataset.state = "idle";
          status.textContent = "身体操作を選択してください";
        }
      }, durationValue > 0 ? durationValue + 500 : 3500);
      return response;
    } catch (error) {
      status.dataset.state = "error";
      status.textContent = `送信失敗: ${error.message}`;
      throw error;
    } finally {
      for (const candidate of buttons) candidate.disabled = false;
    }
  }

  for (const button of buttons) {
    button.addEventListener("click", () => {
      void sendBodyCommand(button);
    });
  }
})();

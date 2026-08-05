(() => {
  const editor = document.getElementById("motionRequest");
  const submitButton = document.getElementById("submitMotion");
  const clearButton = document.getElementById("clearMotion");
  const releaseButton = document.getElementById("releaseMotion");
  const status = document.getElementById("motionStatus");
  if (!editor || !submitButton || !clearButton || !releaseButton || !status) return;

  const examples = {
    reach: {
      operation: "reach",
      target: "right_hand",
      vector: { x: 0.48, y: 1.38, z: 0 },
      timing: {
        duration_seconds: 2.4,
        repetitions: 1,
        easing: "ease_in_out",
        hold_final: false,
      },
      metadata: { purpose: "任意の手先座標へ到達" },
    },
    circle: {
      operation: "circle",
      target: "right_hand",
      pivot: "right_shoulder",
      radius: 0.68,
      direction: 1,
      timing: {
        duration_seconds: 4,
        repetitions: 4,
        easing: "smoothstep",
        hold_final: false,
      },
      metadata: { purpose: "肩を中心に手先を円運動" },
    },
    parallel: {
      operation: "parallel",
      children: [
        {
          operation: "reach",
          target: "left_hand",
          vector: { x: -0.42, y: 1.34, z: 0 },
          timing: { duration_seconds: 2.5, hold_final: false },
        },
        {
          operation: "reach",
          target: "right_hand",
          vector: { x: 0.58, y: 1.08, z: 0 },
          timing: { duration_seconds: 2.5, hold_final: false },
        },
      ],
      metadata: { purpose: "左右の手を別座標へ同時に動かす" },
    },
    sequence: {
      operation: "sequence",
      children: [
        {
          operation: "reach",
          target: "left_ankle",
          vector: { x: -0.30, y: -0.45, z: 0 },
          timing: { duration_seconds: 1.6, hold_final: false },
        },
        {
          operation: "reach",
          target: "right_ankle",
          vector: { x: 0.30, y: -0.45, z: 0 },
          timing: { duration_seconds: 1.6, hold_final: false },
        },
      ],
      metadata: { purpose: "左右の脚を順番に動かす" },
    },
    oscillate: {
      operation: "oscillate",
      target: "root",
      vector: { x: 0.28, y: 0.12, z: 0 },
      timing: {
        duration_seconds: 4,
        repetitions: 3,
        easing: "smoothstep",
        hold_final: false,
      },
      metadata: { purpose: "全身を上下左右へ往復移動" },
    },
  };

  function writeExample(name) {
    const example = examples[name];
    if (!example) return;
    editor.value = JSON.stringify(example, null, 2);
  }

  for (const button of document.querySelectorAll("[data-motion-example]")) {
    button.addEventListener("click", () => writeExample(button.dataset.motionExample));
  }

  submitButton.addEventListener("click", async () => {
    try {
      const payload = JSON.parse(editor.value);
      const response = await postJson("/api/motion", payload);
      const plan = response.plan || {};
      status.textContent = `受付: ${plan.plan_id || "motion"} / ${Number(plan.duration_seconds || 0).toFixed(2)}秒`;
    } catch (error) {
      status.textContent = `Motion送信失敗: ${error.message}`;
      setConnection("error", status.textContent);
    }
  });

  clearButton.addEventListener("click", async () => {
    try {
      await postJson("/api/motion/clear", { release_holds: false });
      status.textContent = "実行中Motionを停止しました。保持姿勢は維持します。";
    } catch (error) {
      status.textContent = `停止失敗: ${error.message}`;
    }
  });

  releaseButton.addEventListener("click", async () => {
    try {
      await postJson("/api/motion/clear", { release_holds: true });
      status.textContent = "実行中Motionと保持姿勢を解除しました。";
    } catch (error) {
      status.textContent = `解除失敗: ${error.message}`;
    }
  });

  async function refreshStatus() {
    try {
      const response = await fetch("/api/motions", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      const active = payload.active_motion_ids || [];
      const held = payload.held_targets || [];
      if (active.length || held.length) {
        status.textContent = `実行中 ${active.length}件 / 保持 ${held.length}箇所`;
      }
    } catch (_error) {
      // SSE側が接続状態を表示するため、補助Statusの失敗は無視する。
    }
  }

  writeExample("reach");
  window.setInterval(refreshStatus, 1000);
})();

"""外部資源と管理操作を持たない、読取専用の静的画面。"""

HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ゆら GUI/Admin</title><link rel="stylesheet" href="/assets/app.css">
<script src="/assets/app.js" defer></script></head>
<body><main><h1>ゆら GUI/Admin</h1><h2>最小Brainの設定</h2>
<p>注入された設定の公開項目を表示します。Core全体の正常性を示すものではありません。</p>
<button id="refresh" type="button">再取得</button>
<p id="status" role="status" aria-live="polite">未取得</p>
<dl><dt>構造識別子</dt><dd id="schema">—</dd><dt>設定ID</dt><dd id="config">—</dd>
<dt>設定リビジョン</dt><dd id="revision">—</dd>
<dt>登録済みBrainモジュール</dt><dd><ul id="modules"></ul></dd>
<dt>投影の生成時刻</dt><dd id="generated">—</dd></dl>
</main></body></html>""".encode()

JAVASCRIPT = """"use strict";
const refreshButton = document.getElementById("refresh");
const statusNode = document.getElementById("status");
async function refresh() {
  refreshButton.disabled = true;
  statusNode.textContent = "取得中";
  try {
    const response = await fetch("/api/v1/configuration/minimum-brain", {
      cache: "no-store", credentials: "omit", redirect: "error"
    });
    if (!response.ok) throw new Error("取得失敗");
    const result = await response.json();
    const values = result.payload.effective_values;
    if (result.model_kind !== "configuration_summary" || result.schema_version !== 1 ||
        result.availability !== "available" ||
        typeof values.schema_id !== "string" || typeof values.config_id !== "string" ||
        !Number.isSafeInteger(values.config_revision) || values.config_revision < 1 ||
        !Array.isArray(values.brain_module_registrations) ||
        !values.brain_module_registrations.every(value => typeof value === "string") ||
        typeof result.generated_at !== "string") throw new Error("形式不一致");
    document.getElementById("schema").textContent = values.schema_id;
    document.getElementById("config").textContent = values.config_id;
    document.getElementById("revision").textContent = String(values.config_revision);
    document.getElementById("generated").textContent = result.generated_at;
    const modules = document.getElementById("modules");
    modules.replaceChildren();
    for (const value of values.brain_module_registrations) {
      const item = document.createElement("li");
      item.textContent = value;
      modules.appendChild(item);
    }
    statusNode.textContent = "設定の公開項目を取得しました";
  } catch {
    for (const id of ["schema", "config", "revision", "generated"]) {
      document.getElementById(id).textContent = "—";
    }
    document.getElementById("modules").replaceChildren();
    statusNode.textContent = "取得できません。接続または応答形式を確認してください";
  } finally {
    refreshButton.disabled = false;
  }
}
refreshButton.addEventListener("click", refresh);
refresh();
""".encode()

CSS = b"""body { font-family: system-ui, sans-serif; margin: 0; color: #172334;
background: #f4f6f8; line-height: 1.65; }
main { max-width: 54rem; margin: 2rem auto; padding: 1.5rem; background: white; }
h1 { font-size: 1.7rem; } h2 { font-size: 1.3rem; }
button { font: inherit; padding: .5rem 1.25rem; cursor: pointer; }
button:disabled { cursor: wait; } button:focus-visible { outline: 3px solid #2058b8; }
dt { font-weight: 600; margin-top: 1rem; } dd { margin: .25rem 0; overflow-wrap: anywhere; }
#status { min-height: 1.65em; } ul { padding-left: 1.5rem; }
"""

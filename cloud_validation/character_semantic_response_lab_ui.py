from __future__ import annotations


CHARACTER_SEMANTIC_RESPONSE_LAB_HTML = r"""
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yura Character / Validator Lab</title>
<style>
:root {
  color-scheme: dark;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
  --panel:#071722e8;
  --panel-2:#04111a;
  --line:#24485e;
  --muted:#93bdd4;
  --text:#e8f5ff;
}
* { box-sizing:border-box; }
html, body { height:100%; }
body {
  margin:0;
  overflow:hidden;
  background:radial-gradient(circle at 50% -20%, #164267 0, #071521 38%, #03090f 75%);
  color:var(--text);
}
main {
  width:min(1480px, 98vw);
  height:100vh;
  margin:0 auto;
  padding:10px 0 12px;
  display:flex;
  flex-direction:column;
  gap:8px;
}
header {
  flex:0 0 auto;
  display:flex;
  gap:14px;
  justify-content:space-between;
  align-items:center;
  min-height:42px;
}
h1 { margin:0; font-size:clamp(20px, 2.2vw, 30px); letter-spacing:.02em; line-height:1.05; }
.subtitle { color:#9dc6df; margin-top:3px; font-size:12px; }
.badge {
  border:1px solid #37637d;
  border-radius:999px;
  padding:5px 9px;
  color:#a9d8ef;
  background:#071b29cc;
  font-size:11px;
  white-space:nowrap;
}
.toolbar, .card {
  border:1px solid var(--line);
  background:var(--panel);
  backdrop-filter:blur(12px);
  border-radius:13px;
  box-shadow:0 14px 34px #0005;
}
.toolbar {
  flex:0 0 auto;
  display:grid;
  grid-template-columns:minmax(260px, 1fr) auto auto auto auto;
  gap:7px;
  padding:8px;
  align-items:center;
}
select, button, input, textarea { font:inherit; }
select, input, textarea {
  width:100%;
  border:1px solid #31546a;
  color:#eaf7ff;
  background:var(--panel-2);
  border-radius:8px;
  padding:7px 9px;
}
button {
  border:1px solid #447089;
  color:#effaff;
  background:#0e3349;
  border-radius:8px;
  padding:7px 12px;
  cursor:pointer;
  font-weight:650;
  white-space:nowrap;
}
button:hover { background:#16445e; }
button.primary { background:#135274; border-color:#5ca4c8; }
button:disabled { opacity:.55; cursor:wait; }
.run-state {
  min-width:116px;
  border:1px solid #355e75;
  border-radius:999px;
  padding:6px 10px;
  text-align:center;
  font-size:12px;
  font-weight:700;
  background:#07131d;
  color:#9fc8de;
}
.run-state[data-state="loaded"] { border-color:#586f8a; color:#c6d9e7; }
.run-state[data-state="running"] { border-color:#c58b3d; color:#ffd699; background:#2b1d0c; }
.run-state[data-state="success"] { border-color:#4d9e79; color:#b6f0d1; background:#0a2419; }
.run-state[data-state="failure"] { border-color:#b85d68; color:#ffc0c8; background:#2a1015; }
.workspace {
  flex:1 1 auto;
  min-height:0;
  display:grid;
  grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);
  gap:8px;
}
.card {
  min-height:0;
  padding:11px;
  overflow:auto;
  scrollbar-gutter:stable;
}
.result-card { display:flex; flex-direction:column; }
.card h2 { margin:0 0 7px; font-size:15px; }
label { display:block; color:var(--muted); margin:7px 0 4px; font-size:11px; }
textarea {
  min-height:74px;
  max-height:180px;
  resize:vertical;
  font-family:ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size:11px;
  line-height:1.35;
}
textarea.tall { min-height:118px; }
.result {
  flex:1 1 auto;
  min-height:0;
  white-space:pre-wrap;
  overflow:auto;
  overflow-wrap:anywhere;
  background:#030b11;
  border:1px solid #26495c;
  border-radius:9px;
  padding:10px;
  font-family:ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size:11px;
  line-height:1.4;
}
.summary { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-bottom:7px; }
.kpi { border:1px solid #25485b; border-radius:9px; padding:7px; background:#06131d; }
.kpi small { color:#7fa9bf; display:block; font-size:10px; }
.kpi strong { display:block; margin-top:2px; font-size:13px; }
.result-actions { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
details { border-top:1px solid #1b3d50; margin-top:8px; padding-top:6px; }
summary { cursor:pointer; color:#bde3f6; font-size:12px; }
.status { margin:6px 0 0; color:#8fc7e3; min-height:1.2em; font-size:11px; }
.state-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin:7px 0 5px; }
.state-head strong { font-size:12px; color:#cbe9f8; }
.switch-label { display:flex; align-items:center; gap:6px; margin:0; color:#9fc4d9; cursor:pointer; user-select:none; }
.switch-label input { width:auto; margin:0; }
.prompt-toggle {
  min-height:34px;
  padding:0 9px;
  border:1px solid #31546a;
  border-radius:8px;
  background:#06131d;
  color:#bde3f6;
  white-space:nowrap;
}
.state-charts { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
.metric-panel { border:1px solid #203f51; border-radius:9px; background:#05121b; padding:7px; min-width:0; }
.metric-title { display:flex; justify-content:space-between; color:#bde3f6; font-size:11px; margin-bottom:5px; }
.metric-list { display:grid; gap:4px; }
.metric-row { display:grid; grid-template-columns:minmax(64px,.8fr) minmax(84px,1.5fr) 42px; gap:6px; align-items:center; font-size:10px; }
.metric-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#9fc4d9; }
.metric-track { height:7px; border-radius:999px; background:#0c2635; overflow:hidden; border:1px solid #214459; }
.metric-bar { height:100%; width:0; border-radius:999px; background:linear-gradient(90deg,#2c7ca4,#7ac8e8); }
.metric-value { text-align:right; font-variant-numeric:tabular-nums; color:#d8effa; }
.state-json { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
.hidden { display:none !important; }
.empty-chart { color:#698da0; font-size:10px; padding:7px 0; }
@media(max-width:900px){
  body { overflow:auto; }
  main { height:auto; min-height:100vh; padding:10px 0 22px; }
  .workspace { grid-template-columns:1fr; }
  .toolbar { grid-template-columns:1fr 1fr; }
  .toolbar select, .run-state, .prompt-toggle { grid-column:1/-1; }
  .card { overflow:visible; }
  .result { min-height:260px; }
  .state-charts, .state-json { grid-template-columns:1fr; }
  .summary { grid-template-columns:1fr 1fr 1fr; }
}
</style>
</head>
<body><main>
<header>
  <div>
    <h1>Character / Validator Lab</h1>
    <div class="subtitle">Semantic Plan → Character生成 → Validator → regeneration を全体Runtimeなしで確認</div>
  </div>
  <div class="badge">stop: character_response_pipeline</div>
</header>
<div class="toolbar">
  <select id="preset" aria-label="プリセット"></select>
  <button id="load">プリセット読込</button>
  <label class="switch-label prompt-toggle"><input id="includePrompts" type="checkbox"> Promptも結果に含める</label>
  <button id="run" class="primary">実行</button>
  <div id="runState" class="run-state" data-state="idle" aria-live="polite">待機</div>
</div>
<div class="workspace">
<section class="card">
  <h2>Input Snapshot</h2>
  <label>ユーザー入力</label><input id="userInput">
  <label>StructuredInputMeaning</label><textarea id="meaning"></textarea>
  <label>Internal Directive</label><textarea id="directive"></textarea>

  <details open>
    <summary>Emotion / Drive</summary>
    <div class="state-head">
      <strong>State values</strong>
      <label class="switch-label"><input id="stateJsonToggle" type="checkbox"> JSON表示</label>
    </div>
    <div id="stateCharts" class="state-charts">
      <div class="metric-panel"><div class="metric-title"><span>Emotion</span><span>0–1</span></div><div id="emotionChart" class="metric-list"></div></div>
      <div class="metric-panel"><div class="metric-title"><span>Drive</span><span>0–1</span></div><div id="driveChart" class="metric-list"></div></div>
    </div>
    <div id="stateJson" class="state-json hidden">
      <div><label>Emotion JSON</label><textarea id="emotion"></textarea></div>
      <div><label>Drive JSON</label><textarea id="drive"></textarea></div>
    </div>
  </details>

  <details><summary>Recent / Memory</summary>
    <label>Recent speech summary</label><textarea id="recentSpeech"></textarea>
    <label>Recent conversation (JSON array)</label><textarea id="conversation"></textarea>
    <label>Recent topic summary</label><textarea id="recentTopic"></textarea>
    <label>Memory</label><textarea id="memory"></textarea>
    <label>Related knowledge</label><textarea id="knowledge"></textarea>
  </details>
  <details><summary>Constraints / Character</summary>
    <label>Response constraints</label><textarea id="constraints"></textarea>
    <label>Character Profile</label><textarea id="profile" class="tall"></textarea>
  </details>
  <div class="status" id="status">待機中</div>
</section>

<section class="card result-card">
  <h2>Pipeline Result</h2>
  <div class="summary">
    <div class="kpi"><small>Status</small><strong id="resultStatus">-</strong></div>
    <div class="kpi"><small>Attempts</small><strong id="attempts">-</strong></div>
    <div class="kpi"><small>Elapsed</small><strong id="elapsed">-</strong></div>
  </div>
  <div class="result-actions"><button id="copy">結果JSONをコピー</button></div>
  <div class="result" id="result">未実行</div>
</section>
</div>
</main>
<script>
const ALL_PRESETS_KEY = '__all_presets__';
let presets = {};
let lastResult = null;
const $ = id => document.getElementById(id);
const pretty = value => JSON.stringify(value, null, 2);
const parse = (id, fallback) => {
  const text = $(id).value.trim();
  return text ? JSON.parse(text) : fallback;
};

function setRunState(state, text) {
  $('runState').dataset.state = state;
  $('runState').textContent = text;
}

function clearResult(state='idle', stateText='待機', resultText='未実行') {
  lastResult = null;
  $('result').textContent = resultText;
  $('resultStatus').textContent = '-';
  $('attempts').textContent = '-';
  $('elapsed').textContent = '-';
  setRunState(state, stateText);
}

function flattenNumeric(value, prefix='') {
  const rows = [];
  if (!value || typeof value !== 'object') return rows;
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof item === 'number' && Number.isFinite(item)) rows.push([path, item]);
    else if (item && typeof item === 'object' && !Array.isArray(item)) rows.push(...flattenNumeric(item, path));
  }
  return rows;
}

function metricLabel(path) {
  return path.replace(/^current\.reactive\./, '').replace(/^current\./, '');
}

function renderMetricChart(containerId, value) {
  const container = $(containerId);
  const rows = flattenNumeric(value);
  if (!rows.length) {
    container.innerHTML = '<div class="empty-chart">数値データなし</div>';
    return;
  }
  container.innerHTML = rows.map(([path, raw]) => {
    const normalized = Math.max(0, Math.min(1, raw));
    const width = (normalized * 100).toFixed(1);
    const shown = Number(raw).toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    const label = metricLabel(path);
    return `<div class="metric-row" title="${path}"><span class="metric-name">${label}</span><span class="metric-track"><span class="metric-bar" style="display:block;width:${width}%"></span></span><span class="metric-value">${shown}</span></div>`;
  }).join('');
}

function renderStateCharts() {
  renderMetricChart('emotionChart', parse('emotion', {}));
  renderMetricChart('driveChart', parse('drive', {}));
}

function setStateJsonMode(enabled) {
  $('stateCharts').classList.toggle('hidden', enabled);
  $('stateJson').classList.toggle('hidden', !enabled);
}

function apply(data) {
  $('userInput').value = data.user_input || '';
  $('meaning').value = pretty(data.structured_input_meaning || {});
  $('directive').value = pretty(data.internal_directive || {});
  $('emotion').value = pretty(data.emotion || {});
  $('drive').value = pretty(data.drive || {});
  $('recentSpeech').value = data.recent_speech_summary || '';
  $('conversation').value = pretty(data.recent_conversation || []);
  $('recentTopic').value = data.recent_topic_summary || '';
  $('memory').value = pretty(data.memory || {});
  $('knowledge').value = pretty(data.related_knowledge || []);
  $('constraints').value = pretty(data.response_constraints || {});
  $('profile').value = pretty(data.character_profile || {});
  $('includePrompts').checked = !!data.include_prompts;
  renderStateCharts();
}

function requestData() {
  return {
    user_input: $('userInput').value,
    structured_input_meaning: parse('meaning', {}),
    internal_directive: parse('directive', {}),
    emotion: parse('emotion', {}),
    drive: parse('drive', {}),
    memory: parse('memory', {}),
    related_knowledge: parse('knowledge', []),
    recent_speech_summary: $('recentSpeech').value,
    recent_conversation: parse('conversation', []),
    recent_topic_summary: $('recentTopic').value,
    response_constraints: parse('constraints', {}),
    character_profile: parse('profile', {}),
    include_prompts: $('includePrompts').checked
  };
}

function batchRequestData(data) {
  return {...data, include_prompts: $('includePrompts').checked};
}

async function postCharacterResponse(data) {
  const response = await fetch('/api/character-response', {
    method: 'POST',
    headers: {'content-type':'application/json'},
    body: JSON.stringify(data)
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
  return payload;
}

function syncPresetControls() {
  const allSelected = $('preset').value === ALL_PRESETS_KEY;
  $('load').disabled = allSelected || $('run').disabled;
  if (allSelected) {
    $('status').textContent = '全プリセットを順番に実行します。入力フォームは変更しません。';
  }
}

async function loadPresets() {
  const r = await fetch('/api/presets');
  presets = await r.json();
  const presetOptions = Object.entries(presets).map(([key, value]) => `<option value="${key}">${value.label}</option>`).join('');
  $('preset').innerHTML = `<option value="${ALL_PRESETS_KEY}">すべて実行（全プリセット）</option>${presetOptions}`;
  const first = Object.keys(presets)[0];
  if (first) {
    $('preset').value = first;
    apply(presets[first].data);
    clearResult('loaded', 'プリセット読込済み');
  }
  syncPresetControls();
}

async function runAllPresets() {
  const entries = Object.entries(presets);
  const startedAt = performance.now();
  const results = [];
  let totalAttempts = 0;

  for (const [index, [key, preset]] of entries.entries()) {
    const position = index + 1;
    setRunState('running', `${position}/${entries.length}`);
    $('status').textContent = `全件実行 ${position}/${entries.length}: 「${preset.label}」`;
    try {
      const payload = await postCharacterResponse(batchRequestData(preset.data));
      totalAttempts += Number(payload.generation_result?.attempts || 0);
      results.push({
        preset_key: key,
        label: preset.label,
        request_ok: true,
        result: payload
      });
    } catch (error) {
      results.push({
        preset_key: key,
        label: preset.label,
        request_ok: false,
        error: String(error.message || error)
      });
    }
  }

  const elapsedMs = Math.round(performance.now() - startedAt);
  const succeeded = results.filter(item => item.request_ok).length;
  const failed = results.length - succeeded;
  const batchResult = {
    execution_mode: 'all_presets',
    include_prompts: $('includePrompts').checked,
    summary: {
      total: results.length,
      succeeded,
      failed,
      elapsed_ms: elapsedMs
    },
    results
  };

  lastResult = batchResult;
  $('result').textContent = pretty(batchResult);
  $('resultStatus').textContent = failed ? `batch ${succeeded}/${results.length}` : 'batch completed';
  $('attempts').textContent = totalAttempts;
  $('elapsed').textContent = `${elapsedMs} ms`;
  setRunState(failed ? 'failure' : 'success', failed ? `${succeeded}/${results.length} 完了` : '全件完了');
  $('status').textContent = failed
    ? `全件実行完了: ${succeeded}/${results.length}件のAPI実行成功。失敗詳細は結果JSONを確認してください。`
    : `全件実行完了: ${results.length}件すべてのAPI実行が完了しました。`;
}

$('stateJsonToggle').onchange = () => {
  if ($('stateJsonToggle').checked) {
    setStateJsonMode(true);
    return;
  }
  try {
    renderStateCharts();
    setStateJsonMode(false);
    $('status').textContent = 'グラフ表示へ切り替えました';
  } catch (error) {
    $('stateJsonToggle').checked = true;
    setStateJsonMode(true);
    setRunState('failure', 'JSONエラー');
    $('status').textContent = `JSON解析失敗: ${error.message}`;
  }
};

$('preset').onchange = () => syncPresetControls();

$('load').onclick = () => {
  if ($('preset').value === ALL_PRESETS_KEY) return;
  clearResult('loaded', 'プリセット読込済み');
  const preset = presets[$('preset').value];
  if (preset) {
    apply(preset.data);
    $('status').textContent = `プリセット「${preset.label}」を読み込みました`;
  }
};

$('run').onclick = async () => {
  clearResult('running', '実行中', '実行中…');
  const allSelected = $('preset').value === ALL_PRESETS_KEY;
  $('status').textContent = allSelected
    ? '全プリセットを順番に実行しています…'
    : 'Character / Validator pipelineを実行しています…';
  $('run').disabled = true;
  $('load').disabled = true;
  $('preset').disabled = true;
  try {
    if (allSelected) {
      await runAllPresets();
      return;
    }
    const payload = await postCharacterResponse(requestData());
    lastResult = payload;
    $('result').textContent = pretty(payload);
    $('resultStatus').textContent = payload.generation_result?.status || '-';
    $('attempts').textContent = payload.generation_result?.attempts ?? '-';
    $('elapsed').textContent = `${payload.elapsed_ms} ms`;
    setRunState('success', '完了');
    $('status').textContent = '実行完了';
  } catch (error) {
    setRunState('failure', '失敗');
    $('status').textContent = `失敗: ${error.message}`;
    $('result').textContent = String(error.stack || error);
  } finally {
    $('run').disabled = false;
    $('preset').disabled = false;
    syncPresetControls();
  }
};

$('copy').onclick = async () => {
  if (!lastResult) {
    $('status').textContent = 'コピーできる実行結果がありません';
    return;
  }
  await navigator.clipboard.writeText(pretty(lastResult));
  $('status').textContent = '結果JSONをコピーしました';
};

setStateJsonMode(false);
loadPresets().catch(error => {
  setRunState('failure', '初期化失敗');
  $('status').textContent = `初期化失敗: ${error.message}`;
});
</script>
</body>
</html>
"""


__all__ = ["CHARACTER_SEMANTIC_RESPONSE_LAB_HTML"]
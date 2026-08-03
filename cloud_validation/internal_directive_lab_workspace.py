from __future__ import annotations

from cloud_validation import internal_directive_lab_compact as compact

LabSettings = compact.LabSettings
InternalDirectiveLabService = compact.InternalDirectiveLabService

_WORKSPACE_STYLE = """
<style id="internal-directive-workspace-style">
  .transfer-panel {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    border-color: var(--line-strong);
  }
  .transfer-copy h2 { margin-bottom: 4px; }
  .transfer-copy p { margin: 0; color: var(--muted); font-size: .85rem; }
  .transfer-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 9px;
  }
  .export-status {
    min-height: 1.4em;
    color: var(--ok);
    font-size: .8rem;
  }
  .editor-header-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 8px;
  }
  .collapse-section-button {
    white-space: nowrap;
  }
  .editor-collapsible-body {
    min-width: 0;
  }
  .editor[data-section="state"] > #stateOverview {
    margin-top: 0;
    margin-bottom: 14px;
  }
  @media (max-width: 720px) {
    .transfer-panel { align-items: stretch; flex-direction: column; }
    .transfer-actions { align-items: stretch; justify-content: flex-start; }
    .transfer-actions button { width: 100%; }
    .editor-header-actions { width: 100%; justify-content: space-between; }
    .editor-header-actions .mode-switch { flex: 1 1 auto; width: auto; }
  }
</style>
"""

_TRANSFER_PANEL = """
<section class="panel transfer-panel" id="transferPanel">
  <div class="transfer-copy">
    <h2>検証データのExport</h2>
    <p>現在の入力条件と、表示中のLLM結果をChatGPTへ渡しやすいテキストファイルにまとめます。</p>
  </div>
  <div class="transfer-actions">
    <button id="exportLabText" type="button">ChatGPT用テキストをExport</button>
    <span class="export-status" id="exportStatus" aria-live="polite"></span>
  </div>
</section>
"""

_RUN_PANEL_MARKER = (
    '<section class="panel"><label class="check-option">'
    '<input id="includePrompt" type="checkbox">生成したプロンプトも結果に含める'
    '</label><div style="height:12px"></div><button class="primary-run" '
    'id="run" type="button">司令塔LLMを実行</button></section>'
)

_WORKSPACE_SCRIPT = r"""
<script id="internal-directive-workspace-script">
const labCollapsibleSections = {
  meaning: 'StructuredInputMeaning',
  state: '内部状態',
  activities: '利用可能Activity',
  ongoing: '進行中Activity',
  profile: 'Character Profile / 存在境界',
};

function setupLabCollapsibleSections() {
  for (const [section, label] of Object.entries(labCollapsibleSections)) {
    const panel = document.querySelector(`.editor[data-section="${section}"]`);
    if (!panel || panel.dataset.collapsibleReady === 'true') continue;
    const header = panel.querySelector(':scope > .editor-header');
    if (!header) continue;

    const overview = section === 'state' ? panel.querySelector('#stateOverview') : null;
    if (overview) {
      overview.dataset.alwaysVisible = 'true';
      panel.insertBefore(overview, header.nextSibling);
    }

    const body = document.createElement('div');
    body.className = 'editor-collapsible-body';
    body.id = `editorCollapsibleBody-${section}`;
    const movableChildren = [...panel.children].filter(
      child => child !== header && child !== overview,
    );
    for (const child of movableChildren) body.appendChild(child);
    panel.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'editor-header-actions';
    const modeSwitch = header.querySelector('.mode-switch');
    if (modeSwitch) actions.appendChild(modeSwitch);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary small collapse-section-button';
    button.dataset.collapseSection = section;
    button.setAttribute('aria-expanded', 'true');
    button.setAttribute('aria-controls', body.id);
    button.setAttribute('aria-label', `${label}を折りたたむ`);
    button.textContent = '折りたたむ';
    button.addEventListener('click', () => {
      const expanded = button.getAttribute('aria-expanded') === 'true';
      const nextExpanded = !expanded;
      body.classList.toggle('hidden', !nextExpanded);
      button.setAttribute('aria-expanded', String(nextExpanded));
      button.setAttribute(
        'aria-label',
        `${label}を${nextExpanded ? '折りたたむ' : '展開する'}`,
      );
      button.textContent = nextExpanded ? '折りたたむ' : '展開する';
    });
    actions.appendChild(button);
    header.appendChild(actions);
    panel.dataset.collapsibleReady = 'true';
  }
}

function labJsonBlock(title, value) {
  return `## ${title}\n\n\`\`\`json\n${JSON.stringify(value, null, 2)}\n\`\`\``;
}

function currentLabPresetName() {
  const select = document.getElementById('presetSelect');
  if (!select || !select.value) return '未選択（手動設定）';
  return select.selectedOptions[0]?.textContent || select.value;
}

function visibleLabResultText() {
  const panel = document.getElementById('resultPanel');
  if (!panel || panel.classList.contains('hidden')) {
    return '## LLM実行結果\n\n未実行、またはプリセット適用後に結果がクリアされています。';
  }

  const resultLines = [
    '## LLM実行結果',
    '',
    `- valid: ${document.getElementById('valid')?.textContent || '-'}`,
    `- mode / model: ${document.getElementById('mode')?.textContent || '-'}`,
    `- elapsed: ${document.getElementById('elapsed')?.textContent || '-'}`,
    `- stop stage: ${document.getElementById('stop')?.textContent || '-'}`,
    '',
    '### Parsed InternalDirective',
    '',
    '```json',
    document.getElementById('parsed')?.textContent || '-',
    '```',
    '',
    '### Raw LLM Response',
    '',
    '<raw_llm_response>',
    document.getElementById('raw')?.textContent || '-',
    '</raw_llm_response>',
  ];

  const promptArea = document.getElementById('promptArea');
  if (promptArea && !promptArea.classList.contains('hidden')) {
    resultLines.push(
      '',
      '### Prompt',
      '',
      '<prompt>',
      document.getElementById('prompt')?.textContent || '-',
      '</prompt>',
    );
  }
  return resultLines.join('\n');
}

function buildLabExportText() {
  syncAllSections();
  const exportedAt = new Date();
  return [
    '# ゆら 内部指示器ラボ 検証データ',
    '',
    '## ChatGPTへの依頼',
    '',
    '以下の入力条件とInternalDirectiveについて、入力意図との整合性、内部状態の反映、不要なActivity指定、質問・話題展開の予算、存在境界の遵守を評価してください。',
    '',
    '## Export情報',
    '',
    `- Export日時: ${exportedAt.toLocaleString('ja-JP')}`,
    `- プリセット: ${currentLabPresetName()}`,
    '',
    labJsonBlock('StructuredInputMeaning', model.meaning),
    '',
    labJsonBlock('内部状態', model.state),
    '',
    labJsonBlock('利用可能Activity', model.activities),
    '',
    labJsonBlock('進行中Activity', model.ongoing),
    '',
    labJsonBlock('Character Profile / 存在境界', model.profile),
    '',
    visibleLabResultText(),
    '',
  ].join('\n');
}

function labExportFilename(date) {
  const pad = value => String(value).padStart(2, '0');
  return [
    'yura-internal-directive-lab-',
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    '-',
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
    '.txt',
  ].join('');
}

function downloadLabExport() {
  const status = document.getElementById('exportStatus');
  try {
    const text = buildLabExportText();
    const now = new Date();
    const blob = new Blob(['\ufeff', text], {
      type: 'text/plain;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = labExportFilename(now);
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    if (status) status.textContent = 'テキストファイルを作成しました。';
  } catch (error) {
    if (status) status.textContent = '';
    alert(error.message);
  }
}

document.getElementById('exportLabText')?.addEventListener('click', downloadLabExport);
setupLabCollapsibleSections();
</script>
"""


def add_workspace_controls(html: str) -> str:
    """実行ボタン直後へExportを置き、5入力領域へ折りたたみ操作を追加する。"""

    if 'id="internal-directive-workspace-script"' in html:
        return html
    with_style = html.replace("</head>", f"{_WORKSPACE_STYLE}</head>", 1)
    if _RUN_PANEL_MARKER not in with_style:
        raise RuntimeError("internal directive run panel was not found")
    with_transfer = with_style.replace(
        _RUN_PANEL_MARKER,
        f"{_RUN_PANEL_MARKER}\n{_TRANSFER_PANEL}",
        1,
    )
    return with_transfer.replace("</body>", f"{_WORKSPACE_SCRIPT}\n</body>", 1)


_WORKSPACE_INDEX_HTML = add_workspace_controls(compact._PRESET_INDEX_HTML)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: InternalDirectiveLabService | None = None,
):
    compact.base._INDEX_HTML = _WORKSPACE_INDEX_HTML
    return compact.base.create_app(settings=settings, service=service)


app = create_app()

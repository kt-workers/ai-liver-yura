const state = {
  manifest: null,
  activeCategory: null,
  revision: 0,
  originalValues: {},
  draftValues: {},
  fields: [],
  validationErrors: [],
};

const elements = {
  connection: document.querySelector('#connection'),
  headerTabs: document.querySelector('#headerTabs'),
  categoryList: document.querySelector('#categoryList'),
  manifestRoot: document.querySelector('#manifestRoot'),
  manifestSummary: document.querySelector('#manifestSummary'),
  validationState: document.querySelector('#validationState'),
  validationSummary: document.querySelector('#validationSummary'),
  reloadState: document.querySelector('#reloadState'),
  reloadSummary: document.querySelector('#reloadSummary'),
  categoryFile: document.querySelector('#categoryFile'),
  categoryTitle: document.querySelector('#categoryTitle'),
  categoryDescription: document.querySelector('#categoryDescription'),
  form: document.querySelector('#configForm'),
  resetButton: document.querySelector('#resetButton'),
  validateButton: document.querySelector('#validateButton'),
  saveButton: document.querySelector('#saveButton'),
  changeCount: document.querySelector('#changeCount'),
  changeSummary: document.querySelector('#changeSummary'),
  validationDetails: document.querySelector('#validationDetails'),
  applyMessage: document.querySelector('#applyMessage'),
  historyOpen: document.querySelector('#historyOpen'),
  historyDialog: document.querySelector('#historyDialog'),
  historyList: document.querySelector('#historyList'),
  previewButton: document.querySelector('#jsonPreviewButton'),
  previewDialog: document.querySelector('#previewDialog'),
  preview: document.querySelector('#jsonPreview'),
  toast: document.querySelector('#toast'),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    const error = new Error(payload.error?.message || `HTTP ${response.status}`);
    error.code = payload.error?.code;
    error.details = payload.error?.details || [];
    throw error;
  }
  return payload;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function changedKeys() {
  const keys = new Set([...Object.keys(state.originalValues), ...Object.keys(state.draftValues)]);
  return [...keys].filter((key) => JSON.stringify(state.originalValues[key]) !== JSON.stringify(state.draftValues[key]));
}

function isDirty() {
  return changedKeys().length > 0;
}

function showToast(message, error = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle('error', error);
  elements.toast.classList.add('visible');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => elements.toast.classList.remove('visible'), 3200);
}

function setConnection(online) {
  elements.connection.classList.toggle('online', online);
  elements.connection.classList.toggle('offline', !online);
  elements.connection.classList.remove('pending');
  elements.connection.querySelector('b').textContent = online ? 'CONFIG SERVER 接続中' : 'CONFIG SERVER 切断';
}

function renderNavigation() {
  const categories = state.manifest?.categories || [];
  const createButton = (category, compact = false) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.category = category.id;
    button.className = compact ? '' : 'category-item';
    if (state.activeCategory === category.id) button.classList.add('active');
    if (!compact && state.activeCategory === category.id && isDirty()) button.classList.add('dirty');
    if (compact) {
      button.textContent = category.label.replace('・VoiceVox', '');
    } else {
      const title = document.createElement('strong');
      title.textContent = category.label;
      const file = document.createElement('small');
      file.textContent = category.file;
      button.append(title, file);
    }
    button.addEventListener('click', () => selectCategory(category.id));
    return button;
  };
  elements.headerTabs.replaceChildren(...categories.map((item) => createButton(item, true)));
  elements.categoryList.replaceChildren(...categories.map((item) => createButton(item, false)));
}

function renderSummary() {
  const count = state.manifest?.categories?.length || 0;
  elements.manifestRoot.textContent = state.manifest?.root || '-';
  elements.manifestSummary.textContent = `${count}カテゴリ / revision ${state.revision}`;
  const valid = state.validationErrors.length === 0;
  elements.validationState.textContent = valid ? 'VALID' : 'ERROR';
  elements.validationState.className = valid ? 'validation-ok' : 'validation-error';
  elements.validationSummary.textContent = valid ? '型・必須項目に問題はありません。' : `${state.validationErrors.length}件の入力エラーがあります。`;
}

function inputFor(field) {
  let input;
  if (field.type === 'boolean') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = Boolean(state.draftValues[field.key]);
  } else if (field.type === 'select') {
    input = document.createElement('select');
    for (const optionValue of field.options || []) {
      const option = document.createElement('option');
      option.value = optionValue;
      option.textContent = optionValue;
      option.selected = state.draftValues[field.key] === optionValue;
      input.append(option);
    }
  } else {
    input = document.createElement('input');
    input.type = field.type === 'integer' ? 'number' : 'text';
    if (field.minimum !== undefined) input.min = String(field.minimum);
    input.value = state.draftValues[field.key] ?? '';
  }
  input.name = field.key;
  input.id = `field-${field.key}`;
  input.addEventListener('input', () => {
    let value;
    if (field.type === 'boolean') value = input.checked;
    else if (field.type === 'integer') value = input.value === '' ? '' : Number(input.value);
    else value = input.value;
    state.draftValues[field.key] = value;
    const fieldError = elements.form.querySelector(`[data-error-for="${field.key}"]`);
    if (fieldError) fieldError.textContent = '';
    state.validationErrors = state.validationErrors.filter((item) => item.field !== field.key);
    updateDirtyState();
    renderSummary();
  });
  return input;
}

function policyLabel(policy) {
  return {
    immediate: '即時反映',
    next_request: '次回処理',
    reconnect: '再接続',
    restart: '再起動',
  }[policy] || policy;
}

function renderForm() {
  elements.form.replaceChildren();
  for (const field of state.fields) {
    const wrapper = document.createElement('div');
    wrapper.className = 'field';
    const head = document.createElement('div');
    head.className = 'field-head';
    const label = document.createElement('label');
    label.htmlFor = `field-${field.key}`;
    label.textContent = field.label;
    const code = document.createElement('code');
    code.textContent = `${state.activeCategory}.${field.key}`;
    head.append(label, code);
    const control = document.createElement('div');
    control.className = 'field-control';
    control.append(inputFor(field));
    const badge = document.createElement('span');
    badge.className = 'policy-badge';
    badge.textContent = policyLabel(field.reload_policy);
    control.append(badge);
    const source = document.createElement('small');
    source.textContent = field.reference ? `参照先: ${field.reference}` : `保存先: ${field.source_file}`;
    const error = document.createElement('div');
    error.className = 'field-error';
    error.dataset.errorFor = field.key;
    const currentError = state.validationErrors.find((item) => item.field === field.key);
    error.textContent = currentError?.message || '';
    wrapper.append(head, control, source, error);
    elements.form.append(wrapper);
  }
}

function renderValidationDetails() {
  elements.validationDetails.replaceChildren();
  if (!state.validationErrors.length) {
    const ok = document.createElement('p');
    ok.className = 'validation-ok';
    ok.textContent = '✓ 現在の入力値は有効です。';
    elements.validationDetails.append(ok);
    return;
  }
  for (const error of state.validationErrors) {
    const item = document.createElement('p');
    item.className = 'validation-error';
    item.textContent = `${error.field}: ${error.message}`;
    elements.validationDetails.append(item);
  }
}

function updateDirtyState() {
  const changes = changedKeys();
  elements.changeCount.textContent = String(changes.length);
  elements.changeSummary.textContent = changes.length ? changes.join(' / ') : '変更はありません。';
  elements.saveButton.disabled = !changes.length || state.validationErrors.length > 0;
  elements.resetButton.disabled = !changes.length;
  elements.validateButton.disabled = !state.activeCategory;
  elements.previewButton.disabled = !state.activeCategory;
  renderNavigation();
}

async function selectCategory(category) {
  if (category === state.activeCategory) return;
  if (isDirty() && !window.confirm('未保存の変更があります。破棄して別のカテゴリへ移動しますか？')) return;
  try {
    const payload = await request(`/api/v1/config/categories/${category}`);
    state.activeCategory = category;
    state.revision = payload.revision;
    state.originalValues = clone(payload.values);
    state.draftValues = clone(payload.values);
    state.fields = payload.fields || [];
    state.validationErrors = payload.validation?.errors || [];
    elements.categoryFile.textContent = payload.category.file;
    elements.categoryTitle.textContent = payload.category.label;
    elements.categoryDescription.textContent = payload.category.description;
    const plan = await validateDraft(false);
    if (plan?.reload_plan) applyReloadPlan(plan.reload_plan);
    renderForm();
    renderValidationDetails();
    updateDirtyState();
    renderSummary();
  } catch (error) {
    showToast(error.message, true);
  }
}

function applyReloadPlan(plan) {
  elements.reloadState.textContent = policyLabel(plan.policy);
  elements.reloadSummary.textContent = plan.message;
  elements.applyMessage.textContent = plan.message;
}

async function validateDraft(showMessage = true) {
  if (!state.activeCategory) return null;
  try {
    const payload = await request('/api/v1/config/validate', {
      method: 'POST',
      body: JSON.stringify({ category: state.activeCategory, values: state.draftValues }),
    });
    state.validationErrors = payload.errors || [];
    applyReloadPlan(payload.reload_plan);
    renderForm();
    renderValidationDetails();
    updateDirtyState();
    renderSummary();
    if (showMessage) showToast(payload.valid ? '設定内容に問題はありません。' : '入力内容を確認してください。', !payload.valid);
    return payload;
  } catch (error) {
    state.validationErrors = error.details || [{ field: 'request', message: error.message }];
    renderValidationDetails();
    renderSummary();
    showToast(error.message, true);
    return null;
  }
}

async function saveDraft() {
  const validation = await validateDraft(false);
  if (!validation?.valid) {
    showToast('入力エラーを修正してから保存してください。', true);
    return;
  }
  try {
    const payload = await request(`/api/v1/config/categories/${state.activeCategory}`, {
      method: 'PUT',
      body: JSON.stringify({ revision: state.revision, values: state.draftValues }),
    });
    state.revision = payload.revision;
    state.originalValues = clone(state.draftValues);
    if (state.manifest) state.manifest.revision = payload.revision;
    applyReloadPlan(payload.reload_plan);
    updateDirtyState();
    renderSummary();
    showToast(`保存しました。${payload.reload_plan.message}`);
  } catch (error) {
    if (error.code === 'validation_failed') state.validationErrors = error.details || [];
    renderForm();
    renderValidationDetails();
    renderSummary();
    showToast(error.message, true);
  }
}

async function openHistory() {
  try {
    const payload = await request('/api/v1/config/history');
    elements.historyList.replaceChildren();
    if (!payload.history?.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = 'まだ保存履歴はありません。';
      elements.historyList.append(empty);
    } else {
      for (const entry of payload.history) {
        const article = document.createElement('article');
        article.className = 'history-entry';
        const title = document.createElement('strong');
        title.textContent = `revision ${entry.revision} / ${entry.category}.yaml`;
        const date = document.createElement('small');
        date.textContent = new Date(entry.saved_at).toLocaleString('ja-JP');
        article.append(title, date);
        elements.historyList.append(article);
      }
    }
    elements.historyDialog.showModal();
  } catch (error) {
    showToast(error.message, true);
  }
}

function openPreview() {
  elements.preview.textContent = JSON.stringify({
    source_file: `${state.activeCategory}.yaml`,
    revision: state.revision,
    values: state.draftValues,
  }, null, 2);
  elements.previewDialog.showModal();
}

async function bootstrap() {
  try {
    state.manifest = await request('/api/v1/config/manifest');
    state.revision = state.manifest.revision;
    setConnection(true);
    renderNavigation();
    renderSummary();
    const first = state.manifest.categories?.[0]?.id;
    if (first) await selectCategory(first);
  } catch (error) {
    setConnection(false);
    showToast(error.message, true);
  }
}

elements.validateButton.addEventListener('click', () => validateDraft(true));
elements.saveButton.addEventListener('click', saveDraft);
elements.resetButton.addEventListener('click', () => {
  state.draftValues = clone(state.originalValues);
  state.validationErrors = [];
  renderForm();
  renderValidationDetails();
  updateDirtyState();
  renderSummary();
});
elements.historyOpen.addEventListener('click', openHistory);
elements.previewButton.addEventListener('click', openPreview);
for (const button of document.querySelectorAll('[data-close]')) {
  button.addEventListener('click', () => document.querySelector(`#${button.dataset.close}`)?.close());
}
window.addEventListener('beforeunload', (event) => {
  if (!isDirty()) return;
  event.preventDefault();
  event.returnValue = '';
});

bootstrap();

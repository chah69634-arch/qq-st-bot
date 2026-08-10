const OWNER_TURN_TEMPLATE_PLACEHOLDER = 'PRESENCE_OWNER_TOKEN';
let _ownerTurnCursor = '';
let _ownerTurnCursorHistory = [];
let _ownerTurnNextCursor = '';

function ownerTurnText(key, fallback, params) {
  return typeof t === 'function' ? t(key, fallback, params) : fallback;
}

function ownerTurnSetText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = String(value ?? '—');
}

function ownerTurnFormatTime(value) {
  if (value == null || value === '') return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return new Date(number * 1000).toISOString();
}

function ownerTurnRenderPanel(id, rows) {
  const element = document.getElementById(id);
  if (!element) return;
  element.innerHTML = rows.map(([label, value]) => `<div class="status-summary-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('');
}

function ownerTurnTemplates() {
  const base = window.location.origin;
  return {
    curl: `export ${OWNER_TURN_TEMPLATE_PLACEHOLDER}='<one-time local secret>'\ncurl --fail-with-body -X POST "${base}/v1/owner/turns" \\\n  -H "Authorization: Bearer $${OWNER_TURN_TEMPLATE_PLACEHOLDER}" \\\n  -H "Content-Type: application/json" \\\n  --data '{"client_turn_id":"demo-001","message":"hello"}'`,
    python: `import os\nimport requests\n\nbase_url = "${base}"\ntoken = os.environ["${OWNER_TURN_TEMPLATE_PLACEHOLDER}"]\nresponse = requests.post(\n    f"{base_url}/v1/owner/turns",\n    headers={"Authorization": f"Bearer {token}"},\n    json={"client_turn_id": "demo-001", "message": "hello"},\n    timeout=30,\n)\nprint(response.status_code, response.json())`,
    typescript: `const baseUrl = "${base}";\nconst token = process.env.${OWNER_TURN_TEMPLATE_PLACEHOLDER};\nif (!token) throw new Error("${OWNER_TURN_TEMPLATE_PLACEHOLDER} is required");\nconst response = await fetch(\`\${baseUrl}/v1/owner/turns\`, {\n  method: "POST",\n  headers: { Authorization: \`Bearer \${token}\`, "Content-Type": "application/json" },\n  body: JSON.stringify({ client_turn_id: "demo-001", message: "hello" }),\n});\nconsole.log(response.status, await response.json());`,
  };
}

function loadOwnerTurnTemplates() {
  const templates = ownerTurnTemplates();
  Object.entries(templates).forEach(([name, value]) => ownerTurnSetText(`owner-turn-template-${name}`, value));
  ownerTurnSetText('owner-turn-base-url', window.location.origin);
  ownerTurnSetText('owner-turn-status-example', '{\n  "status": "accepted",\n  "client_turn_id": "demo-001",\n  "canonical_turn_id": "<server-issued id>",\n  "reply": "<owner-input response>"\n}\n\n202 = request accepted while the turn is still running\n409 = same client_turn_id was reused with a different payload\n503 = execution outcome unknown after restart; do not rerun blindly');
}

async function loadOwnerTurnTokenMetadata() {
  const element = document.getElementById('owner-turn-token-metadata');
  if (!element) return;
  element.innerHTML = `<div class="loading">${escapeHtml(ownerTurnText('common.loading', '加载中…'))}</div>`;
  try {
    const data = await api('GET', '/auth/tokens');
    const tokens = (data.tokens || []).filter(item => (item.profiles || []).includes('owner-input'));
    if (!tokens.length) {
      element.innerHTML = `<div class="empty">${escapeHtml(ownerTurnText('owner_turn.api.token_none', '未发现 owner-input token'))}</div>`;
      return;
    }
    element.innerHTML = `<div class="tbl-wrap"><table><thead><tr><th>${escapeHtml(ownerTurnText('owner_turn.api.token_label', 'Label'))}</th><th>${escapeHtml(ownerTurnText('owner_turn.api.token_disabled', 'Disabled'))}</th><th>${escapeHtml(ownerTurnText('owner_turn.api.token_expires', 'Expires'))}</th><th>${escapeHtml(ownerTurnText('owner_turn.api.hash_prefix', 'Hash prefix'))}</th></tr></thead><tbody>${tokens.map(item => `<tr><td>${escapeHtml(item.label)}</td><td>${escapeHtml(String(Boolean(item.disabled)))}</td><td>${escapeHtml(item.expires_at || '—')}</td><td><code>${escapeHtml(item.hash_prefix || '—')}</code></td></tr>`).join('')}</tbody></table></div>`;
  } catch (error) {
    element.innerHTML = `<div class="empty">${escapeHtml(ownerTurnText('owner_turn.api.token_load_failed', 'Token 元数据加载失败：{error}', {error: error.message}))}</div>`;
  }
}

function ownerTurnSelectTab(tab) {
  document.querySelectorAll('.owner-turn-tab').forEach(panel => { panel.hidden = panel.id !== `owner-turn-tab-${tab}`; });
  document.querySelectorAll('.owner-turn-tabs [data-action="ownerTurnSelectTab"]').forEach(button => {
    const active = button.dataset.actionArgs === JSON.stringify([tab]);
    button.classList.toggle('btn-primary', active);
    button.classList.toggle('btn-ghost', !active);
  });
  if (tab === 'observability') loadOwnerTurnReceipts();
  if (tab === 'deployment') loadOwnerTurnDeployment();
}

function ownerTurnReceiptQuery(cursor = '') {
  const params = new URLSearchParams({limit: '25'});
  const status = document.getElementById('owner-turn-filter-status')?.value || '';
  const caller = document.getElementById('owner-turn-filter-caller')?.value.trim() || '';
  const after = document.getElementById('owner-turn-filter-after')?.value || '';
  const before = document.getElementById('owner-turn-filter-before')?.value || '';
  if (status) params.set('status', status);
  if (caller) params.set('caller', caller);
  if (after) params.set('created_after', after);
  if (before) params.set('created_before', before);
  if (cursor) params.set('cursor', cursor);
  return `/observability/owner-turns?${params}`;
}

async function loadOwnerTurnReceipts({reset = false} = {}) {
  const state = document.getElementById('owner-turn-receipts-state');
  if (!state) return;
  if (reset) { _ownerTurnCursor = ''; _ownerTurnCursorHistory = []; }
  state.innerHTML = `<div class="loading">${escapeHtml(ownerTurnText('common.loading', '加载中…'))}</div>`;
  try {
    const data = await api('GET', ownerTurnReceiptQuery(_ownerTurnCursor));
    const rows = data.receipts || data.items || [];
    const body = document.getElementById('owner-turn-receipts-body');
    body.innerHTML = rows.map(item => `<tr><td>${escapeHtml(item.caller)}</td><td><code>${escapeHtml(item.client_turn_id)}</code></td><td><code>${escapeHtml(item.canonical_turn_id || '—')}</code></td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(ownerTurnFormatTime(item.created_at))}</td><td>${escapeHtml(ownerTurnFormatTime(item.updated_at))}</td><td>${escapeHtml(item.error_code || '—')}</td></tr>`).join('');
    if (!rows.length) state.innerHTML = `<div class="empty">${escapeHtml(ownerTurnText('owner_turn.obs.empty', '当前筛选没有记录'))}</div>`;
    else state.replaceChildren();
    const counts = data.status_counts || {};
    ownerTurnRenderPanel('owner-turn-status-summary', Object.entries(counts).map(([key, value]) => [key, String(value)]));
    _ownerTurnNextCursor = data.next_cursor || '';
  } catch (error) {
    state.innerHTML = `<div class="empty">${escapeHtml(ownerTurnText('owner_turn.obs.load_failed', '观测加载失败：{error}', {error: error.message}))}</div>`;
  }
}

function ownerTurnNextPage() {
  if (!_ownerTurnNextCursor) return;
  _ownerTurnCursorHistory.push(_ownerTurnCursor);
  _ownerTurnCursor = _ownerTurnNextCursor;
  loadOwnerTurnReceipts();
}

function ownerTurnPreviousPage() {
  if (!_ownerTurnCursorHistory.length) return;
  _ownerTurnCursor = _ownerTurnCursorHistory.pop() || '';
  loadOwnerTurnReceipts();
}

function ownerTurnDeploymentRows(data) {
  return Object.entries(data || {}).filter(([key]) => !['credentials'].includes(key)).map(([key, value]) => [key, typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')]);
}

async function loadOwnerTurnDeployment() {
  const targets = [
    ['owner-turn-deployment-capabilities', '/observability/deployment-capabilities'],
    ['owner-turn-deployment-preflight', '/system/deployment-preflight'],
    ['owner-turn-diary-sync', '/integrations/diary/sync/status'],
  ];
  await Promise.all(targets.map(async ([id, path]) => {
    try { ownerTurnRenderPanel(id, ownerTurnDeploymentRows(await api('GET', path))); }
    catch (error) { ownerTurnRenderPanel(id, [['error', error.message]]); }
  }));
}

async function copyOwnerTurnTemplate(name) {
  const value = ownerTurnTemplates()[name];
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    toast(ownerTurnText('owner_turn.api.copied', '已复制'));
  } catch (_error) {
    toast(ownerTurnText('owner_turn.api.copy_failed', '复制失败，请手动复制'), 'err');
  }
}

function loadOwnerTurnApiPage() {
  loadOwnerTurnTemplates();
  loadOwnerTurnTokenMetadata();
  ownerTurnSelectTab('api');
}

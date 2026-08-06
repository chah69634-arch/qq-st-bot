// ══════════════════════════════════════════════════════════
//  State
// ══════════════════════════════════════════════════════════
let TOKEN = localStorage.getItem('qq_admin_key') || '';
let BASE  = window.location.origin;
let _currentUser = null;
let _allUsers = [];
const ACTIVE_PAGE_SESSION_KEY = 'admin_active_page';
window._charName = '叶瑄';  // fallback; overwritten after login by _initCharName()

window.addEventListener('admin-language-changed', () => {
  const activePage = document.querySelector('.page.active');
  const appVisible = document.getElementById('app').style.display !== 'none';
  if (activePage && appVisible) goto(activePage.id.replace(/^page-/, ''));
});


const _pageFragmentLoads = new Map();
const ADMIN_UI_FRAGMENT_VERSION = 'admin-ui-capability-entrances-1';

function getRememberedPage() {
  try {
    const page = sessionStorage.getItem(ACTIVE_PAGE_SESSION_KEY);
    if (page && document.getElementById('page-' + page)) return page;
    sessionStorage.removeItem(ACTIVE_PAGE_SESSION_KEY);
  } catch (_error) { /* Storage can be unavailable in restricted browser contexts. */ }
  return null;
}

function rememberPage(page) {
  try {
    sessionStorage.setItem(ACTIVE_PAGE_SESSION_KEY, page);
  } catch (_error) { /* Page navigation must still work without storage access. */ }
}

function clearRememberedPage() {
  try {
    sessionStorage.removeItem(ACTIVE_PAGE_SESSION_KEY);
  } catch (_error) { /* Best effort only. */ }
}

function _actionArgs(element) {
  const raw = element.dataset.actionArgs;
  if (!raw) return [];
  try {
    const args = JSON.parse(raw);
    return Array.isArray(args) ? args : [];
  } catch (error) {
    console.error('[admin] invalid data-action-args', raw, error);
    return [];
  }
}

function _runAction(event) {
  const element = event.currentTarget;
  const action = element.dataset.action;
  const args = _actionArgs(element);
  if (action === 'focus-element') {
    document.getElementById(args[0])?.click();
    return;
  }
  const fn = window[action];
  if (typeof fn !== 'function') {
    console.error('[admin] missing action handler', action);
    return;
  }
  fn(...args, element);
}

function bindPageActions(scope) {
  if (!scope) return;
  const actions = [
    ...(scope.matches?.('[data-action]') ? [scope] : []),
    ...scope.querySelectorAll('[data-action]'),
  ];
  actions.forEach(element => {
    if (element.dataset.actionBound === 'true') return;
    element.addEventListener('click', _runAction);
    element.dataset.actionBound = 'true';
  });
}

async function loadPageFragment(page) {
  const container = document.getElementById('page-' + page);
  if (!container || container.dataset.pageLoaded === 'true') return container;
  if (!_pageFragmentLoads.has(page)) {
    const request = fetch(`/static/pages/${encodeURIComponent(page)}.html?v=${ADMIN_UI_FRAGMENT_VERSION}`)
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then(html => {
        container.innerHTML = html;
        container.dataset.pageLoaded = 'true';
        window.AdminI18n?.applyI18n(container);
        bindPageActions(container);
        return container;
      })
      .catch(error => {
        _pageFragmentLoads.delete(page);
        console.error(`[admin] failed to load page fragment ${page}`, error);
        throw error;
      });
    _pageFragmentLoads.set(page, request);
  }
  return _pageFragmentLoads.get(page);
}

function bindShellActions() {
  bindPageActions(document.getElementById('auth-overlay'));
  bindPageActions(document.querySelector('nav'));
  bindPageActions(document.querySelector('main'));
  bindPageActions(document.getElementById('nav-menu-toggle'));
  bindPageActions(document.getElementById('nav-backdrop'));
}

const MOBILE_NAV_MEDIA = window.matchMedia('(max-width: 767px)');

function setSidebarOpen(open) {
  const shouldOpen = Boolean(open) && MOBILE_NAV_MEDIA.matches;
  const app = document.getElementById('app');
  const toggle = document.getElementById('nav-menu-toggle');
  const backdrop = document.getElementById('nav-backdrop');
  app.classList.toggle('admin-sidebar-open', shouldOpen);
  document.body.classList.toggle('admin-sidebar-open', shouldOpen);
  toggle.setAttribute('aria-expanded', String(shouldOpen));
  backdrop.setAttribute('aria-hidden', String(!shouldOpen));
  backdrop.tabIndex = shouldOpen ? 0 : -1;
}

function toggleSidebar() {
  setSidebarOpen(!document.getElementById('app').classList.contains('admin-sidebar-open'));
}

function closeSidebar() {
  setSidebarOpen(false);
}

function initMobileSidebar() {
  document.querySelector('nav').addEventListener('click', event => {
    if (event.target.closest('a[data-page]')) closeSidebar();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeSidebar();
  });
  MOBILE_NAV_MEDIA.addEventListener('change', () => closeSidebar());
  setSidebarOpen(false);
}


async function goto(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  const pageElement = document.getElementById('page-' + page);
  if (!pageElement) {
    console.error('[admin] unknown page', page);
    return;
  }
  pageElement.classList.add('active');
  document.querySelector(`nav a[data-page="${page}"]`)?.classList.add('active');

  try {
    await loadPageFragment(page);
  } catch (_error) {
    return;
  }
  rememberPage(page);

  const loaders = {
    setup:           loadSetupPage,
    status:          loadStatus,
    users:           () => { loadUsers(); loadBlacklist(); },
    logs:            loadLogs,
    'auth-tokens':   () => { loadAuthTokens(); loadChannelToggles(); },
    'model-routing': loadModelRouting,
    mcp:             loadMcpPage,
    tools:           loadToolsPage,
    'relationship-facts': loadRelationshipFactsPage,
    character:       loadCharacterPage,
    lorebook:        () => { loadLorebook(); loadJbEntries(); },
    'dream-settings': loadDreamSettings,
    scheduler:       loadScheduler,
    integrations:    loadGardenIntegrations,
    'observe-mood':    loadObserveMood,
    'observe-dream':   loadObserveDream,
    'observe-memory':  () => {},
    'observe-hidden':  loadObserveHidden,
    'observe-chatlog': loadObserveChatlogDates,
    'observe-runtime': loadObserveRuntime,
    'observe-growth':  () => initObserveCharacters('obs-growth-char', loadObserveGrowth),
    'observe-visual':  loadObserveVisual,
    'observe-spend':   loadObserveSpend,
    'observe-group-arbiter': initObserveGroupArbiter,
    'observe-memory-summary': () => initObserveCharacters('obs-memory-summary-char'),
    'observe-prompt':  () => { loadObservePromptUidList(); loadPromptAblation(); loadOutputSegmentEnforce(); },
    'observe-tools':   () => loadObserveToolUidList(),
    'observe-dream-prompt': () => loadObserveDreamPromptUidList(),
    'observe-trigger-catalog': () => loadTriggerCatalog(),
    'observe-vector':          () => loadVector(),
    'observe-provenance':      () => loadProvenance(),
    'observe-resource-completeness': () => loadResourceCompleteness(),
    'observe-api-contract':          () => loadApiContractCheck(),
    'observe-runtime-signals':       () => loadRuntimeSignals(),
    'observe-autonomy':              loadObserveAutonomy,
    'observe-char-permissions':      () => initObserveCharacters('obs-charperm-char', loadCharPermissions),
  };
  if (page !== 'scheduler') _stopWatchStatusPoller();
  if (loaders[page]) loaders[page]();
}

bindShellActions();
initMobileSidebar();

// ══════════════════════════════════════════════════════════
//  API helper
// ══════════════════════════════════════════════════════════
function authHeaders(extra) {
  return { 'Authorization': `Bearer ${TOKEN}`, 'Content-Type': 'application/json', ...extra };
}

async function api(method, path, body) {
  const opts = { method, headers: authHeaders() };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`HTTP ${r.status}: ${t}`);
  }
  return r.json();
}

// Small structured editor for settings whose supported keys vary by provider.
function renderKeyValueEditor(id, values = {}, options = {}) {
  const root = document.getElementById(id);
  if (!root) return;
  const entries = Object.entries(values || {}).filter(([key]) => !options.exclude?.includes(key));
  const rows = entries.length ? entries : [['', '']];
  root.innerHTML = rows.map(([key, value]) => `
    <div class="form-row" data-kv-row>
      <input data-kv-key placeholder="key" value="${escapeHtml(String(key))}">
      <input data-kv-value placeholder="value" value="${escapeHtml(value == null ? '' : String(value))}">
      <select data-kv-type><option value="string">text</option><option value="number">number</option><option value="boolean">true/false</option></select>
      <button type="button" class="btn btn-ghost btn-sm" data-action="removeKeyValueRow">Remove</button>
    </div>`).join('');
  root.querySelectorAll('[data-kv-row]').forEach((row, index) => {
    const value = entries[index]?.[1];
    const type = typeof value === 'number' ? 'number' : typeof value === 'boolean' ? 'boolean' : 'string';
    row.querySelector('[data-kv-type]').value = type;
  });
}

function addKeyValueRow(id) {
  const root = document.getElementById(id);
  if (!root) return;
  root.insertAdjacentHTML('beforeend', '<div class="form-row" data-kv-row><input data-kv-key placeholder="key"><input data-kv-value placeholder="value"><select data-kv-type><option value="string">text</option><option value="number">number</option><option value="boolean">true/false</option></select><button type="button" class="btn btn-ghost btn-sm" data-action="removeKeyValueRow">Remove</button></div>');
  bindPageActions(root);
}

function removeKeyValueRow(button) {
  const row = button.closest('[data-kv-row]');
  const root = row?.parentElement;
  row?.remove();
  if (root && !root.querySelector('[data-kv-row]')) addKeyValueRow(root.id);
}

function readKeyValueEditor(id) {
  const result = {};
  document.querySelectorAll(`#${CSS.escape(id)} [data-kv-row]`).forEach(row => {
    const key = row.querySelector('[data-kv-key]').value.trim();
    const raw = row.querySelector('[data-kv-value]').value;
    const type = row.querySelector('[data-kv-type]').value;
    if (!key) return;
    if (type === 'number') {
      const value = Number(raw);
      if (!Number.isFinite(value)) throw new Error(`${key} must be a number`);
      result[key] = value;
    } else if (type === 'boolean') {
      if (!/^(true|false)$/i.test(raw.trim())) throw new Error(`${key} must be true or false`);
      result[key] = raw.trim().toLowerCase() === 'true';
    } else result[key] = raw;
  });
  return result;
}

// ══════════════════════════════════════════════════════════
//  Toast
// ══════════════════════════════════════════════════════════
let _toastTimer;
function toast(msg, type = 'ok') {
  msg = window.AdminI18n ? AdminI18n.translateUiText(msg) : msg;
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `show ${type}`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.className = '', 3200);
}

// ══════════════════════════════════════════════════════════
//  Status page
// ══════════════════════════════════════════════════════════

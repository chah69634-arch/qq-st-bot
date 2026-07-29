// ══════════════════════════════════════════════════════════
//  State
// ══════════════════════════════════════════════════════════
let TOKEN = localStorage.getItem('qq_admin_key') || '';
let BASE  = window.location.origin;
let _currentUser = null;
let _allUsers = [];
window._charName = '叶瑄';  // fallback; overwritten after login by _initCharName()

window.addEventListener('admin-language-changed', () => {
  const activePage = document.querySelector('.page.active');
  const appVisible = document.getElementById('app').style.display !== 'none';
  if (activePage && appVisible) goto(activePage.id.replace(/^page-/, ''));
});


const _pageFragmentLoads = new Map();
const ADMIN_UI_FRAGMENT_VERSION = 'admin-ui-existence-1';

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
  fn(...args);
}

function bindPageActions(scope) {
  if (!scope) return;
  scope.querySelectorAll('[data-action]').forEach(element => {
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

  const loaders = {
    setup:           loadSetupPage,
    status:          loadStatus,
    users:           () => { loadUsers(); loadBlacklist(); },
    logs:            loadLogs,
    'auth-tokens':   () => { loadAuthTokens(); loadChannelToggles(); },
    'model-routing': loadModelRouting,
    mcp:             loadMcpPage,
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
    'observe-char-permissions':      () => initObserveCharacters('obs-charperm-char', loadCharPermissions),
  };
  if (page !== 'scheduler') _stopWatchStatusPoller();
  if (loaders[page]) loaders[page]();
}

bindShellActions();

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

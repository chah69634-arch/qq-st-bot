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



function goto(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  document.querySelector(`nav a[data-page="${page}"]`).classList.add('active');

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
    pet:             loadPet,
    yexuan:          loadYexuanPage,
    scheduler:       loadScheduler,
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
    'observe-probe':   () => loadObserveProbeUidList(),
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

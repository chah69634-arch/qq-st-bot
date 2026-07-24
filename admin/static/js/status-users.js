async function loadStatus() {
  loadFeatureFlags();
  try {
    const d = await api('GET', '/status');
    document.getElementById('s-users').textContent    = d.known_user_count ?? '—';
  } catch(e) {
    toast(t('status.error.load', '获取状态失败: {error}', {error: e.message}), 'err');
  }
  loadToolRegistry();
  loadProxy();
  loadContextConfig();
  loadLlmParams();
  loadVisionParams();
  loadScreenPeekSettings();
  loadMetaMode();
  loadTtsConfig();
  loadStickerConfig();
  _ensurePronounUidOptions().then(() => {
    if (document.getElementById('pn-uid-select').value) loadUserPronoun();
  });
}

async function reloadConfig() {
  try {
    const d = await api('POST', '/reload');
    toast(d.message, 'ok');
    loadStatus();
  } catch(e) { toast(t('status.error.reload', '热重载失败: {error}', {error: e.message}), 'err'); }
}

// ══════════════════════════════════════════════════════════
//  Users page
// ══════════════════════════════════════════════════════════
async function loadUsers() {
  try {
    const d = await api('GET', '/users/');
    _allUsers = d.users || [];
    renderUsers(_allUsers);
  } catch(e) { toast('加载用户失败: ' + e.message, 'err'); }
}

function filterUsers() {
  const q = document.getElementById('user-search').value.trim().toLowerCase();
  renderUsers(q ? _allUsers.filter(u => u.includes(q)) : _allUsers).catch(() => {});
}

function renderUsers(list) {
  const el = document.getElementById('user-table-body');
  if (!list.length) { el.innerHTML = '<div class="empty">没有找到用户记录</div>'; return; }

  const rows = list.map(uid => `
    <tr style="cursor:pointer" onclick="toggleUserRelPanel('${uid}')">
      <td><code style="font-family:var(--mono);font-size:13px">${uid}</code>
        <span style="font-size:11px;color:var(--muted);margin-left:6px">点击展开关系配置</span>
      </td>
      <td>
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openMemModal('${uid}')">查看记忆</button>
      </td>
    </tr>
    <tr id="rel-panel-row-${uid}" style="display:none">
      <td colspan="2" style="padding:0">
        <div style="padding:14px 20px 16px;background:rgba(0,0,0,.2);border-top:1px solid var(--border)">
          <div style="font-size:12px;color:var(--muted);margin-bottom:10px">关系配置：${uid}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;max-width:560px">
            <label class="field">
              <span>角色 (role)</span>
              <select id="ri-role-${uid}">
                <option value="stranger">stranger（陌生人）</option>
                <option value="friend">friend（朋友）</option>
                <option value="close_friend">close_friend（好友）</option>
                <option value="lover">lover（恋人）</option>
                <option value="master">master（主人）</option>
                <option value="default">default（全局默认）</option>
              </select>
            </label>
            <label class="field">
              <span>昵称 (nickname)</span>
              <input type="text" id="ri-nickname-${uid}" placeholder="留空则无">
            </label>
          </div>
          <div style="margin-top:10px;max-width:560px">
            <label class="field">
              <span>额外提示词 (extra_prompt)</span>
              <textarea id="ri-extra-${uid}" style="min-height:56px"
                placeholder="在系统提示末尾追加的用户专属指令…"></textarea>
            </label>
          </div>
          <div style="margin-top:10px">
            <button class="btn btn-primary btn-sm" onclick="saveUserRelInline('${uid}')">保存关系配置</button>
          </div>
        </div>
      </td>
    </tr>`).join('');

  el.innerHTML = `<div class="tbl-wrap"><table>
    <tr><th>用户 ID</th><th style="width:100px">操作</th></tr>
    ${rows}
  </table></div>`;
}

async function toggleUserRelPanel(uid) {
  const row = document.getElementById(`rel-panel-row-${uid}`);
  if (!row) return;
  const isOpen = row.style.display !== 'none';
  if (isOpen) {
    row.style.display = 'none';
    return;
  }
  row.style.display = '';
  try {
    const d = await api('GET', `/relations/${uid}`);
    const r = d.raw || d.merged || {};
    document.getElementById(`ri-role-${uid}`).value     = r.role || 'stranger';
    document.getElementById(`ri-nickname-${uid}`).value = r.nickname || '';
    document.getElementById(`ri-extra-${uid}`).value    = r.extra_prompt || '';
  } catch { /* no existing relation, keep defaults */ }
}

async function saveUserRelInline(uid) {
  const body = {
    role:         document.getElementById(`ri-role-${uid}`).value,
    nickname:     document.getElementById(`ri-nickname-${uid}`).value || null,
    extra_prompt: document.getElementById(`ri-extra-${uid}`).value,
    priority: 1,
    permissions: { agent_control: false, image_gen: false },
  };
  try {
    const d = await api('PUT', `/relations/${uid}`, body);
    toast(d.message, 'ok');
  } catch(e) { toast('保存失败: ' + e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  Blacklist page
// ══════════════════════════════════════════════════════════
async function loadBlacklist() {
  try {
    const d = await api('GET', '/relations/blacklist');
    renderBlacklist(d.blacklist || []);
  } catch(e) { toast('加载黑名单失败: ' + e.message, 'err'); }
}

function renderBlacklist(list) {
  const el = document.getElementById('bl-list');
  if (!list.length) { el.innerHTML = '<div class="empty">黑名单为空</div>'; return; }
  el.innerHTML = `<div class="tbl-wrap"><table>
    <tr><th>用户 ID</th><th>操作</th></tr>
    ${list.map(uid => `<tr>
      <td><code style="font-family:var(--mono)">${uid}</code></td>
      <td><button class="btn btn-ghost btn-sm" onclick="removeBlacklist('${uid}')">解除屏蔽</button></td>
    </tr>`).join('')}
  </table></div>`;
}

async function addBlacklist() {
  const uid = document.getElementById('bl-add-input').value.trim();
  if (!uid) { toast('请输入 QQ 号', 'warn'); return; }
  try {
    const d = await api('POST', '/relations/blacklist', {user_id: uid});
    toast(d.message, 'ok');
    document.getElementById('bl-add-input').value = '';
    renderBlacklist(d.blacklist || []);
  } catch(e) { toast('添加失败: ' + e.message, 'err'); }
}

async function removeBlacklist(uid) {
  try {
    const d = await api('DELETE', `/relations/blacklist/${uid}`);
    toast(d.message, 'ok');
    renderBlacklist(d.blacklist || []);
  } catch(e) { toast('移除失败: ' + e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  Logs page
// ══════════════════════════════════════════════════════════
async function loadLogs() {
  const lines = document.getElementById('log-lines').value;
  try {
    const d = await api('GET', `/logs?lines=${lines}`);
    const box = document.getElementById('log-box');
    box.textContent = d.logs || '（日志为空）';
    box.scrollTop = box.scrollHeight;
    if (d.total_lines !== undefined) {
      document.getElementById('log-meta').textContent = `共 ${d.total_lines} 行，显示最后 ${lines} 行`;
    }
  } catch(e) { toast('加载日志失败: ' + e.message, 'err'); }
}

async function clearLogs() {
  if (!confirm('确定清空错误日志吗？')) return;
  try {
    const d = await api('DELETE', '/logs');
    toast(d.message, 'ok');
    document.getElementById('log-box').textContent = '（日志已清空）';
    document.getElementById('log-meta').textContent = '';
  } catch(e) { toast('清空失败: ' + e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  Memory modal
// ══════════════════════════════════════════════════════════
function openMemModal(uid) {
  _currentUser = uid;
  document.getElementById('mem-modal-title').textContent = `用户记忆：${uid}`;
  document.getElementById('mem-modal').classList.add('open');
  memTab('profile');
}

function closeMemModal() {
  document.getElementById('mem-modal').classList.remove('open');
  _currentUser = null;
}

function memTab(tab) {
  ['profile','history','rag'].forEach(t => {
    document.getElementById(`mem-${t}-panel`).style.display = t === tab ? '' : 'none';
    document.getElementById(`mt-${t}`).classList.toggle('btn-primary', t === tab);
    document.getElementById(`mt-${t}`).classList.toggle('btn-ghost',   t !== tab);
  });
  if (tab === 'profile') loadProfile();
  if (tab === 'history') loadHistory();
}

async function loadProfile() {
  const uid = _currentUser;
  try {
    const d = await api('GET', `/users/${uid}/profile`);
    const p = d.profile || {};
    const el = document.getElementById('profile-view');
    el.innerHTML = `<div class="profile-grid">
      ${[['姓名/称呼','name'],['所在地','location'],['职业/学校','occupation'],['兴趣爱好','interests'],['宠物','pets']].map(([lbl, key]) =>
        `<div class="profile-field"><div class="lbl">${lbl}</div><div class="val">${p[key] ? `<span class="i18n-raw">${escapeHtml(String(p[key]))}</span>` : '<span style="color:var(--muted)">未知</span>'}</div></div>`
      ).join('')}
      <div class="profile-field" style="grid-column:1/-1">
        <div class="lbl">重要事实</div>
        <div class="val">${(p.important_facts||[]).length
          ? (p.important_facts).map(f => `<div class="i18n-raw" style="margin-bottom:3px">• ${escapeHtml(String(f))}</div>`).join('')
          : '<span style="color:var(--muted)">暂无</span>'
        }</div>
      </div>
    </div>`;
  } catch(e) { toast('加载画像失败: ' + e.message, 'err'); }
}

async function loadHistory() {
  const uid = _currentUser;
  try {
    const d = await api('GET', `/memory/${uid}/short-term`);
    const msgs = d.history || [];
    const el = document.getElementById('msg-list');
    if (!msgs.length) { el.innerHTML = '<div class="empty">暂无对话历史</div>'; return; }
    el.innerHTML = msgs.map(m =>
      `<div class="msg ${m.role}">
        <div class="role">${m.role === 'user' ? '用户' : 'Bot'}</div>
        <div class="i18n-raw">${escapeHtml(m.content)}</div>
      </div>`
    ).join('');
    el.scrollTop = el.scrollHeight;
  } catch(e) { toast('加载历史失败: ' + e.message, 'err'); }
}

async function searchRAG() {
  const uid = _currentUser;
  const q = document.getElementById('rag-query').value.trim();
  if (!q) return;
  const el = document.getElementById('rag-results');
  el.innerHTML = '<div class="loading">搜索中…</div>';
  try {
    const d = await api('GET', `/memory/${uid}/rag/search?query=${encodeURIComponent(q)}`);
    const results = d.results || [];
    el.innerHTML = results.length
      ? results.map((r, i) => `<div class="i18n-raw" style="margin-bottom:8px;padding:8px;background:var(--border);border-radius:6px;font-size:12px;line-height:1.6">${i+1}. ${escapeHtml(r)}</div>`).join('')
      : '<div class="empty">未找到相关记忆</div>';
  } catch(e) { toast('搜索失败: ' + e.message, 'err'); el.innerHTML = ''; }
}

async function clearMemoryPart(part) {
  const uid = _currentUser;
  const labels = {'short-term':'短期历史','profile':'画像','rag':'RAG 记忆'};
  if (!confirm(`确定清空用户 ${uid} 的${labels[part]}吗？`)) return;
  try {
    let d;
    if (part === 'short-term') d = await api('DELETE', `/memory/${uid}/short-term`);
    else if (part === 'rag')   d = await api('DELETE', `/memory/${uid}/rag`);
    else if (part === 'profile') {
      d = await api('PUT', `/users/${uid}/profile`, {
        name:null, location:null, pets:null, interests:null, occupation:null, important_facts:[]
      });
    }
    toast(d.message, 'ok');
    // Refresh current tab
    if (part === 'short-term') loadHistory();
    else if (part === 'profile') loadProfile();
  } catch(e) { toast('清空失败: ' + e.message, 'err'); }
}

async function clearAllMemory() {
  const uid = _currentUser;
  if (!confirm(`确定清除用户 ${uid} 的所有记忆（历史 + 画像 + RAG）吗？`)) return;
  try {
    const d = await api('DELETE', `/users/${uid}/memory`);
    toast(d.message, 'ok');
    loadProfile();
  } catch(e) { toast('清除失败: ' + e.message, 'err'); }
}

// ── Profile edit ──
async function editProfile() {
  const uid = _currentUser;
  try {
    const d = await api('GET', `/users/${uid}/profile`);
    const p = d.profile || {};
    document.getElementById('pe-name').value       = p.name || '';
    document.getElementById('pe-location').value   = p.location || '';
    document.getElementById('pe-occupation').value = p.occupation || '';
    document.getElementById('pe-interests').value  = p.interests || '';
    document.getElementById('pe-pets').value       = p.pets || '';
    document.getElementById('pe-facts').value      = (p.important_facts||[]).join('\n');
    document.getElementById('profile-edit-modal').classList.add('open');
  } catch(e) { toast('加载画像失败: ' + e.message, 'err'); }
}

function closeProfileEdit() { document.getElementById('profile-edit-modal').classList.remove('open'); }

async function saveProfile() {
  const uid = _currentUser;
  const facts = document.getElementById('pe-facts').value
    .split('\n').map(s => s.trim()).filter(Boolean);
  const body = {
    name:           document.getElementById('pe-name').value || null,
    location:       document.getElementById('pe-location').value || null,
    occupation:     document.getElementById('pe-occupation').value || null,
    interests:      document.getElementById('pe-interests').value || null,
    pets:           document.getElementById('pe-pets').value || null,
    important_facts: facts,
  };
  try {
    const d = await api('PUT', `/users/${uid}/profile`, body);
    toast(d.message, 'ok');
    closeProfileEdit();
    loadProfile();
  } catch(e) { toast('保存失败: ' + e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  Lorebook
// ══════════════════════════════════════════════════════════

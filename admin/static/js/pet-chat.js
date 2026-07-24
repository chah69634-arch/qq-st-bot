async function loadPet() {
  const el = document.getElementById('pet-display');
  el.innerHTML = '<div class="loading">加载中…</div>';
  try {
    const d = await api('GET', '/pet');
    if (!d.pet) {
      el.innerHTML = `<div class="empty">还没有宠物，创建一只吧～</div>`;
      return;
    }
    const p = d.pet;
    const moodPct    = Math.round(p.mood ?? 80);
    const hungerPct  = Math.round(p.hunger ?? 20);
    el.innerHTML = `
      <div style="display:flex;align-items:flex-start;gap:20px;flex-wrap:wrap">
        <div style="font-size:3rem;line-height:1">${speciesEmoji(p.species)}</div>
        <div style="flex:1;min-width:200px">
          <div style="font-size:1.2rem;font-weight:700;color:var(--accent);margin-bottom:4px">${escapeHtml(p.name)}
            <span style="font-size:0.8rem;color:var(--muted);font-weight:400">（${escapeHtml(p.species)}）</span>
          </div>
          <div style="font-size:13px;color:var(--muted);margin-bottom:12px;font-style:italic">${escapeHtml(p.greeting || '')}</div>
          <div style="display:flex;flex-direction:column;gap:8px;max-width:280px">
            <div>
              <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
                <span>心情</span><span style="color:var(--accent)">${moodPct}/100</span>
              </div>
              <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden">
                <div style="height:100%;background:var(--success);border-radius:3px;width:${moodPct}%"></div>
              </div>
            </div>
            <div>
              <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
                <span>饥饿度</span><span style="color:${hungerPct>=70?'var(--danger)':'var(--muted)'}">${hungerPct}/100</span>
              </div>
              <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden">
                <div style="height:100%;background:${hungerPct>=70?'var(--danger)':'var(--warn)'};border-radius:3px;width:${hungerPct}%"></div>
              </div>
            </div>
          </div>
          <div style="display:flex;gap:8px;margin-top:14px">
            <button class="btn btn-ghost btn-sm" onclick="petInteract('pet')">🤚 摸摸头</button>
            <button class="btn btn-ghost btn-sm" onclick="petInteract('feed')">🍖 喂食</button>
          </div>
        </div>
      </div>`;
    // 预填设置表单
    document.getElementById('pet-name-input').value = p.name || '';
    document.getElementById('pet-species-input').value = p.species || '猫';
  } catch(e) { el.innerHTML = `<div class="empty">加载失败：${escapeHtml(e.message)}</div>`; }
}

function speciesEmoji(s) {
  const m = {猫:'🐱', 狗:'🐶', 兔子:'🐰', 鸟:'🐦'};
  return m[s] || '🐾';
}

async function petInteract(action) {
  try {
    const d = await api('PUT', '/pet/interact', { action });
    toast(d.message, 'ok');
    await loadPet();
  } catch(e) { toast('操作失败：' + e.message, 'err'); }
}

async function savePet() {
  const name    = document.getElementById('pet-name-input').value.trim();
  const species = document.getElementById('pet-species-input').value;
  if (!name) { toast('请输入宠物名字', 'warn'); return; }
  try {
    const d = await api('POST', '/pet', { name, species });
    toast(d.message, 'ok');
    await loadPet();
  } catch(e) { toast('保存失败：' + e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  💬 与他
// ══════════════════════════════════════════════════════════
let _chatMsgs = [];

async function loadYexuanPage() {
  // 加载 frontend_owner 的好感度
  try {
    const d = await api('GET', '/memory/frontend_owner/affection');
    _updateChatAffection(d.value, d.label);
  } catch { _updateChatAffection(0, '陌生人'); }
}

function _updateChatAffection(value, label) {
  document.getElementById('chat-level-label').textContent  = label || '——';
  document.getElementById('chat-affection-val').textContent = `好感度: ${value ?? 0}`;
  document.getElementById('chat-aff-bar').style.width = Math.round((value ?? 0) / 10) + '%';
}

async function sendChatMsg() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  const btn = document.getElementById('chat-send-btn');
  btn.disabled = true;

  // 渲染用户消息
  _appendChatBubble('user', msg);

  // loading 占位
  const loadId = 'chat-loading-' + Date.now();
  const msgsEl = document.getElementById('chat-messages');
  msgsEl.insertAdjacentHTML('beforeend',
    `<div id="${loadId}" style="align-self:flex-start;color:var(--muted);font-size:13px;font-style:italic">${window._charName || '叶瑄'}正在输入…</div>`);
  msgsEl.scrollTop = msgsEl.scrollHeight;

  try {
    const d = await api('POST', '/chat', { message: msg });
    document.getElementById(loadId)?.remove();
    _appendChatBubble('assistant', d.reply || `（${window._charName || '叶瑄'}没有回应）`);
    _updateChatAffection(d.affection, d.level);
  } catch(e) {
    document.getElementById(loadId)?.remove();
    _appendChatBubble('assistant', `（出了点问题：${e.message}）`);
    toast('发送失败：' + e.message, 'err');
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

function _appendChatBubble(role, text) {
  const msgsEl = document.getElementById('chat-messages');
  // 清除初始占位
  const empty = msgsEl.querySelector('.empty');
  if (empty) empty.remove();

  const isUser = role === 'user';
  const bubble = document.createElement('div');
  bubble.style.cssText = `
    max-width:75%;padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.6;
    align-self:${isUser ? 'flex-end' : 'flex-start'};
    background:${isUser ? 'rgba(124,106,255,.2)' : 'var(--border)'};
    white-space:pre-wrap;word-break:break-word;
  `;
  bubble.textContent = text;
  msgsEl.appendChild(bubble);
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

// ══════════════════════════════════════════════════════════
//  调度器页面
// ══════════════════════════════════════════════════════════

const SC_TRIGGER_LABELS = {
  morning_greeting: '早安问候',
  night_reminder:   '晚安催睡',
  random_message:   '随机日间消息',
  hr_high:          '心率偏高(>100)',
  hr_critical:      '心率危急(>120)',
  sleep_end:        '睡眠结束',
  weather_alert:    '天气提醒',
  period_reminder:  '生理期关心',
  diary_reminder:   '日记缺失提醒',
  diary_inject:     '日记内容注入',
  daily_journal:        '每日手账',
  diary_share_reminder: '日记分享提醒',
};

async function loadProactiveLedger() {
  const el = document.getElementById('sc-ledger-body');
  if (!el) return;
  try {
    const d = await api('GET', '/scheduler/proactive-ledger');
    const gapH = (d.effective_gap_seconds / 3600).toFixed(2);
    const nextIn = d.next_allowed_in_seconds > 0 ? _fmtSec(d.next_allowed_in_seconds) : '现在可发';
    const budgetPct = d.daily_budget ? Math.round(100 * d.daily_count / d.daily_budget) : 0;
    const recentRows = (d.recent || []).slice().reverse().map(r => {
      const ts = r.ts ? new Date(r.ts * 1000).toLocaleTimeString() : '';
      return `<tr>
        <td style="color:var(--muted);font-size:12px">${ts}</td>
        <td>${escapeHtml(r.trigger_name || '')}</td>
        <td style="color:var(--muted)">${escapeHtml(r.gist || '')}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `
      <table style="width:100%;font-size:13px;border-collapse:collapse;margin-bottom:8px">
        <tr>
          <td style="padding:6px 0;color:var(--muted);width:140px">生效全局间隔</td>
          <td style="font-weight:600">${gapH} 小时</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:var(--muted)">下次可发</td>
          <td style="font-weight:600">${nextIn}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:var(--muted)">今日已发 / 预算</td>
          <td style="font-weight:600">${d.daily_count} / ${d.daily_budget}（${d.daily_logical_day || ''}）</td>
        </tr>
      </table>
      <div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:12px">
        <div style="height:100%;background:var(--accent);border-radius:2px;width:${Math.max(0,Math.min(100,budgetPct))}%"></div>
      </div>
      <div class="tbl-wrap"><table>
        <tr><th>时间</th><th>触发器</th><th>内容摘要</th></tr>
        ${recentRows || '<tr><td colspan="3" class="empty">暂无记录</td></tr>'}
      </table></div>`;
  } catch(e) {
    el.innerHTML = `<div class="empty">加载失败: ${escapeHtml(e.message)}</div>`;
  }
}

const SC_BOOL_FIELDS = ['enabled','morning_greeting','night_reminder','random_message','daily_journal','period_reminder','diary_reminder','diary_inject','presence_nag'];

async function loadProvenance() {
  const el = document.getElementById('prov-content');
  if (!el) return;

  // populate uid dropdown once
  const uidSel = document.getElementById('prov-uid');
  if (uidSel && !uidSel.options.length) {
    try {
      const d = await api('GET', '/users');
      (d.users || []).forEach(u => {
        const o = document.createElement('option');
        o.value = o.textContent = u;
        uidSel.appendChild(o);
      });
    } catch(e) { /* non-fatal */ }
  }

  const uid = uidSel ? uidSel.value : '';
  if (!uid) { el.innerHTML = '<div class="empty">请先选择 uid</div>'; return; }

  const artifact = (document.getElementById('prov-artifact')||{}).value || '';
  const field    = (document.getElementById('prov-field')||{}).value || '';
  const scope    = (document.getElementById('prov-scope')||{}).checked ? 'yexuan_self' : '';

  el.innerHTML = '<div style="color:var(--muted)">加载中…</div>';
  try {
    const params = new URLSearchParams({ limit: 100 });
    if (artifact) params.set('artifact', artifact);
    if (field)    params.set('field', field);
    if (scope)    params.set('scope', scope);
    const d = await api('GET', `/provenance/${encodeURIComponent(uid)}?${params}`);
    const records = d.records || [];
    if (!records.length) {
      el.innerHTML = '<div class="empty">该 uid 暂无溯源记录（日志从接入当日起前向积累）</div>';
      return;
    }
    let html = '';
    records.forEach((r, i) => {
      const ts = r.ts ? new Date(r.ts * 1000).toLocaleString('zh-CN') : '—';
      const artBadge = r.artifact ? `<span style="background:var(--bg-secondary);padding:1px 6px;border-radius:8px;font-size:11px">${escapeHtml(r.artifact)}</span>` : '';
      const fldBadge = r.field ? `<span style="background:var(--bg-secondary);padding:1px 6px;border-radius:8px;font-size:11px">${escapeHtml(r.field)}</span>` : '';
      const trigger  = r.trigger_signal ? `<span style="font-size:11px;color:var(--muted)">${escapeHtml(r.trigger_signal)}</span>` : '';
      const before = r.before_gist ? escapeHtml(r.before_gist) : '<em style="color:var(--muted)">（无）</em>';
      const after  = r.after_gist  ? escapeHtml(r.after_gist)  : '<em style="color:var(--muted)">（无）</em>';
      const originId = `prov-origin-${i}`;
      const originJson = JSON.stringify(r.origin || {}, null, 2);
      html += `<div class="card" style="margin-bottom:10px;padding:12px 14px">
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
          <span style="font-size:12px;color:var(--muted)">${ts}</span>
          ${artBadge}${fldBadge}${trigger}
        </div>
        <div style="font-size:12px;margin-bottom:6px">
          <span style="color:#9ca3af">改动前：</span><span style="color:#fca5a5">${before}</span>
          <span style="margin:0 8px;color:var(--muted)">→</span>
          <span style="color:#86efac">${after}</span>
        </div>
        <div style="font-size:12px">
          <span style="cursor:pointer;color:var(--muted)" onclick="togglePromptLayer('${originId}')">▶ 来源聊天（origin）</span>
          <div id="${originId}" style="display:none;margin-top:6px">
            <pre style="font-size:11px;white-space:pre-wrap;word-break:break-all;background:var(--bg-secondary);padding:8px;border-radius:4px;max-height:160px;overflow:auto">${escapeHtml(originJson)}</pre>
          </div>
        </div>
      </div>`;
    });
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div style="color:#ef4444">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

// ══════════════════════════════════════════════════════════
//  向量库（observe-vector）
// ══════════════════════════════════════════════════════════
async function _vecEnsureUids() {
  const sel = document.getElementById('vec-uid');
  if (!sel || sel.options.length) return;
  try {
    const d = await api('GET', '/users');
    (d.users || []).forEach(u => {
      const o = document.createElement('option');
      o.value = o.textContent = u;
      sel.appendChild(o);
    });
  } catch(e) { /* non-fatal */ }
}

async function loadVector() {
  await _vecEnsureUids();
  const uid = (document.getElementById('vec-uid')||{}).value || '';
  if (!uid) return;
  const source  = (document.getElementById('vec-source')||{}).value || '';
  const statsEl = document.getElementById('vec-stats');
  const contEl  = document.getElementById('vec-content');
  if (statsEl) statsEl.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  if (contEl)  contEl.innerHTML  = '';
  try {
    const params = new URLSearchParams({ limit: 100 });
    if (source) params.set('source', source);
    const d = await api('GET', `/observe/vector/${encodeURIComponent(uid)}?${params}`);
    const st = d.stats || {};
    const by = st.by_source || {};

    // update source dropdown
    const srcSel = document.getElementById('vec-source');
    if (srcSel) {
      const cur = srcSel.value;
      srcSel.innerHTML = '<option value="">全部 source</option>';
      Object.keys(by).forEach(k => {
        const o = document.createElement('option');
        o.value = o.textContent = k;
        srcSel.appendChild(o);
      });
      if (cur) srcSel.value = cur;
    }

    // stats bar
    const badges = Object.entries(by).map(([k,v]) =>
      `<span style="background:var(--bg-secondary);padding:2px 8px;border-radius:8px;font-size:11px">${escapeHtml(k)} ${v}</span>`
    ).join(' ');
    if (statsEl) statsEl.innerHTML =
      `<span style="font-size:13px">总条数 <strong>${st.total||0}</strong> · 维度 <strong>${st.dim||'—'}</strong></span> ${badges}`;

    // entries list
    const entries = d.entries || [];
    if (!entries.length) {
      if (contEl) contEl.innerHTML = '<div class="empty">暂无条目</div>';
      return;
    }
    let html = '';
    entries.forEach((e, i) => {
      const ts = e.ts ? new Date(e.ts * 1000).toLocaleString('zh-CN') : '—';
      const prevId = `vec-prev-${i}`;
      const preview = e.text_preview || '';
      html += `<div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:12px">
        <span style="background:var(--bg-secondary);padding:1px 6px;border-radius:6px;margin-right:6px">${escapeHtml(e.source||'—')}</span>
        <code style="font-size:11px">${escapeHtml((e.source_id||'').slice(0,60))}</code>
        <span style="color:var(--muted);margin-left:8px">${ts}</span>
        ${preview.length > 80
          ? `<div style="cursor:pointer;color:var(--muted);margin-top:4px" onclick="togglePromptLayer('${prevId}')">▶ 预览</div>
             <div id="${prevId}" style="display:none"><pre style="font-size:11px;white-space:pre-wrap;word-break:break-all;background:var(--bg-secondary);padding:6px;border-radius:4px;margin-top:4px;max-height:120px;overflow:auto">${escapeHtml(preview)}</pre></div>`
          : preview ? `<div style="color:var(--muted);margin-top:2px">${escapeHtml(preview)}</div>` : ''
        }
      </div>`;
    });
    if (contEl) contEl.innerHTML = html;
  } catch(e) {
    if (statsEl) statsEl.innerHTML = '';
    if (contEl)  contEl.innerHTML = `<div style="color:#ef4444">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

async function searchVector() {
  await _vecEnsureUids();
  const uid = (document.getElementById('vec-uid')||{}).value || '';
  const q   = (document.getElementById('vec-q')||{}).value || '';
  const src = (document.getElementById('vec-source')||{}).value || '';
  const el  = document.getElementById('vec-content');
  if (!el) return;
  if (!uid || !q.trim()) { el.innerHTML = '<div class="empty">请选择 uid 并输入检索词</div>'; return; }
  el.innerHTML = '<div style="color:var(--muted)">检索中…</div>';
  try {
    const params = new URLSearchParams({ q, k: 8 });
    if (src) params.set('source', src);
    const d = await api('GET', `/observe/vector/${encodeURIComponent(uid)}/search?${params}`);
    if (d.error === 'embed_failed') {
      el.innerHTML = '<div style="color:#ef4444">嵌入模型未配置或调用失败</div>'; return;
    }
    const results = d.results || [];
    if (!results.length) { el.innerHTML = '<div class="empty">无匹配结果</div>'; return; }
    let html = '';
    results.forEach((r, i) => {
      const sim = ((r.similarity||0)*100).toFixed(1);
      html += `<div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:12px">
        <span style="background:#1a3a1a;color:#86efac;padding:1px 8px;border-radius:8px;font-size:11px">${sim}%</span>
        <code style="margin-left:8px;font-size:11px">${escapeHtml((r.source_id||'').slice(0,60))}</code>
        ${r.preview ? `<div style="color:var(--muted);margin-top:4px;font-size:11px">${escapeHtml((r.preview||'').slice(0,200))}${(r.preview||'').length>200?'…':''}</div>` : ''}
      </div>`;
    });
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div style="color:#ef4444">检索失败：${escapeHtml(e.message)}</div>`;
  }
}
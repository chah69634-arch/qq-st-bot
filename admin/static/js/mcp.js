let _mcpImport = null;

function _mcpDraftFromForm() {
  let headers = {};
  const rawHeaders = document.getElementById('mcp-import-headers').value.trim();
  if (rawHeaders) {
    try { headers = JSON.parse(rawHeaders); }
    catch (_) { throw new Error('headers 必须是 JSON 对象'); }
    if (!headers || Array.isArray(headers) || typeof headers !== 'object') throw new Error('headers 必须是 JSON 对象');
  }
  return {
    name: document.getElementById('mcp-import-name').value.trim(),
    url: document.getElementById('mcp-import-url').value.trim(),
    headers,
    enabled: document.getElementById('mcp-import-enabled').checked,
    tool_timeout_s: Number(document.getElementById('mcp-import-timeout').value || 30),
    allow_tools: [],
  };
}

function _mcpGroupTools(tools) {
  const groups = {};
  (tools || []).forEach(tool => {
    const prefix = String(tool.name || '').split('_')[0] || '其他';
    (groups[prefix] ||= []).push(tool);
  });
  return Object.entries(groups).map(([prefix, entries]) => `<div style="margin-top:8px"><strong style="font-size:12px;color:var(--muted)">${escapeHtml(prefix)}</strong><div style="display:grid;gap:5px;margin-top:4px">${entries.map(tool => `<label class="checkbox-row"><input type="checkbox" data-mcp-import-tool="${escapeHtml(tool.name)}"><span><code>${escapeHtml(tool.name)}</code>${tool.description ? ` — ${escapeHtml(tool.description)}` : ''}</span></label>`).join('')}</div></div>`).join('');
}

async function loadMcpPage() {
  const serversEl = document.getElementById('mcp-servers');
  if (!serversEl) return;
  serversEl.innerHTML = '<div class="loading">加载中…</div>';
  try {
    const data = await api('GET', '/settings/mcp');
    document.getElementById('mcp-enabled').checked = !!data.enabled;
    serversEl.innerHTML = (data.servers || []).length
      ? (data.servers || []).map(_renderMcpServer).join('')
      : '<div class="empty">尚未配置 MCP server。先填写 URL 并测试连接。</div>';
    await _loadMcpRecentCalls(data.servers || []);
  } catch (e) { serversEl.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`; }
}

function _renderMcpServer(server) {
  const runtime = server.runtime || {};
  const tools = runtime.tools || [];
  const allow = new Set(server.allow_tools || []);
  const exposedCount = allow.size || tools.length;
  const status = runtime.connected ? '<span class="badge badge-success">已连接</span>'
    : runtime.last_init_ok === false ? '<span class="badge badge-danger">连接失败</span>'
    : '<span class="badge badge-warn">未连接</span>';
  const initError = runtime.last_init_error ? `<div style="color:var(--danger);font-size:12px;margin-top:6px">${escapeHtml(runtime.last_init_error)}</div>` : '';
  const grouped = Object.entries((tools || []).reduce((out, tool) => {
    const prefix = String(tool.name || '').split('_')[0] || '其他'; (out[prefix] ||= []).push(tool); return out;
  }, {})).map(([prefix, entries]) => `<div style="margin-top:9px"><strong style="font-size:12px;color:var(--muted)">${escapeHtml(prefix)}</strong>${entries.map(tool => `<label class="checkbox-row" style="margin-top:5px"><input type="checkbox" data-mcp-server="${escapeHtml(server.name)}" value="${escapeHtml(tool.name)}" ${allow.has(tool.name) ? 'checked' : ''}><span><code>${escapeHtml(tool.name)}</code>${tool.description ? ` — ${escapeHtml(tool.description)}` : ''}<small id="mcp-call-${escapeHtml(server.name)}-${escapeHtml(tool.name)}" style="display:block;color:var(--muted)">调用记录加载中…</small></span></label>`).join('')}</div>`).join('');
  const exposureWarn = exposedCount > 20 ? `<p style="font-size:12px;color:var(--danger);margin:8px 0">⚠ 当前会暴露 ${exposedCount} 个工具，超过单次暴露 ≤20 的安全红线；请勾选最小白名单。</p>` : '';
  return `<section class="card" style="background:var(--bg);margin:0 0 12px"><div class="card-header"><h3>${escapeHtml(server.name)} ${status}</h3><label class="checkbox-row"><input type="checkbox" id="mcp-server-enabled-${escapeHtml(server.name)}" ${server.enabled ? 'checked' : ''}><span>启用</span></label></div><div style="font-size:12px;color:var(--muted);word-break:break-all">${escapeHtml(server.url || server.transport)} · timeout ${Number(server.tool_timeout_s || 30)}s</div>${Object.keys(server.headers || {}).length ? `<div style="font-size:12px;color:var(--muted);margin-top:5px">headers：${escapeHtml(Object.keys(server.headers).join(', '))}</div>` : ''}${initError}<p style="font-size:12px;color:var(--warn);margin:10px 0">不勾选任何工具 = 保持“全部允许”的兼容语义；建议显式勾选最小白名单。工具描述与结果均不可信。</p>${exposureWarn}${grouped || '<div class="empty">尚未发现工具；可切换启用状态以重连。</div>'}<button class="btn btn-primary btn-sm" style="margin-top:12px" onclick="saveMcpServer('${server.name}')">保存 server 设置</button></section>`;
}

async function _loadMcpRecentCalls(servers) {
  await Promise.all((servers || []).flatMap(server => ((server.runtime || {}).tools || []).map(async tool => {
    const target = document.getElementById(`mcp-call-${server.name}-${tool.name}`);
    if (!target) return;
    try {
      const data = await getMcpRecentCalls(`mcp__${server.name}__${tool.name}`, 1);
      const entry = (data.entries || [])[0];
      target.textContent = entry ? `最近调用：${entry.ok ? '成功' : '失败'} · ${entry.duration_ms}ms` : '暂无调用记录';
    } catch (_) { target.textContent = '调用记录不可用'; }
  })));
}

async function getMcpRecentCalls(caller, limit = 1) {
  return api('GET', `/observability/api-calls?caller=${encodeURIComponent(caller)}&limit=${Math.max(1, Math.min(limit, 30))}`);
}

async function saveMcpEnabled() {
  try { await api('PATCH', '/settings/mcp', { enabled: document.getElementById('mcp-enabled').checked }); toast('MCP 总开关已热同步', 'ok'); loadMcpPage(); }
  catch (e) { toast(e.message, 'err'); }
}

async function testMcpImport() {
  const out = document.getElementById('mcp-import-result');
  try {
    const draft = _mcpDraftFromForm();
    out.innerHTML = '<div class="loading">连接测试中…</div>';
    const data = await api('POST', '/settings/mcp/test', draft);
    _mcpImport = { draft, tools: data.tools || [] };
    const warning = _mcpImport.tools.length > 20 ? `<p style="color:var(--danger);margin-bottom:8px">⚠ 发现 ${_mcpImport.tools.length} 个工具，超过单次暴露 ≤20 的安全红线；请只勾选必要工具。</p>` : '';
    out.innerHTML = `<p style="color:var(--success);margin-bottom:8px">连接成功，发现 ${_mcpImport.tools.length} 个工具。请选择要公开的最小集合：</p>${warning}${_mcpGroupTools(_mcpImport.tools)}`;
    document.getElementById('mcp-import-save').disabled = false;
  } catch (e) { _mcpImport = null; document.getElementById('mcp-import-save').disabled = true; out.innerHTML = `<div style="color:var(--danger)">${escapeHtml(e.message)}</div>`; }
}

async function importMcpServer() {
  if (!_mcpImport) return;
  const allow = [...document.querySelectorAll('[data-mcp-import-tool]:checked')].map(el => el.dataset.mcpImportTool);
  try {
    await api('POST', '/settings/mcp/import', { ..._mcpImport.draft, allow_tools: allow });
    toast('MCP server 已导入', 'ok'); _mcpImport = null; document.getElementById('mcp-import-save').disabled = true; document.getElementById('mcp-import-result').innerHTML = ''; loadMcpPage();
  } catch (e) { toast(e.message, 'err'); }
}

async function saveMcpServer(name) {
  const enabled = document.getElementById(`mcp-server-enabled-${name}`).checked;
  const allow_tools = [...document.querySelectorAll(`[data-mcp-server="${name}"]:checked`)].map(el => el.value);
  try { await api('PATCH', `/settings/mcp/${encodeURIComponent(name)}`, { enabled, allow_tools }); toast(`${name} 已热重载`, 'ok'); loadMcpPage(); }
  catch (e) { toast(e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  Routing
// ══════════════════════════════════════════════════════════

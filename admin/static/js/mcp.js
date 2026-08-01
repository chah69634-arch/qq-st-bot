let _mcpImport = null;
let _mcpConsoleData = null;
let _mcpConsolePending = null;
const MCP_EXPANDED_SERVERS_STORAGE_KEY = 'qq_admin_mcp_expanded_servers_v1';

function _loadMcpExpandedServers() {
  try {
    const saved = JSON.parse(localStorage.getItem(MCP_EXPANDED_SERVERS_STORAGE_KEY) || '[]');
    return new Set(Array.isArray(saved) ? saved.filter(name => typeof name === 'string') : []);
  } catch (_) {
    return new Set();
  }
}

function _persistMcpExpandedServers() {
  try {
    localStorage.setItem(MCP_EXPANDED_SERVERS_STORAGE_KEY, JSON.stringify([..._mcpExpandedServers]));
  } catch (_) { /* 私密模式或受限存储时仍保持默认收起。 */ }
}

// 没有已保存状态的 server 默认收起。
const _mcpExpandedServers = _loadMcpExpandedServers();

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
    transport: document.getElementById('mcp-import-transport').value,
    use_proxy: document.getElementById('mcp-import-use-proxy').checked,
    headers,
    enabled: document.getElementById('mcp-import-enabled').checked,
    tool_timeout_s: Number(document.getElementById('mcp-import-timeout').value || 30),
    allow_tools: [],
  };
}

function _mcpSuggestion(tool) {
  return tool?.suggestion || { effect: null, source: 'unknown', status: 'confirmation_required', high_risk: false };
}

function _mcpEffectBadge(suggestion, policyStatus = '') {
  const effect = suggestion.effect || '待确认';
  const source = suggestion.source === 'name_description' ? '名称/描述建议' : suggestion.source || '待确认';
  const risk = suggestion.high_risk ? ' 高风险' : '';
  const pending = policyStatus && policyStatus !== 'confirmed' && policyStatus !== 'legacy_allowed'
    ? ' 待确认' : '';
  return `<small style="display:block;color:${suggestion.high_risk ? 'var(--danger)' : 'var(--muted)'}">建议 ${escapeHtml(effect)} · ${escapeHtml(source)}${risk}${pending}</small>`;
}

function _mcpGroupTools(tools) {
  const groups = {};
  (tools || []).forEach(tool => {
    const prefix = String(tool.name || '').split('_')[0] || '其他';
    (groups[prefix] ||= []).push(tool);
  });
  return Object.entries(groups).map(([prefix, entries]) => `<div style="margin-top:8px"><strong style="font-size:12px;color:var(--muted)">${escapeHtml(prefix)}</strong><div style="display:grid;gap:5px;margin-top:4px">${entries.map(tool => `<label class="checkbox-row"><input type="checkbox" data-mcp-import-tool="${escapeHtml(tool.name)}"><span><code>${escapeHtml(tool.name)}</code>${tool.description ? ` — ${escapeHtml(tool.description)}` : ''}${_mcpEffectBadge(_mcpSuggestion(tool))}</span></label>`).join('')}</div></div>`).join('');
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
    bindPageActions(serversEl);
    _moveMcpSaveControls(serversEl);
    _setMcpConsoleData(data);
    await _loadMcpRecentCalls(data.servers || []);
    await loadMcpDebugRequests();
  } catch (e) { serversEl.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`; }
}

function _mcpConsoleEligibleTools(server) {
  if (!server?.enabled || !server?.runtime?.connected) return [];
  return (server.tool_states || []).filter(tool => tool.allowlisted && tool.registered
    && (tool.policy_status === 'confirmed' || tool.policy_status === 'legacy_allowed'));
}

function _setMcpConsoleData(data) {
  _mcpConsoleData = data || null;
  _mcpConsolePending = null;
  const serverSelect = document.getElementById('mcp-console-server');
  if (!serverSelect) return;
  const servers = (_mcpConsoleData?.servers || []).filter(server => server.enabled && server.runtime?.connected);
  const selected = servers.some(server => server.name === serverSelect.value) ? serverSelect.value : (servers[0]?.name || '');
  serverSelect.innerHTML = servers.length
    ? servers.map(server => `<option value="${escapeHtml(server.name)}">${escapeHtml(server.name)}</option>`).join('')
    : `<option value="">${escapeHtml(t('mcp.console.no_server', '没有可用的已连接 MCP server。'))}</option>`;
  serverSelect.value = selected;
  _renderMcpConsoleTool();
  bindPageActions(document.getElementById('mcp-console-card'));
}

function _selectedMcpConsoleTool() {
  const serverName = document.getElementById('mcp-console-server')?.value || '';
  const toolName = document.getElementById('mcp-console-tool')?.value || '';
  const server = (_mcpConsoleData?.servers || []).find(item => item.name === serverName);
  return { server, tool: _mcpConsoleEligibleTools(server).find(item => item.name === toolName) };
}

function _renderMcpConsoleTool() {
  const serverSelect = document.getElementById('mcp-console-server');
  const toolSelect = document.getElementById('mcp-console-tool');
  const info = document.getElementById('mcp-console-tool-info');
  const schema = document.getElementById('mcp-console-schema');
  const invoke = document.getElementById('mcp-console-invoke');
  if (!serverSelect || !toolSelect || !info || !schema || !invoke) return;
  const server = (_mcpConsoleData?.servers || []).find(item => item.name === serverSelect.value);
  const tools = _mcpConsoleEligibleTools(server);
  const selected = tools.some(tool => tool.name === toolSelect.value) ? toolSelect.value : (tools[0]?.name || '');
  toolSelect.innerHTML = tools.length
    ? tools.map(tool => `<option value="${escapeHtml(tool.name)}">${escapeHtml(tool.name)}</option>`).join('')
    : `<option value="">${escapeHtml(t('mcp.console.no_tool', '该 server 没有可调用工具。'))}</option>`;
  toolSelect.value = selected;
  const tool = tools.find(item => item.name === selected);
  info.textContent = tool
    ? `${tool.description || t('mcp.console.no_description', '未提供工具说明')}\n` +
      `effect: ${tool.effect || 'unclassified'}${tool.require_confirm ? ' · confirmation required' : ''}`
    : t('mcp.console.no_tool', '该 server 没有可调用工具。');
  schema.textContent = JSON.stringify(tool?.input_schema || {}, null, 2);
  invoke.disabled = !_mcpConsoleData?.enabled || !tool;
}

function changeMcpConsoleServer() {
  _mcpConsolePending = null;
  _renderMcpConsoleTool();
  clearMcpConsole();
}

function changeMcpConsoleTool() {
  _mcpConsolePending = null;
  clearMcpConsole();
  _renderMcpConsoleTool();
}

function _showMcpConsoleResult(text) {
  document.getElementById('mcp-console-result').textContent = text || '';
}

function clearMcpConsole() {
  _mcpConsolePending = null;
  document.getElementById('mcp-console-confirmation').hidden = true;
  document.getElementById('mcp-console-confirm-message').textContent = '';
  _showMcpConsoleResult('');
}

async function refreshMcpConsole() {
  try {
    _setMcpConsoleData(await api('GET', '/settings/mcp'));
    toast(t('mcp.console.refreshed', 'MCP 工具状态已刷新'), 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function invokeMcpConsole() {
  const { server, tool } = _selectedMcpConsoleTool();
  if (!server || !tool) return;
  let arguments_;
  try {
    arguments_ = JSON.parse(document.getElementById('mcp-console-arguments').value || '{}');
    if (!arguments_ || Array.isArray(arguments_) || typeof arguments_ !== 'object') throw new Error(t('mcp.console.arguments_object', '参数必须是 JSON 对象'));
  } catch (e) {
    _showMcpConsoleResult(`${t('mcp.console.arguments_error', '参数 JSON 无效：')}${e.message}`);
    return;
  }
  clearMcpConsole();
  try {
    const result = await api('POST', '/settings/mcp/console/invoke', { server: server.name, tool: tool.name, arguments: arguments_ });
    if (result.status === 'confirmation_required') {
      _mcpConsolePending = result;
      document.getElementById('mcp-console-confirm-message').textContent = result.confirmation_message || '';
      document.getElementById('mcp-console-confirmation').hidden = false;
      _showMcpConsoleResult(`audit_id: ${result.audit_id}`);
      return;
    }
    _showMcpConsoleResult(`audit_id: ${result.audit_id}\n\n${result.result || t('mcp.console.no_result', '调用完成，无文本结果。')}`);
  } catch (e) { _showMcpConsoleResult(`${t('mcp.console.invoke_error', '调用被拒绝或失败：')}${e.message}`); }
}

async function confirmMcpConsole() {
  if (!_mcpConsolePending?.confirmation_id) return;
  const confirmationId = _mcpConsolePending.confirmation_id;
  clearMcpConsole();
  try {
    const result = await api('POST', '/settings/mcp/console/confirm', { confirmation_id: confirmationId });
    _showMcpConsoleResult(`audit_id: ${result.audit_id}\n\n${result.result || t('mcp.console.no_result', '调用完成，无文本结果。')}`);
  } catch (e) { _showMcpConsoleResult(`${t('mcp.console.confirm_error', '确认调用失败：')}${e.message}`); }
}

function _moveMcpSaveControls(root) {
  root.querySelectorAll('[data-action="saveMcpServer"]').forEach(button => {
    const header = button.closest('section')?.querySelector('.card-header');
    const enabledControl = header?.querySelector('[id^="mcp-server-enabled-"]')?.closest('label');
    if (!header || !enabledControl) return;
    button.style.margin = '0 5px 0 auto';
    enabledControl.before(button);
  });
}

async function loadMcpDebugRequests() {
  const out = document.getElementById('mcp-llm-debug-entries');
  if (!out) return;
  try {
    const [settings, snapshots] = await Promise.all([
      api('GET', '/llm-debug-requests'),
      api('GET', '/observability/llm-debug-requests?limit=10'),
    ]);
    document.getElementById('mcp-llm-debug-enabled').checked = !!settings.enabled;
    document.getElementById('mcp-llm-debug-keep-days').value = String(settings.keep_days || 1);
    out.textContent = (snapshots.entries || []).length
      ? (snapshots.entries || []).map(entry => JSON.stringify(entry, null, 2)).join('\n\n')
      : t('mcp.llm_debug.empty', '暂无请求快照。开启后完成一次模型调用，再刷新此处。');
  } catch (e) {
    out.textContent = t('mcp.llm_debug.load_error', '读取调试快照失败: {error}', { error: e.message });
  }
}

async function saveMcpDebugRequests() {
  try {
    const keep_days = Number(document.getElementById('mcp-llm-debug-keep-days').value || 1);
    await api('PUT', '/llm-debug-requests', {
      enabled: document.getElementById('mcp-llm-debug-enabled').checked,
      keep_days,
    });
    toast(t('mcp.llm_debug.saved', 'LLM 请求调试设置已保存'), 'ok');
    await loadMcpDebugRequests();
  } catch (e) { toast(t('mcp.llm_debug.save_error', '保存调试设置失败: {error}', { error: e.message }), 'err'); }
}

async function clearMcpDebugRequests() {
  if (!confirm(t('mcp.llm_debug.clear_confirm', '确定清理所有 LLM 请求调试快照吗？此操作不可恢复。'))) return;
  try {
    await api('DELETE', '/observability/llm-debug-requests');
    toast(t('mcp.llm_debug.cleared', 'LLM 请求调试快照已清理'), 'ok');
    await loadMcpDebugRequests();
  } catch (e) { toast(t('mcp.llm_debug.clear_error', '清理调试快照失败: {error}', { error: e.message }), 'err'); }
}

function _mcpServerTools(name) {
  return [...document.querySelectorAll(`[data-mcp-server="${name}"]:checked`)].map(el => el.value);
}

function _mcpPresetButtons(server) {
  const active = server.active_tool_preset || '';
  const args = escapeHtml(JSON.stringify([server.name, '']));
  const custom = `<button class="btn btn-ghost btn-sm" data-action="selectMcpToolPreset" data-action-args="${args}">${escapeHtml(t('mcp.preset.custom', '自定义'))}</button>`;
  const presets = (server.tool_presets || []).map(preset => {
    const actionArgs = escapeHtml(JSON.stringify([server.name, preset.name]));
    const klass = preset.name === active ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
    return `<button class="${klass}" data-action="selectMcpToolPreset" data-action-args="${actionArgs}">${escapeHtml(preset.name)}</button>`;
  }).join('');
  return `<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span style="font-size:12px;color:var(--muted)">${escapeHtml(t('mcp.preset.selected', '工具预设'))}</span>${custom}${presets || `<span style="font-size:12px;color:var(--muted)">${escapeHtml(t('mcp.preset.none', '还没有预设'))}</span>`}</div>`;
}

function _mcpPolicyControl(server, tool, allowlisted) {
  const state = (server.tool_states || []).find(item => item.name === tool.name) || {};
  const suggestion = state.suggestion || _mcpSuggestion(tool);
  const badge = _mcpEffectBadge(suggestion, state.policy_status || '');
  if (!allowlisted) return badge;
  const selected = state.policy?.effect || state.effect || suggestion.effect || 'write';
  const options = ['read', 'write', 'actuate', 'emergency'].map(effect =>
    `<option value="${effect}" ${effect === selected ? 'selected' : ''}>${effect}</option>`
  ).join('');
  const args = escapeHtml(JSON.stringify([server.name, tool.name]));
  const selectId = `mcp-policy-effect-${server.name}-${tool.name}`;
  return `${badge}<span style="display:flex;gap:6px;align-items:center;margin-top:4px"><span style="font-size:12px;color:var(--muted)">${escapeHtml(t('mcp.policy.mode', '模式'))}</span><select id="${escapeHtml(selectId)}" style="max-width:116px">${options}</select><button class="btn btn-ghost btn-sm" data-action="saveMcpToolPolicy" data-action-args="${args}">${escapeHtml(t('mcp.policy.save_mode', '保存模式'))}</button></span>`;
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
  }, {})).map(([prefix, entries]) => `<div style="margin-top:9px"><strong style="font-size:12px;color:var(--muted)">${escapeHtml(prefix)}</strong>${entries.map(tool => `<label class="checkbox-row" style="margin-top:5px"><input type="checkbox" data-mcp-server="${escapeHtml(server.name)}" value="${escapeHtml(tool.name)}" ${allow.has(tool.name) ? 'checked' : ''}><span><code>${escapeHtml(tool.name)}</code>${tool.description ? ` — ${escapeHtml(tool.description)}` : ''}${_mcpPolicyControl(server, tool, allow.has(tool.name))}<small id="mcp-call-${escapeHtml(server.name)}-${escapeHtml(tool.name)}" style="display:block;color:var(--muted)">调用记录加载中…</small></span></label>`).join('')}</div>`).join('');
  const exposureWarn = exposedCount > 20 ? `<p style="font-size:12px;color:var(--danger);margin:8px 0">⚠ 当前会暴露 ${exposedCount} 个工具，超过单次暴露 ≤20 的安全红线；请勾选最小白名单。</p>` : '';
  const actionArgs = escapeHtml(JSON.stringify([server.name]));
  const collapsed = !_mcpExpandedServers.has(server.name);
  const collapseArgs = escapeHtml(JSON.stringify([server.name]));
  const saveLabel = escapeHtml(t('mcp.save_server', '设置'));
  const deleteLabel = escapeHtml(t('mcp.delete_server', '删除 server'));
  const proxyControl = server.is_local_url
    ? `<span style="font-size:12px;color:var(--muted)">${escapeHtml(t('mcp.proxy_direct', '本地地址：始终直连'))}</span>`
    : `<label class="checkbox-row" style="margin-top:8px"><input type="checkbox" id="mcp-server-use-proxy-${escapeHtml(server.name)}" ${server.use_proxy ? 'checked' : ''}><span>${escapeHtml(t('mcp.proxy_label', '远程 MCP 使用全局代理'))}</span></label>`;
  const presets = (server.tool_presets || []).map(preset => {
    const editArgs = escapeHtml(JSON.stringify([server.name, preset.name]));
    return `<div style="display:flex;gap:6px;align-items:center;margin-top:5px"><code>${escapeHtml(preset.name)}</code><span style="font-size:12px;color:var(--muted)">${preset.tools.length} ${escapeHtml(t('mcp.preset.tools', '个工具'))}</span><button class="btn btn-ghost btn-sm" data-action="editMcpToolPreset" data-action-args="${editArgs}">${escapeHtml(t('common.edit', '修改'))}</button><button class="btn btn-danger btn-sm" data-action="deleteMcpToolPreset" data-action-args="${editArgs}">${escapeHtml(t('common.delete', '删除'))}</button></div>`;
  }).join('');
  return `<section class="card" data-mcp-presets="${escapeHtml(JSON.stringify(server.tool_presets || []))}" style="background:var(--bg);margin:0 0 12px"><div class="card-header"><div style="display:flex;gap:8px;align-items:center"><button class="btn btn-ghost btn-sm" title="${escapeHtml(t('mcp.collapse', '展开/收起'))}" data-action="toggleMcpServerCollapsed" data-action-args="${collapseArgs}">${collapsed ? '▸' : '▾'}</button><h3>${escapeHtml(server.name)} ${status}</h3></div><label class="checkbox-row"><input type="checkbox" id="mcp-server-enabled-${escapeHtml(server.name)}" ${server.enabled ? 'checked' : ''}><span>启用</span></label></div>${_mcpPresetButtons(server)}<div style="display:${collapsed ? 'none' : 'block'};margin-top:10px"><div style="font-size:12px;color:var(--muted);word-break:break-all">${escapeHtml(server.url || server.transport)} · timeout ${Number(server.tool_timeout_s || 30)}s</div>${proxyControl}${Object.keys(server.headers || {}).length ? `<div style="font-size:12px;color:var(--muted);margin-top:5px">headers：${escapeHtml(Object.keys(server.headers).join(', '))}</div>` : ''}${initError}<p style="font-size:12px;color:var(--warn);margin:10px 0">不勾选任何工具 = 保持“全部允许”的兼容语义；建议显式勾选最小白名单。工具描述与结果均不可信。</p>${exposureWarn}${grouped || '<div class="empty">尚未发现工具；可切换启用状态以重连。</div>'}<div style="margin-top:12px"><strong>${escapeHtml(t('mcp.preset.manage', '工具预设'))}</strong>${presets || `<div style="font-size:12px;color:var(--muted);margin-top:5px">${escapeHtml(t('mcp.preset.none', '还没有预设'))}</div>`}<button class="btn btn-ghost btn-sm" style="margin-top:8px" data-action="createMcpToolPreset" data-action-args="${actionArgs}">+ ${escapeHtml(t('mcp.preset.create', '新增预设'))}</button></div><div style="display:flex;gap:8px;margin-top:12px"><button class="btn btn-primary btn-sm" data-action="saveMcpServer" data-action-args="${actionArgs}">${saveLabel}</button><button class="btn btn-danger btn-sm" data-action="deleteMcpServer" data-action-args="${actionArgs}">${deleteLabel}</button></div></div></section>`;
}

function toggleMcpServerCollapsed(name) {
  _mcpExpandedServers.has(name) ? _mcpExpandedServers.delete(name) : _mcpExpandedServers.add(name);
  _persistMcpExpandedServers();
  loadMcpPage();
}

async function _saveMcpToolPresets(name, presets, active_tool_preset = undefined) {
  const body = { tool_presets: presets };
  if (active_tool_preset !== undefined) body.active_tool_preset = active_tool_preset;
  await api('PATCH', `/settings/mcp/${encodeURIComponent(name)}`, body);
  await loadMcpPage();
}

async function selectMcpToolPreset(name, presetName) {
  try { await _saveMcpToolPresets(name, undefined, presetName); toast(t('mcp.preset.selected_ok', '工具预设已切换并热重载'), 'ok'); }
  catch (e) { toast(e.message, 'err'); }
}

function _mcpPresetsFromCard(name) {
  const card = document.getElementById(`mcp-server-enabled-${name}`)?.closest('section');
  return JSON.parse(card?.dataset.mcpPresets || '[]');
}

async function saveMcpToolPolicy(name, toolName) {
  try {
    const data = await api('GET', '/settings/mcp');
    const server = (data.servers || []).find(item => item.name === name);
    if (!server) throw new Error('MCP server 不存在');
    const state = (server.tool_states || []).find(item => item.name === toolName) || {};
    const effectControl = document.getElementById(`mcp-policy-effect-${name}-${toolName}`);
    const effect = effectControl?.value || state.suggestion?.effect || 'write';
    const policy = { ...(server.tool_policy || {}) };
    policy[toolName] = { ...(state.policy || {}), effect };
    if (state.suggestion?.high_risk && policy[toolName].require_confirm === undefined) {
      policy[toolName].require_confirm = true;
    }
    const result = await api('PATCH', `/settings/mcp/${encodeURIComponent(name)}`, { tool_policy: policy });
    toast(result.reload_status === 'restart_required'
      ? t('mcp.policy.restart_required', '模式已保存，需要重启服务')
      : t('mcp.policy.saved', '工具模式已保存并热重载'), result.reload_status === 'restart_required' ? 'err' : 'ok');
    await loadMcpPage();
  } catch (e) { toast(e.message, 'err'); }
}

async function createMcpToolPreset(name) {
  const presetName = prompt(t('mcp.preset.name_prompt', '请输入预设名称：'))?.trim();
  if (!presetName) return;
  const presets = _mcpPresetsFromCard(name);
  presets.push({ name: presetName, tools: _mcpServerTools(name) });
  try { await _saveMcpToolPresets(name, presets); toast(t('mcp.preset.created', '工具预设已保存'), 'ok'); }
  catch (e) { toast(e.message, 'err'); }
}

async function editMcpToolPreset(name, oldName) {
  const presets = _mcpPresetsFromCard(name);
  const preset = presets.find(item => item.name === oldName);
  if (!preset) return;
  const newName = prompt(t('mcp.preset.rename_prompt', '修改预设名称：'), oldName)?.trim();
  if (!newName) return;
  preset.name = newName;
  preset.tools = _mcpServerTools(name);
  try { await _saveMcpToolPresets(name, presets, newName); toast(t('mcp.preset.updated', '工具预设已更新'), 'ok'); }
  catch (e) { toast(e.message, 'err'); }
}

async function deleteMcpToolPreset(name, presetName) {
  if (!confirm(t('mcp.preset.delete_confirm', '删除工具预设“{name}”？', { name: presetName }))) return;
  const presets = _mcpPresetsFromCard(name).filter(item => item.name !== presetName);
  try { await _saveMcpToolPresets(name, presets, ''); toast(t('mcp.preset.deleted', '工具预设已删除'), 'ok'); }
  catch (e) { toast(e.message, 'err'); }
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
    const result = await api('POST', '/settings/mcp/import', { ..._mcpImport.draft, allow_tools: allow });
    toast(result.reload_status === 'restart_required' ? 'MCP server 已导入，需要重启服务' : 'MCP server 已导入；请选择确认每个工具的策略', result.reload_status === 'restart_required' ? 'err' : 'ok'); _mcpImport = null; document.getElementById('mcp-import-save').disabled = true; document.getElementById('mcp-import-result').innerHTML = ''; loadMcpPage();
  } catch (e) { toast(e.message, 'err'); }
}

async function saveMcpServer(name) {
  const enabled = document.getElementById(`mcp-server-enabled-${name}`).checked;
  const toolInputs = [...document.querySelectorAll(`[data-mcp-server="${name}"]`)];
  const proxyControl = document.getElementById(`mcp-server-use-proxy-${name}`);
  const body = { enabled };
  // A disabled server has no runtime-discovered checkboxes. Do not turn that
  // absence into an empty persisted whitelist when it is being re-enabled.
  if (toolInputs.length) body.allow_tools = toolInputs.filter(el => el.checked).map(el => el.value);
  if (proxyControl) body.use_proxy = proxyControl.checked;
  try { const result = await api('PATCH', `/settings/mcp/${encodeURIComponent(name)}`, body); toast(result.reload_status === 'restart_required' ? `${name} 已保存，需要重启服务` : `${name} 已热重载`, result.reload_status === 'restart_required' ? 'err' : 'ok'); loadMcpPage(); }
  catch (e) { toast(e.message, 'err'); }
}

async function deleteMcpServer(name) {
  const question = t('mcp.delete_confirm', '确定删除 MCP server “{name}”吗？这会立即断开连接并移除它的工具。', { name });
  if (!confirm(question)) return;
  try {
    await api('DELETE', `/settings/mcp/${encodeURIComponent(name)}`);
    toast(t('mcp.delete_success', 'MCP server “{name}”已删除', { name }), 'ok');
    loadMcpPage();
  } catch (e) { toast(e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  Routing
// ══════════════════════════════════════════════════════════

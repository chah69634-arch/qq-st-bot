function _giFmtTime(value) {
  if (!value) return '—';
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

function _giBool(value) {
  return value ? '<span class="badge badge-success">enabled</span>' : '<span class="badge badge-warn">disabled</span>';
}

function refreshGardenTemplate() {
  const target = document.getElementById('gi-template');
  if (!target) return;
  const repoInput = document.getElementById('gi-repo-path');
  const repo = (repoInput?.value || '').trim() || '<PRESENCE_REPO>';
  const injectorPath = `${repo}\\integrations\\galatea_garden\\inject.py`;
  const argsJson = JSON.stringify([injectorPath]);
  const state = window._gardenIntegrationState || {};
  const uid = state.uid || '<当前 uid>';
  const charId = state.char_id || '<当前 char_id>';
  const baseUrl = window.location.origin || '<当前后端地址>';
  target.value = `$env:GARDEN_BASE_URL = "https://galatea.abysslumina.com"
$env:GARDEN_MACHINE_TOKEN = "<请在本地填写>"

$env:GARDEN_INJECTOR_EXECUTABLE = "python"
$env:GARDEN_INJECTOR_ARGS_JSON = '${argsJson}'
$env:GARDEN_INJECTOR_WORKING_DIRECTORY = "${repo}"

$env:PRESENCE_BASE_URL = "${baseUrl}"
$env:PRESENCE_INTEGRATION_TOKEN = "<创建或轮换时复制一次>"
$env:PRESENCE_UID = "${uid}"
$env:PRESENCE_CHAR_ID = "${charId}"`;
}

async function loadGardenIntegrations() {
  const target = document.getElementById('gi-status');
  if (!target) return;
  target.innerHTML = '<div class="loading">加载中…</div>';
  try {
    const payload = await api('GET', '/integrations/garden/status');
    const state = payload.garden || {};
    window._gardenIntegrationState = state;
    target.innerHTML = `<div class="tbl-wrap"><table>
      <tr><th>项目</th><th>状态</th></tr>
      <tr><td>Garden</td><td>${_giBool(state.enabled)}</td></tr>
      <tr><td>bridge</td><td>${escapeHtml(state.bridge_status || 'unknown')}</td></tr>
      <tr><td>machine token（仅本进程环境探测）</td><td>${escapeHtml(state.machine_token || 'missing')}</td></tr>
      <tr><td>Presence integration token</td><td>${escapeHtml(state.integration_token || 'missing')}</td></tr>
      <tr><td>uid / char_id</td><td>${escapeHtml(state.uid || '—')} / ${escapeHtml(state.char_id || '—')}</td></tr>
      <tr><td>last wake received</td><td>${_giFmtTime(state.last_wake_received)}</td></tr>
      <tr><td>last successful drain</td><td>${_giFmtTime(state.last_successful_drain)}</td></tr>
      <tr><td>pending / processing / expired</td><td>${Number(state.pending_count || 0)} / ${Number(state.processing_count || 0)} / ${Number(state.expired_count || 0)}</td></tr>
      <tr><td>consecutive failures</td><td>${Number(state.consecutive_failures || 0)}</td></tr>
      <tr><td>current backoff until</td><td>${_giFmtTime(state.current_backoff_until)}</td></tr>
      <tr><td>scheduler</td><td>${state.scheduler_running ? 'running' : 'not running'}</td></tr>
    </table></div>`;
    refreshGardenTemplate();
  } catch (error) {
    target.innerHTML = `<div class="empty">加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

async function copyGardenTemplate() {
  const target = document.getElementById('gi-template');
  if (!target) return;
  try {
    await navigator.clipboard.writeText(target.value);
    toast('配置模板已复制', 'ok');
  } catch (_) {
    target.focus();
    target.select();
    toast('请手动复制模板', 'warn');
  }
}

async function sendGardenTestWake() {
  if (!window.confirm('提交一条遵守现有 gate 的 Garden 测试提示？它不会强制立即回复。')) return;
  const result = document.getElementById('gi-test-result');
  const button = document.getElementById('gi-test-button');
  if (button) button.disabled = true;
  if (result) result.textContent = '提交中…';
  try {
    const payload = await api('POST', '/integrations/garden/test-wake', {});
    const status = String(payload.status || 'rejected');
    if (result) result.textContent = `结果：${status}`;
    toast(`Garden 测试唤醒：${status}`, status === 'rejected' ? 'warn' : 'ok');
    await loadGardenIntegrations();
  } catch (error) {
    if (result) result.textContent = '提交失败';
    toast(`测试唤醒失败: ${error.message}`, 'err');
  } finally {
    if (button) button.disabled = false;
  }
}

window.refreshGardenTemplate = refreshGardenTemplate;
window.loadGardenIntegrations = loadGardenIntegrations;
window.copyGardenTemplate = copyGardenTemplate;
window.sendGardenTestWake = sendGardenTestWake;

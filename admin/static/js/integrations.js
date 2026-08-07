function _giFmtTime(value) {
  if (!value) return '—';
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

function _giBool(value) {
  const key = value ? 'common.enabled' : 'common.disabled';
  return `<span class="badge ${value ? 'badge-success' : 'badge-warn'}">${escapeHtml(t(key, value ? '已启用' : '未启用'))}</span>`;
}

function refreshGardenTemplate() {
  const target = document.getElementById('gi-template');
  if (!target) return;
  const repoInput = document.getElementById('gi-repo-path');
  const repo = (repoInput?.value || '').trim() || '<PRESENCE_REPO>';
  const injectorPath = `${repo}\\integrations\\galatea_garden\\inject.py`;
  const argsJson = JSON.stringify([injectorPath]);
  const state = window._gardenIntegrationState || {};
  const uid = state.uid || t('integrations.template.current_uid', '<当前 uid>');
  const charId = state.char_id || t('integrations.template.current_char', '<当前 char_id>');
  const baseUrl = window.location.origin || t('integrations.template.current_backend', '<当前后端地址>');
  target.value = `$env:GARDEN_BASE_URL = "https://galatea.abysslumina.com"
$env:GARDEN_MACHINE_TOKEN = "${t('integrations.template.fill_locally', '<请在本地填写>')}"

$env:GARDEN_INJECTOR_EXECUTABLE = "python"
$env:GARDEN_INJECTOR_ARGS_JSON = '${argsJson}'
$env:GARDEN_INJECTOR_WORKING_DIRECTORY = "${repo}"

$env:PRESENCE_BASE_URL = "${baseUrl}"
$env:PRESENCE_INTEGRATION_TOKEN = "${t('integrations.template.copy_once', '<创建或轮换时复制一次>')}"
$env:PRESENCE_UID = "${uid}"
$env:PRESENCE_CHAR_ID = "${charId}"`;
}

async function loadGardenIntegrations() {
  const target = document.getElementById('gi-status');
  if (!target) return;
  target.innerHTML = `<div class="loading">${escapeHtml(t('common.loading', '加载中…'))}</div>`;
  try {
    const payload = await api('GET', '/integrations/garden/status');
    const state = payload.garden || {};
    window._gardenIntegrationState = state;
    target.innerHTML = `<div class="tbl-wrap"><table>
      <tr><th>${escapeHtml(t('integrations.status.item', '项目'))}</th><th>${escapeHtml(t('common.status', '状态'))}</th></tr>
      <tr><td>Garden</td><td>${_giBool(state.enabled)}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.bridge', '中继'))}</td><td>${escapeHtml(state.bridge_status || t('common.unknown', '未知'))}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.machine_token', '机器 token（仅本进程环境探测）'))}</td><td>${escapeHtml(state.machine_token || t('integrations.status.missing', '缺失'))}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.integration_token', 'Presence 集成 token'))}</td><td>${escapeHtml(state.integration_token || t('integrations.status.missing', '缺失'))}</td></tr>
      <tr><td>uid / char_id</td><td>${escapeHtml(state.uid || '—')} / ${escapeHtml(state.char_id || '—')}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.last_wake', '最近收到唤醒'))}</td><td>${_giFmtTime(state.last_wake_received)}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.last_success', '最近成功处理'))}</td><td>${_giFmtTime(state.last_successful_drain)}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.reason_channel', '最近原因 / 通道'))}</td><td>${escapeHtml(state.last_reason || '—')} / ${state.last_reason ? t(state.time_sensitive_lane ? 'integrations.status.time_sensitive' : 'integrations.status.normal_lane', state.time_sensitive_lane ? '时间敏感对话' : '普通对话') : '—'}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.disposition', '最近处理结果'))}</td><td>${escapeHtml(state.last_disposition || '—')}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.attempts', '最近尝试 / 下次尝试'))}</td><td>${_giFmtTime(state.last_attempt_at)} / ${_giFmtTime(state.last_next_attempt_at)}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.queue', '等待 / 处理中 / 已过期'))}</td><td>${Number(state.pending_count || 0)} / ${Number(state.processing_count || 0)} / ${Number(state.expired_count || 0)}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.failures', '连续失败次数'))}</td><td>${Number(state.consecutive_failures || 0)}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.backoff', '当前退避至'))}</td><td>${_giFmtTime(state.current_backoff_until)}</td></tr>
      <tr><td>${escapeHtml(t('integrations.status.scheduler', '调度器'))}</td><td>${escapeHtml(t(state.scheduler_running ? 'integrations.status.running' : 'integrations.status.not_running', state.scheduler_running ? '运行中' : '未运行'))}</td></tr>
    </table></div>`;
    refreshGardenTemplate();
  } catch (error) {
    target.innerHTML = `<div class="empty">${escapeHtml(t('common.load_failed', '加载失败: {error}', {error: error.message}))}</div>`;
  }
}

async function copyGardenTemplate() {
  const target = document.getElementById('gi-template');
  if (!target) return;
  try {
    await navigator.clipboard.writeText(target.value);
    toast(t('integrations.template.copied', '配置模板已复制'), 'ok');
  } catch (_) {
    target.focus();
    target.select();
    toast(t('integrations.template.copy_manual', '请手动复制模板'), 'warn');
  }
}

async function sendGardenTestWake() {
  if (!window.confirm(t('integrations.test.confirm', '提交一条遵守现有门控的 Garden 测试提示？它不会强制立即回复。'))) return;
  const result = document.getElementById('gi-test-result');
  const button = document.getElementById('gi-test-button');
  if (button) button.disabled = true;
  if (result) result.textContent = t('integrations.test.submitting', '提交中…');
  try {
    const payload = await api('POST', '/integrations/garden/test-wake', {});
    const status = String(payload.status || 'rejected');
    const statusLabel = t(`integrations.test.status.${status}`, status);
    if (result) result.textContent = t('integrations.test.result', '结果：{status}', {status: statusLabel});
    toast(t('integrations.test.toast', 'Garden 测试唤醒：{status}', {status: statusLabel}), status === 'rejected' ? 'warn' : 'ok');
    await loadGardenIntegrations();
  } catch (error) {
    if (result) result.textContent = t('integrations.test.failed', '提交失败');
    toast(t('integrations.test.error', '测试唤醒失败: {error}', {error: error.message}), 'err');
  } finally {
    if (button) button.disabled = false;
  }
}

window.refreshGardenTemplate = refreshGardenTemplate;
window.loadGardenIntegrations = loadGardenIntegrations;
window.copyGardenTemplate = copyGardenTemplate;
window.sendGardenTestWake = sendGardenTestWake;

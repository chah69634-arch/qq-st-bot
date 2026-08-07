const _OVERVIEW_FEATURES = [
  'tool_loop', 'mcp', 'self_capability', 'autonomy', 'scheduler',
  'channels', 'model_routing', 'embedding', 'tts', 'hardware_intiface',
];

const _overviewBool = value => value ? t('overview.value.enabled', 'Enabled') : t('overview.value.disabled', 'Disabled');

function _overviewValue(value) {
  if (typeof value === 'boolean') return _overviewBool(value);
  if (value === null || value === undefined || value === '') return '-';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '-';
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}: ${_overviewValue(item)}`).join('; ');
  return String(value);
}

function _overviewSource(source) {
  return t(`overview.source.${source}`, source || '-');
}

function _overviewStatus(status) {
  return t(`overview.status.${status}`, status || '-');
}

function _overviewReload(row) {
  return row.restart_required
    ? t('overview.reload.restart', 'Restart required')
    : t('overview.reload.hot', 'Hot reload');
}

function _overviewFeatureLabel(id) {
  return t(`overview.feature.${id}`, id);
}

function _overviewStateClass(status) {
  if (status === 'enabled') return 'badge-success';
  if (status === 'disabled' || status === 'dormant') return 'badge-danger';
  return 'badge-warn';
}

function _renderOverviewState(payload) {
  const host = document.getElementById('overview-effective-state');
  if (!host) return;
  const rows = (payload.features || []).filter(item => _OVERVIEW_FEATURES.includes(item.id));
  if (!rows.length) {
    host.innerHTML = `<div class="empty">${escapeHtml(t('overview.effective.empty', 'No effective-state data is available.'))}</div>`;
    return;
  }
  host.innerHTML = `<table><thead><tr>
    <th>${escapeHtml(t('overview.table.feature', 'Feature'))}</th>
    <th>${escapeHtml(t('overview.table.default', 'Default'))}</th>
    <th>${escapeHtml(t('overview.table.configured', 'Configured'))}</th>
    <th>${escapeHtml(t('overview.table.effective', 'Effective'))}</th>
    <th>${escapeHtml(t('overview.table.source', 'Source'))}</th>
    <th>${escapeHtml(t('overview.table.runtime', 'Runtime'))}</th>
    <th>${escapeHtml(t('overview.table.reload', 'Apply'))}</th>
    <th>${escapeHtml(t('overview.table.edit', 'Edit'))}</th>
  </tr></thead><tbody>${rows.map(item => {
    const reason = item.blocking_reason || item.explanation || '';
    const edit = item.edit_page && !item.read_only
      ? `<button type="button" class="btn btn-ghost btn-sm" data-action="goto" data-action-args='[${JSON.stringify(item.edit_page)}]'>${escapeHtml(t('overview.edit', 'Open'))}</button>`
      : `<span class="badge">${escapeHtml(t('overview.readonly', 'Read-only'))}</span>`;
    return `<tr>
      <td><strong>${escapeHtml(_overviewFeatureLabel(item.id))}</strong>${item.contradictory ? `<div class="admin-source-hint">${escapeHtml(reason)}</div>` : ''}</td>
      <td>${escapeHtml(_overviewValue(item.default_value))}</td>
      <td>${escapeHtml(_overviewValue(item.configured_value))}</td>
      <td>${escapeHtml(_overviewValue(item.effective_value))}</td>
      <td>${escapeHtml(_overviewSource(item.override_source))}</td>
      <td><span class="badge ${_overviewStateClass(item.runtime_status)}">${escapeHtml(_overviewStatus(item.runtime_status))}</span>${reason && !item.contradictory ? `<div class="admin-source-hint">${escapeHtml(reason)}</div>` : ''}</td>
      <td>${escapeHtml(_overviewReload(item))}</td>
      <td>${edit}</td>
    </tr>`;
  }).join('')}</tbody></table>`;
  bindPageActions(host);
}

async function loadOverview() {
  const host = document.getElementById('overview-effective-state');
  if (!host) return;
  host.innerHTML = `<div class="loading">${escapeHtml(t('common.loading', 'Loading...'))}</div>`;
  try {
    _renderOverviewState(await api('GET', '/admin/control-center/effective-state'));
  } catch (error) {
    host.innerHTML = `<div class="empty">${escapeHtml(t('overview.effective.error', 'Unable to read effective state: {error}', {error: error.message}))}</div>`;
  }
}

(function () {
  'use strict';

  function _opsTime(value) {
    if (value == null || value === '') return t('dream_ops.unknown', 'Unknown');
    const date = new Date(Number(value) * 1000);
    return Number.isNaN(date.getTime()) ? escapeHtml(String(value)) : escapeHtml(date.toLocaleString());
  }

  function _opsLabel(prefix, value) {
    const key = `${prefix}.${value || 'unknown'}`;
    return escapeHtml(t(key, value || t('dream_ops.unknown', 'Unknown')));
  }

  function _opsBadge(prefix, value, className = 'badge-accent') {
    return `<span class="badge ${className}">${_opsLabel(prefix, value)}</span>`;
  }

  function _opsCountCard(labelKey, value, className = '') {
    const display = typeof value === 'number' ? Number(value || 0) : escapeHtml(String(value || t('dream_ops.unknown', 'Unknown')));
    return `<div class="stat dream-ops-count ${className}"><div class="val">${display}</div><div class="lbl">${escapeHtml(t(labelKey, labelKey))}</div></div>`;
  }

  function _renderDreamOpsOverview(data) {
    const current = data.current || {};
    const archives = data.archives || [];
    const lifecycle = data.exit_lifecycle || [];
    const postcards = data.postcards || [];
    const currentLabel = current.status || t('dream_ops.unknown', 'Unknown');
    document.getElementById('dream-ops-overview').innerHTML = [
      _opsCountCard('dream_ops.current', currentLabel, 'dream-ops-current'),
      _opsCountCard('dream_ops.archive_count', archives.length),
      _opsCountCard('dream_ops.lifecycle_count', lifecycle.length),
      _opsCountCard('dream_ops.postcard_count', postcards.length),
    ].join('');
    const consistency = document.getElementById('dream-ops-consistency');
    const ok = data.consistency?.last_greeted_matches_last_dream;
    const closeOk = data.consistency?.close_metadata_consistent;
    const closeLabel = closeOk == null
      ? t('dream_ops.close_metadata_unknown', 'Close metadata not available')
      : t(closeOk ? 'dream_ops.close_metadata_ok' : 'dream_ops.close_metadata_mismatch', closeOk ? 'Close metadata consistent' : 'Close metadata mismatch');
    consistency.textContent = `${t(ok ? 'dream_ops.consistency_ok' : 'dream_ops.consistency_pending', ok ? 'Consistent' : 'Pending outreach')} · ${closeLabel}`;
  }

  function _renderDreamOpsArchives(items) {
    const host = document.getElementById('dream-ops-archives');
    if (!items.length) {
      host.innerHTML = `<div class="empty">${escapeHtml(t('dream_ops.empty', 'No records'))}</div>`;
      return;
    }
    host.innerHTML = `<table><thead><tr><th>${escapeHtml(t('dream_ops.col.dream', 'Dream'))}</th><th>${escapeHtml(t('dream_ops.col.time', 'Time'))}</th><th>${escapeHtml(t('dream_ops.col.mode', 'Mode'))}</th><th>${escapeHtml(t('dream_ops.col.world', 'World'))}</th><th>${escapeHtml(t('dream_ops.col.completion', 'Completion'))}</th><th>${escapeHtml(t('dream_ops.col.summary', 'Summary'))}</th></tr></thead><tbody>${items.map(item => {
      const title = item.summary_title || item.dream_id || '';
      const preview = item.summary_preview || t('dream_ops.no_summary', 'No safe summary yet');
      return `<tr><td><code>${escapeHtml(item.dream_id || '')}</code><br><small>${escapeHtml(title)}</small></td><td>${_opsTime(item.started_at)}<br>${_opsTime(item.ended_at)}</td><td>${escapeHtml(item.dream_mode || 'unknown')}</td><td>${escapeHtml(item.world_name || 'unknown')}</td><td>${_opsLabel('dream_ops.completion', item.completion)}</td><td title="${escapeHtml(preview)}">${escapeHtml(preview)}</td></tr>`;
    }).join('')}</tbody></table>`;
  }

  function _scenarioIds(value) {
    return Array.isArray(value)
      ? value.filter(item => /^[EB][1-9][0-9]{0,2}$/.test(String(item))).map(escapeHtml).join('、')
      : '';
  }

  function _renderDreamOpsScenarioProgress(data) {
    const host = document.getElementById('dream-ops-scenario-progress');
    if (!host) return;
    const progress = data.scenario_progress || {};
    const last = progress.last;
    if (!last) {
      host.innerHTML = `<div class="empty">${escapeHtml(t('dream_ops.empty', 'No records'))}</div>`;
      return;
    }
    const transition = last.from_stage_id && last.to_stage_id
      ? `${escapeHtml(last.from_stage_id)} → ${escapeHtml(last.to_stage_id)}`
      : t('dream_ops.scenario.no_transition', 'None');
    const reason = _opsLabel('dream_ops.scenario.reason', last.disposition || last.reason || 'unknown');
    const profile = `${escapeHtml(last.prompt_profile || 'scenario')} / ${escapeHtml(last.prompt_profile_version || 'v2')}`;
    host.innerHTML = `<div class="page-context-source" style="padding:12px 14px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px 18px">
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.current_stage', 'Current stage'))}：</span><code>${escapeHtml(progress.current_stage_id || '—')}</code></span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.final_stage', 'Final stage'))}：</span><code>${escapeHtml(progress.final_stage_id || '—')}</code></span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.control', 'Control'))}：</span>${_opsBadge('dream_ops.scenario.control_status', last.control_status || 'unknown', last.control_status === 'valid' ? 'badge-success' : 'badge-warn')}</span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.profile', 'Profile'))}：</span><code>${profile}</code></span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.hit', 'Valid hit'))}：</span><code>${_scenarioIds(last.matched_exit_ids) || '—'}</code> (${Number(last.valid_exit_sign_count || 0)})</span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.blocked', 'Blocked'))}：</span><code>${_scenarioIds(last.blocked_ids) || '—'}</code></span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.unknown', 'Unknown IDs'))}：</span>${Number(last.unknown_exit_sign_count || 0) + Number(last.unknown_blocked_event_count || 0)}</span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.reason_label', 'Reason'))}：</span>${reason}</span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.stall', 'Stall turns'))}：</span>${Number(last.stall_turns || 0)}</span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.recovery', 'Recovery'))}：</span>${last.recovery_pending ? escapeHtml(t('common.enabled', 'Enabled')) : escapeHtml(t('common.disabled', 'Disabled'))}</span>
      <span><span class="muted">${escapeHtml(t('dream_ops.scenario.transition', 'Last transition'))}：</span><code>${transition}</code></span>
    </div></div>`;
  }

  function _renderDreamOpsLifecycle(items) {
    const host = document.getElementById('dream-ops-lifecycle');
    if (!items.length) {
      host.innerHTML = `<div class="empty">${escapeHtml(t('dream_ops.empty', 'No records'))}</div>`;
      return;
    }
    host.innerHTML = `<table><thead><tr><th>${escapeHtml(t('dream_ops.col.dream', 'Dream'))}</th><th>${escapeHtml(t('dream_ops.col.lifecycle', 'Status'))}</th><th>${escapeHtml(t('dream_ops.col.reason', 'Reason'))}</th><th>${escapeHtml(t('dream_ops.col.attempts', 'Attempts'))}</th><th>${escapeHtml(t('dream_ops.col.time', 'Time'))}</th></tr></thead><tbody>${items.map(item => {
      const className = item.lifecycle === 'sent' ? 'badge-success' : item.lifecycle === 'blocked' || item.lifecycle === 'expired' ? 'badge-warn' : 'badge-accent';
      return `<tr><td><code>${escapeHtml(item.dream_id || '')}</code></td><td>${_opsBadge('dream_ops.lifecycle', item.lifecycle, className)}</td><td>${_opsLabel('dream_ops.reason', item.reason_code || 'unknown')}</td><td>${Number(item.attempts || 0)}</td><td>${_opsTime(item.sent_at || item.last_attempt_at || item.ready_at || item.created_at)}</td></tr>`;
    }).join('')}</tbody></table>`;
  }

  function _renderDreamOpsContinuation(data) {
    const host = document.getElementById('dream-ops-continuation');
    if (!host) return;
    const items = data.continuation?.recent || [];
    if (!items.length) {
      host.innerHTML = `<div class="empty">${escapeHtml(t('dream_ops.empty', 'No records'))}</div>`;
      return;
    }
    host.innerHTML = `<table><thead><tr><th>${escapeHtml(t('dream_ops.col.dream', 'Dream'))}</th><th>${escapeHtml(t('dream_ops.col.lifecycle', 'Status'))}</th><th>${escapeHtml(t('dream_ops.col.reason', 'Reason'))}</th><th>${escapeHtml(t('dream_ops.col.attempts', 'Attempts'))}</th><th>${escapeHtml(t('dream_ops.col.time', 'Time'))}</th></tr></thead><tbody>${items.map(item => {
      const success = item.lifecycle === 'sent';
      const terminal = item.lifecycle === 'cancelled' || item.lifecycle === 'failed';
      return `<tr><td><code>${escapeHtml(item.dream_id || '')}</code></td><td>${_opsBadge('dream_ops.lifecycle', item.lifecycle, success ? 'badge-success' : terminal ? 'badge-warn' : 'badge-accent')}</td><td>${_opsLabel('dream_ops.reason', item.reason_code || 'unknown')}</td><td>${Number(item.attempts || 0)}</td><td>${_opsTime(item.sent_at || item.last_attempt_at || item.created_at)}</td></tr>`;
    }).join('')}</tbody></table>`;
  }

  function _renderDreamOpsPostcards(items) {
    const host = document.getElementById('dream-ops-postcards');
    if (!items.length) {
      host.innerHTML = `<div class="empty">${escapeHtml(t('dream_ops.empty', 'No records'))}</div>`;
      return;
    }
    host.innerHTML = `<table><thead><tr><th>${escapeHtml(t('dream_ops.col.dream', 'Dream'))}</th><th>${escapeHtml(t('dream_ops.col.generation', 'Generation'))}</th><th>${escapeHtml(t('dream_ops.col.delivery', 'Delivery'))}</th><th>${escapeHtml(t('dream_ops.col.schedule', 'Scheduled date'))}</th><th>${escapeHtml(t('dream_ops.col.attempts', 'Attempts'))}</th><th>${escapeHtml(t('dream_ops.col.reason', 'Reason'))}</th></tr></thead><tbody>${items.map(item => {
      const generation = item.generation_status || (item.last_error === 'generation_failed' ? 'generation_failed' : 'unknown');
      const delivery = item.delivery_status || (item.sent ? 'sent' : 'not_scheduled');
      const error = item.last_error ? ` · ${item.last_error}` : '';
      return `<tr><td><code>${escapeHtml(item.dream_id || '')}</code></td><td>${_opsLabel('dream_ops.generation', generation)}</td><td>${_opsLabel('dream_ops.delivery', delivery)}${escapeHtml(error)}</td><td>${escapeHtml(item.scheduled_date || '—')}</td><td>${Number(item.attempts || 0)}</td><td>${_opsLabel('dream_ops.reason', item.eligibility_reason || 'unknown')}</td></tr>`;
    }).join('')}</tbody></table>`;
  }

  async function loadObserveDreamOperations() {
    const overview = document.getElementById('dream-ops-overview');
    if (!overview) return;
    overview.innerHTML = `<div class="loading">${escapeHtml(t('dream_ops.loading', 'Loading…'))}</div>`;
    try {
      const data = await api('GET', '/dream/operations');
      _renderDreamOpsOverview(data);
      _renderDreamOpsArchives(data.archives || []);
      _renderDreamOpsScenarioProgress(data);
      _renderDreamOpsLifecycle(data.exit_lifecycle || []);
      _renderDreamOpsContinuation(data);
      _renderDreamOpsPostcards(data.postcards || []);
    } catch (error) {
      const message = escapeHtml(t('dream_ops.load_failed', 'Failed to load: {error}', {error: error.message}));
      overview.innerHTML = `<div class="empty">${message}</div>`;
      ['dream-ops-archives', 'dream-ops-scenario-progress', 'dream-ops-lifecycle', 'dream-ops-continuation', 'dream-ops-postcards'].forEach(id => {
        const host = document.getElementById(id);
        if (host) host.innerHTML = `<div class="empty">${message}</div>`;
      });
    }
  }

  window.loadObserveDreamOperations = loadObserveDreamOperations;
}());

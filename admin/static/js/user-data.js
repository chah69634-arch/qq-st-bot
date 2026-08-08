async function loadUserDataPage() {
  const el = document.getElementById('user-data-content');
  if (!el) return;
  const ui = (key, fallback, params) => t(`user_data.${key}`, fallback, params);
  const categoryLabel = category => ui(`category.${category}`, category);

  const render = async () => {
    el.innerHTML = `<div style="color:var(--muted)">${ui('loading', 'Loading...')}</div>`;
    try {
      const category = document.getElementById('user-data-category')?.value || '';
      const charId = document.getElementById('user-data-char')?.value || '';
      const qs = new URLSearchParams();
      if (category) qs.set('category', category);
      if (charId) qs.set('char_id', charId);
      const data = await api('GET', `/user-data/assets${qs.toString() ? `?${qs.toString()}` : ''}`);
      const categories = data.categories || [];
      const assets = data.assets || [];

      let html = '<div class="card"><div class="form-row">';
      html += `<label class="field"><span>${ui('category', 'Category')}</span><select id="user-data-category">`;
      html += `<option value="">${ui('all', 'All')}</option>`;
      for (const cat of categories) {
        html += `<option value="${escapeHtml(cat.id)}" ${cat.id === category ? 'selected' : ''}>${escapeHtml(categoryLabel(cat.id))}${cat.desktop_available ? '' : ` · ${ui('partial', 'partial')}`}</option>`;
      }
      html += '</select></label>';
      html += `<label class="field"><span>${ui('character', 'Character')}</span><input id="user-data-char" value="${escapeHtml(charId || '')}" placeholder="&lt;char_id&gt;"></label>`;
      html += `<div class="field"><span>&nbsp;</span><button class="btn btn-ghost btn-sm" data-action="reloadUserData">${ui('refresh', 'Refresh')}</button></div>`;
      html += '</div></div>';

      html += `<div class="card"><table class="tbl"><thead><tr><th>${ui('logical_id', 'Logical ID')}</th><th>${ui('category', 'Category')}</th><th>${ui('source', 'Source')}</th><th>${ui('status', 'Status')}</th><th>${ui('size', 'Size')}</th><th>${ui('updated_at', 'Updated')}</th><th></th></tr></thead><tbody>`;
      for (const asset of assets) {
        html += `<tr>
          <td>${escapeHtml(asset.logical_id)}</td>
          <td>${escapeHtml(categoryLabel(asset.category))}</td>
          <td>${escapeHtml(asset.source)}</td>
          <td>${escapeHtml(asset.desktop_available ? 'available' : asset.availability || 'partial')}</td>
          <td>${Number(asset.size || 0).toLocaleString()}</td>
          <td>${new Date(Number(asset.updated_at || 0) * 1000).toLocaleString()}</td>
          <td><button class="btn btn-ghost btn-sm" data-action="deleteUserDataAsset" data-action-args='${JSON.stringify([asset.category, asset.logical_id, asset.scope || {}])}'>${ui('delete', 'Delete')}</button></td>
        </tr>`;
      }
      html += '</tbody></table></div>';

      html += '<div class="card"><div class="form-row">';
      html += `<label class="field"><span>${ui('category', 'Category')}</span><select id="user-data-upload-category">`;
      for (const cat of categories) html += `<option value="${escapeHtml(cat.id)}">${escapeHtml(categoryLabel(cat.id))}</option>`;
      html += '</select></label>';
      html += `<label class="field"><span>${ui('logical_id', 'Logical ID')}</span><input id="user-data-upload-id"></label>`;
      html += `<label class="field"><span>${ui('file', 'File')}</span><input type="file" id="user-data-upload-file"></label>`;
      html += '</div><div class="form-row">';
      html += `<label class="field"><span>${ui('character', 'Character')}</span><input id="user-data-upload-char" value="${escapeHtml(charId || '')}"></label>`;
      html += `<label class="field"><span>${ui('scope_extra', 'Emotion / pack')}</span><input id="user-data-upload-extra" placeholder="neutral / pack"></label>`;
      html += `<div class="field"><span>&nbsp;</span><button class="btn btn-primary btn-sm" data-action="uploadUserDataAsset">${ui('upload', 'Upload')}</button></div>`;
      html += '</div></div>';

      html += '<div id="user-data-status" class="empty"></div>';
      el.innerHTML = html;
      bindPageActions(el);
    } catch (e) {
      el.innerHTML = `<div style="color:#ef4444">${ui('load_failed', 'Load failed: {error}', {error: e.message})}</div>`;
    }
  };

  window.reloadUserData = render;
  window.uploadUserDataAsset = async () => {
    const file = document.getElementById('user-data-upload-file')?.files?.[0];
    if (!file) return toast(ui('choose_file', 'Choose a file first.'), 'error');
    const form = new FormData();
    form.append('category', document.getElementById('user-data-upload-category').value);
    form.append('logical_id', document.getElementById('user-data-upload-id').value.trim());
    form.append('file', file, file.name);
    const uploadCharId = document.getElementById('user-data-upload-char').value.trim();
    if (uploadCharId) form.append('char_id', uploadCharId);
    const uploadCategory = document.getElementById('user-data-upload-category').value;
    const extra = document.getElementById('user-data-upload-extra').value.trim();
    if (uploadCategory === 'sticker_pack') {
      const [pack, emotion] = extra.split('/', 2).map(value => value.trim());
      if (pack) form.append('pack', pack);
      if (emotion) form.append('emotion', emotion);
    } else if (extra) {
      form.append('emotion', extra);
    }
    const resp = await fetch(BASE + '/user-data/assets', { method: 'POST', headers: { Authorization: `Bearer ${TOKEN}` }, body: form });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    await render();
  };
  window.deleteUserDataAsset = async (category, logicalId, scope = {}) => {
    const scopeQuery = new URLSearchParams(scope).toString();
    const impact = await api('GET', `/user-data/assets/${encodeURIComponent(category)}/${encodeURIComponent(logicalId)}/impact${scopeQuery ? `?${scopeQuery}` : ''}`);
    if (!confirm(ui('delete_confirm', 'Delete {logicalId}?\nBindings: {bindings}', {logicalId, bindings: JSON.stringify(impact.bindings || [])}))) return;
    const deleteBody = {};
    const deleteCharId = document.getElementById('user-data-char')?.value.trim();
    if (deleteCharId) deleteBody.char_id = deleteCharId;
    Object.assign(deleteBody, scope);
    await api('DELETE', `/user-data/assets/${encodeURIComponent(category)}/${encodeURIComponent(logicalId)}`, deleteBody);
    await render();
  };

  await render();
}

let _dreamCurrentWorld = '';
let _dreamLoreEntries  = [];
let _dreamLoreEditIdx  = -1;
let _dreamAuthoringMode = 'sandbox';
let _dreamScenarios = [];
let _dreamScenarioEditingId = null;
let _dreamCurrentPreset = '';

async function loadDreamSettings() {
  document.getElementById('dream-authoring-mode-select').value = _dreamAuthoringMode;
  onDreamAuthoringModeChange();
  await Promise.all([loadDreamWorlds(), loadStandaloneDreamPresets()]);
}

// ══════════════════════════════════════════════════════════
//  三模式切换（sandbox / scenario / mirror）——只切本页创作栏
// ══════════════════════════════════════════════════════════
function onDreamAuthoringModeChange() {
  const mode = document.getElementById('dream-authoring-mode-select').value;
  _dreamAuthoringMode = mode;
  document.getElementById('dream-authoring-sandbox').style.display = mode === 'sandbox' ? '' : 'none';
  document.getElementById('dream-authoring-scenario').style.display = mode === 'scenario' ? '' : 'none';
  document.getElementById('dream-authoring-mirror').style.display = mode === 'mirror' ? '' : 'none';
  if (mode === 'scenario') loadDreamScenarios();
}

async function loadDreamWorlds() {
  try {
    const d = await api('GET', '/dream/worlds');
    const sel = document.getElementById('dream-world-select');
    const prev = sel.value;
    sel.innerHTML = '<option value="">-- 选择世界 --</option>';
    (d.worlds || []).forEach(w => {
      const opt = document.createElement('option');
      opt.value = w;
      opt.textContent = w;
      sel.appendChild(opt);
    });
    if (prev && d.worlds.includes(prev)) {
      sel.value = prev;
    }
    onDreamWorldChange();
  } catch(e) {
    toast('加载世界列表失败: ' + e.message, 'err');
  }
}

async function newDreamWorld() {
  const world = prompt('新建世界名称（用作文件夹名，不能以 _ 开头）：');
  if (!world) return;
  const label = prompt('世界显示名（可留空，默认与世界名相同）：', world.trim()) || '';
  try {
    const d = await api('POST', '/dream/worlds', { world: world.trim(), label: label.trim() });
    toast(`世界 ${d.world} 已创建`, 'ok');
    await loadDreamWorlds();
    document.getElementById('dream-world-select').value = d.world;
    onDreamWorldChange();
  } catch(e) { toast('新建失败：' + e.message, 'err'); }
}

async function renameDreamWorld() {
  const world = _dreamCurrentWorld;
  if (!world) { toast('请先选择世界', 'warn'); return; }
  const new_name = prompt(`重命名「${world}」为：`, world);
  if (!new_name || new_name === world) return;
  try {
    const d = await api('PUT', `/dream/worlds/${encodeURIComponent(world)}/rename`, { new_name });
    toast(`已重命名为 ${d.world}`, 'ok');
    await loadDreamWorlds();
    document.getElementById('dream-world-select').value = d.world;
    onDreamWorldChange();
  } catch(e) { toast('重命名失败：' + e.message, 'err'); }
}

async function deleteDreamWorld() {
  const world = _dreamCurrentWorld;
  if (!world) { toast('请先选择世界', 'warn'); return; }
  if (!confirm(t('dynamic.dream.delete_world_confirm', 'Delete world “{name}”? Its lorebook will be deleted. Independent presets are kept.', { name: world }))) return;
  try {
    await api('DELETE', `/dream/worlds/${encodeURIComponent(world)}`);
    toast(`世界 ${world} 已删除`, 'ok');
    _dreamCurrentWorld = '';
    await loadDreamWorlds();
  } catch(e) { toast('删除失败：' + e.message, 'err'); }
}

function onDreamWorldChange() {
  const world = document.getElementById('dream-world-select').value;
  _dreamCurrentWorld = world;
  if (!world) {
    document.getElementById('dream-lore-card').style.display = 'none';
    return;
  }
  document.getElementById('dream-lore-card').style.display = '';
  loadDreamLore();
}

async function loadDreamLore() {
  if (!_dreamCurrentWorld) return;
  const el = document.getElementById('dream-lore-list');
  el.innerHTML = '<div class="loading">加载中…</div>';
  try {
    const d = await api('GET', `/dream/worlds/${encodeURIComponent(_dreamCurrentWorld)}/lorebook`);
    _dreamLoreEntries = d.entries || [];
    renderDreamLore();
  } catch(e) {
    el.innerHTML = `<div class="empty">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function renderDreamLore() {
  const el = document.getElementById('dream-lore-list');
  if (!_dreamLoreEntries.length) {
    el.innerHTML = '<div class="empty">暂无条目</div>';
    return;
  }
  const rows = _dreamLoreEntries.map((e, i) => {
    const kw = (e.keywords || []).join(', ');
    const preview = (e.content || '').slice(0, 80).replace(/\n/g, ' ');
    return `<tr>
      <td style="font-size:12px;color:var(--accent)">${escapeHtml(kw)}</td>
      <td style="font-size:12px;color:var(--muted)">${escapeHtml(preview)}…</td>
      <td style="text-align:center;white-space:nowrap">
        <button class="btn btn-ghost btn-sm" onclick="openDreamLoreModal(${i})">编辑</button>
        <button class="btn btn-danger btn-sm" style="margin-left:4px" onclick="deleteDreamLoreEntry(${i})">删除</button>
      </td>
    </tr>`;
  }).join('');
  el.innerHTML = `<div class="tbl-wrap"><table>
    <thead><tr><th>Keywords</th><th>内容预览</th><th style="width:140px">操作</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

async function loadStandaloneDreamPresets() {
  const select = document.getElementById('dream-preset-select');
  const text = document.getElementById('dream-preset-text');
  try {
    const [assets, settings] = await Promise.all([
      api('GET', '/dream/presets'),
      api('GET', '/dream/settings'),
    ]);
    const selected = new Set(settings.jailbreak_presets || []);
    const previous = _dreamCurrentPreset || select.value;
    select.innerHTML = '';
    (assets.presets || []).forEach(preset => {
      const option = document.createElement('option');
      option.value = preset.id;
      option.textContent = preset.label === preset.id ? preset.id : `${preset.label} (${preset.id})`;
      option.selected = selected.has(preset.id);
      select.appendChild(option);
    });
    _dreamCurrentPreset = previous && [...select.options].some(option => option.value === previous)
      ? previous
      : [...select.selectedOptions][0]?.value || select.options[0]?.value || '';
    if (_dreamCurrentPreset) {
      await loadStandaloneDreamPresetContent();
    } else {
      text.value = '';
    }
  } catch(e) {
    toast(t('dynamic.dream.presets_load_failed', 'Failed to load presets: {error}', { error: e.message }), 'err');
  }
}

async function onStandaloneDreamPresetChange() {
  _dreamCurrentPreset = document.getElementById('dream-preset-select').value;
  await loadStandaloneDreamPresetContent();
}

async function loadStandaloneDreamPresetContent() {
  if (!_dreamCurrentPreset) return;
  try {
    const d = await api('GET', `/dream/presets/${encodeURIComponent(_dreamCurrentPreset)}`);
    document.getElementById('dream-preset-text').value = d.content || '';
  } catch(e) {
    toast(t('dynamic.dream.presets_load_failed', 'Failed to load presets: {error}', { error: e.message }), 'err');
  }
}

async function saveStandaloneDreamPreset() {
  if (!_dreamCurrentPreset) {
    toast(t('dynamic.dream.select_preset', 'Select a preset first'), 'warn');
    return;
  }
  const content = document.getElementById('dream-preset-text').value;
  try {
    await api('PUT', `/dream/presets/${encodeURIComponent(_dreamCurrentPreset)}`, { content });
    toast(t('dynamic.dream.preset_saved', 'Preset saved'), 'ok');
  } catch(e) {
    toast(t('common.operation_failed', 'Operation failed: {error}', { error: e.message }), 'err');
  }
}

async function createStandaloneDreamPreset() {
  const id = prompt(t('dynamic.dream.new_preset_id', 'New preset ID (letters, numbers, _ and - only):'));
  if (!id) return;
  try {
    await api('POST', '/dream/presets', { id: id.trim(), content: '' });
    _dreamCurrentPreset = id.trim();
    await loadStandaloneDreamPresets();
    const option = [...document.getElementById('dream-preset-select').options]
      .find(item => item.value === _dreamCurrentPreset);
    if (option) option.selected = true;
    toast(t('dynamic.dream.preset_created', 'Preset created. Save the selection to use it in the next dream.'), 'ok');
  } catch(e) {
    toast(t('common.create_failed', 'Create failed: {error}', { error: e.message }), 'err');
  }
}

async function saveStandaloneDreamPresetSelection() {
  const presets = [...document.getElementById('dream-preset-select').selectedOptions]
    .map(option => option.value);
  if (!presets.length) {
    toast(t('dynamic.dream.select_one_preset', 'Select at least one preset'), 'warn');
    return;
  }
  try {
    await api('PATCH', '/dream/settings', { jailbreak_presets: presets });
    toast(t('dynamic.dream.preset_selection_saved', 'Preset selection saved for the next dream'), 'ok');
  } catch(e) {
    toast(t('common.operation_failed', 'Operation failed: {error}', { error: e.message }), 'err');
  }
}

async function deleteStandaloneDreamPreset() {
  if (!_dreamCurrentPreset) {
    toast(t('dynamic.dream.select_preset', 'Select a preset first'), 'warn');
    return;
  }
  if (!confirm(t('dynamic.dream.delete_preset_confirm', 'Delete preset “{id}”? This cannot be undone.', { id: _dreamCurrentPreset }))) return;
  try {
    await api('DELETE', `/dream/presets/${encodeURIComponent(_dreamCurrentPreset)}`);
    _dreamCurrentPreset = '';
    await loadStandaloneDreamPresets();
    toast(t('dynamic.dream.preset_deleted', 'Preset deleted'), 'ok');
  } catch(e) {
    toast(t('common.delete_failed', 'Delete failed: {error}', { error: e.message }), 'err');
  }
}

function openDreamLoreModal(idx = -1) {
  _dreamLoreEditIdx = idx;
  const modal = document.getElementById('dream-lore-modal');
  const title = document.getElementById('dream-lore-modal-title');
  if (idx >= 0 && idx < _dreamLoreEntries.length) {
    const e = _dreamLoreEntries[idx];
    title.textContent = '编辑世界书条目';
    document.getElementById('dl-keywords').value = (e.keywords || []).join(', ');
    document.getElementById('dl-content').value = e.content || '';
    document.getElementById('dl-insertion-order').value = e.insertion_order ?? 0;
    document.getElementById('dl-regex').checked = !!e.regex;
  } else {
    title.textContent = '新增世界书条目';
    document.getElementById('dl-keywords').value = '';
    document.getElementById('dl-content').value = '';
    document.getElementById('dl-insertion-order').value = _dreamLoreEntries.length;
    document.getElementById('dl-regex').checked = false;
  }
  modal.classList.add('open');
}

function closeDreamLoreModal() {
  document.getElementById('dream-lore-modal').classList.remove('open');
}

async function saveDreamLoreEntry() {
  const world = _dreamCurrentWorld;
  if (!world) return;
  const kw = document.getElementById('dl-keywords').value.split(',').map(s => s.trim()).filter(Boolean);
  const content = document.getElementById('dl-content').value.trim();
  const insertion_order = parseInt(document.getElementById('dl-insertion-order').value) || 0;
  const regex = document.getElementById('dl-regex').checked;
  if (!kw.length) { toast('Keywords 不能为空', 'err'); return; }
  if (!content) { toast('Content 不能为空', 'err'); return; }
  try {
    if (_dreamLoreEditIdx >= 0) {
      await api('PUT', `/dream/worlds/${encodeURIComponent(world)}/lorebook/${_dreamLoreEditIdx}`,
        { keywords: kw, content, insertion_order, regex });
      toast('条目已更新', 'ok');
    } else {
      await api('POST', `/dream/worlds/${encodeURIComponent(world)}/lorebook`,
        { keywords: kw, content, insertion_order, regex });
      toast('条目已新增', 'ok');
    }
    closeDreamLoreModal();
    loadDreamLore();
  } catch(e) {
    toast('保存失败: ' + e.message, 'err');
  }
}

async function deleteDreamLoreEntry(idx) {
  const world = _dreamCurrentWorld;
  if (!world) return;
  if (!confirm(`确认删除第 ${idx} 条条目？`)) return;
  try {
    await api('DELETE', `/dream/worlds/${encodeURIComponent(world)}/lorebook/${idx}`);
    toast('条目已删除', 'ok');
    loadDreamLore();
  } catch(e) {
    toast('删除失败: ' + e.message, 'err');
  }
}

// ══════════════════════════════════════════════════════════
//  scenario 剧本创作栏（Brief 96 §3）
// ══════════════════════════════════════════════════════════
async function loadDreamScenarios() {
  const el = document.getElementById('dream-scenario-list');
  el.innerHTML = '<div class="loading">加载中…</div>';
  try {
    const d = await api('GET', '/dream/scenarios');
    _dreamScenarios = d.scenarios || [];
    renderDreamScenarios();
  } catch(e) {
    el.innerHTML = `<div class="empty">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function renderDreamScenarios() {
  const el = document.getElementById('dream-scenario-list');
  if (!_dreamScenarios.length) {
    el.innerHTML = '<div class="empty">暂无剧本</div>';
    return;
  }
  const rows = _dreamScenarios.map(s => `<tr>
    <td style="font-size:12px;color:var(--accent)">${escapeHtml(s.id)}</td>
    <td style="font-size:12px">${escapeHtml(s.title)}</td>
    <td style="text-align:center;white-space:nowrap">
      <button class="btn btn-ghost btn-sm" onclick="openDreamScenarioEditor('${escapeHtml(s.id)}')">编辑</button>
      <button class="btn btn-danger btn-sm" style="margin-left:4px" onclick="deleteDreamScenario('${escapeHtml(s.id)}')">删除</button>
    </td>
  </tr>`).join('');
  el.innerHTML = `<div class="tbl-wrap"><table>
    <thead><tr><th>ID</th><th>标题</th><th style="width:140px">操作</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

function _dreamScenarioSkeletonYaml(id, title) {
  return `id: ${id}
title: ${title}
stages:
  - id: stage_1
    name: 阶段一
    dramatic_task: 描述这一阶段角色要完成的戏剧任务
    entry_pressure: 描述进入这一阶段时的压力/驱动
    exit_signs: []
    not_yet_allowed: []
`;
}

function fillDreamScenarioSkeleton() {
  const id = document.getElementById('ds-id').value.trim();
  if (!id) { toast('请先填写剧本 ID', 'warn'); return; }
  const title = document.getElementById('ds-title').value.trim() || id;
  const yamlEl = document.getElementById('ds-yaml');
  if (yamlEl.value.trim() && !confirm('已有 YAML 内容，确认覆盖为骨架模板？')) return;
  yamlEl.value = _dreamScenarioSkeletonYaml(id, title);
}

async function openDreamScenarioEditor(id) {
  _dreamScenarioEditingId = id;
  document.getElementById('dream-scenario-editor-card').style.display = '';
  const idInput = document.getElementById('ds-id');
  if (id) {
    document.getElementById('dream-scenario-editor-title').textContent = `编辑剧本 · ${id}`;
    idInput.value = id;
    idInput.disabled = true;
    document.getElementById('ds-title').value = '';
    document.getElementById('ds-yaml').value = '加载中…';
    try {
      const d = await api('GET', `/dream/scenarios/${encodeURIComponent(id)}`);
      document.getElementById('ds-yaml').value = d.yaml || '';
    } catch(e) {
      toast('读取失败: ' + e.message, 'err');
      document.getElementById('ds-yaml').value = '';
    }
  } else {
    document.getElementById('dream-scenario-editor-title').textContent = '新建剧本';
    idInput.value = '';
    idInput.disabled = false;
    document.getElementById('ds-title').value = '';
    document.getElementById('ds-yaml').value = '';
  }
}

function closeDreamScenarioEditor() {
  document.getElementById('dream-scenario-editor-card').style.display = 'none';
  _dreamScenarioEditingId = null;
}

async function saveDreamScenario() {
  const id = document.getElementById('ds-id').value.trim();
  const yaml = document.getElementById('ds-yaml').value;
  if (!id) { toast('ID 不能为空', 'err'); return; }
  if (!yaml.trim()) { toast('YAML 内容不能为空', 'err'); return; }
  try {
    if (_dreamScenarioEditingId) {
      await api('PUT', `/dream/scenarios/${encodeURIComponent(_dreamScenarioEditingId)}`, { yaml });
      toast('剧本已保存', 'ok');
    } else {
      await api('POST', '/dream/scenarios', { id, yaml });
      toast('剧本已新建', 'ok');
    }
    closeDreamScenarioEditor();
    loadDreamScenarios();
  } catch(e) { toast('保存失败: ' + e.message, 'err'); }
}

async function deleteDreamScenario(id) {
  if (!confirm(`确认删除剧本「${id}」？此操作不可撤销。`)) return;
  try {
    await api('DELETE', `/dream/scenarios/${encodeURIComponent(id)}`);
    toast('剧本已删除', 'ok');
    if (_dreamScenarioEditingId === id) closeDreamScenarioEditor();
    loadDreamScenarios();
  } catch(e) { toast('删除失败: ' + e.message, 'err'); }
}

// ══════════════════════════════════════════════════════════
//  印象溯源（observe-provenance）
// ══════════════════════════════════════════════════════════

/* ============================================================
   BACnet Simulator — Frontend App
   REST + WebSocket, render points, CRUD, live updates,
   Start/Stop engine, inline PV edit, random mode, CSV I/O
   ============================================================ */

const API = '';
let allObjects = [];
let activeTypeFilter = new Set();
let editingObject = null;
let engineRunning = false;
let ws = null;

// --- DOM refs ---
const tbody         = document.getElementById('objects-body');
const emptyState    = document.getElementById('empty-state');
const searchInput   = document.getElementById('search-input');
const typeFilters   = document.getElementById('type-filters');
const pointCount    = document.getElementById('point-count');
const connStatus    = document.getElementById('conn-status');
const deviceNameEl  = document.getElementById('device-name');
const deviceIdEl    = document.getElementById('device-id');
const modalOverlay  = document.getElementById('modal-overlay');
const modalTitle    = document.getElementById('modal-title');
const modalForm     = document.getElementById('modal-form');
const modalSubmit   = document.getElementById('modal-submit');
const toastContainer = document.getElementById('toast-container');
const btnEngine     = document.getElementById('btn-engine');
const engineLabel   = document.getElementById('engine-label');

// --- Constants ---
const UNITS_MAP = {
  62: '°C', 64: '°F', 98: '%', 29: '%RH', 48: 'kW',
  53: 'V', 47: 'A', 95: '', 63: 'K',
};

const TYPE_INFO = {
  analogInput:          { short: 'AI',  badge: 'ai'  },
  analogOutput:         { short: 'AO',  badge: 'ao'  },
  analogValue:          { short: 'AV',  badge: 'av'  },
  binaryInput:          { short: 'BI',  badge: 'bi'  },
  binaryOutput:         { short: 'BO',  badge: 'bo'  },
  binaryValue:          { short: 'BV',  badge: 'bv'  },
  multiStateInput:      { short: 'MSI', badge: 'msi' },
  multiStateOutput:     { short: 'MO',  badge: 'mo'  },
  multiStateValue:      { short: 'MSV', badge: 'msv' },
  characterstringValue: { short: 'CSV', badge: 'csv' },
};

const READONLY_TYPES     = new Set(['analogInput', 'binaryInput', 'multiStateInput']);
const COMMANDABLE_ALWAYS = new Set(['analogOutput', 'binaryOutput', 'multiStateOutput']);
const COMMANDABLE_OPT    = new Set(['analogValue', 'binaryValue', 'multiStateValue']);
const MULTISTATE_TYPES   = new Set(['multiStateInput', 'multiStateOutput', 'multiStateValue']);
const ANALOG_TYPES       = new Set(['analogInput', 'analogOutput', 'analogValue']);

// ============================================================
// Engine Start / Stop
// ============================================================

function updateEngineUI(running) {
  engineRunning = running;
  if (running) {
    btnEngine.classList.remove('stopped');
    engineLabel.textContent = 'Stop';
    document.getElementById('engine-icon-play').style.display = 'none';
    document.getElementById('engine-icon-stop').style.display = '';
  } else {
    btnEngine.classList.add('stopped');
    engineLabel.textContent = 'Start';
    document.getElementById('engine-icon-play').style.display = '';
    document.getElementById('engine-icon-stop').style.display = 'none';
  }
}

async function shutdownApp() {
  if (!await modalConfirm('This will close the application.', 'Shutdown', 'Shutdown', true)) return;
  try {
    await fetch(`${API}/api/shutdown`, { method: 'POST' });
  } catch (e) {}
  document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#64748B;font-size:16px">Simulator has been shut down. You can close this window.</div>';
}

async function toggleEngine() {
  const action = engineRunning ? 'stop' : 'start';
  try {
    btnEngine.disabled = true;
    const result = await fetchJSON(`/api/engine/${action}`, { method: 'POST' });
    toast(result.status === 'started' ? 'Simulator started' : 'Simulator stopped',
          result.status === 'started' ? 'success' : 'info');
  } catch (e) {
    toast(e.message || `Failed to ${action}`, 'error');
  } finally {
    btnEngine.disabled = false;
  }
}

// ============================================================
// Render
// ============================================================

function renderTable() {
  const query = searchInput.value.toLowerCase();
  const filtered = allObjects.filter(o => {
    if (activeTypeFilter.size > 0 && !activeTypeFilter.has(o.type)) return false;
    if (query) {
      return o.name.toLowerCase().includes(query)
        || o.type.toLowerCase().includes(query)
        || String(o.instance).includes(query);
    }
    return true;
  });

  tbody.innerHTML = '';
  emptyState.style.display = filtered.length ? 'none' : '';

  filtered.forEach(o => {
    const tr = document.createElement('tr');
    tr.dataset.type = o.type;
    tr.dataset.instance = o.instance;

    const info = TYPE_INFO[o.type] || { short: o.type, badge: '' };
    const unit = UNITS_MAP[o.units] || '';
    const pvDisplay = formatPV(o);
    const randomDot = o.random_enabled ? '<span class="random-badge" title="Random simulation active"></span>' : '';

    tr.innerHTML = `
      <td><span class="type-badge type-badge--${info.badge}">${info.short}</span></td>
      <td class="mono">${o.instance}</td>
      <td title="${escHtml(o.description)}">${escHtml(o.name)}</td>
      <td>${randomDot}<span class="pv-cell" data-key="${o.type}:${o.instance}" onclick="inlineEditPV(this,'${o.type}',${o.instance})">${pvDisplay}</span></td>
      <td class="mono" style="color:var(--text-muted);font-size:12px">${unit}</td>
      <td><span class="cmd-dot cmd-dot--${o.commandable ? 'yes' : 'no'}"></span></td>
      <td>
        <button class="btn--icon" onclick="openEdit('${o.type}',${o.instance})" title="Edit">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="btn--icon danger" onclick="deleteObj('${o.type}',${o.instance})" title="Delete">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  pointCount.textContent = `${allObjects.length} points`;
}

function formatPV(o) {
  if (o.type.startsWith('binary')) {
    return o.present_value ? 'Active' : 'Inactive';
  }
  if (MULTISTATE_TYPES.has(o.type) && o.state_text && o.state_text.length) {
    const idx = Number(o.present_value) - 1;
    const label = o.state_text[idx] || '?';
    return `${o.present_value} — ${label}`;
  }
  if (typeof o.present_value === 'number') {
    return Number.isInteger(o.present_value) ? String(o.present_value) : o.present_value.toFixed(2);
  }
  return String(o.present_value);
}

function renderTypeFilters() {
  const types = [...new Set(allObjects.map(o => o.type))].sort();
  typeFilters.innerHTML = '';
  types.forEach(t => {
    const info = TYPE_INFO[t] || { short: t };
    const chip = document.createElement('span');
    chip.className = 'type-chip' + (activeTypeFilter.has(t) ? ' active' : '');
    chip.textContent = info.short;
    chip.onclick = () => {
      if (activeTypeFilter.has(t)) {
        activeTypeFilter.delete(t);
      } else {
        activeTypeFilter.add(t);
      }
      renderTypeFilters();
      renderTable();
    };
    typeFilters.appendChild(chip);
  });
}

function flashPV(type, instance, value) {
  const cell = document.querySelector(`.pv-cell[data-key="${type}:${instance}"]`);
  if (!cell) return;
  // don't flash if user is inline-editing this cell
  if (cell.querySelector('input') || cell.querySelector('select')) return;
  const obj = allObjects.find(o => o.type === type && o.instance === instance);
  cell.textContent = obj ? formatPV(obj) : value;
  cell.classList.add('flash');
  setTimeout(() => cell.classList.remove('flash'), 350);
}

// ============================================================
// Inline PV Edit (click on value in table)
// ============================================================

function inlineEditPV(cell, type, instance) {
  if (cell.querySelector('input') || cell.querySelector('select')) return;
  const obj = allObjects.find(o => o.type === type && o.instance === instance);
  if (!obj) return;

  const isBinary = type === 'binaryInput' || type === 'binaryOutput' || type === 'binaryValue';
  const isMultiState = MULTISTATE_TYPES.has(type);

  cell.textContent = '';

  if (isBinary) {
    // Dropdown for binary types: Inactive (0) / Active (1)
    const sel = document.createElement('select');
    sel.className = 'pv-inline-input';
    const optInactive = document.createElement('option');
    optInactive.value = '0';
    optInactive.textContent = 'Inactive';
    const optActive = document.createElement('option');
    optActive.value = '1';
    optActive.textContent = 'Active';
    sel.appendChild(optInactive);
    sel.appendChild(optActive);
    sel.value = obj.present_value ? '1' : '0';

    cell.appendChild(sel);
    sel.focus();

    const commit = async () => {
      const val = Number(sel.value);
      try {
        await fetchJSON(`/api/objects/${type}/${instance}`, {
          method: 'PUT',
          body: JSON.stringify({ present_value: val }),
        });
      } catch (e) {
        toast(e.message || 'Update failed', 'error');
      }
      obj.present_value = val;
      cell.textContent = formatPV(obj);
    };

    sel.onblur = commit;
    sel.onchange = () => sel.blur();
    sel.onkeydown = (e) => {
      if (e.key === 'Escape') { cell.textContent = formatPV(obj); }
    };
  } else if (isMultiState && obj.state_text && obj.state_text.length) {
    // Dropdown for multi-state types using state_text
    const sel = document.createElement('select');
    sel.className = 'pv-inline-input';
    obj.state_text.forEach((label, i) => {
      const opt = document.createElement('option');
      opt.value = String(i + 1);
      opt.textContent = `${i + 1} — ${label}`;
      sel.appendChild(opt);
    });
    sel.value = String(obj.present_value);

    cell.appendChild(sel);
    sel.focus();

    const commit = async () => {
      const val = Number(sel.value);
      try {
        await fetchJSON(`/api/objects/${type}/${instance}`, {
          method: 'PUT',
          body: JSON.stringify({ present_value: val }),
        });
      } catch (e) {
        toast(e.message || 'Update failed', 'error');
      }
      obj.present_value = val;
      cell.textContent = formatPV(obj);
    };

    sel.onblur = commit;
    sel.onchange = () => sel.blur();
    sel.onkeydown = (e) => {
      if (e.key === 'Escape') { cell.textContent = formatPV(obj); }
    };
  } else {
    // Text input for all other types
    const input = document.createElement('input');
    input.className = 'pv-inline-input';
    input.type = 'text';
    input.value = obj.present_value;

    cell.appendChild(input);
    input.focus();
    input.select();

    const commit = async () => {
      let val = input.value;
      // parse number
      if (!isNaN(Number(val))) val = Number(val);

      try {
        await fetchJSON(`/api/objects/${type}/${instance}`, {
          method: 'PUT',
          body: JSON.stringify({ present_value: val }),
        });
      } catch (e) {
        toast(e.message || 'Update failed', 'error');
      }
      // re-render cell (WebSocket will also update, but be immediate)
      obj.present_value = val;
      cell.textContent = formatPV(obj);
    };

    input.onblur = commit;
    input.onkeydown = (e) => {
      if (e.key === 'Enter') { input.blur(); }
      if (e.key === 'Escape') {
        cell.textContent = formatPV(obj);
      }
    };
  }
}

// ============================================================
// Config
// ============================================================

async function loadConfig() {
  try {
    const [cfg, ifaces, engineSt] = await Promise.all([
      fetchJSON('/api/config'),
      fetchJSON('/api/interfaces'),
      fetchJSON('/api/engine/status'),
    ]);

    updateEngineUI(engineSt.running);

    deviceNameEl.textContent = cfg.device.name;
    deviceIdEl.textContent = cfg.device.instance;

    document.getElementById('cfg-port').value = cfg.connection.bacnet_ip.port;
    document.getElementById('cfg-instance').value = cfg.device.instance;
    document.getElementById('cfg-name').value = cfg.device.name;
    document.getElementById('cfg-network').value = cfg.connection.network_number;
    document.getElementById('cfg-apdu-timeout').value = cfg.connection.bacnet_ip.apdu_timeout_ms;
    document.getElementById('cfg-apdu-retries').value = cfg.connection.bacnet_ip.apdu_retries;

    const ifSelect = document.getElementById('cfg-interface');
    ifSelect.innerHTML = '';
    ifaces.forEach(i => {
      const opt = document.createElement('option');
      opt.value = i.value;
      opt.textContent = i.label;
      if (i.value === cfg.connection.bacnet_ip.interface) opt.selected = true;
      ifSelect.appendChild(opt);
    });

    // MS/TP fields
    const mstpEnabled = document.getElementById('cfg-mstp-enabled');
    if (mstpEnabled) mstpEnabled.checked = cfg.connection.mstp.enabled;
    const macEl = document.getElementById('cfg-mac');
    if (macEl) macEl.value = cfg.connection.mstp.mac_address;
    const maxMasterEl = document.getElementById('cfg-max-master');
    if (maxMasterEl) maxMasterEl.value = cfg.connection.mstp.max_master;
    const maxInfoEl = document.getElementById('cfg-max-info');
    if (maxInfoEl) maxInfoEl.value = cfg.connection.mstp.max_info_frames;
    const baudEl = document.getElementById('cfg-baud');
    if (baudEl) baudEl.value = cfg.connection.mstp.baud;

    try {
      const ports = await fetchJSON('/api/serial-ports');
      const serialSelect = document.getElementById('cfg-serial');
      serialSelect.innerHTML = '<option value="">— Select port —</option>';
      ports.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.port;
        opt.textContent = `${p.port} — ${p.description}`;
        if (p.port === cfg.connection.mstp.serial_port) opt.selected = true;
        serialSelect.appendChild(opt);
      });
    } catch (e) {}
  } catch (e) {
    toast('Failed to load config', 'error');
  }
}

// ============================================================
// WebSocket
// ============================================================

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/api/ws`);

  ws.onopen = () => {
    connStatus.className = 'status-indicator status-indicator--online';
    connStatus.querySelector('.status-indicator__text').textContent = 'Online';
  };

  ws.onclose = () => {
    connStatus.className = 'status-indicator status-indicator--offline';
    connStatus.querySelector('.status-indicator__text').textContent = 'Offline';
    setTimeout(connectWS, 2000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);

    if (msg.event === 'snapshot') {
      allObjects = msg.objects;
      if (msg.running !== undefined) updateEngineUI(msg.running);
      renderTypeFilters();
      renderTable();
    }
    else if (msg.event === 'value_change') {
      const obj = allObjects.find(o => o.type === msg.type && o.instance === msg.instance);
      if (obj) {
        obj.present_value = msg.value;
        flashPV(msg.type, msg.instance, msg.value);
      }
    }
    else if (msg.event === 'object_added') {
      allObjects.push(msg.object);
      renderTypeFilters();
      renderTable();
    }
    else if (msg.event === 'object_removed') {
      allObjects = allObjects.filter(o => !(o.type === msg.type && o.instance === msg.instance));
      renderTypeFilters();
      renderTable();
    }
    else if (msg.event === 'engine_status') {
      updateEngineUI(msg.running);
    }
    else if (msg.event === 'mstp_status') {
      toast(msg.message, 'info');
    }
    else if (msg.event === 'random_config') {
      const obj = allObjects.find(o => o.type === msg.type && o.instance === msg.instance);
      if (obj) {
        obj.random_enabled = msg.random_enabled;
        obj.random_min = msg.random_min;
        obj.random_max = msg.random_max;
        obj.random_interval = msg.random_interval;
        renderTable();
      }
    }
  };
}

// ============================================================
// CRUD
// ============================================================

async function loadObjects() {
  try {
    allObjects = await fetchJSON('/api/objects');
    renderTypeFilters();
    renderTable();
  } catch (e) {
    toast('Failed to load objects', 'error');
  }
}

async function deleteObj(type, instance) {
  if (!await modalConfirm(`Delete ${type}:${instance}?`, 'Delete point', 'Delete', true)) return;
  try {
    await fetchJSON(`/api/objects/${type}/${instance}`, { method: 'DELETE' });
    toast('Deleted', 'success');
  } catch (e) {
    toast(e.message || 'Delete failed', 'error');
  }
}

// ============================================================
// CSV Export / Import
// ============================================================

async function exportCSV() {
  try {
    const res = await fetch(`${API}/api/export/csv`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const now = new Date();
    const ts = now.getFullYear()
      + String(now.getMonth()+1).padStart(2,'0')
      + String(now.getDate()).padStart(2,'0')
      + '_' + String(now.getHours()).padStart(2,'0')
      + String(now.getMinutes()).padStart(2,'0')
      + String(now.getSeconds()).padStart(2,'0');
    a.download = `bacnet_points_${ts}.csv`;
    // showSaveFilePicker ถ้า browser รองรับ (Chrome/Edge) → เลือกที่จัดเก็บได้
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: a.download,
          types: [{ description: 'CSV', accept: { 'text/csv': ['.csv'] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        toast('Exported', 'success');
        URL.revokeObjectURL(url);
        return;
      } catch (e) {
        if (e.name === 'AbortError') { URL.revokeObjectURL(url); return; }
      }
    }
    // fallback: download ตรง
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast('Exported', 'success');
  } catch (e) {
    toast('Export failed', 'error');
  }
}

let _importFile = null;

function importCSV(input) {
  const file = input.files[0];
  if (!file) return;
  _importFile = file;
  input.value = '';
  document.getElementById('import-overlay').style.display = 'flex';
  document.querySelector('input[name="import-mode"][value="overwrite"]').checked = true;
}

function closeImportModal() {
  document.getElementById('import-overlay').style.display = 'none';
  _importFile = null;
}

async function confirmImport() {
  if (!_importFile) return;
  const mode = document.querySelector('input[name="import-mode"]:checked').value;

  if (mode === 'replace' && !await modalConfirm('This will DELETE all existing points and replace with CSV content.', 'Replace All', 'Replace All', true)) return;

  const form = new FormData();
  form.append('file', _importFile);
  closeImportModal();

  try {
    const result = await fetch(`${API}/api/import/csv?mode=${mode}`, { method: 'POST', body: form });
    const data = await result.json();
    if (!result.ok) throw new Error(data.detail || 'Import failed');
    const parts = [];
    if (data.imported) parts.push(`${data.imported} added`);
    if (data.updated) parts.push(`${data.updated} updated`);
    if (data.errors && data.errors.length) parts.push(`${data.errors.length} errors`);
    toast(parts.join(', ') || 'No changes', parts.length && !data.errors.length ? 'success' : 'info');
    if (data.errors && data.errors.length) console.warn('Import errors:', data.errors);
  } catch (e) {
    toast(e.message || 'Import failed', 'error');
  }
}

// ============================================================
// Modal — Add / Edit
// ============================================================

function openAdd() {
  editingObject = null;
  modalTitle.textContent = 'Add point';
  modalSubmit.textContent = 'Add point';

  document.getElementById('obj-type').disabled = false;
  document.getElementById('obj-instance').disabled = false;
  document.getElementById('obj-type').value = 'analogValue';
  document.getElementById('obj-instance').value = '';
  document.getElementById('obj-name').value = '';
  document.getElementById('obj-desc').value = '';
  document.getElementById('obj-pv').value = '0';
  document.getElementById('obj-units').value = '95';
  document.getElementById('obj-states').value = '';
  document.getElementById('obj-cmd').checked = false;
  document.getElementById('obj-rd').value = '0';
  document.getElementById('obj-random').checked = false;
  document.getElementById('obj-random-min').value = '0';
  document.getElementById('obj-random-max').value = '100';
  document.getElementById('obj-random-interval').value = '5';
  document.getElementById('pa-section').style.display = 'none';

  updateModalFields();
  modalOverlay.style.display = 'flex';
}

function openEdit(type, instance) {
  const obj = allObjects.find(o => o.type === type && o.instance === instance);
  if (!obj) return;

  editingObject = { type, instance };
  modalTitle.textContent = 'Edit point';
  modalSubmit.textContent = 'Save changes';

  document.getElementById('obj-type').value = obj.type;
  document.getElementById('obj-type').disabled = true;
  document.getElementById('obj-instance').value = obj.instance;
  document.getElementById('obj-instance').disabled = true;
  document.getElementById('obj-name').value = obj.name;
  document.getElementById('obj-desc').value = obj.description || '';
  document.getElementById('obj-pv').value = obj.present_value;
  document.getElementById('obj-units').value = obj.units;
  document.getElementById('obj-cmd').checked = obj.commandable;
  document.getElementById('obj-rd').value = obj.relinquish_default;

  // Random fields
  document.getElementById('obj-random').checked = obj.random_enabled || false;
  document.getElementById('obj-random-min').value = obj.random_min != null ? obj.random_min : '0';
  document.getElementById('obj-random-max').value = obj.random_max != null ? obj.random_max : '100';
  document.getElementById('obj-random-interval').value = obj.random_interval || 5;

  if (obj.state_text) {
    document.getElementById('obj-states').value = obj.state_text.join(', ');
  }

  updateModalFields();

  if (obj.commandable && obj.priority_array) {
    document.getElementById('pa-section').style.display = '';
    renderPriorityArray(obj);
  } else {
    document.getElementById('pa-section').style.display = 'none';
  }

  modalOverlay.style.display = 'flex';
}

function closeModal() {
  modalOverlay.style.display = 'none';
  editingObject = null;
}

function updateModalFields() {
  const type = document.getElementById('obj-type').value;
  const isMS = MULTISTATE_TYPES.has(type);
  const isAnalog = ANALOG_TYPES.has(type);
  const canCmd = COMMANDABLE_OPT.has(type);
  const alwaysCmd = COMMANDABLE_ALWAYS.has(type);

  document.getElementById('ms-fields').style.display = isMS ? '' : 'none';
  document.getElementById('cmd-fields').style.display = (canCmd || alwaysCmd) ? '' : 'none';
  document.getElementById('random-fields').style.display = isAnalog ? '' : 'none';

  if (alwaysCmd) {
    document.getElementById('obj-cmd').checked = true;
    document.getElementById('obj-cmd').disabled = true;
  } else if (canCmd) {
    document.getElementById('obj-cmd').disabled = false;
  } else {
    document.getElementById('obj-cmd').checked = false;
    document.getElementById('obj-cmd').disabled = true;
  }
}

const PA_LABELS = [
  'Manual-Life Safety','Auto-Life Safety','Available','Available',
  'Critical Equipment','Minimum On/Off','Available','Manual Operator',
  'Available','Available','Available','Available',
  'Available','Available','Available','Available',
];

function renderPriorityArray(obj) {
  const grid = document.getElementById('pa-grid');
  const pvResult = document.getElementById('pa-pv-result');
  grid.innerHTML = '';
  if (!obj.priority_array) { pvResult.innerHTML = ''; return; }

  obj.priority_array.forEach((val, i) => {
    const slot = document.createElement('div');
    slot.className = 'pa-slot' + (val !== null ? ' active' : '');
    slot.title = `P${i+1}: ${PA_LABELS[i]}`;

    const label = document.createElement('span');
    label.className = 'pa-slot__label';
    label.textContent = `P${i + 1}`;
    slot.appendChild(label);

    const valSpan = document.createElement('span');
    valSpan.className = 'pa-slot__value';
    valSpan.textContent = val !== null ? String(val) : '—';
    slot.appendChild(valSpan);

    slot.onclick = () => editPrioritySlot(obj, i, slot);
    grid.appendChild(slot);
  });

  updatePVResult(obj);
}

function editPrioritySlot(obj, slotIdx, slotEl) {
  if (slotEl.querySelector('input')) return;
  const oldVal = obj.priority_array[slotIdx];

  slotEl.classList.add('editing');
  const valSpan = slotEl.querySelector('.pa-slot__value');
  const input = document.createElement('input');
  input.className = 'pa-slot__input';
  input.type = 'text';
  input.value = oldVal !== null ? String(oldVal) : '';
  input.placeholder = '—';
  valSpan.textContent = '';
  valSpan.appendChild(input);
  input.focus();
  input.select();

  const commit = async () => {
    slotEl.classList.remove('editing');
    const raw = input.value.trim();
    const newVal = raw === '' ? null : (isNaN(Number(raw)) ? raw : Number(raw));

    try {
      const resp = await fetchJSON(`/api/objects/${obj.type}/${obj.instance}/priority`, {
        method: 'PUT',
        body: JSON.stringify({ slot: slotIdx + 1, value: newVal }),
      });
      obj.priority_array = resp.priority_array;
      obj.present_value = resp.present_value;
      renderPriorityArray(obj);
      // update PV field in modal
      document.getElementById('obj-pv').value = resp.present_value;
      renderTable();
    } catch (e) {
      toast(e.message || 'Priority write failed', 'error');
      valSpan.textContent = oldVal !== null ? String(oldVal) : '—';
    }
  };

  input.onblur = commit;
  input.onkeydown = (e) => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') {
      slotEl.classList.remove('editing');
      valSpan.textContent = oldVal !== null ? String(oldVal) : '—';
    }
  };
}

async function clearAllPriority() {
  if (!editingObject) return;
  const obj = allObjects.find(o => o.type === editingObject.type && o.instance === editingObject.instance);
  if (!obj) return;

  if (!await modalConfirm(
    'Clear all priority slots? Present value will revert to relinquish default.',
    'Clear priority array', 'Clear all', true
  )) return;

  for (let i = 0; i < 16; i++) {
    if (obj.priority_array[i] !== null) {
      try {
        const resp = await fetchJSON(`/api/objects/${obj.type}/${obj.instance}/priority`, {
          method: 'PUT',
          body: JSON.stringify({ slot: i + 1, value: null }),
        });
        obj.priority_array = resp.priority_array;
        obj.present_value = resp.present_value;
      } catch (e) {}
    }
  }
  renderPriorityArray(obj);
  document.getElementById('obj-pv').value = obj.present_value;
  renderTable();
  toast('Priority array cleared', 'success');
}

function updatePVResult(obj) {
  const pvResult = document.getElementById('pa-pv-result');
  const activeSlot = obj.priority_array.findIndex(v => v !== null);
  if (activeSlot >= 0) {
    pvResult.innerHTML = `Present Value = <strong>${obj.present_value}</strong> (from P${activeSlot + 1}: ${PA_LABELS[activeSlot]})`;
  } else {
    pvResult.innerHTML = `Present Value = <strong>${obj.present_value}</strong> (relinquish default)`;
  }
}

async function handleModalSubmit(e) {
  e.preventDefault();

  const type = document.getElementById('obj-type').value;
  const instance = Number(document.getElementById('obj-instance').value);
  const name = document.getElementById('obj-name').value.trim();
  const desc = document.getElementById('obj-desc').value.trim();
  const pvRaw = document.getElementById('obj-pv').value;
  const units = Number(document.getElementById('obj-units').value);
  const commandable = document.getElementById('obj-cmd').checked;
  const rdRaw = document.getElementById('obj-rd').value;

  let pv = isNaN(Number(pvRaw)) ? pvRaw : Number(pvRaw);
  let rd = isNaN(Number(rdRaw)) ? rdRaw : Number(rdRaw);

  // Random config
  const randomEnabled = document.getElementById('obj-random').checked;
  const randomMin = parseFloat(document.getElementById('obj-random-min').value) || 0;
  const randomMax = parseFloat(document.getElementById('obj-random-max').value) || 100;
  const randomInterval = parseFloat(document.getElementById('obj-random-interval').value) || 5;

  if (editingObject) {
    const body = { present_value: pv, description: desc, name };
    try {
      const result = await fetchJSON(`/api/objects/${editingObject.type}/${editingObject.instance}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      const idx = allObjects.findIndex(o => o.type === editingObject.type && o.instance === editingObject.instance);
      if (idx >= 0) Object.assign(allObjects[idx], result);

      // Update random config
      if (ANALOG_TYPES.has(editingObject.type)) {
        await fetchJSON(`/api/objects/${editingObject.type}/${editingObject.instance}/random`, {
          method: 'PUT',
          body: JSON.stringify({
            random_enabled: randomEnabled,
            random_min: randomMin,
            random_max: randomMax,
            random_interval: randomInterval,
          }),
        });
      }

      renderTable();
      closeModal();
      toast('Saved', 'success');
    } catch (e) {
      toast(e.message || 'Update failed', 'error');
    }
  } else {
    const body = {
      type, instance, name, description: desc,
      present_value: pv, units, commandable, relinquish_default: rd,
    };

    if (MULTISTATE_TYPES.has(type)) {
      const stateStr = document.getElementById('obj-states').value;
      const states = stateStr.split(',').map(s => s.trim()).filter(Boolean);
      body.number_of_states = states.length;
      body.state_text = states;
    }

    try {
      const result = await fetchJSON('/api/objects', {
        method: 'POST',
        body: JSON.stringify(body),
      });

      // Set random config after creation
      if (randomEnabled && ANALOG_TYPES.has(type)) {
        await fetchJSON(`/api/objects/${type}/${instance}/random`, {
          method: 'PUT',
          body: JSON.stringify({
            random_enabled: randomEnabled,
            random_min: randomMin,
            random_max: randomMax,
            random_interval: randomInterval,
          }),
        });
      }

      closeModal();
      toast('Point added', 'success');
    } catch (e) {
      toast(e.message || 'Create failed', 'error');
    }
  }
}

// ============================================================
// Connection form
// ============================================================

async function handleConnSubmit(e) {
  e.preventDefault();
  const body = {
    connection: {
      bacnet_ip: {
        enabled: true,
        interface: document.getElementById('cfg-interface').value,
        port: Number(document.getElementById('cfg-port').value),
        apdu_timeout_ms: Number(document.getElementById('cfg-apdu-timeout').value),
        apdu_retries: Number(document.getElementById('cfg-apdu-retries').value),
        segmentation: 'both',
        max_apdu_length: 1476,
      },
      mstp: {
        enabled: document.getElementById('cfg-mstp-enabled')?.checked || false,
        serial_port: document.getElementById('cfg-serial')?.value || '',
        baud: Number(document.getElementById('cfg-baud')?.value || 38400),
        mac_address: Number(document.getElementById('cfg-mac')?.value || 1),
        max_master: Number(document.getElementById('cfg-max-master')?.value || 127),
        max_info_frames: Number(document.getElementById('cfg-max-info')?.value || 1),
      },
      network_number: Number(document.getElementById('cfg-network').value),
    },
    device: {
      instance: Number(document.getElementById('cfg-instance').value),
      name: document.getElementById('cfg-name').value,
      vendor_id: 0,
      vendor_name: 'BMS Simulator',
    },
  };

  try {
    const result = await fetchJSON('/api/config', {
      method: 'PUT',
      body: JSON.stringify(body),
    });
    deviceNameEl.textContent = body.device.name;
    deviceIdEl.textContent = body.device.instance;
    toast(result.restarted ? 'Applied — BACnet restarted' : 'Applied', 'success');
  } catch (e) {
    toast(e.message || 'Failed to apply', 'error');
  }
}

// ============================================================
// Sidebar toggles
// ============================================================

function initToggles() {
  document.querySelectorAll('.sidebar__toggle').forEach(btn => {
    const target = document.getElementById(btn.dataset.target);
    const isCollapsed = target.classList.contains('collapsed');
    btn.setAttribute('aria-expanded', !isCollapsed);

    btn.onclick = () => {
      const collapsed = target.classList.toggle('collapsed');
      btn.setAttribute('aria-expanded', !collapsed);
    };
  });
}

// ============================================================
// Helpers
// ============================================================

async function fetchJSON(url, opts = {}) {
  const headers = {};
  if (opts.body && typeof opts.body === 'string') {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(API + url, { headers, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

function toast(message, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast--${type}`;
  el.textContent = message;
  toastContainer.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 200); }, 3000);
}

let _confirmResolve = null;

function modalConfirm(message, title = 'Confirm', okLabel = 'OK', okDanger = false) {
  return new Promise((resolve) => {
    _confirmResolve = resolve;
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-message').textContent = message;
    const okBtn = document.getElementById('confirm-ok-btn');
    okBtn.textContent = okLabel;
    okBtn.className = okDanger ? 'btn btn--danger' : 'btn btn--primary';
    document.getElementById('confirm-overlay').style.display = 'flex';
  });
}

function resolveConfirm(result) {
  document.getElementById('confirm-overlay').style.display = 'none';
  if (_confirmResolve) { _confirmResolve(result); _confirmResolve = null; }
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ============================================================
// Init
// ============================================================

document.getElementById('btn-add-point').onclick = openAdd;
document.getElementById('modal-close').onclick = closeModal;
document.getElementById('modal-cancel').onclick = closeModal;
modalOverlay.onclick = (e) => { if (e.target === modalOverlay) closeModal(); };
modalForm.onsubmit = handleModalSubmit;
document.getElementById('conn-form').onsubmit = handleConnSubmit;
document.getElementById('obj-type').onchange = updateModalFields;
searchInput.oninput = renderTable;

initToggles();
loadConfig();
loadObjects();
connectWS();

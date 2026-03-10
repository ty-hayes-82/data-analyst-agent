// State
let currentContract = null;
let currentRunId = null;
let pollTimer = null;

// --- Tab navigation ---
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
});

function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.section').forEach(s => s.classList.toggle('active', s.id === name));
  if (name === 'history') loadHistory();
  if (name === 'monitor' && currentRunId) pollRun(currentRunId);
}

// --- Load datasets ---
async function loadDatasets() {
  const res = await fetch('/api/datasets');
  const datasets = await res.json();
  const sel = document.getElementById('dataset-select');
  sel.innerHTML = '<option value="">-- Select a dataset --</option>';
  datasets.forEach(d => {
    const safeName = (d.display_name || d.name).replace(/"/g, '&quot;');
    sel.innerHTML += `<option value="${d.id}" data-name="${safeName}">${escapeHtml(d.display_name || d.name)} (${escapeHtml(d.name)})</option>`;
  });
  sel.addEventListener('change', onDatasetChange);
}

async function onDatasetChange() {
  const sel = document.getElementById('dataset-select');
  const id = sel.value;
  if (!id) {
    document.getElementById('run-btn').disabled = true;
    return;
  }

  const res = await fetch(`/api/datasets/${id}/contract`);
  if (!res.ok) {
    alert(`Failed to load contract for ${id}`);
    return;
  }
  currentContract = await res.json();
  const c = currentContract;

  // Description
  const descEl = document.getElementById('dataset-description');
  const infoEl = document.getElementById('dataset-info');
  if (c.description) {
    descEl.textContent = c.description;
    infoEl.style.display = 'block';
  } else {
    infoEl.style.display = 'none';
  }

  // Metrics
  const mg = document.getElementById('metrics-group');
  const metricsActions = document.getElementById('metrics-actions');
  mg.innerHTML = '';
  const metricsList = c.metrics || [];
  metricsList.forEach(m => {
    mg.innerHTML += `<label><input type="checkbox" name="metric" value="${m.name}" checked> ${m.name}${m.description ? ' (' + m.description.slice(0, 50) + ')' : ''}</label>`;
  });
  if (metricsActions) {
    metricsActions.style.display = metricsList.length > 0 ? 'inline' : 'none';
  }

  // Hierarchies — editor with filtering
  renderHierarchyEditor(c);

  // Time range
  const rangeMonths = (c.time || {}).range_months || 24;
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - rangeMonths);
  document.getElementById('end-date').value = end.toISOString().split('T')[0];
  document.getElementById('start-date').value = start.toISOString().split('T')[0];

  // Depth
  const maxDepth = (c.reporting || {}).max_drill_depth || 3;
  document.getElementById('max-depth').value = Math.min(maxDepth, 5);
  document.getElementById('max-depth').max = maxDepth;

  // Frequency
  document.getElementById('frequency').value = (c.time || {}).frequency || 'unknown';

  document.getElementById('run-btn').disabled = false;
}

// --- Run analysis ---
document.getElementById('run-btn').addEventListener('click', submitRun);

async function submitRun() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  btn.textContent = 'Starting...';

  const sel = document.getElementById('dataset-select');
  const metrics = [...document.querySelectorAll('input[name="metric"]:checked')].map(c => c.value);
  const hierarchy = document.getElementById('hierarchy-select')?.value || '';

  const focusChecks = [...document.querySelectorAll('input[name="focus"]:checked')].map(c => c.value);
  const customFocus = document.getElementById('custom-focus')?.value?.trim() || '';

  const hierarchyLevels = getCustomHierarchyLevels();
  const hierarchyFilters = getHierarchyFilters();

  const body = {
    dataset_id: sel.value,
    dataset_name: sel.options[sel.selectedIndex].dataset.name || sel.value,
    metrics,
    hierarchy,
    hierarchy_levels: hierarchyLevels,
    hierarchy_filters: hierarchyFilters,
    analysis_focus: focusChecks,
    custom_focus: customFocus,
    max_drill_depth: parseInt(document.getElementById('max-depth').value) || 3,
    start_date: document.getElementById('start-date').value,
    end_date: document.getElementById('end-date').value,
  };

  try {
    const res = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) {
      let errMsg = `Server error (${res.status})`;
      try { const errData = await res.json(); errMsg = errData.detail || errMsg; } catch { errMsg = await res.text().catch(() => errMsg); }
      throw new Error(errMsg);
    }
    const run = await res.json();
    currentRunId = run.id;
    showTab('monitor');
    pollRun(run.id);
  } catch (e) {
    alert('Failed to start run: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run Analysis';
  }
}

// --- Monitor ---
function pollRun(runId) {
  if (pollTimer) clearInterval(pollTimer);

  const render = async () => {
    const [runRes, logRes, progressRes] = await Promise.all([
      fetch(`/api/runs/${runId}`),
      fetch(`/api/runs/${runId}/log?lines=80`),
      fetch(`/api/runs/${runId}/progress`),
    ]);
    const run = await runRes.json();
    const log = await logRes.text();
    const progress = progressRes.ok ? await progressRes.json() : { stages: [], percent: 0 };

    const mc = document.getElementById('monitor-content');
    const statusClass = `badge-${run.status}`;
    const elapsed = run.finished_at
      ? Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000)
      : Math.round((Date.now() - new Date(run.started_at + 'Z').getTime()) / 1000);

    const pct = progress.percent || 0;
    const currentLabel = (progress.stages || []).find(s => s.status === 'running')?.label || '';

    // Build stage timeline
    const stagesHtml = (progress.stages || []).map(s => {
      const icon = s.status === 'completed' ? '&#10003;' : s.status === 'running' ? '&#9679;' : '&#9675;';
      const cls = `stage-${s.status}`;
      const dur = s.duration != null ? ` (${s.duration.toFixed(1)}s)` : '';
      return `<div class="pipeline-stage ${cls}"><span class="stage-icon">${icon}</span><span class="stage-label">${escapeHtml(s.label)}${dur}</span></div>`;
    }).join('');

    // Info badges
    const infoBadges = progress.info ? Object.entries(progress.info).map(([k, v]) =>
      `<span class="info-badge">${k.replace(/_/g, ' ')}: ${v}</span>`
    ).join('') : '';

    mc.innerHTML = `
      <div class="info-grid">
        <div class="info-card"><div class="label">Run ID</div><div class="value">${run.id}</div></div>
        <div class="info-card"><div class="label">Status</div><div class="value"><span class="badge ${statusClass}">${run.status}</span></div></div>
        <div class="info-card"><div class="label">Dataset</div><div class="value">${escapeHtml(run.dataset_name)}</div></div>
        <div class="info-card"><div class="label">Elapsed</div><div class="value">${elapsed}s</div></div>
        <div class="info-card"><div class="label">Metrics</div><div class="value">${(run.metrics || []).join(', ') || 'all'}</div></div>
        ${run.analysis_focus && run.analysis_focus.length ? `<div class="info-card"><div class="label">Focus</div><div class="value">${run.analysis_focus.map(f => f.replace(/_/g, ' ')).join(', ')}</div></div>` : ''}
      </div>

      <div class="progress-section">
        <div class="progress-header">
          <span class="progress-label">${run.status === 'running' ? (currentLabel || 'Processing...') : run.status === 'completed' ? 'Complete' : run.status}</span>
          <span class="progress-pct">${pct}%</span>
        </div>
        <div class="progress-bar-lg"><div class="progress-fill-lg ${run.status === 'completed' ? 'complete' : run.status === 'failed' ? 'failed' : ''}" style="width:${pct}%"></div></div>
        ${infoBadges ? `<div class="info-badges">${infoBadges}</div>` : ''}
      </div>

      <div class="pipeline-stages-section">
        <h3>Pipeline Stages</h3>
        <div class="pipeline-stages">${stagesHtml || '<span style="color:#8b949e">Waiting for pipeline to start...</span>'}</div>
      </div>

      ${run.status !== 'running' ? `<div class="actions"><button class="btn" onclick="viewResults('${run.id}')">View Results</button></div>` : ''}

      <details class="log-details" ${run.status !== 'running' ? '' : 'open'}>
        <summary>Live Log</summary>
        <div class="log-viewer" id="log-box">${escapeHtml(log)}</div>
      </details>
    `;
    const box = document.getElementById('log-box');
    if (box) box.scrollTop = box.scrollHeight;

    if (run.status !== 'running') {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  render();
  pollTimer = setInterval(render, 2000);
}

// --- History ---
async function loadHistory() {
  const res = await fetch('/api/runs');
  const runs = await res.json();
  const body = document.getElementById('history-body');

  if (!runs.length) {
    body.innerHTML = '<tr><td colspan="7" style="color:#8b949e">No runs yet</td></tr>';
    return;
  }

  body.innerHTML = runs.map(r => {
    const statusClass = `badge-${r.status}`;
    const elapsed = r.finished_at
      ? Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000) + 's'
      : r.status === 'running' ? 'running...' : '-';
    const started = new Date(r.started_at + 'Z').toLocaleString();
    return `<tr>
      <td>${r.id}</td>
      <td>${r.dataset_name || r.dataset_id}</td>
      <td>${(r.metrics || []).join(', ') || 'all'}</td>
      <td><span class="badge ${statusClass}">${r.status}</span></td>
      <td>${started}</td>
      <td>${elapsed}</td>
      <td>
        ${r.status === 'running' ? `<button class="btn btn-secondary" onclick="currentRunId='${r.id}';showTab('monitor')">Monitor</button>` : ''}
        ${r.status !== 'running' ? `<button class="btn btn-secondary" onclick="viewResults('${r.id}')">Results</button>` : ''}
      </td>
    </tr>`;
  }).join('');
}

// --- Results ---
async function viewResults(runId) {
  showTab('results');

  const [runRes, outputsRes] = await Promise.all([
    fetch(`/api/runs/${runId}`),
    fetch(`/api/runs/${runId}/outputs`),
  ]);
  const run = await runRes.json();
  const outputs = await outputsRes.json();

  // Info cards
  const info = document.getElementById('results-info');
  const elapsed = run.finished_at
    ? Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000)
    : '-';
  info.innerHTML = `
    <div class="info-card"><div class="label">Run ID</div><div class="value">${run.id}</div></div>
    <div class="info-card"><div class="label">Status</div><div class="value"><span class="badge badge-${run.status}">${run.status}</span></div></div>
    <div class="info-card"><div class="label">Duration</div><div class="value">${elapsed}s</div></div>
    <div class="info-card"><div class="label">Metrics</div><div class="value">${(run.metrics || []).join(', ')}</div></div>
  `;

  // File list
  const fl = document.getElementById('results-files');
  const categoryLabels = { executive_brief: 'Executive Brief', metric_report: 'Metric Report', alerts: 'Alerts', log: 'Log', cache: 'Cache', other: 'Other' };
  const sorted = [...outputs].sort((a, b) => {
    const order = ['executive_brief', 'metric_report', 'alerts', 'log', 'cache', 'other'];
    return order.indexOf(a.category) - order.indexOf(b.category);
  });

  fl.innerHTML = sorted.map(f => {
    const size = f.size > 1024 ? (f.size / 1024).toFixed(1) + ' KB' : f.size + ' B';
    return `<li>
      <span class="name" onclick="viewFile('${runId}', '${f.name}')">${f.name}</span>
      <span class="meta">${categoryLabels[f.category] || f.category} &middot; ${size}</span>
    </li>`;
  }).join('');

  document.getElementById('result-content').style.display = 'none';

  // Auto-load executive brief if available
  const brief = sorted.find(f => f.category === 'executive_brief' && f.name.endsWith('.md'));
  if (brief) viewFile(runId, brief.name);
}

async function viewFile(runId, filename) {
  const rc = document.getElementById('result-content');
  rc.style.display = 'block';
  rc.innerHTML = '<p style="color:#8b949e">Loading...</p>';

  const res = await fetch(`/api/runs/${runId}/files/${filename}`);
  const contentType = res.headers.get('content-type') || '';

  if (contentType.includes('html')) {
    // Markdown rendered to HTML
    const html = await res.text();
    // Extract body content
    const match = html.match(/<body>([\s\S]*)<\/body>/);
    rc.innerHTML = match ? match[1] : html;
  } else if (contentType.includes('json')) {
    const text = await res.text();
    try {
      rc.innerHTML = `<pre>${escapeHtml(JSON.stringify(JSON.parse(text), null, 2))}</pre>`;
    } catch {
      rc.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
    }
  } else {
    const text = await res.text();
    rc.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
  }
}

// --- Helpers ---
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function selectAllMetrics() {
  document.querySelectorAll('input[name="metric"]').forEach(cb => { cb.checked = true; });
}

function deselectAllMetrics() {
  document.querySelectorAll('input[name="metric"]').forEach(cb => { cb.checked = false; });
}


// --- Auto-detect Dataset ---
let detectedResult = null;

// Upload area interactions
document.addEventListener('DOMContentLoaded', () => {
  const area = document.getElementById('upload-area');
  const input = document.getElementById('file-input');
  if (!area || !input) return;

  area.addEventListener('click', () => input.click());
  area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('dragover'); });
  area.addEventListener('dragleave', () => area.classList.remove('dragover'));
  area.addEventListener('drop', e => {
    e.preventDefault();
    area.classList.remove('dragover');
    if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
  });
  input.addEventListener('change', () => { if (input.files.length) uploadFile(input.files[0]); });
});

async function uploadFile(file) {
  if (!file.name.endsWith('.csv')) {
    alert('Please upload a CSV file.');
    return;
  }

  document.getElementById('upload-area').style.display = 'none';
  document.getElementById('detect-progress').style.display = 'block';
  document.getElementById('detect-results').style.display = 'none';

  const bar = document.getElementById('detect-progress-bar');
  const status = document.getElementById('detect-status');

  bar.style.width = '20%';
  status.textContent = `Uploading ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)...`;

  const formData = new FormData();
  formData.append('file', file);

  try {
    bar.style.width = '50%';
    status.textContent = 'Analyzing dataset structure...';

    const res = await fetch('/api/datasets/detect', { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Detection failed');
    }

    bar.style.width = '100%';
    status.textContent = 'Analysis complete!';
    detectedResult = await res.json();

    setTimeout(() => renderDetectResults(detectedResult), 500);
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    bar.style.width = '0%';
    setTimeout(() => {
      document.getElementById('detect-progress').style.display = 'none';
      document.getElementById('upload-area').style.display = 'block';
    }, 3000);
  }
}

function renderDetectResults(result) {
  document.getElementById('detect-progress').style.display = 'none';
  document.getElementById('detect-results').style.display = 'block';

  const c = result.contract;
  const fi = result.file_info;

  // File info cards
  document.getElementById('detect-file-info').innerHTML = `
    <div class="info-card"><div class="label">File</div><div class="value">${fi.name}</div></div>
    <div class="info-card"><div class="label">Size</div><div class="value">${(fi.size_bytes / 1024 / 1024).toFixed(1)} MB</div></div>
    <div class="info-card"><div class="label">Columns</div><div class="value">${fi.total_columns}</div></div>
    <div class="info-card"><div class="label">Sampled Rows</div><div class="value">${fi.sampled_rows.toLocaleString()}</div></div>
  `;

  // Warnings
  const wDiv = document.getElementById('detect-warnings');
  if (result.warnings && result.warnings.length) {
    wDiv.innerHTML = `<div class="warning-box"><strong>Review needed:</strong><ul>${result.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('')}</ul></div>`;
  } else {
    wDiv.innerHTML = '';
  }

  // Basic fields
  document.getElementById('detect-name').value = c.name || '';
  document.getElementById('detect-display-name').value = c.display_name || '';
  document.getElementById('detect-description').value = c.description || '';

  // Time config
  const timeSelect = document.getElementById('detect-time-col');
  timeSelect.innerHTML = fi.headers.map(h =>
    `<option value="${h}" ${h === (c.time || {}).column ? 'selected' : ''}>${h}</option>`
  ).join('');
  document.getElementById('detect-frequency').value = (c.time || {}).frequency || 'unknown';

  // Confidence badges
  for (const [key, level] of Object.entries(result.confidence || {})) {
    const el = document.getElementById('conf-' + key.replace('_column', ''));
    if (el) { el.textContent = level; el.className = 'confidence-badge ' + level; }
  }

  // Metrics
  const ml = document.getElementById('detect-metrics-list');
  ml.innerHTML = (c.metrics || []).map((m, i) => {
    const det = (result.metric_details || [])[i] || {};
    const stats = det.stats || {};
    return `<div class="detect-item">
      <input type="checkbox" name="detect-metric" value="${i}" checked>
      <span class="item-name">${escapeHtml(m.column)}</span>
      <span class="item-type">${m.type}</span>
      <span class="item-detail">
        ${m.format} | range: ${stats.min ?? '?'} - ${stats.max ?? '?'} | mean: ${stats.mean ?? '?'}
      </span>
      <select onchange="detectedResult.contract.metrics[${i}].type=this.value">
        <option value="additive" ${m.type === 'additive' ? 'selected' : ''}>Additive</option>
        <option value="ratio" ${m.type === 'ratio' ? 'selected' : ''}>Ratio</option>
        <option value="non_additive" ${m.type === 'non_additive' ? 'selected' : ''}>Non-Additive</option>
      </select>
    </div>`;
  }).join('') || '<p style="color:#8b949e;padding:1em">No metrics detected</p>';

  // Dimensions
  const dl = document.getElementById('detect-dimensions-list');
  dl.innerHTML = (c.dimensions || []).map((d, i) => {
    const det = (result.dimension_details || [])[i] || {};
    const samples = (det.sample_values || []).slice(0, 5).join(', ');
    return `<div class="detect-item">
      <input type="checkbox" name="detect-dimension" value="${i}" checked>
      <span class="item-name">${escapeHtml(d.column)}</span>
      <span class="item-type">${d.role}</span>
      <span class="item-detail">${samples ? 'e.g. ' + escapeHtml(samples) : d.description}</span>
      <select onchange="detectedResult.contract.dimensions[${i}].role=this.value">
        <option value="primary" ${d.role === 'primary' ? 'selected' : ''}>Primary</option>
        <option value="secondary" ${d.role === 'secondary' ? 'selected' : ''}>Secondary</option>
        <option value="time" ${d.role === 'time' ? 'selected' : ''}>Time</option>
      </select>
    </div>`;
  }).join('') || '<p style="color:#8b949e;padding:1em">No dimensions detected</p>';

  // Hierarchies
  const hl = document.getElementById('detect-hierarchies-list');
  hl.innerHTML = (c.hierarchies || []).map((h, i) => `
    <div class="detect-item">
      <input type="checkbox" name="detect-hierarchy" value="${i}" checked>
      <span class="item-name">${escapeHtml(h.name)}</span>
      <span class="item-detail">${escapeHtml(h.description)}</span>
    </div>
  `).join('') || '<p style="color:#8b949e;padding:1em">No hierarchies detected. You can add them manually after saving.</p>';
}

async function confirmContract() {
  if (!detectedResult) return;

  const btn = document.getElementById('confirm-contract-btn');
  btn.disabled = true;
  btn.textContent = 'Saving...';

  // Apply user edits
  const c = detectedResult.contract;
  c.name = document.getElementById('detect-name').value;
  c.display_name = document.getElementById('detect-display-name').value;
  c.description = document.getElementById('detect-description').value;
  c.time.column = document.getElementById('detect-time-col').value;
  c.time.frequency = document.getElementById('detect-frequency').value;

  // Filter unchecked metrics
  const checkedMetrics = [...document.querySelectorAll('input[name="detect-metric"]:checked')].map(c => parseInt(c.value));
  c.metrics = c.metrics.filter((_, i) => checkedMetrics.includes(i));

  // Filter unchecked dimensions
  const checkedDims = [...document.querySelectorAll('input[name="detect-dimension"]:checked')].map(c => parseInt(c.value));
  c.dimensions = c.dimensions.filter((_, i) => checkedDims.includes(i));

  // Filter unchecked hierarchies
  const checkedHiers = [...document.querySelectorAll('input[name="detect-hierarchy"]:checked')].map(c => parseInt(c.value));
  c.hierarchies = c.hierarchies.filter((_, i) => checkedHiers.includes(i));

  try {
    const res = await fetch('/api/datasets/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contract: c, file_path: detectedResult.file_info.name }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Save failed');
    }
    const result = await res.json();
    alert('Dataset saved! You can now select it in the New Analysis tab.');
    resetUpload();
    loadDatasets();  // Refresh dataset list
    showTab('new-analysis');
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Confirm & Save Dataset';
  }
}

function resetUpload() {
  detectedResult = null;
  document.getElementById('upload-area').style.display = 'block';
  document.getElementById('detect-progress').style.display = 'none';
  document.getElementById('detect-results').style.display = 'none';
  document.getElementById('file-input').value = '';
}


// --- Hierarchy Editor ---
let hierarchyEditorOpen = false;
let currentHierarchyLevels = [];
let hierarchyFilterCache = {};

function renderHierarchyEditor(contract) {
  const sel = document.getElementById('hierarchy-select');
  const editBtn = document.getElementById('edit-hierarchy-btn');
  const filterDiv = document.getElementById('hierarchy-filters');

  sel.innerHTML = '';
  (contract.hierarchies || []).forEach((h, i) => {
    const levels = (h.children || []).join(' \u2192 ');
    sel.innerHTML += `<option value="${h.name}" ${i === 0 ? 'selected' : ''}>${h.name} (${levels})</option>`;
  });

  editBtn.style.display = contract.hierarchies?.length ? 'inline-block' : 'none';

  hierarchyEditorOpen = false;
  document.getElementById('hierarchy-level-editor').style.display = 'none';
  hierarchyFilterCache = {};

  if (contract.hierarchies?.length) {
    setHierarchyLevels(contract.hierarchies[0], contract);
  }

  sel.onchange = () => {
    const h = (contract.hierarchies || []).find(x => x.name === sel.value);
    if (h) {
      setHierarchyLevels(h, contract);
      renderHierarchyLevelsList(currentContract);
      renderHierarchyFilters();
    }
  };

  renderHierarchyFilters();
}

function setHierarchyLevels(hierarchy, contract) {
  const dims = contract.dimensions || [];
  currentHierarchyLevels = (hierarchy.children || []).map(childName => {
    const dim = dims.find(d => d.name === childName || d.column === childName);
    return {
      name: dim ? dim.name : childName,
      column: dim ? dim.column : childName,
      description: dim ? dim.description : ''
    };
  });
  hierarchyFilterCache = {};
}

function toggleHierarchyEditor() {
  hierarchyEditorOpen = !hierarchyEditorOpen;
  const editor = document.getElementById('hierarchy-level-editor');
  editor.style.display = hierarchyEditorOpen ? 'block' : 'none';
  if (hierarchyEditorOpen) {
    renderHierarchyLevelsList(currentContract);
  }
}

function renderHierarchyLevelsList(contract) {
  const list = document.getElementById('hierarchy-levels-list');
  const usedCols = new Set(currentHierarchyLevels.map(l => l.column));

  list.innerHTML = currentHierarchyLevels.map((level, i) => `
    <div class="hierarchy-level-item" draggable="true" data-index="${i}"
         ondragstart="onLevelDragStart(event)" ondragover="onLevelDragOver(event)"
         ondrop="onLevelDrop(event)" ondragend="onLevelDragEnd(event)">
      <span class="level-number">${i + 1}</span>
      <span class="level-name">${escapeHtml(level.name)}</span>
      <span class="level-col">${escapeHtml(level.column)}</span>
      <button class="btn-remove" onclick="removeHierarchyLevel(${i})" title="Remove level">&times;</button>
    </div>
  `).join('');

  const allDims = (contract?.dimensions || []).filter(d => d.role !== 'time' && !usedCols.has(d.column));
  const availDiv = document.getElementById('available-dimensions');
  const availList = document.getElementById('available-dims-list');

  if (allDims.length) {
    availDiv.style.display = 'block';
    availList.innerHTML = allDims.map(d =>
      `<span class="dim-chip" onclick="addDimensionToHierarchy('${d.name}', '${d.column}', '${(d.description || '').replace(/'/g, "\\'")}')" title="${escapeHtml(d.description || '')}">${escapeHtml(d.name)}</span>`
    ).join('');
  } else {
    availDiv.style.display = 'none';
  }
}

function addDimensionToHierarchy(name, column, description) {
  currentHierarchyLevels.push({ name, column, description });
  renderHierarchyLevelsList(currentContract);
  renderHierarchyFilters();
}

function removeHierarchyLevel(index) {
  const removed = currentHierarchyLevels.splice(index, 1)[0];
  if (removed) delete hierarchyFilterCache[removed.column];
  renderHierarchyLevelsList(currentContract);
  renderHierarchyFilters();
}

function addHierarchyLevel() {
  document.getElementById('available-dimensions').style.display = 'block';
}

let dragIndex = null;
function onLevelDragStart(e) {
  dragIndex = parseInt(e.target.closest('.hierarchy-level-item').dataset.index);
  e.target.closest('.hierarchy-level-item').classList.add('dragging');
}
function onLevelDragOver(e) { e.preventDefault(); }
function onLevelDrop(e) {
  e.preventDefault();
  const dropIndex = parseInt(e.target.closest('.hierarchy-level-item').dataset.index);
  if (dragIndex !== null && dragIndex !== dropIndex) {
    const [moved] = currentHierarchyLevels.splice(dragIndex, 1);
    currentHierarchyLevels.splice(dropIndex, 0, moved);
    renderHierarchyLevelsList(currentContract);
  }
}
function onLevelDragEnd(e) {
  dragIndex = null;
  document.querySelectorAll('.hierarchy-level-item').forEach(el => el.classList.remove('dragging'));
}

// --- Hierarchy Filters ---
async function renderHierarchyFilters() {
  const container = document.getElementById('hierarchy-filter-levels');
  const wrapper = document.getElementById('hierarchy-filters');

  if (!currentHierarchyLevels.length || !currentContract) {
    wrapper.style.display = 'none';
    return;
  }

  wrapper.style.display = 'block';
  container.innerHTML = currentHierarchyLevels.map((level, i) => {
    const cached = hierarchyFilterCache[level.column];
    const activeCount = cached?.selected ? cached.selected.size : 0;
    const totalCount = cached?.values ? cached.values.length : '...';
    const badge = activeCount > 0 ? `<span class="filter-active-badge">${activeCount} selected</span>` : '';
    return `
      <div class="hierarchy-filter-level" id="filter-level-${i}">
        <div class="filter-header" onclick="toggleFilterLevel(${i}, '${level.column}')">
          <span class="filter-title">${escapeHtml(level.name)}${badge}</span>
          <span>
            <span class="filter-count">${totalCount} values</span>
            <span class="filter-toggle">&#9660;</span>
          </span>
        </div>
        <div class="filter-body" id="filter-body-${i}">
          <input type="text" class="filter-search" placeholder="Search values..." oninput="filterSearchValues(${i}, '${level.column}', this.value)">
          <div class="filter-values" id="filter-values-${i}">Loading...</div>
          <div class="filter-actions">
            <button onclick="selectAllFilter(${i}, '${level.column}')">Select All</button>
            <button onclick="deselectAllFilter(${i}, '${level.column}')">Deselect All</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

async function toggleFilterLevel(index, column) {
  const el = document.getElementById(`filter-level-${index}`);
  const isExpanded = el.classList.contains('expanded');

  if (isExpanded) {
    el.classList.remove('expanded');
    return;
  }

  el.classList.add('expanded');

  if (!hierarchyFilterCache[column]) {
    const datasetId = document.getElementById('dataset-select').value;
    try {
      const res = await fetch(`/api/datasets/${encodeURIComponent(datasetId)}/dimension-values/${encodeURIComponent(column)}`);
      if (res.ok) {
        const data = await res.json();
        hierarchyFilterCache[column] = {
          values: data.values,
          selected: new Set(),
          truncated: data.truncated
        };
      } else {
        hierarchyFilterCache[column] = { values: [], selected: new Set(), truncated: false };
      }
    } catch {
      hierarchyFilterCache[column] = { values: [], selected: new Set(), truncated: false };
    }
    renderFilterCount(index, column);
  }

  renderFilterValues(index, column);
}

function renderFilterValues(index, column, searchTerm) {
  const cache = hierarchyFilterCache[column];
  if (!cache) return;

  const container = document.getElementById(`filter-values-${index}`);
  let values = cache.values;
  if (searchTerm) {
    const lower = searchTerm.toLowerCase();
    values = values.filter(v => v.toLowerCase().includes(lower));
  }

  if (values.length === 0) {
    container.innerHTML = '<span style="color:#8b949e;font-size:0.85em">No values found</span>';
    return;
  }

  const shown = values.slice(0, 200);
  container.innerHTML = shown.map(v => {
    const checked = cache.selected.size === 0 || cache.selected.has(v) ? 'checked' : '';
    const safeV = v.replace(/'/g, "\\'").replace(/"/g, '&quot;');
    return `<label><input type="checkbox" ${checked} onchange="onFilterValueChange('${safeV}', '${column}', this.checked, ${index})"> ${escapeHtml(v)}</label>`;
  }).join('');

  if (values.length > 200) {
    container.innerHTML += `<span style="color:#8b949e;font-size:0.8em;width:100%;display:block;margin-top:0.5em">Showing 200 of ${values.length} — use search to narrow</span>`;
  }
}

function onFilterValueChange(value, column, checked, index) {
  const cache = hierarchyFilterCache[column];
  if (!cache) return;

  if (cache.selected.size === 0 && !checked) {
    cache.values.forEach(v => { if (v !== value) cache.selected.add(v); });
  } else if (checked) {
    cache.selected.add(value);
    if (cache.selected.size === cache.values.length) {
      cache.selected.clear();
    }
  } else {
    cache.selected.delete(value);
  }

  renderFilterCount(index, column);
}

function renderFilterCount(index, column) {
  const cache = hierarchyFilterCache[column];
  if (!cache) return;

  const titleEl = document.querySelector(`#filter-level-${index} .filter-title`);
  const countEl = document.querySelector(`#filter-level-${index} .filter-count`);
  const level = currentHierarchyLevels[index];

  countEl.textContent = `${cache.values.length} values`;

  const badge = cache.selected.size > 0 && cache.selected.size < cache.values.length
    ? `<span class="filter-active-badge">${cache.selected.size} of ${cache.values.length}</span>`
    : '';
  titleEl.innerHTML = `${escapeHtml(level.name)}${badge}`;
}

function filterSearchValues(index, column, term) {
  renderFilterValues(index, column, term);
}

function selectAllFilter(index, column) {
  const cache = hierarchyFilterCache[column];
  if (!cache) return;
  cache.selected.clear();
  renderFilterValues(index, column);
  renderFilterCount(index, column);
}

function deselectAllFilter(index, column) {
  const cache = hierarchyFilterCache[column];
  if (!cache) return;
  cache.selected = new Set(['__none__']);
  renderFilterValues(index, column);
  renderFilterCount(index, column);
}

function clearAllFilters() {
  hierarchyFilterCache = {};
  renderHierarchyFilters();
}

function getCustomHierarchyLevels() {
  if (!hierarchyEditorOpen || !currentHierarchyLevels.length) return [];
  return currentHierarchyLevels.map(l => l.column);
}

function getHierarchyFilters() {
  const filters = {};
  for (const [column, cache] of Object.entries(hierarchyFilterCache)) {
    if (cache.selected.size > 0 && !cache.selected.has('__none__')) {
      filters[column] = [...cache.selected];
    }
  }
  return filters;
}


// --- Init ---
loadDatasets();

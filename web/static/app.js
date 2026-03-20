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
    sel.innerHTML += `<option value="${d.id}" data-name="${safeName}">${escapeHtml(d.display_name || d.name)}</option>`;
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

  // Load saved defaults (from editor's "Analysis Defaults" section)
  const dRes = await fetch(`/api/datasets/${encodeURIComponent(id)}/defaults`);
  const savedDefaults = dRes.ok ? await dRes.json() : {};

  // Description
  const descEl = document.getElementById('dataset-description');
  const infoEl = document.getElementById('dataset-info');
  if (c.description) {
    descEl.textContent = c.description;
    infoEl.style.display = 'block';
  } else {
    infoEl.style.display = 'none';
  }

  // Metrics — grouped by brief_category, using display names
  const mg = document.getElementById('metrics-group');
  mg.innerHTML = '';
  const metricsByCategory = {};
  (c.metrics || []).forEach(m => {
    const cat = m.brief_category || 'Other';
    if (!metricsByCategory[cat]) metricsByCategory[cat] = [];
    metricsByCategory[cat].push(m);
  });
  // Use saved defaults if available, otherwise fall back to top 8 metrics
  const defaultMetrics = (savedDefaults.metrics && savedDefaults.metrics.length > 0)
    ? savedDefaults.metrics
    : (c.metrics || []).slice(0, 8).map(m => m.name);
  for (const [cat, metrics] of Object.entries(metricsByCategory)) {
    const catDiv = document.createElement('div');
    catDiv.className = 'metrics-group-category';
    catDiv.innerHTML = `<div class="category-header">${cat}</div>`;
    const checkboxDiv = document.createElement('div');
    checkboxDiv.className = 'checkbox-group';
    metrics.forEach(m => {
      const displayName = m.display_name || m.brief_label || m.name;
      const checked = defaultMetrics.includes(m.name) ? 'checked' : '';
      checkboxDiv.innerHTML += `<label><input type="checkbox" name="metric" value="${m.name}" ${checked}> ${displayName}</label>`;
    });
    catDiv.appendChild(checkboxDiv);
    mg.appendChild(catDiv);
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

  // Frequency (optional element)
  const freqEl = document.getElementById('frequency');
  if (freqEl) freqEl.value = (c.time || {}).frequency || 'unknown';

  // Apply saved defaults for period type, brief style, and focus
  const periodEl = document.getElementById('period-type');
  if (periodEl && savedDefaults.period_type) periodEl.value = savedDefaults.period_type;
  const briefEl = document.getElementById('brief-style');
  if (briefEl && savedDefaults.brief_style) briefEl.value = savedDefaults.brief_style;
  if (savedDefaults.focus && savedDefaults.focus.length > 0) {
    document.querySelectorAll('input[name="focus"]').forEach(cb => {
      cb.checked = savedDefaults.focus.includes(cb.value);
    });
  }

  document.getElementById('run-btn').disabled = false;
  activeDimFilters = {};
  if (typeof populateDimFilterSelect === 'function') populateDimFilterSelect();
  if (typeof renderActiveDimFilters === 'function') renderActiveDimFilters();
  if (typeof updateStepSummaries === 'function') updateStepSummaries();
}

// --- Run analysis ---
document.getElementById('run-btn').addEventListener('click', submitRun);

async function submitRun() {
  // Validate form before submission
  if (typeof validateForm === 'function' && !validateForm()) return;

  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  const originalHTML = btn.innerHTML;
  btn.innerHTML = '<span class="btn-icon">⏳</span> Starting Analysis...';

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
    period_type: document.getElementById('period-type')?.value || '',
    brief_style: document.getElementById('brief-style')?.value || 'ceo',
    dimension_filters: getDimensionFilters(),
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
    const userMsg = e.message.includes('Server error') 
      ? 'Unable to start analysis. Please try again or contact support.' 
      : 'Error: ' + e.message;
    alert(userMsg);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHTML;
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
    const displayName = h.display_name || h.name;
    const levelCount = (h.children || h.levels || []).length;
    sel.innerHTML += `<option value="${h.name}" ${i === 0 ? 'selected' : ''}>${escapeHtml(displayName)} - ${levelCount} levels</option>`;
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
  currentHierarchyLevels = (hierarchy.children || hierarchy.levels || []).map(childName => {
    const dim = dims.find(d => d.name === childName || d.column === childName);
    return {
      name: dim ? (dim.display_name || dim.name) : childName,
      column: dim ? dim.column : childName,
      displayName: dim ? (dim.display_name || dim.name) : childName,
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
      <span class="level-name">${escapeHtml(level.displayName || level.name)}</span>
      <button class="btn-remove" onclick="removeHierarchyLevel(${i})" title="Remove level">&times;</button>
    </div>
  `).join('');

  const allDims = (contract?.dimensions || []).filter(d => d.role !== 'time' && !usedCols.has(d.column));
  const availDiv = document.getElementById('available-dimensions');
  const availList = document.getElementById('available-dims-list');

  if (allDims.length) {
    availDiv.style.display = 'block';
    availList.innerHTML = allDims.map(d =>
      `<span class="dim-chip" onclick="addDimensionToHierarchy('${d.name}', '${d.column}', '${(d.description || '').replace(/'/g, "\\'")}')" title="${escapeHtml(d.description || '')}">${escapeHtml(d.display_name || d.name)}</span>`
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

function addCustomFilterValue(index, column) {
  const searchInput = document.querySelector(`#filter-level-${index} .filter-search`);
  const value = searchInput?.value?.trim();
  if (!value) return;
  if (!hierarchyFilterCache[column]) {
    hierarchyFilterCache[column] = { values: [], selected: new Set(), truncated: false };
  }
  if (!hierarchyFilterCache[column].values.includes(value)) {
    hierarchyFilterCache[column].values.unshift(value);
  }
  hierarchyFilterCache[column].selected.add(value);
  searchInput.value = '';
  renderFilterValues(index, column);
  renderFilterCount(index, column);
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
          <span class="filter-title">${escapeHtml(level.displayName || level.name)}${badge}</span>
          <span>
            <span class="filter-count">${totalCount} values</span>
            <span class="filter-toggle">&#9660;</span>
          </span>
        </div>
        <div class="filter-body" id="filter-body-${i}">
          <input type="text" class="filter-search" placeholder="Search or type a value..." oninput="filterSearchValues(${i}, '${level.column}', this.value)">
          <div class="filter-values" id="filter-values-${i}">Loading...</div>
          <div class="filter-actions">
            <button onclick="selectAllFilter(${i}, '${level.column}')">Select All</button>
            <button onclick="deselectAllFilter(${i}, '${level.column}')">Deselect All</button>
            <button onclick="addCustomFilterValue(${i}, '${level.column}')">+ Add Typed Value</button>
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


// --- Dimension Filters (independent of hierarchy) ---
let activeDimFilters = {};

function populateDimFilterSelect() {
  const sel = document.getElementById('dim-filter-select');
  if (!sel || !currentContract) return;
  const dims = currentContract.dimensions || [];
  sel.innerHTML = '<option value="">+ Add dimension filter...</option>';
  dims.forEach(d => {
    if (!activeDimFilters[d.column]) {
      sel.innerHTML += `<option value="${d.column}">${escapeHtml(d.display_name || d.name)}</option>`;
    }
  });
}

async function onDimFilterSelect() {
  const sel = document.getElementById('dim-filter-select');
  const col = sel.value;
  if (!col) return;

  const dim = (currentContract.dimensions || []).find(d => d.column === col);
  const displayName = dim ? (dim.display_name || dim.name) : col;

  // Fetch values
  const datasetId = document.getElementById('dataset-select').value;
  let values = [];
  try {
    const res = await fetch(`/api/datasets/${encodeURIComponent(datasetId)}/dimension-values/${encodeURIComponent(col)}`);
    if (res.ok) {
      const data = await res.json();
      values = data.values || [];
    }
  } catch {}

  activeDimFilters[col] = { displayName, values, selected: new Set(), typed: '' };
  sel.value = '';
  populateDimFilterSelect();
  renderActiveDimFilters();
}

function renderActiveDimFilters() {
  const container = document.getElementById('active-dim-filters');
  if (!container) return;
  container.innerHTML = Object.entries(activeDimFilters).map(([col, f]) => {
    const selectedBadge = f.selected.size > 0 ? ` (${f.selected.size} selected)` : '';
    const valueOptions = f.values.slice(0, 25).map(v => {
      const checked = f.selected.has(v) ? 'checked' : '';
      return `<label style="display:inline-flex;gap:0.3em;margin:0.2em 0.4em;font-size:0.85em"><input type="checkbox" ${checked} onchange="toggleDimFilter('${col}','${v.replace(/'/g,"\\'")}',this.checked)"> ${escapeHtml(v)}</label>`;
    }).join('');
    return `
      <div class="info-card" style="margin-top:0.5em;padding:0.8em">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong style="font-size:0.9em">${escapeHtml(f.displayName)}${selectedBadge}</strong>
          <button class="btn btn-sm btn-secondary" onclick="removeDimFilter('${col}')" style="padding:0.2em 0.5em;font-size:0.75em">Remove</button>
        </div>
        <div style="margin-top:0.5em">
          <input type="text" placeholder="Type a value and press Enter..." style="font-size:0.85em;margin-bottom:0.3em"
            onkeydown="if(event.key==='Enter'){addTypedDimFilter('${col}',this.value);this.value=''}">
          <div style="max-height:120px;overflow-y:auto">${valueOptions || '<span style="color:#8b949e;font-size:0.85em">Type a value above</span>'}</div>
        </div>
      </div>`;
  }).join('');
}

function toggleDimFilter(col, val, checked) {
  if (checked) activeDimFilters[col].selected.add(val);
  else activeDimFilters[col].selected.delete(val);
  renderActiveDimFilters();
}
function removeDimFilter(col) {
  delete activeDimFilters[col];
  populateDimFilterSelect();
  renderActiveDimFilters();
}
function addTypedDimFilter(col, val) {
  val = val.trim();
  if (!val || !activeDimFilters[col]) return;
  if (!activeDimFilters[col].values.includes(val)) activeDimFilters[col].values.unshift(val);
  activeDimFilters[col].selected.add(val);
  renderActiveDimFilters();
}

function getDimensionFilters() {
  const filters = {};
  for (const [col, f] of Object.entries(activeDimFilters)) {
    if (f.selected.size > 0) filters[col] = [...f.selected];
  }
  return filters;
}


// --- Contract Editor ---
let editorContract = null;

async function loadContractEditor() {
  const sel = document.getElementById('editor-dataset-select');
  const id = sel.value;
  if (!id) { document.getElementById('editor-content').style.display = 'none'; return; }

  const res = await fetch(`/api/datasets/${encodeURIComponent(id)}/contract`);
  if (!res.ok) { alert('Failed to load contract'); return; }
  editorContract = await res.json();
  document.getElementById('editor-content').style.display = 'block';
  document.getElementById('editor-nav').style.display = 'flex';
  editorDirty = false;
  const ind = document.getElementById('editor-dirty-indicator');
  if (ind) ind.style.display = 'none';
  const status = document.getElementById('editor-save-status');
  if (status) status.textContent = '';

  // Refresh section
  const ds = editorContract.data_source || {};
  const srcType = document.getElementById('ed-source-type');
  if (srcType) srcType.value = ds.type || 'unknown';
  const srcFile = document.getElementById('ed-source-file');
  if (srcFile) srcFile.value = ds.file || 'Not configured';

  // General
  document.getElementById('ed-display-name').value = editorContract.display_name || '';
  document.getElementById('ed-description').value = editorContract.description || '';
  document.getElementById('ed-variance-pct').value = (editorContract.materiality || {}).variance_pct || 5;
  document.getElementById('ed-max-depth').value = (editorContract.reporting || {}).max_drill_depth || 3;
  document.getElementById('ed-brief-levels').value = (editorContract.reporting || {}).executive_brief_drill_levels || 0;
  document.getElementById('ed-output-format').value = (editorContract.reporting || {}).output_format || 'pdf';

  // Metrics — grouped by category
  const ml = document.getElementById('ed-metrics-list');
  const metrics = editorContract.metrics || [];
  document.getElementById('editor-metrics-summary').textContent = `${metrics.length} metrics`;
  const metricsByCat = {};
  metrics.forEach((m, i) => {
    const cat = m.brief_category || 'Other';
    if (!metricsByCat[cat]) metricsByCat[cat] = [];
    metricsByCat[cat].push({ ...m, _idx: i });
  });
  // Populate category filter
  const catFilterSel = document.getElementById('ed-metrics-cat-filter');
  if (catFilterSel) {
    catFilterSel.innerHTML = '<option value="">All Categories</option>' +
      Object.keys(metricsByCat).map(c => `<option value="${c}">${c}</option>`).join('');
  }

  ml.innerHTML = Object.entries(metricsByCat).map(([cat, items]) => `
    <div style="margin-bottom:1em" data-category="${escapeHtml(cat)}">
      <div style="font-size:0.8em;color:#58a6ff;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.5em;padding-bottom:0.3em;border-bottom:1px solid #21262d">${escapeHtml(cat)} (${items.length})</div>
      ${items.map(m => `
        <div class="detect-item">
          <span class="item-name" style="min-width:160px">${escapeHtml(m.display_name || m.name)}</span>
          <span class="item-type">${m.format || 'float'}</span>
          <span class="item-type" style="background:${m.optimization==='minimize'?'#2d1016':'#0d2818'};color:${m.optimization==='minimize'?'#f85149':'#3fb950'}">${m.optimization || 'maximize'}</span>
          <input type="text" value="${escapeHtml(m.brief_label || m.display_name || m.name)}" style="max-width:140px"
            onchange="editorContract.metrics[${m._idx}].brief_label=this.value" title="Brief label">
          <select style="max-width:140px" onchange="editorContract.metrics[${m._idx}].brief_category=this.value" title="Category">
            ${['Revenue / yield','Network efficiency','Volume','Productivity','Capacity','Operations'].map(c =>
              `<option ${m.brief_category===c?'selected':''}>${c}</option>`).join('')}
          </select>
        </div>`).join('')}
    </div>`).join('');

  // Dimensions
  const dl = document.getElementById('ed-dimensions-list');
  const dims = editorContract.dimensions || [];
  document.getElementById('editor-dimensions-summary').textContent = `${dims.length} dimensions`;
  dl.innerHTML = dims.map((d, i) => `
    <div class="detect-item">
      <span class="item-name" style="min-width:160px">${escapeHtml(d.display_name || d.name)}</span>
      <span class="item-type">${d.role || 'secondary'}</span>
      <input type="text" value="${escapeHtml(d.display_name || d.name)}" style="max-width:160px"
        onchange="editorContract.dimensions[${i}].display_name=this.value" title="Display name">
      <select style="max-width:110px" onchange="editorContract.dimensions[${i}].role=this.value" title="Role: Primary = used in drill-down, Secondary = available for filtering">
        <option value="primary" ${d.role==='primary'?'selected':''}>Primary</option>
        <option value="secondary" ${d.role==='secondary'?'selected':''}>Secondary</option>
      </select>
    </div>`).join('');

  // Derived KPIs
  const kl = document.getElementById('ed-kpis-list');
  const kpis = editorContract.derived_kpis || [];
  document.getElementById('editor-kpis-summary').textContent = `${kpis.length} KPIs`;
  // Resolve display names for KPI formulas
  const metricNameMap = {};
  (editorContract.metrics || []).forEach(m => { metricNameMap[m.name] = m.display_name || m.brief_label || m.name; });
  kl.innerHTML = kpis.map(k => {
    const numName = metricNameMap[k.numerator] || k.numerator;
    const denName = metricNameMap[k.denominator] || k.denominator;
    const formula = `${numName} / ${denName}${k.multiply ? ' × ' + k.multiply : ''}`;
    return `<div class="detect-item">
      <span class="item-name" style="min-width:140px">${escapeHtml(k.display_name || k.brief_label || k.name)}</span>
      <span class="item-detail">${escapeHtml(formula)}</span>
      <span class="item-type">${k.format || 'float'}</span>
      <span class="item-type" style="background:#1f2937;color:#8b949e">system-managed</span>
    </div>`;
  }).join('') || '<p style="color:#8b949e;padding:0.5em">No derived KPIs defined</p>';

  // Load defaults
  const dRes = await fetch(`/api/datasets/${encodeURIComponent(id)}/defaults`);
  const defaults = dRes.ok ? await dRes.json() : {};
  const defaultMetrics = defaults.metrics || [];

  // Render default metrics as checkboxes
  const dmContainer = document.getElementById('ed-default-metrics-checkboxes');
  if (dmContainer) {
    dmContainer.innerHTML = (editorContract.metrics || []).map(m => {
      const checked = defaultMetrics.includes(m.name) ? 'checked' : '';
      return `<label><input type="checkbox" name="ed-default-metric" value="${m.name}" ${checked}> ${escapeHtml(m.display_name || m.name)}</label>`;
    }).join('');
  }

  document.getElementById('ed-default-period').value = defaults.period_type || '';
  document.getElementById('ed-default-brief').value = defaults.brief_style || 'ceo';
  document.querySelectorAll('#ed-default-focus input').forEach(cb => {
    cb.checked = (defaults.focus || []).includes(cb.value);
  });
}

async function saveContract() {
  const id = document.getElementById('editor-dataset-select').value;
  if (!id || !editorContract) return;
  editorContract.display_name = document.getElementById('ed-display-name').value;
  editorContract.description = document.getElementById('ed-description').value;
  if (!editorContract.materiality) editorContract.materiality = {};
  editorContract.materiality.variance_pct = parseFloat(document.getElementById('ed-variance-pct').value) || 5;
  if (!editorContract.reporting) editorContract.reporting = {};
  editorContract.reporting.max_drill_depth = parseInt(document.getElementById('ed-max-depth').value) || 3;
  editorContract.reporting.executive_brief_drill_levels = parseInt(document.getElementById('ed-brief-levels').value) || 0;
  editorContract.reporting.output_format = document.getElementById('ed-output-format').value;

  const res = await fetch(`/api/datasets/${encodeURIComponent(id)}/contract`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(editorContract)
  });
  return res.ok;
}

async function saveDefaults() {
  const id = document.getElementById('editor-dataset-select').value;
  if (!id) return;
  const defaults = {
    metrics: [...document.querySelectorAll('input[name="ed-default-metric"]:checked')].map(cb => cb.value),
    focus: [...document.querySelectorAll('#ed-default-focus input:checked')].map(cb => cb.value),
    period_type: document.getElementById('ed-default-period').value,
    brief_style: document.getElementById('ed-default-brief').value,
  };
  const res = await fetch(`/api/datasets/${encodeURIComponent(id)}/defaults`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(defaults)
  });
  return res.ok;
}

async function saveAll() {
  const id = document.getElementById('editor-dataset-select').value;
  if (!id) return;
  const contractOk = await saveContract();
  const defaultsOk = await saveDefaults();
  if (contractOk && defaultsOk) {
    editorDirty = false;
    const ind = document.getElementById('editor-dirty-indicator');
    if (ind) ind.style.display = 'none';
    const status = document.getElementById('editor-save-status');
    if (status) status.textContent = 'All changes saved';
    setTimeout(() => { if (status) status.textContent = ''; }, 3000);
  } else {
    alert('Some changes may not have saved. Please check and try again.');
  }
}


// --- Editor Navigation & Dirty State ---
function scrollToEditorSection(sectionId) {
  const el = document.getElementById(sectionId);
  if (el) {
    if (el.classList.contains('collapsed')) el.classList.remove('collapsed');
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

let editorDirty = false;
function markDirty() {
  editorDirty = true;
  const ind = document.getElementById('editor-dirty-indicator');
  if (ind) ind.style.display = 'inline-flex';
  const status = document.getElementById('editor-save-status');
  if (status) status.textContent = 'Unsaved changes';
}

// Track changes on editor inputs
document.addEventListener('change', (e) => {
  if (e.target.closest('#editor-content')) markDirty();
});
document.addEventListener('input', (e) => {
  if (e.target.closest('#editor-content') && e.target.tagName !== 'SELECT') markDirty();
});


// --- Metrics Search/Filter ---
function filterEditorMetrics(searchTerm) {
  const catFilter = document.getElementById('ed-metrics-cat-filter')?.value || '';
  const items = document.querySelectorAll('#ed-metrics-list .detect-item');
  const lower = (searchTerm || '').toLowerCase();
  items.forEach(item => {
    const name = item.querySelector('.item-name')?.textContent?.toLowerCase() || '';
    const cat = item.closest('[data-category]')?.dataset?.category || '';
    const matchSearch = !lower || name.includes(lower);
    const matchCat = !catFilter || cat === catFilter;
    item.style.display = (matchSearch && matchCat) ? '' : 'none';
  });
}


// --- Custom KPI Editor ---
function addCustomKPI() {
  const form = document.getElementById('ed-kpi-add-form');
  form.style.display = 'block';
  // Populate metric selects
  const metrics = editorContract?.metrics || [];
  ['kpi-new-num', 'kpi-new-den'].forEach(selId => {
    const sel = document.getElementById(selId);
    sel.innerHTML = '<option value="">Select metric...</option>' +
      metrics.map(m => `<option value="${m.name}">${escapeHtml(m.display_name || m.name)}</option>`).join('');
  });
}

function confirmAddKPI() {
  const name = document.getElementById('kpi-new-name').value.trim();
  const displayName = document.getElementById('kpi-new-display').value.trim();
  const num = document.getElementById('kpi-new-num').value;
  const den = document.getElementById('kpi-new-den').value;
  const mult = parseInt(document.getElementById('kpi-new-mult').value) || 1;
  const fmt = document.getElementById('kpi-new-format').value;

  if (!name || !num || !den) { alert('Please fill in name, numerator, and denominator'); return; }

  if (!editorContract.derived_kpis) editorContract.derived_kpis = [];
  editorContract.derived_kpis.push({
    name, display_name: displayName || name, brief_label: displayName || name,
    brief_category: 'Operations', numerator: num, denominator: den,
    multiply: mult, format: fmt, description: `${displayName || name} (user-defined)`
  });

  document.getElementById('ed-kpi-add-form').style.display = 'none';
  markDirty();
  loadContractEditor(); // refresh
}


// --- Data Profiling ---
async function profileDataset() {
  const id = document.getElementById('editor-dataset-select').value;
  if (!id) return;
  const btn = document.getElementById('profile-btn');
  btn.disabled = true;
  btn.textContent = 'Profiling...';
  try {
    const res = await fetch(`/api/datasets/${encodeURIComponent(id)}/profile?sample_size=2000`);
    if (!res.ok) throw new Error(await res.text());
    const profile = await res.json();

    document.getElementById('profile-results').style.display = 'block';
    document.getElementById('editor-profile-summary').textContent = `${profile.row_count} rows, ${profile.column_count} columns`;

    // Summary cards
    const numericCols = profile.columns.filter(c => c.type === 'numeric').length;
    const catCols = profile.columns.filter(c => c.type === 'categorical').length;
    document.getElementById('profile-summary').innerHTML = `
      <div class="info-card"><div class="label">Rows Sampled</div><div class="value">${profile.row_count.toLocaleString()}</div></div>
      <div class="info-card"><div class="label">Columns</div><div class="value">${profile.column_count}</div></div>
      <div class="info-card"><div class="label">Numeric</div><div class="value">${numericCols}</div></div>
      <div class="info-card"><div class="label">Categorical</div><div class="value">${catCols}</div></div>
    `;

    // Column details
    document.getElementById('profile-columns').innerHTML = profile.columns.map(c => {
      let detail = `${c.non_null} non-null (${(100 - c.null_pct).toFixed(0)}%) | ${c.unique} unique`;
      if (c.type === 'numeric') {
        detail += ` | range: ${c.min?.toLocaleString()} - ${c.max?.toLocaleString()} | mean: ${c.mean?.toLocaleString()}`;
      } else if (c.top_values) {
        const top3 = Object.entries(c.top_values).slice(0, 3).map(([k, v]) => `${k} (${v})`).join(', ');
        detail += ` | top: ${top3}`;
      }
      return `<div class="detect-item">
        <span class="item-name">${escapeHtml(c.name)}</span>
        <span class="item-type">${c.type}</span>
        <span class="item-detail">${detail}</span>
      </div>`;
    }).join('');

    // Sample rows table
    if (profile.sample_rows?.length) {
      const cols = Object.keys(profile.sample_rows[0]);
      const thead = cols.map(c => `<th>${escapeHtml(c)}</th>`).join('');
      const tbody = profile.sample_rows.map(row =>
        '<tr>' + cols.map(c => `<td>${escapeHtml(String(row[c] ?? ''))}</td>`).join('') + '</tr>'
      ).join('');
      document.getElementById('profile-sample').innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
    }
  } catch (e) {
    alert('Profile failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sample & Profile Data';
  }
}


// --- Init ---
loadDatasets();

// Also populate editor dataset dropdown
fetch('/api/datasets').then(r => r.json()).then(datasets => {
  const sel = document.getElementById('editor-dataset-select');
  if (sel) {
    datasets.forEach(d => {
      sel.innerHTML += `<option value="${d.id}">${escapeHtml(d.display_name || d.name)}</option>`;
    });
  }
});

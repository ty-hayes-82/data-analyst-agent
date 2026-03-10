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
    sel.innerHTML += `<option value="${d.id}" data-name="${d.display_name}">${d.display_name} (${d.name})</option>`;
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
  mg.innerHTML = '';
  (c.metrics || []).forEach(m => {
    mg.innerHTML += `<label><input type="checkbox" name="metric" value="${m.name}" checked> ${m.name}${m.description ? ' (' + m.description.slice(0, 50) + ')' : ''}</label>`;
  });

  // Hierarchies
  const hg = document.getElementById('hierarchy-group');
  hg.innerHTML = '';
  (c.hierarchies || []).forEach((h, i) => {
    const levels = (h.children || []).join(' > ');
    hg.innerHTML += `<label><input type="radio" name="hierarchy" value="${h.name}" ${i === 0 ? 'checked' : ''}> ${h.name} (${levels})</label>`;
  });

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
  const hierarchy = document.querySelector('input[name="hierarchy"]:checked')?.value || '';

  const focusChecks = [...document.querySelectorAll('input[name="focus"]:checked')].map(c => c.value);
  const customFocus = document.getElementById('custom-focus')?.value?.trim() || '';

  const body = {
    dataset_id: sel.value,
    dataset_name: sel.options[sel.selectedIndex].dataset.name || sel.value,
    metrics,
    hierarchy,
    analysis_focus: focusChecks,
    custom_focus: customFocus,
    max_drill_depth: parseInt(document.getElementById('max-depth').value) || 3,
    start_date: document.getElementById('start-date').value,
    end_date: document.getElementById('end-date').value,
  };

  try {
    const res = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
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
    const [runRes, logRes] = await Promise.all([
      fetch(`/api/runs/${runId}`),
      fetch(`/api/runs/${runId}/log?lines=100`),
    ]);
    const run = await runRes.json();
    const log = await logRes.text();

    const mc = document.getElementById('monitor-content');
    const statusClass = `badge-${run.status}`;
    const elapsed = run.finished_at
      ? Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000)
      : Math.round((Date.now() - new Date(run.started_at + 'Z').getTime()) / 1000);

    mc.innerHTML = `
      <div class="info-grid">
        <div class="info-card"><div class="label">Run ID</div><div class="value">${run.id}</div></div>
        <div class="info-card"><div class="label">Status</div><div class="value"><span class="badge ${statusClass}">${run.status}</span></div></div>
        <div class="info-card"><div class="label">Dataset</div><div class="value">${run.dataset_name}</div></div>
        <div class="info-card"><div class="label">Elapsed</div><div class="value">${elapsed}s</div></div>
        <div class="info-card"><div class="label">Metrics</div><div class="value">${(run.metrics || []).join(', ') || 'all'}</div></div>
        ${run.analysis_focus && run.analysis_focus.length ? `<div class="info-card"><div class="label">Focus</div><div class="value">${run.analysis_focus.map(f => f.replace(/_/g, ' ')).join(', ')}</div></div>` : ''}
      </div>
      ${run.status !== 'running' ? `<div class="actions"><button class="btn" onclick="viewResults('${run.id}')">View Results</button></div>` : ''}
      <h3>Live Log</h3>
      <div class="log-viewer" id="log-box">${escapeHtml(log)}</div>
    `;
    const box = document.getElementById('log-box');
    if (box) box.scrollTop = box.scrollHeight;

    if (run.status !== 'running') {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  render();
  pollTimer = setInterval(render, 3000);
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

// --- Init ---
loadDatasets();

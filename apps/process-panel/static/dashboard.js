const state = {
  data: null,
  agentsLabel: {
    notion_worker: "Notion Worker",
    notion_scheduler: "Notion Scheduler"
  }
};

function formatNumber(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("pt-BR").format(value);
}

function formatRate(value) {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins < 60) return `${mins}m ${secs}s`;
  const hours = Math.floor(mins / 60);
  const rem = mins % 60;
  return `${hours}h ${rem}m`;
}

function formatAge(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  return formatDuration(seconds);
}

function buildTable(headers, rows) {
  const head = document.createElement("div");
  head.className = "table-head";
  headers.forEach((h) => {
    const span = document.createElement("span");
    span.textContent = h;
    head.appendChild(span);
  });

  const body = document.createElement("div");
  body.className = "table-body";

  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "table-row";
    row.forEach((cell) => {
      const span = document.createElement("span");
      span.textContent = cell;
      item.appendChild(span);
    });
    body.appendChild(item);
  });

  const wrapper = document.createElement("div");
  wrapper.className = "table compact";
  wrapper.appendChild(head);
  wrapper.appendChild(body);
  return wrapper;
}

function renderAgentRuns() {
  const container = document.getElementById("agentRunsTable");
  container.innerHTML = "";
  const rows = Object.entries(state.data.agents || {}).map(([id, stats]) => [
    state.agentsLabel[id] || id,
    formatNumber(stats.runs_total),
    formatNumber(stats.runs_last),
    formatNumber(stats.failed_last)
  ]);
  container.appendChild(buildTable(["Agente", "Total", "7 dias", "Falhas 7d"], rows));
}

function renderTaskTypeRuns() {
  const container = document.getElementById("taskTypeRunsTable");
  container.innerHTML = "";
  const rows = Object.entries(state.data.task_types || {})
    .sort((a, b) => (b[1].runs_total || 0) - (a[1].runs_total || 0))
    .map(([type, stats]) => [
      type,
      formatNumber(stats.runs_total),
      formatNumber(stats.runs_last),
      formatNumber(stats.failed_last)
    ]);
  container.appendChild(buildTable(["Tipo", "Total", "7 dias", "Falhas 7d"], rows));
}

function renderItemsPerRun() {
  const container = document.getElementById("itemsPerRunTable");
  container.innerHTML = "";
  const rows = Object.entries(state.data.agents || {}).map(([id, stats]) => [
    state.agentsLabel[id] || id,
    stats.avg_items_per_run === null ? "—" : stats.avg_items_per_run.toFixed(2),
    formatNumber(stats.last_items_processed)
  ]);
  container.appendChild(buildTable(["Agente", "Media", "Ultimo ciclo"], rows));
}

function renderFailureRates() {
  const container = document.getElementById("failureRatesTable");
  container.innerHTML = "";
  const rows = [];
  Object.entries(state.data.agents || {}).forEach(([id, stats]) => {
    rows.push([
      `Agente: ${state.agentsLabel[id] || id}`,
      formatRate(stats.failure_rate),
      `${formatNumber(stats.runs_failed)} / ${formatNumber(stats.runs_total)}`
    ]);
  });
  Object.entries(state.data.task_types || {}).forEach(([type, stats]) => {
    rows.push([
      `Tipo: ${type}`,
      formatRate(stats.failure_rate),
      `${formatNumber(stats.runs_failed)} / ${formatNumber(stats.runs_total)}`
    ]);
  });
  container.appendChild(buildTable(["Categoria", "Taxa", "Falhas"], rows));
}

function renderAvgDuration() {
  const container = document.getElementById("avgDurationTable");
  container.innerHTML = "";
  const rows = [];
  Object.entries(state.data.agents || {}).forEach(([id, stats]) => {
    rows.push([
      `Agente: ${state.agentsLabel[id] || id}`,
      formatDuration(stats.avg_duration_sec),
      formatDuration(stats.last_duration_sec)
    ]);
  });
  Object.entries(state.data.task_types || {}).forEach(([type, stats]) => {
    rows.push([
      `Tipo: ${type}`,
      formatDuration(stats.avg_duration_sec),
      "—"
    ]);
  });
  container.appendChild(buildTable(["Categoria", "Media", "Ultimo ciclo"], rows));
}

function renderBacklog() {
  const container = document.getElementById("backlogContent");
  container.innerHTML = "";
  const data = state.data.backlog_estimate || {};
  const total = data.last_tasks_seen ?? "—";
  const lastCheck = data.last_check_at || "—";
  const wrapper = document.createElement("div");
  wrapper.className = "backlog-grid";

  const totalBox = document.createElement("div");
  totalBox.innerHTML = `<span class="label">Tasks em fila (amostra)</span><span class="value">${formatNumber(total)}</span>`;

  const checkBox = document.createElement("div");
  checkBox.innerHTML = `<span class="label">Ultima leitura</span><span class="value">${lastCheck}</span>`;

  wrapper.appendChild(totalBox);
  wrapper.appendChild(checkBox);

  const list = document.createElement("div");
  list.className = "backlog-list";
  const byType = data.last_tasks_seen_by_type || {};
  const entries = Object.entries(byType);
  if (entries.length === 0) {
    list.textContent = "Sem dados por tipo ainda.";
  } else {
    entries.forEach(([type, count]) => {
      const row = document.createElement("div");
      row.className = "backlog-row";
      row.innerHTML = `<span>${type}</span><span>${formatNumber(count)}</span>`;
      list.appendChild(row);
    });
  }

  container.appendChild(wrapper);
  container.appendChild(list);
}

function renderLastSuccess() {
  const container = document.getElementById("lastSuccessTable");
  container.innerHTML = "";
  const rows = Object.entries(state.data.agents || {}).map(([id, stats]) => [
    state.agentsLabel[id] || id,
    stats.last_success_at || "—",
    formatAge(stats.last_success_age_sec)
  ]);
  container.appendChild(buildTable(["Agente", "Ultimo sucesso", "Tempo desde"], rows));
}

function renderErrorTrend() {
  const container = document.getElementById("errorTrendTable");
  container.innerHTML = "";
  const rows = Object.entries(state.data.agents || {}).map(([id, stats]) => {
    const trend = (stats.trend_last_days || []).map((entry) => entry.failed);
    return [
      state.agentsLabel[id] || id,
      trend.join(" · "),
      (stats.trend_last_days || []).map((entry) => entry.date.slice(5)).join(" ")
    ];
  });
  container.appendChild(buildTable(["Agente", "Falhas (7d)", "Dias"], rows));
}

function renderDashboard() {
  renderAgentRuns();
  renderTaskTypeRuns();
  renderItemsPerRun();
  renderFailureRates();
  renderAvgDuration();
  renderBacklog();
  renderLastSuccess();
  renderErrorTrend();
}

async function loadDashboard() {
  const res = await fetch("/api/dashboard");
  if (!res.ok) {
    throw new Error("Falha ao carregar dashboard");
  }
  state.data = await res.json();
}

async function refresh() {
  try {
    await loadDashboard();
    renderDashboard();
  } catch (err) {
    console.error(err);
  }
}

document.getElementById("refreshDashboard").addEventListener("click", refresh);
refresh();

const state = {
  logs: [],
  currentLog: null,
  lastStatus: null
};

const elements = {
  refreshBtn: document.getElementById("refreshBtn"),
  logsBtn: document.getElementById("logsBtn"),
  logsModal: document.getElementById("logsModal"),
  closeLogs: document.getElementById("closeLogs"),
  logsList: document.getElementById("logsList"),
  logContent: document.getElementById("logContent"),
  logViewerTitle: document.getElementById("logViewerTitle"),
  reloadLog: document.getElementById("reloadLog"),
  processRows: document.getElementById("processRows"),
  launchctlHint: document.getElementById("launchctlHint"),
  nw: {
    status: document.getElementById("nw-status-dot"),
    lastCheck: document.getElementById("nw-last-check"),
    nextCheck: document.getElementById("nw-next-check"),
    lastSuccess: document.getElementById("nw-last-success"),
    lastTasks: document.getElementById("nw-last-tasks"),
    error: document.getElementById("nw-error"),
    runBtn: document.getElementById("nw-run-btn"),
    runStatus: document.getElementById("nw-run-status")
  },
  ns: {
    status: document.getElementById("ns-status-dot"),
    lastCheck: document.getElementById("ns-last-check"),
    nextCheck: document.getElementById("ns-next-check"),
    lastSuccess: document.getElementById("ns-last-success"),
    summary: document.getElementById("ns-last-summary"),
    error: document.getElementById("ns-error"),
    runBtn: document.getElementById("ns-run-btn"),
    runStatus: document.getElementById("ns-run-status")
  }
};

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

function formatInterval(seconds) {
  if (!seconds) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function setStatusDot(el, data) {
  el.classList.remove("active", "inactive");
  if (data && data.active) {
    el.classList.add("active");
    el.title = "Ativo";
  } else if (data && data.loaded) {
    el.classList.add("inactive");
    el.title = "Carregado, mas nao ativo";
  } else {
    el.title = "Inativo";
  }
}

function setErrorBox(el, text, timestamp) {
  if (text) {
    const when = timestamp ? ` (${formatDate(timestamp)})` : "";
    el.textContent = `Erro recente${when}: ${text}`;
    el.hidden = false;
  } else {
    el.hidden = true;
    el.textContent = "";
  }
}

function updateWorkerCards(payload) {
  const nw = payload.workers?.notion_worker || {};
  setStatusDot(elements.nw.status, nw);
  elements.nw.lastCheck.textContent = formatDate(nw.last_check_at);
  elements.nw.nextCheck.textContent = formatDate(nw.next_check_at);
  elements.nw.lastSuccess.textContent = formatDate(nw.last_success_at);
  elements.nw.lastTasks.textContent = nw.last_tasks_seen ?? "—";
  setErrorBox(elements.nw.error, nw.last_error, nw.last_error_at);

  const ns = payload.workers?.notion_scheduler || {};
  setStatusDot(elements.ns.status, ns);
  elements.ns.lastCheck.textContent = formatDate(ns.last_check_at);
  elements.ns.nextCheck.textContent = formatDate(ns.next_check_at);
  elements.ns.lastSuccess.textContent = formatDate(ns.last_success_at);
  if (ns.last_created != null || ns.last_skipped != null) {
    const created = ns.last_created ?? 0;
    const skipped = ns.last_skipped ?? 0;
    elements.ns.summary.textContent = `${created} / ${skipped}`;
  } else {
    elements.ns.summary.textContent = "—";
  }
  setErrorBox(elements.ns.error, ns.last_error, ns.last_error_at);
}

function updateProcessTable(payload) {
  elements.processRows.innerHTML = "";
  const processes = payload.processes || [];
  processes.forEach((proc) => {
    const row = document.createElement("div");
    row.className = "table-row";

    const label = document.createElement("span");
    label.textContent = proc.label || "—";

    const interval = document.createElement("span");
    interval.textContent = formatInterval(proc.start_interval);

    const status = document.createElement("span");
    status.className = "status-pill";
    if (proc.active) {
      status.classList.add("active");
      status.textContent = "Ativo";
    } else if (proc.loaded) {
      status.classList.add("inactive");
      status.textContent = "Carregado";
    } else {
      status.classList.add("unknown");
      status.textContent = "Inativo";
    }

    row.append(label, interval, status);
    elements.processRows.appendChild(row);
  });

  if (!processes.length) {
    const empty = document.createElement("div");
    empty.className = "table-row";
    empty.textContent = "Nenhum processo encontrado em runner/launchd.";
    elements.processRows.appendChild(empty);
  }

  if (payload.launchctl_error) {
    elements.launchctlHint.textContent = `launchctl indisponivel: ${payload.launchctl_error}`;
  } else {
    elements.launchctlHint.textContent = "Atualizado";
  }
}

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    state.lastStatus = data;
    updateWorkerCards(data);
    updateProcessTable(data);
  } catch (err) {
    console.error(err);
  }
}

async function runWorker(workerId, runStatusEl, runBtnEl) {
  runBtnEl.disabled = true;
  runStatusEl.textContent = "Disparando...";
  try {
    const res = await fetch(`/api/run/${workerId}`);
    const data = await res.json();
    if (!res.ok || !data.ok) {
      runStatusEl.textContent = "Falha ao disparar.";
    } else {
      runStatusEl.textContent = `Executado em ${formatDate(data.started_at)}`;
    }
  } catch (err) {
    runStatusEl.textContent = "Erro ao disparar.";
  }
  runBtnEl.disabled = false;
  setTimeout(fetchStatus, 2000);
}

async function openLogs() {
  elements.logsModal.classList.add("open");
  elements.logsModal.setAttribute("aria-hidden", "false");
  await loadLogsList();
}

function closeLogs() {
  elements.logsModal.classList.remove("open");
  elements.logsModal.setAttribute("aria-hidden", "true");
}

async function loadLogsList() {
  elements.logsList.innerHTML = "Carregando...";
  try {
    const res = await fetch("/api/logs");
    const data = await res.json();
    state.logs = data.logs || [];
    renderLogsList();
  } catch (err) {
    elements.logsList.innerHTML = "Erro ao carregar logs.";
  }
}

function renderLogsList() {
  elements.logsList.innerHTML = "";
  if (!state.logs.length) {
    elements.logsList.textContent = "Sem logs no momento.";
    return;
  }
  state.logs.forEach((log) => {
    const item = document.createElement("div");
    item.className = "log-item";
    item.textContent = `${log.name} (${Math.round(log.size / 1024)} KB)`;
    item.addEventListener("click", () => selectLog(log.name));
    if (state.currentLog === log.name) {
      item.classList.add("active");
    }
    elements.logsList.appendChild(item);
  });
}

async function selectLog(name) {
  state.currentLog = name;
  renderLogsList();
  elements.logViewerTitle.textContent = name;
  elements.reloadLog.disabled = false;
  await loadLogContent();
}

async function loadLogContent() {
  if (!state.currentLog) return;
  elements.logContent.textContent = "Carregando...";
  try {
    const res = await fetch(`/api/logs/${state.currentLog}?tail=20000`);
    const data = await res.json();
    elements.logContent.textContent = data.content || "(vazio)";
  } catch (err) {
    elements.logContent.textContent = "Erro ao carregar log.";
  }
}

function init() {
  elements.refreshBtn.addEventListener("click", fetchStatus);
  elements.logsBtn.addEventListener("click", openLogs);
  elements.closeLogs.addEventListener("click", closeLogs);
  elements.logsModal.addEventListener("click", (event) => {
    if (event.target === elements.logsModal) {
      closeLogs();
    }
  });
  elements.reloadLog.addEventListener("click", loadLogContent);

  elements.nw.runBtn.addEventListener("click", () => runWorker("notion_worker", elements.nw.runStatus, elements.nw.runBtn));
  elements.ns.runBtn.addEventListener("click", () => runWorker("notion_scheduler", elements.ns.runStatus, elements.ns.runBtn));

  fetchStatus();
  setInterval(fetchStatus, 20000);
}

init();

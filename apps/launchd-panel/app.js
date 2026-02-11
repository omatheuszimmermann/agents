const state = {
  jobs: [],
  filteredJobs: [],
  selectedId: null,
  editingId: null
};

const elements = {
  jobList: document.getElementById("jobList"),
  jobCount: document.getElementById("jobCount"),
  searchInput: document.getElementById("searchInput"),
  activeOnlyToggle: document.getElementById("activeOnlyToggle"),
  detailBody: document.getElementById("detailBody"),
  detailStatus: document.getElementById("detailStatus"),
  form: document.getElementById("jobForm"),
  formTitle: document.getElementById("formTitle"),
  formHint: document.getElementById("formHint"),
  resetFormBtn: document.getElementById("resetFormBtn"),
  newJobBtn: document.getElementById("newJobBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  scheduleType: document.querySelector("select[name='scheduleType']"),
  scheduleValue: document.querySelector("input[name='scheduleValue']"),
  weekdaysField: document.getElementById("weekdaysField")
};

const template = document.getElementById("jobCardTemplate");

const api = {
  async list() {
    const res = await fetch("/api/launchd/jobs");
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.error || "Falha ao listar jobs");
    }
    return res.json();
  },
  async create(job) {
    const res = await fetch("/api/launchd/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job)
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.error || "Falha ao criar job");
    }
    return res.json();
  },
  async update(jobId, updates) {
    const res = await fetch(`/api/launchd/jobs/${encodeURIComponent(jobId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates)
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.error || "Falha ao atualizar job");
    }
    return res.json();
  },
  async remove(jobId) {
    const res = await fetch(`/api/launchd/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    if (!res.ok && res.status !== 204) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.error || "Falha ao remover job");
    }
  }
};

function scheduleLabel(job) {
  if (job.scheduleType === "weekly") {
    const days = (job.scheduleDays || []).map(weekdayName).join(", ");
    const time = job.scheduleValue || "--";
    return `weekly: ${days || "--"} ${time}`;
  }
  if (job.scheduleType === "calendar") {
    return `calendar: ${job.scheduleValue || "--"}`;
  }
  if (job.scheduleType === "interval") {
    return `interval: ${job.scheduleValue || "--"}s`;
  }
  return "no schedule";
}

function runAtLoadLabel(job) {
  return job.runAtLoad ? "RunAtLoad: yes" : "RunAtLoad: no";
}

function weekdayName(value) {
  const map = {
    1: "Seg",
    2: "Ter",
    3: "Qua",
    4: "Qui",
    5: "Sex",
    6: "Sab",
    7: "Dom"
  };
  return map[value] || String(value);
}

function clearWeekdays() {
  const inputs = elements.form.querySelectorAll("input[name='weekday']");
  inputs.forEach((input) => {
    input.checked = false;
  });
}

function setWeekdays(values) {
  const inputs = elements.form.querySelectorAll("input[name='weekday']");
  inputs.forEach((input) => {
    input.checked = values.includes(Number(input.value));
  });
}

function getSelectedWeekdays() {
  const inputs = elements.form.querySelectorAll("input[name='weekday']:checked");
  return Array.from(inputs).map((input) => Number(input.value));
}

function toggleScheduleFields() {
  const type = elements.scheduleType.value;
  if (type === "weekly") {
    elements.weekdaysField.style.display = "flex";
    elements.scheduleValue.placeholder = "09:00";
  } else {
    elements.weekdaysField.style.display = "none";
    elements.scheduleValue.placeholder = type === "interval" ? "3600" : "09:00";
  }
}

function renderList() {
  elements.jobList.innerHTML = "";
  const fragment = document.createDocumentFragment();
  state.filteredJobs.forEach((job) => {
    const card = template.content.cloneNode(true);
    const article = card.querySelector(".job-card");
    const title = card.querySelector("h3");
    const file = card.querySelector(".file");
    const status = card.querySelector(".status");
    const schedule = card.querySelector(".schedule");
    const runAtLoad = card.querySelector(".runatload");
    const selectBtn = card.querySelector(".select");
    const deleteBtn = card.querySelector(".delete");

    title.textContent = job.label;
    file.textContent = job.filename;
    status.textContent = job.loaded ? "loaded" : "unloaded";
    status.classList.add(job.loaded ? "loaded" : "unloaded");
    schedule.textContent = scheduleLabel(job);
    runAtLoad.textContent = runAtLoadLabel(job);

    selectBtn.addEventListener("click", () => selectJob(job.id));
    deleteBtn.addEventListener("click", () => confirmDelete(job.id));

    article.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      selectJob(job.id);
    });

    fragment.appendChild(card);
  });
  elements.jobList.appendChild(fragment);
  elements.jobCount.textContent = String(state.filteredJobs.length);
}

function renderDetail(job) {
  if (!job) {
    elements.detailBody.innerHTML = "<p class=\"muted\">Selecione um item na lista para editar ou excluir.</p>";
    elements.detailStatus.textContent = "Selecione um job";
    return;
  }

  elements.detailStatus.textContent = job.loaded ? "Ativo" : "Inativo";

  elements.detailBody.innerHTML = `
    <div class="detail-item"><strong>Label</strong><span>${job.label}</span></div>
    <div class="detail-item"><strong>Arquivo</strong><span>${job.filename}</span></div>
    <div class="detail-item"><strong>Schedule</strong><span>${scheduleLabel(job)}</span></div>
    <div class="detail-item"><strong>RunAtLoad</strong><span>${job.runAtLoad ? "yes" : "no"}</span></div>
    <div class="detail-item"><strong>KeepAlive</strong><span>${job.keepAlive ? "yes" : "no"}</span></div>
    <div class="detail-item"><strong>ProgramArguments</strong><span>${job.programArgs}</span></div>
    <div class="detail-item"><strong>Stdout</strong><span>${job.stdoutPath}</span></div>
    <div class="detail-item"><strong>Stderr</strong><span>${job.stderrPath}</span></div>
    <div class="actions">
      <button class="btn ghost" id="detailEditBtn">Editar</button>
      <button class="btn danger" id="detailDeleteBtn">Excluir</button>
    </div>
  `;

  document.getElementById("detailEditBtn").addEventListener("click", () => startEdit(job));
  document.getElementById("detailDeleteBtn").addEventListener("click", () => confirmDelete(job.id));
}

function applyFilters() {
  const search = elements.searchInput.value.toLowerCase();
  const activeOnly = elements.activeOnlyToggle.checked;

  state.filteredJobs = state.jobs.filter((job) => {
    const matchesSearch =
      job.label.toLowerCase().includes(search) || job.filename.toLowerCase().includes(search);
    const matchesActive = !activeOnly || job.loaded;
    return matchesSearch && matchesActive;
  });

  renderList();
}

async function refresh() {
  try {
    state.jobs = await api.list();
    applyFilters();
    const selected = state.jobs.find((job) => job.id === state.selectedId);
    renderDetail(selected || null);
  } catch (error) {
    console.error(error);
    elements.detailStatus.textContent = "Erro";
    elements.detailBody.innerHTML = "<p class=\\\"muted\\\">Falha ao buscar dados reais.</p>";
  }
}

function selectJob(jobId) {
  state.selectedId = jobId;
  const job = state.jobs.find((item) => item.id === jobId);
  renderDetail(job || null);
}

function resetForm() {
  elements.form.reset();
  state.editingId = null;
  elements.formTitle.textContent = "Criar novo job";
  elements.formHint.textContent = "LaunchAgents";
  clearWeekdays();
  toggleScheduleFields();
}

function startEdit(job) {
  state.editingId = job.id;
  elements.formTitle.textContent = `Editar: ${job.label}`;
  elements.formHint.textContent = job.loaded ? "Ativo" : "Inativo";

  const formData = new FormData(elements.form);
  formData.set("label", job.label);
  formData.set("filename", job.filename);
  formData.set("scheduleType", job.scheduleType);
  formData.set("scheduleValue", job.scheduleValue || "");
  formData.set("programArgs", job.programArgs || "");
  formData.set("stdoutPath", job.stdoutPath || "");
  formData.set("stderrPath", job.stderrPath || "");
  formData.set("runAtLoad", job.runAtLoad ? "on" : "");
  formData.set("keepAlive", job.keepAlive ? "on" : "");

  for (const [key, value] of formData.entries()) {
    const field = elements.form.elements[key];
    if (!field) continue;
    if (field.type === "checkbox") {
      field.checked = value === "on";
    } else {
      field.value = value;
    }
  }

  clearWeekdays();
  if (job.scheduleDays && job.scheduleDays.length) {
    setWeekdays(job.scheduleDays);
  }
  toggleScheduleFields();
}

async function confirmDelete(jobId) {
  const job = state.jobs.find((item) => item.id === jobId);
  if (!job) return;
  const confirmed = window.confirm(`Excluir ${job.label}?`);
  if (!confirmed) return;
  try {
    await api.remove(jobId);
  } catch (error) {
    alert(error?.message || "Falha ao remover job.");
    return;
  }
  if (state.selectedId === jobId) {
    state.selectedId = null;
    renderDetail(null);
  }
  await refresh();
}

function jobFromForm() {
  const data = new FormData(elements.form);
  const scheduleType = data.get("scheduleType");
  const scheduleValue = data.get("scheduleValue").trim();
  const scheduleDays = getSelectedWeekdays();

  return {
    id: data.get("label").trim(),
    label: data.get("label").trim(),
    filename: data.get("filename").trim(),
    loaded: true,
    scheduleType: scheduleType,
    scheduleValue: scheduleType === "none" ? "" : scheduleValue,
    scheduleDays: scheduleType === "weekly" ? scheduleDays : [],
    runAtLoad: data.get("runAtLoad") === "on",
    keepAlive: data.get("keepAlive") === "on",
    programArgs: data.get("programArgs").trim(),
    stdoutPath: data.get("stdoutPath").trim(),
    stderrPath: data.get("stderrPath").trim()
  };
}

async function handleSubmit(event) {
  event.preventDefault();
  const job = jobFromForm();

  if (!job.label) {
    alert("Label obrigatorio.");
    return;
  }
  if (!job.filename.endsWith(".plist")) {
    alert("Arquivo deve terminar com .plist");
    return;
  }
  if (job.scheduleType === "weekly" && job.scheduleDays.length === 0) {
    alert("Selecione pelo menos um dia da semana.");
    return;
  }
  if (job.scheduleType === "weekly" && !job.scheduleValue) {
    alert("Informe o horario (HH:MM).");
    return;
  }

  try {
    if (state.editingId) {
      await api.update(state.editingId, job);
    } else {
      const exists = state.jobs.some((item) => item.id === job.id);
      if (exists) {
        alert("Label ja existe.");
        return;
      }
      await api.create(job);
    }
  } catch (error) {
    alert(error?.message || "Falha ao salvar job.");
    return;
  }

  resetForm();
  await refresh();
}

function registerEvents() {
  elements.searchInput.addEventListener("input", applyFilters);
  elements.activeOnlyToggle.addEventListener("change", applyFilters);
  elements.form.addEventListener("submit", handleSubmit);
  elements.resetFormBtn.addEventListener("click", resetForm);
  elements.scheduleType.addEventListener("change", toggleScheduleFields);
  elements.newJobBtn.addEventListener("click", () => {
    resetForm();
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  });
  elements.refreshBtn.addEventListener("click", refresh);
}

async function init() {
  registerEvents();
  toggleScheduleFields();
  await refresh();
}

init();

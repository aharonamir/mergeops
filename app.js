const seedMembers = [
  {
    id: "lior",
    name: "Lior Cohen",
    github: "liorco",
    aliases: "lior@company.dev, lcohen",
    focus: "Billing API extraction",
    responsibilities: "Payments, API contracts, release safety",
    owns: "agent-core, perfrouter",
    expertise: ["backend", "payments", "python"],
    timezone: "Asia/Jerusalem",
    availability: "active"
  },
  {
    id: "maya",
    name: "Maya Levi",
    github: "mayalevi",
    aliases: "maya@company.dev",
    focus: "Reviewing search index rollout",
    responsibilities: "Frontend workflows, bilingual search UX",
    owns: "jiuwenswarm-ide, token-optimizer",
    expertise: ["frontend", "search", "typescript"],
    timezone: "Asia/Jerusalem",
    availability: "focus mode"
  },
  {
    id: "noam",
    name: "Noam Bar",
    github: "noambar",
    aliases: "nbar, noam@company.dev",
    focus: "CI stability and Docker cache fixes",
    responsibilities: "Infra, CI, local developer tooling",
    owns: "agent-worx, docs",
    expertise: ["infra", "ci", "docker"],
    timezone: "Europe/Berlin",
    availability: "overloaded"
  },
  {
    id: "dana",
    name: "Dana Katz",
    github: "danak",
    aliases: "dana@company.dev",
    focus: "Agent permission model",
    responsibilities: "Security review, agent guardrails",
    owns: "WildClawBench, agent-core/security",
    expertise: ["security", "agents", "reviews"],
    timezone: "Asia/Jerusalem",
    availability: "active"
  }
];

const prs = [
  {
    id: 842,
    title: "Rework session permission prompts for opencode bridge",
    repo: "agent-core",
    owner: "dana",
    status: "conflict",
    review: "2 unresolved comments",
    checks: "blocked",
    age: 4,
    branch: "feature/session-permissions",
    comments: 9,
    issue: "SEC-118",
    summary: "Touches approval gates and session permission handoff. Conflict in permission policy tests.",
    search: "permission approval הרשאות אישור opencode"
  },
  {
    id: 317,
    title: "Add Hebrew/English issue expansion to repository search",
    repo: "token-optimizer",
    owner: "maya",
    status: "review",
    review: "waiting on backend",
    checks: "passing",
    age: 2,
    branch: "search/bilingual-expansion",
    comments: 5,
    issue: "SRCH-42",
    summary: "Adds bilingual query normalization and issue/PR result grouping.",
    search: "bilingual search hebrew english חיפוש עברית issues prs"
  },
  {
    id: 1055,
    title: "Stabilize memtier docker compose harness",
    repo: "jiuwenswarm-memtier",
    owner: "noam",
    status: "checks",
    review: "approved",
    checks: "1 failing",
    age: 6,
    branch: "infra/memtier-compose",
    comments: 1,
    issue: "CI-77",
    summary: "Flaky redis service startup; failing on cold cache path.",
    search: "docker compose redis ci failing בדיקות"
  },
  {
    id: 229,
    title: "Extract billing router from benchmark runner",
    repo: "perfrouter",
    owner: "lior",
    status: "ready",
    review: "approved",
    checks: "passing",
    age: 1,
    branch: "billing/router-extract",
    comments: 0,
    issue: "BILL-21",
    summary: "Small extraction with test coverage and clean branch.",
    search: "billing router ready merge תשלום"
  },
  {
    id: 640,
    title: "Normalize web channel team member avatars",
    repo: "jiuwenswarm",
    owner: "maya",
    status: "review",
    review: "needs design review",
    checks: "passing",
    age: 3,
    branch: "web/avatar-normalization",
    comments: 4,
    issue: "WEB-64",
    summary: "Updates avatar component states and fallback initials.",
    search: "avatar team member frontend עיצוב"
  },
  {
    id: 901,
    title: "Move harness task loop config into schema layer",
    repo: "agent-core",
    owner: "lior",
    status: "conflict",
    review: "changes requested",
    checks: "not run",
    age: 8,
    branch: "harness/task-loop-schema",
    comments: 11,
    issue: "CORE-209",
    summary: "Large refactor with schema conflicts and stale branch.",
    search: "schema task loop conflict קונפליקט"
  }
];

const agentBackends = {
  opencode: {
    label: "opencode",
    sdk: "@opencode-ai/sdk",
    endpoint: "http://localhost:4096",
    model: "team default",
    status: "ready for approval-gated sessions",
    sessionNoun: "opencode session"
  },
  codex: {
    label: "Codex",
    sdk: "OpenAI/Codex agent adapter",
    endpoint: "local or hosted codex runner",
    model: "gpt-5-codex",
    status: "adapter selected, connection pending",
    sessionNoun: "Codex run"
  },
  anthropic: {
    label: "Anthropic",
    sdk: "Anthropic agent adapter",
    endpoint: "Anthropic API / internal runner",
    model: "Claude team default",
    status: "adapter selected, connection pending",
    sessionNoun: "Anthropic run"
  }
};

const state = {
  members: JSON.parse(localStorage.getItem("mergeops.members") || "null") || seedMembers,
  theme: localStorage.getItem("mergeops.theme") || "system",
  agentBackend: localStorage.getItem("mergeops.agentBackend") || "opencode",
  queue: "all",
  repo: "all",
  owner: "all",
  search: "",
  runs: [
    { pr: "#842", title: "Conflict analysis prepared", backend: "opencode", state: "awaiting approval", detail: "opencode produced a fix branch plan and identified 3 files to reconcile." },
    { pr: "#1055", title: "CI failure investigation", state: "checks running", detail: "Session is replaying Docker startup with cached and cold service paths." }
  ]
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function iconForTheme() {
  return state.theme === "light" ? "i-sun" : state.theme === "dark" ? "i-moon" : "i-monitor";
}

function applyTheme() {
  const resolved = state.theme === "system"
    ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : state.theme;
  document.documentElement.dataset.theme = resolved;
  $("#themeToggle use").setAttribute("href", `#${iconForTheme()}`);
  $("#themeToggle").setAttribute("aria-label", `Theme: ${state.theme}`);
  $("#themeToggle").setAttribute("title", `Theme: ${state.theme}`);
}

function cycleTheme() {
  state.theme = state.theme === "system" ? "light" : state.theme === "light" ? "dark" : "system";
  localStorage.setItem("mergeops.theme", state.theme);
  applyTheme();
}

function memberById(id) {
  return state.members.find((member) => member.id === id) || state.members[0];
}

function initials(name) {
  return name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

function statusLabel(status) {
  return {
    conflict: "Conflict",
    review: "Needs review",
    ready: "Ready",
    checks: "Checks"
  }[status] || status;
}

function activeBackend() {
  return agentBackends[state.agentBackend] || agentBackends.opencode;
}

function renderBackendChrome() {
  const backend = activeBackend();
  $("#agentBackendLabel").textContent = backend.label;
  $("#agentBackendEndpoint").textContent = backend.endpoint.replace(/^https?:\/\//, "");
  $("#agentBackendStatus").textContent = backend.status;
  $("#agentRunsIntro").textContent = `${backend.label} remediation sessions, generated patches, checks, and approval state.`;
}

function filteredPrs() {
  const query = state.search.trim().toLowerCase();
  return prs.filter((pr) => {
    const queueMatch =
      state.queue === "all" ||
      (state.queue === "blocked" && ["conflict", "checks"].includes(pr.status)) ||
      (state.queue === "review" && pr.status === "review") ||
      (state.queue === "ready" && pr.status === "ready");
    const repoMatch = state.repo === "all" || pr.repo === state.repo;
    const ownerMatch = state.owner === "all" || pr.owner === state.owner;
    const searchTarget = `${pr.title} ${pr.repo} ${pr.branch} ${pr.issue} ${pr.summary} ${pr.search}`.toLowerCase();
    return queueMatch && repoMatch && ownerMatch && (!query || searchTarget.includes(query));
  });
}

function renderFilters() {
  const repos = ["all", ...new Set(prs.map((pr) => pr.repo))];
  $("#repoFilter").innerHTML = repos.map((repo) => `<option value="${repo}">${repo === "all" ? "All repos" : repo}</option>`).join("");
  $("#repoFilter").value = state.repo;
  $("#ownerFilter").innerHTML = [`<option value="all">All members</option>`, ...state.members.map((member) => `<option value="${member.id}">${member.name}</option>`)].join("");
  $("#ownerFilter").value = state.owner;
}

function renderMetrics() {
  const visible = filteredPrs();
  const metrics = [
    ["Open", prs.length],
    ["Conflicts", prs.filter((pr) => pr.status === "conflict").length],
    ["Review comments", prs.reduce((sum, pr) => sum + pr.comments, 0)],
    ["Ready", prs.filter((pr) => pr.status === "ready").length],
    ["Merged this week", 14],
    ["Closed without merge", 3]
  ];
  $("#metricsRack").innerHTML = metrics.map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");
  $("#resultCount").textContent = `${visible.length} matching PRs`;
}

function renderTeamStrip() {
  $("#teamStrip").innerHTML = state.members.map((member) => {
    const owned = prs.filter((pr) => pr.owner === member.id);
    const blocked = owned.filter((pr) => ["conflict", "checks"].includes(pr.status)).length;
    return `
      <article class="member-tile">
        <div class="member-top">
          <span class="avatar">${initials(member.name)}</span>
          <span class="member-meta"><strong>${member.name}</strong><span>@${member.github} · ${member.availability}</span></span>
          <span class="load">${owned.length} PRs</span>
        </div>
        <div class="tag-row">
          <span class="tag">${member.focus}</span>
          <span class="status ${blocked ? "conflict" : "ready"}">${blocked ? `${blocked} blocked` : "clear"}</span>
        </div>
      </article>
    `;
  }).join("");
}

function renderPrRows() {
  const rows = filteredPrs();
  $("#prRows").innerHTML = rows.map((pr) => {
    const member = memberById(pr.owner);
    return `
      <div class="pr-row" role="row">
        <div class="pr-cell"><span class="status ${pr.status}">${statusLabel(pr.status)}</span></div>
        <div class="pr-cell">
          <span class="pr-title">
            <strong>${pr.title}</strong>
            <span>${pr.repo} #${pr.id} · ${pr.branch}</span>
          </span>
        </div>
        <div class="pr-cell">${member.name}</div>
        <div class="pr-cell">${pr.review}</div>
        <div class="pr-cell">${pr.checks}</div>
        <div class="pr-cell">${pr.age}d</div>
        <div class="pr-cell"><button class="text-btn" data-open-pr="${pr.id}">Inspect</button></div>
      </div>
    `;
  }).join("");
}

function renderPeople() {
  $("#peopleGrid").innerHTML = state.members.map((member, index) => `
    <article class="person-card">
      <header>
        <span class="avatar">${initials(member.name)}</span>
        <span class="member-meta"><strong>${member.name}</strong><span>@${member.github} · ${member.timezone}</span></span>
      </header>
      <div class="profile-fields">
        ${inputField(index, "focus", "Current focus", member.focus)}
        ${inputField(index, "responsibilities", "Responsibilities", member.responsibilities)}
        ${inputField(index, "owns", "Owned repos / areas", member.owns)}
        ${inputField(index, "availability", "Availability", member.availability)}
        ${inputField(index, "aliases", "Git aliases", member.aliases, true)}
      </div>
    </article>
  `).join("");
}

function inputField(index, key, label, value, full = false) {
  return `
    <label class="field ${full ? "full" : ""}">
      <span>${label}</span>
      <input data-member-index="${index}" data-member-key="${key}" value="${value}">
    </label>
  `;
}

function renderRuns() {
  $("#runsList").innerHTML = state.runs.map((run) => `
    <article class="run-item">
      <div>
        <strong>${run.pr} · ${run.title}</strong>
        <p>${run.detail}</p>
      </div>
      <span class="status agent">${run.backend || activeBackend().label} · ${run.state}</span>
    </article>
  `).join("");
}

function settingsInput(label, value, type = "text") {
  return `<label class="field"><span>${label}</span><input type="${type}" value="${value}"></label>`;
}

function settingsSelect(label, id, options, value) {
  return `
    <label class="field">
      <span>${label}</span>
      <select id="${id}">
        ${options.map((option) => `<option value="${option.value}" ${option.value === value ? "selected" : ""}>${option.label}</option>`).join("")}
      </select>
    </label>
  `;
}

function renderSettings() {
  $("#teamSettings").innerHTML = `
    <h2>Team</h2>
    <div class="settings-grid">
      ${settingsInput("Default reviewer group", "maintainers")}
      ${settingsInput("OOO source", "manual")}
      ${settingsInput("CODEOWNERS sync", "enabled")}
      ${settingsInput("Capacity warning threshold", "5 open PRs")}
    </div>
  `;
  $("#repoSettings").innerHTML = `
    <h2>Repositories</h2>
    <div class="settings-grid">
      ${settingsInput("GitHub organization", "synthetic-org")}
      ${settingsInput("Included repos", "agent-core, jiuwenswarm, token-optimizer")}
      ${settingsInput("Stale PR age", "4 days")}
      ${settingsInput("Ignored actors", "dependabot, renovate")}
    </div>
  `;
  $("#integrationSettings").innerHTML = `
    <h2>Integrations</h2>
    <div class="settings-grid">
      ${settingsInput("GitHub App", "not connected")}
      ${settingsSelect("Backend agent SDK", "agentBackendSelect", [
        { value: "opencode", label: "opencode" },
        { value: "codex", label: "Codex" },
        { value: "anthropic", label: "Anthropic" }
      ], state.agentBackend)}
      ${settingsInput("Agent endpoint", activeBackend().endpoint)}
      ${settingsInput("SDK package / adapter", activeBackend().sdk)}
      ${settingsInput("Default model/provider", activeBackend().model)}
      ${settingsInput("CI provider", "GitHub Actions")}
    </div>
  `;
  $("#policySettings").innerHTML = `
    <h2>Automation Policy</h2>
    <label class="toggle-line"><span>Agents may create fix branches</span><input type="checkbox" checked></label>
    <label class="toggle-line"><span>Push requires human approval</span><input type="checkbox" checked></label>
    <label class="toggle-line"><span>Run tests before approval request</span><input type="checkbox" checked></label>
    <label class="toggle-line"><span>Automerge after approval</span><input type="checkbox"></label>
  `;
  $("#searchSettings").innerHTML = `
    <h2>Search</h2>
    <div class="settings-grid">
      ${settingsInput("Languages", "English, Hebrew")}
      ${settingsInput("Search scope", "PRs, issues, comments, code")}
      ${settingsInput("Reindex schedule", "hourly")}
      ${settingsInput("Domain dictionary", "manual + repo terms")}
    </div>
  `;
  $("#preferenceSettings").innerHTML = `
    <h2>Preferences</h2>
    <div class="settings-grid">
      ${settingsInput("Theme", state.theme)}
      ${settingsInput("Default view", "Intervention queue")}
      ${settingsInput("Density", "compact")}
      ${settingsInput("Time window", "14 days")}
    </div>
  `;
}

function openDrawer(prId) {
  const pr = prs.find((item) => item.id === Number(prId));
  const member = memberById(pr.owner);
  const backend = activeBackend();
  $("#drawerRepo").textContent = `${pr.repo} #${pr.id}`;
  $("#drawerTitle").textContent = pr.title;
  $("#drawerBody").innerHTML = `
    <section class="detail-block">
      <div class="tag-row">
        <span class="status ${pr.status}">${statusLabel(pr.status)}</span>
        <span class="tag">${pr.issue}</span>
        <span class="tag">${member.name}</span>
      </div>
      <p>${pr.summary}</p>
    </section>
    <section class="detail-block">
      <h3>Operational state</h3>
      <div class="kv-grid">
        <div class="kv"><span>Review</span><strong>${pr.review}</strong></div>
        <div class="kv"><span>Checks</span><strong>${pr.checks}</strong></div>
        <div class="kv"><span>Age</span><strong>${pr.age} days</strong></div>
        <div class="kv"><span>Comments</span><strong>${pr.comments}</strong></div>
      </div>
    </section>
    <section class="detail-block">
      <h3>Owner context</h3>
      <p><strong>${member.focus}</strong></p>
      <p>${member.responsibilities}</p>
      <div class="tag-row">${member.expertise.map((tag) => `<span class="tag">${tag}</span>`).join("")}</div>
    </section>
    <section class="detail-block">
      <h3>${backend.label} remediation plan</h3>
      <div class="timeline">
        <div class="step is-done"><i>1</i><span>Create ${backend.sessionNoun} for ${pr.branch}</span></div>
        <div class="step is-done"><i>2</i><span>Analyze conflicts, comments, checks, and linked issue context</span></div>
        <div class="step"><i>3</i><span>Prepare fix branch and patch summary</span></div>
        <div class="step"><i>4</i><span>Run required checks</span></div>
        <div class="step"><i>5</i><span>Request human approval before push</span></div>
      </div>
    </section>
    <section class="approval-panel">
      <strong>Approval gate</strong>
      <p>Agent work may prepare the patch. Pushing remains locked until a human approves the diff and check result.</p>
      <div class="button-row">
        <button class="primary-btn" data-start-run="${pr.id}"><svg><use href="#i-play"></use></svg><span>Prepare fix</span></button>
        <button class="secondary-btn">Request review</button>
        <button class="danger-btn">Hold PR</button>
      </div>
    </section>
  `;
  $("#drawer").classList.add("is-open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#scrim").classList.add("is-open");
}

function closeDrawer() {
  $("#drawer").classList.remove("is-open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").classList.remove("is-open");
}

function renderAll() {
  renderBackendChrome();
  renderFilters();
  renderMetrics();
  renderTeamStrip();
  renderPrRows();
  renderPeople();
  renderRuns();
  renderSettings();
}

function bindEvents() {
  $("#themeToggle").addEventListener("click", cycleTheme);
  $("#globalSearch").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderMetrics();
    renderPrRows();
  });
  $("#repoFilter").addEventListener("change", (event) => {
    state.repo = event.target.value;
    renderMetrics();
    renderPrRows();
  });
  $("#ownerFilter").addEventListener("change", (event) => {
    state.owner = event.target.value;
    renderMetrics();
    renderPrRows();
  });
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.remove("is-active"));
    $$(".view").forEach((view) => view.classList.remove("is-visible"));
    button.classList.add("is-active");
    $(`#${button.dataset.view}`).classList.add("is-visible");
  }));
  $$(".seg").forEach((button) => button.addEventListener("click", () => {
    $$(".seg").forEach((item) => item.classList.remove("is-active"));
    button.classList.add("is-active");
    state.queue = button.dataset.queue;
    renderMetrics();
    renderPrRows();
  }));
  document.addEventListener("click", (event) => {
    const prButton = event.target.closest("[data-open-pr]");
    if (prButton) openDrawer(prButton.dataset.openPr);
    const startRun = event.target.closest("[data-start-run]");
    if (startRun) {
      const pr = prs.find((item) => item.id === Number(startRun.dataset.startRun));
      state.runs.unshift({
        pr: `#${pr.id}`,
        title: "Fix preparation requested",
        backend: activeBackend().label,
        state: "awaiting human approval",
        detail: `${activeBackend().sessionNoun} queued for ${pr.repo}/${pr.branch}; no push will happen until approved.`
      });
      renderRuns();
      startRun.querySelector("span").textContent = "Queued";
      startRun.disabled = true;
    }
  });
  document.addEventListener("change", (event) => {
    if (event.target.id !== "agentBackendSelect") return;
    state.agentBackend = event.target.value;
    localStorage.setItem("mergeops.agentBackend", state.agentBackend);
    renderBackendChrome();
    renderRuns();
    renderSettings();
  });
  $("#closeDrawer").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawer();
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("#globalSearch").focus();
    }
  });
  document.addEventListener("input", (event) => {
    const input = event.target.closest("[data-member-index]");
    if (!input) return;
    const index = Number(input.dataset.memberIndex);
    const key = input.dataset.memberKey;
    state.members[index][key] = input.value;
    localStorage.setItem("mergeops.members", JSON.stringify(state.members));
    renderTeamStrip();
  });
  $$(".settings-tabs button").forEach((button) => button.addEventListener("click", () => {
    $$(".settings-tabs button").forEach((item) => item.classList.remove("is-active"));
    $$(".settings-panel").forEach((panel) => panel.classList.remove("is-visible"));
    button.classList.add("is-active");
    $(`#${button.dataset.settings}`).classList.add("is-visible");
  }));
  $("#addMemberBtn").addEventListener("click", () => {
    const id = `member-${Date.now()}`;
    state.members.push({
      id,
      name: "New Member",
      github: "github-id",
      aliases: "",
      focus: "Current focus",
      responsibilities: "Responsibilities",
      owns: "Owned repos / areas",
      expertise: ["reviewer"],
      timezone: "Asia/Jerusalem",
      availability: "active"
    });
    localStorage.setItem("mergeops.members", JSON.stringify(state.members));
    renderAll();
  });
}

applyTheme();
renderAll();
bindEvents();

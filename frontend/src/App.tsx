import { useEffect, useMemo, useState } from "react";
import {
  GitPullRequest,
  Activity,
  Plus,
  Save,
  Trash2,
  Monitor,
  Moon,
  Play,
  Search,
  Settings,
  Sun,
  Users,
  X,
  RefreshCw,
  FolderGit2
} from "lucide-react";
import { clearAction, createAgentRun, createCheckout, createTeamMember, deleteTeamMember, loadAppData, syncGitHub, updateGitHubSettings, updateTeamMember } from "./api";
import type { ActionRecord, ActivityEvent, AgentBackend, AgentRun, AppData, GitHubSettings, GitHubSyncResult, PullRequest, QueueFilter, RepositoryConfig, TeamMember, ThemePreference, View } from "./types";

const themeIcons = {
  system: Monitor,
  light: Sun,
  dark: Moon
};

const views: Array<{ id: View; label: string; icon: typeof GitPullRequest }> = [
  { id: "cockpit", label: "PR Cockpit", icon: GitPullRequest },
  { id: "team", label: "Team Workspace", icon: Users },
  { id: "agents", label: "Actions", icon: Play },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "settings", label: "Settings", icon: Settings }
];

function initials(name: string) {
  return name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

function statusFor(pr: PullRequest) {
  if (pr.state === "closed") return "closed";
  if (pr.state === "merged") return "merged";
  if (pr.state === "draft") return "draft";
  if (pr.mergeable === "conflicting") return "conflict";
  if (pr.checkState === "failing") return "checks";
  if (pr.reviewState === "approved" && pr.checkState === "passing") return "ready";
  return "review";
}

function statusLabel(status: string) {
  return {
    closed: "Closed",
    merged: "Merged",
    draft: "Draft",
    conflict: "Conflict",
    checks: "Checks",
    ready: "Ready",
    review: "Needs review"
  }[status] ?? status;
}

function actionFromRun(run: AgentRun): ActionRecord {
  return { id: run.id, kind: "agent_run", repository: run.repository, pullRequestId: run.pullRequestId, pullRequestNumber: run.pullRequestNumber, action: run.action, status: run.status, summary: run.summary, workspacePath: run.workspacePath, baseCommit: run.baseCommit, createdAt: run.createdAt };
}

export function App() {
  const [data, setData] = useState<AppData | null>(null);
  const [activeView, setActiveView] = useState<View>("cockpit");
  const [theme, setTheme] = useState<ThemePreference>(() => (localStorage.getItem("mergeops.theme") as ThemePreference) || "system");
  const [backendId, setBackendId] = useState<AgentBackend["id"]>(() => (localStorage.getItem("mergeops.agentBackend") as AgentBackend["id"]) || "opencode");
  const [queue, setQueue] = useState<QueueFilter>("all");
  const [repo, setRepo] = useState("all");
  const [owner, setOwner] = useState("all");
  const [dateRange, setDateRange] = useState<number | "all">(60);
  const [query, setQuery] = useState("");
  const [selectedPr, setSelectedPr] = useState<PullRequest | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [actions, setActions] = useState<ActionRecord[]>([]);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [checkoutMessage, setCheckoutMessage] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");

  useEffect(() => {
    loadAppData().then((payload) => {
      setData(payload);
      setRuns(payload.agentRuns);
      setActions(payload.actions ?? payload.agentRuns.map(actionFromRun));
      setActivity(payload.activity ?? []);
    });
  }, []);

  useEffect(() => {
    const resolved = theme === "system"
      ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : theme;
    document.documentElement.dataset.theme = resolved;
    localStorage.setItem("mergeops.theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("mergeops.agentBackend", backendId);
  }, [backendId]);

  const backend = useMemo(() => {
    return data?.agentBackends.find((item) => item.id === backendId) ?? data?.agentBackends[0];
  }, [backendId, data]);

  const teamById = useMemo(() => {
    return new Map((data?.teamMembers ?? []).map((member) => [member.id, member]));
  }, [data]);

  const scopedPrs = useMemo(() => {
    const registeredMemberIds = new Set(data?.teamMembers.map((member) => member.id) ?? []);
    return (data?.pullRequests ?? []).filter((pr) => {
      const memberMatch = owner === "all" ? registeredMemberIds.has(pr.ownerMemberId) : pr.ownerMemberId === owner;
      const rangeMatch = dateRange === "all" || pr.ageDays <= dateRange;
      return memberMatch && rangeMatch;
    });
  }, [data, dateRange, owner]);

  const filteredPrs = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return scopedPrs.filter((pr) => {
      const status = statusFor(pr);
      const queueMatch =
        queue === "all" ||
        (queue === "blocked" && ["conflict", "checks"].includes(status)) ||
        (queue === "review" && status === "review") ||
        (queue === "ready" && status === "ready") ||
        (queue === "merged" && pr.state === "merged");
      const repoMatch = repo === "all" || pr.repository === repo;
      const searchTarget = `${pr.title} ${pr.repository} ${pr.sourceBranch} ${pr.linkedIssueIds.join(" ")} ${pr.summary} ${pr.searchText}`.toLowerCase();
      return queueMatch && repoMatch && (!needle || searchTarget.includes(needle));
    });
  }, [query, queue, repo, scopedPrs]);

  if (!data || !backend) {
    return <main className="loading">Loading MergeOps</main>;
  }

  const ThemeIcon = themeIcons[theme];
  const repos = ["all", ...new Set(data.pullRequests.map((pr) => pr.repository))];

  async function startRun(pr: PullRequest) {
    const run = await createAgentRun({ backendId, pullRequestId: pr.id, action: pr.mergeable === "conflicting" ? "fix_conflicts" : "rebase" });
    setRuns((current) => [run, ...current]);
    setActions((current) => [actionFromRun(run), ...current]);
    const refreshed = await loadAppData();
    setActivity(refreshed.activity ?? []);
  }

  async function checkoutPr(pr: PullRequest) {
    setCheckoutMessage("Creating isolated checkout...");
    try {
      const result = await createCheckout(pr.id);
      setActions((current) => [result.action, ...current]);
      const refreshed = await loadAppData();
      setActivity(refreshed.activity ?? []);
      setCheckoutMessage(`${result.summary} Base ${result.baseCommit?.slice(0, 12) ?? "unknown"}.`);
    } catch (error) {
      setCheckoutMessage(error instanceof Error ? error.message : "Could not create isolated checkout");
    }
  }

  async function saveTeamMember(memberId: string, patch: Partial<TeamMember>) {
    const updated = await updateTeamMember(memberId, patch);
    setData((current) => current ? {
      ...current,
      teamMembers: current.teamMembers.map((member) => member.id === memberId ? updated : member)
    } : current);
  }

  async function addTeamMember(member: Omit<TeamMember, "id">) {
    const created = await createTeamMember(member);
    setData((current) => current ? { ...current, teamMembers: [...current.teamMembers, created] } : current);
    return created;
  }

  async function removeTeamMember(memberId: string) {
    await deleteTeamMember(memberId);
    setData((current) => current ? {
      ...current,
      teamMembers: current.teamMembers.filter((member) => member.id !== memberId)
    } : current);
  }

  async function saveGitHubSettings(input: {
    username?: string | null;
    token?: string;
    repositories?: RepositoryConfig[];
  }) {
    const github = await updateGitHubSettings(input);
    setData((current) => current ? { ...current, github } : current);
  }

  async function runGitHubSync() {
    const result = await syncGitHub();
    const payload = await loadAppData();
    setData(payload);
    setRuns(payload.agentRuns);
    setActions(payload.actions ?? payload.agentRuns.map(actionFromRun));
    setActivity(payload.activity ?? []);
    return result;
  }

  async function syncFromToolbar() {
    setSyncing(true);
    setSyncMessage("");
    try {
      const result = await runGitHubSync();
      setSyncMessage(result.errors.length ? `Synced ${result.pullRequestsImported} PRs · ${result.errors.length} error${result.errors.length === 1 ? "" : "s"}` : `Synced ${result.pullRequestsImported} PRs`);
    } catch {
      setSyncMessage("Sync failed · check Settings");
    } finally {
      setSyncing(false);
    }
  }

  async function removeAction(actionId: string) {
    await clearAction(actionId);
    setActions((current) => current.filter((action) => action.id !== actionId));
    const refreshed = await loadAppData();
    setActivity(refreshed.activity ?? []);
  }

  return (
    <div className="app-shell">
      <aside className="side-nav" aria-label="Primary">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">MO</span>
          <div>
            <strong>MergeOps</strong>
            <span>SDLC cockpit</span>
          </div>
        </div>
        <nav className="nav-list">
          {views.map((view) => {
            const Icon = view.icon;
            return (
              <button key={view.id} className={`nav-item ${activeView === view.id ? "is-active" : ""}`} onClick={() => setActiveView(view.id)}>
                <Icon size={18} />
                <span>{view.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="side-status">
          <span>{backend.displayName}</span>
          <strong>{backend.endpoint.replace(/^https?:\/\//, "")}</strong>
          <small>ready for approval-gated sessions</small>
        </div>
      </aside>

      <main className="workspace">
        {activeView === "cockpit" && (
          <header className="topbar">
            <label className="search-wrap" aria-label="Bilingual PR and issue search">
              <Search size={18} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} type="search" placeholder="Search PRs, issues, comments, Hebrew or English" />
            </label>
            <div className="top-actions">
              <select value={repo} onChange={(event) => setRepo(event.target.value)} aria-label="Repository filter">
                {repos.map((item) => <option key={item} value={item}>{item === "all" ? "All repos" : item}</option>)}
              </select>
              <select value={owner} onChange={(event) => setOwner(event.target.value)} aria-label="Team member filter">
                <option value="all">All members</option>
                {data.teamMembers.map((member) => <option key={member.id} value={member.id}>{member.displayName}</option>)}
              </select>
              <select value={dateRange} onChange={(event) => setDateRange(event.target.value === "all" ? "all" : Number(event.target.value))} aria-label="PR age range">
                <option value={30}>Last 30 days</option>
                <option value={60}>Last 60 days</option>
                <option value={90}>Last 90 days</option>
                <option value="all">All time</option>
              </select>
              <button className="secondary-btn sync-btn" type="button" onClick={syncFromToolbar} disabled={syncing}>
                <RefreshCw size={16} className={syncing ? "spin" : ""} />
                {syncing ? "Syncing" : "Re-sync"}
              </button>
              {syncMessage ? <span className="sync-status">{syncMessage}</span> : null}
              <button className="icon-btn" type="button" onClick={() => setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system")} aria-label={`Theme: ${theme}`} title={`Theme: ${theme}`}>
                <ThemeIcon size={18} />
              </button>
            </div>
          </header>
        )}

        {activeView === "cockpit" && (
          <Cockpit
            prs={filteredPrs}
            allPrs={scopedPrs}
            teamMembers={data.teamMembers}
            teamById={teamById}
            github={data.github}
            queue={queue}
            onQueueChange={setQueue}
            onSelectPr={setSelectedPr}
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
          />
        )}
        {activeView === "team" && <TeamWorkspace members={data.teamMembers} onSaveMember={saveTeamMember} onAddMember={addTeamMember} onDeleteMember={removeTeamMember} />}
        {activeView === "agents" && <ActionsView actions={actions} onClear={removeAction} />}
        {activeView === "activity" && <ActivityView events={activity} />}
        {activeView === "settings" && (
          <SettingsView
            backendId={backendId}
            backends={data.agentBackends}
            onBackendChange={setBackendId}
            theme={theme}
            onThemeChange={setTheme}
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            query={query}
            onQueryChange={setQuery}
            members={data.teamMembers}
            onOpenTeam={() => setActiveView("team")}
            github={data.github}
            onSaveGitHub={saveGitHubSettings}
            onSyncGitHub={runGitHubSync}
          />
        )}
      </main>

      {selectedPr && (
        <PrDrawer
          pr={selectedPr}
          member={teamById.get(selectedPr.ownerMemberId)}
          backend={backend}
          onClose={() => setSelectedPr(null)}
          onStartRun={() => startRun(selectedPr)}
          onCheckout={() => checkoutPr(selectedPr)}
          checkoutMessage={checkoutMessage}
        />
      )}
    </div>
  );
}

function Cockpit(props: {
  prs: PullRequest[];
  allPrs: PullRequest[];
  teamMembers: TeamMember[];
  teamById: Map<string, TeamMember>;
  github?: GitHubSettings | null;
  queue: QueueFilter;
  onQueueChange: (queue: QueueFilter) => void;
  onSelectPr: (pr: PullRequest) => void;
  dateRange: number | "all";
  onDateRangeChange: (range: number | "all") => void;
}) {
  const openCount = props.allPrs.filter((pr) => pr.state === "open").length;
  const mergedCount = props.allPrs.filter((pr) => pr.state === "merged").length;
  const closedCount = props.allPrs.filter((pr) => pr.state === "closed").length;
  const repositoryNames = props.github?.repositories.map((repository) => repository.name).join(", ");
  const lastSynced = props.github?.lastSyncedAt ? new Date(props.github.lastSyncedAt).toLocaleString() : "not synced";
  const metrics = [
    ["Open", openCount],
    ["Merged", mergedCount],
    ["Closed", closedCount],
    ["Conflicts", props.allPrs.filter((pr) => pr.mergeable === "conflicting").length],
    ["Review comments", props.allPrs.reduce((sum, pr) => sum + pr.unresolvedCommentCount, 0)],
    ["Ready", props.allPrs.filter((pr) => statusFor(pr) === "ready").length]
  ];

  return (
    <section className="view is-visible" aria-labelledby="cockpitTitle">
      <div className="view-head">
        <div>
          <h1 id="cockpitTitle">PR Triage</h1>
          <p>
            {props.allPrs.length
              ? `${props.allPrs.length} team PRs in the last ${props.dateRange === "all" ? "all time" : `${props.dateRange} days`} · ${repositoryNames || "configured repositories"} · last sync ${lastSynced}`
              : `No registered-member PRs in the last ${props.dateRange === "all" ? "all time" : `${props.dateRange} days`} · last sync ${lastSynced}`}
          </p>
        </div>
      </div>
      <div className="cockpit-filters">
        <div className="saved-views" role="group" aria-label="Saved views">
          {(["all", "blocked", "review", "ready", "merged"] as QueueFilter[]).map((item) => (
            <button key={item} className={`seg ${props.queue === item ? "is-active" : ""}`} onClick={() => props.onQueueChange(item)}>
              {item === "all" ? "All" : item === "blocked" ? "Blocked" : item === "review" ? "Needs review" : item === "ready" ? "Ready" : "Merged"}
            </button>
          ))}
        </div>
      </div>
      <div className="metrics-rack">
        {metrics.map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}
      </div>
      <div className="team-strip">
        {props.teamMembers.map((member) => {
          const owned = props.allPrs.filter((pr) => pr.ownerMemberId === member.id);
          const blocked = owned.filter((pr) => ["conflict", "checks"].includes(statusFor(pr))).length;
          return (
            <article className="member-tile" key={member.id}>
              <div className="member-top">
                <span className="avatar">{initials(member.displayName)}</span>
                <span className="member-meta"><strong>{member.displayName}</strong><span>@{member.githubUsername} · {member.availability.replace("_", " ")}</span></span>
                <span className="load">{owned.length} PRs</span>
              </div>
              <div className="tag-row">
                <span className="tag">{member.currentFocus}</span>
                <span className={`status ${blocked ? "conflict" : "ready"}`}>{blocked ? `${blocked} blocked` : "clear"}</span>
              </div>
            </article>
          );
        })}
      </div>
      <div className="table-shell">
        <div className="table-toolbar">
          <strong>Live PRs</strong>
          <span>{props.prs.length} matching PRs</span>
        </div>
        <div className="pr-table" role="table" aria-label="Pull requests">
          <div className="pr-row pr-head" role="row">
            <span>Priority</span><span>PR</span><span>Owner</span><span>Review</span><span>Checks</span><span>Age</span><span>Action</span>
          </div>
          {props.prs.map((pr) => {
            const member = props.teamById.get(pr.ownerMemberId);
            const status = statusFor(pr);
            return (
              <div className="pr-row" role="row" key={pr.id}>
                <div className="pr-cell"><span className={`status ${status}`}>{statusLabel(status)}</span></div>
                <div className="pr-cell"><span className="pr-title"><strong>{pr.title}</strong><span>{pr.repository} #{pr.number} · {pr.state} · {pr.sourceBranch}</span></span></div>
                <div className="pr-cell">{member?.displayName ?? pr.author}</div>
                <div className="pr-cell">{pr.reviewState.replace("_", " ")}</div>
                <div className="pr-cell">{pr.checkState.replace("_", " ")}</div>
                <div className="pr-cell">{pr.ageDays}d</div>
                <div className="pr-cell"><button className="text-btn" onClick={() => props.onSelectPr(pr)}>Inspect</button></div>
              </div>
            );
          })}
          {!props.prs.length && (
            <div className="empty-state">
              <strong>No PRs match this view</strong>
              <span>Clear search, switch to All repos / All members, or check the sync result in Settings.</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function TeamWorkspace({
  members,
  onSaveMember,
  onAddMember,
  onDeleteMember
}: {
  members: TeamMember[];
  onSaveMember: (memberId: string, patch: Partial<TeamMember>) => Promise<void>;
  onAddMember: (member: Omit<TeamMember, "id">) => Promise<TeamMember>;
  onDeleteMember: (memberId: string) => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState(members[0]?.id ?? "");
  const [draft, setDraft] = useState<TeamMemberDraft>(() => memberToDraft(members[0]));
  const [status, setStatus] = useState("");
  const selectedMember = members.find((member) => member.id === selectedId);

  useEffect(() => {
    // An empty selection is deliberate: it is the new-member form.
    if (!selectedId) return;
    const nextMember = members.find((member) => member.id === selectedId) ?? members[0];
    if (nextMember?.id !== selectedId) setSelectedId(nextMember?.id ?? "");
    setDraft(memberToDraft(nextMember));
  }, [members, selectedId]);

  function updateDraft(key: keyof TeamMemberDraft, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function saveDraft(event: React.FormEvent) {
    event.preventDefault();
    setStatus("Saving member");
    try {
      if (selectedMember) {
        await onSaveMember(selectedMember.id, draftToMemberPayload(draft));
        setStatus("Member saved");
      } else {
        const created = await onAddMember(draftToNewMember(draft));
        setSelectedId(created.id);
        setStatus("Member added");
      }
    } catch {
      setStatus("Member save failed");
    }
  }

  async function addMember() {
    setSelectedId("");
    setDraft(emptyMemberDraft());
    setStatus("Adding new member");
  }

  async function deleteMember() {
    if (!selectedMember) return;
    setStatus("Deleting member");
    try {
      await onDeleteMember(selectedMember.id);
      setStatus("Member deleted");
    } catch {
      setStatus("Delete failed");
    }
  }

  return (
    <section className="view is-visible" aria-labelledby="teamTitle">
      <div className="view-head">
        <div>
          <h1 id="teamTitle">Team workspace</h1>
          <p>{members.length} team members · edit GitHub IDs, responsibilities, focus, ownership, aliases, and availability.</p>
        </div>
        <button className="primary-btn" onClick={addMember}><Plus size={18} /><span>Add member</span></button>
      </div>
      <div className="team-manager">
        <div className="member-list" aria-label="Team members">
          {members.map((member) => (
            <button key={member.id} className={`member-row ${selectedId === member.id ? "is-active" : ""}`} onClick={() => setSelectedId(member.id)}>
              <span className="avatar">{initials(member.displayName)}</span>
              <span className="member-meta"><strong>{member.displayName}</strong><span>@{member.githubUsername} · {member.availability.replace("_", " ")}</span></span>
            </button>
          ))}
          {!members.length ? <div className="empty-state compact"><strong>No members yet</strong><span>Add your first team member.</span></div> : null}
        </div>
        <form className="person-card member-editor" onSubmit={saveDraft}>
          <header>
            <span className="avatar">{initials(draft.displayName || "New Member")}</span>
            <span className="member-meta">
              <strong>{selectedMember ? "Edit team member" : "New team member"}</strong>
              <span>{selectedMember ? `Member id: ${selectedMember.id}` : "Created locally after save"}</span>
            </span>
          </header>
          <div className="profile-fields">
            <ProfileInput label="Display name" value={draft.displayName} onChange={(value) => updateDraft("displayName", value)} />
            <ProfileInput label="GitHub username" value={draft.githubUsername} onChange={(value) => updateDraft("githubUsername", value)} />
            <ProfileInput label="Current focus" value={draft.currentFocus} onChange={(value) => updateDraft("currentFocus", value)} />
            <ProfileInput label="Responsibilities" value={draft.responsibilities} onChange={(value) => updateDraft("responsibilities", value)} />
            <ProfileInput label="Owned repos" value={draft.ownedRepos} onChange={(value) => updateDraft("ownedRepos", value)} />
            <ProfileInput label="Owned paths" value={draft.ownedPaths} onChange={(value) => updateDraft("ownedPaths", value)} />
            <ProfileInput label="Expertise tags" value={draft.expertiseTags} onChange={(value) => updateDraft("expertiseTags", value)} />
            <ProfileInput label="Timezone" value={draft.timezone} onChange={(value) => updateDraft("timezone", value)} />
            <label className="field">
              <span>Availability</span>
              <select value={draft.availability} onChange={(event) => updateDraft("availability", event.target.value)}>
                <option value="active">Active</option>
                <option value="focus_mode">Focus mode</option>
                <option value="ooo">Out of office</option>
                <option value="overloaded">Overloaded</option>
                <option value="inactive">Inactive</option>
              </select>
            </label>
            <ProfileInput label="Git aliases" value={draft.gitAliases} onChange={(value) => updateDraft("gitAliases", value)} full />
            <ProfileInput label="Emails" value={draft.emails} onChange={(value) => updateDraft("emails", value)} full />
          </div>
          <div className="settings-actions">
            <button className="primary-btn" type="submit"><Save size={18} /><span>Save member</span></button>
            <button className="danger-btn" type="button" onClick={deleteMember} disabled={!selectedMember}><Trash2 size={18} /><span>Delete</span></button>
            {status ? <span className="sync-status">{status}</span> : null}
          </div>
        </form>
      </div>
    </section>
  );
}

function splitList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function ProfileInput({ label, value, full = false, onChange }: { label: string; value: string; full?: boolean; onChange: (value: string) => void }) {
  return (
    <label className={`field ${full ? "full" : ""}`}>
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

type TeamMemberDraft = {
  displayName: string;
  githubUsername: string;
  gitAliases: string;
  emails: string;
  currentFocus: string;
  responsibilities: string;
  ownedRepos: string;
  ownedPaths: string;
  expertiseTags: string;
  timezone: string;
  availability: TeamMember["availability"];
};

function emptyMemberDraft(): TeamMemberDraft {
  return {
    displayName: "",
    githubUsername: "",
    gitAliases: "",
    emails: "",
    currentFocus: "",
    responsibilities: "",
    ownedRepos: "",
    ownedPaths: "",
    expertiseTags: "",
    timezone: "Asia/Jerusalem",
    availability: "active"
  };
}

function memberToDraft(member?: TeamMember): TeamMemberDraft {
  if (!member) return emptyMemberDraft();
  return {
    displayName: member.displayName,
    githubUsername: member.githubUsername,
    gitAliases: member.gitAliases.join(", "),
    emails: member.emails.join(", "),
    currentFocus: member.currentFocus,
    responsibilities: member.responsibilities,
    ownedRepos: member.ownedRepos.join(", "),
    ownedPaths: member.ownedPaths.join(", "),
    expertiseTags: member.expertiseTags.join(", "),
    timezone: member.timezone,
    availability: member.availability
  };
}

function draftToMemberPayload(draft: TeamMemberDraft): Partial<TeamMember> {
  return {
    displayName: draft.displayName.trim(),
    githubUsername: draft.githubUsername.trim(),
    gitAliases: splitList(draft.gitAliases),
    emails: splitList(draft.emails),
    currentFocus: draft.currentFocus.trim(),
    responsibilities: draft.responsibilities.trim(),
    ownedRepos: splitList(draft.ownedRepos),
    ownedPaths: splitList(draft.ownedPaths),
    expertiseTags: splitList(draft.expertiseTags),
    timezone: draft.timezone.trim() || "Asia/Jerusalem",
    availability: draft.availability
  };
}

function draftToNewMember(draft: TeamMemberDraft): Omit<TeamMember, "id"> {
  return {
    displayName: draft.displayName.trim() || "New Member",
    githubUsername: draft.githubUsername.trim(),
    gitAliases: splitList(draft.gitAliases),
    emails: splitList(draft.emails),
    currentFocus: draft.currentFocus.trim(),
    responsibilities: draft.responsibilities.trim(),
    ownedRepos: splitList(draft.ownedRepos),
    ownedPaths: splitList(draft.ownedPaths),
    expertiseTags: splitList(draft.expertiseTags),
    timezone: draft.timezone.trim() || "Asia/Jerusalem",
    availability: draft.availability
  };
}

function ActionsView({ actions, onClear }: { actions: ActionRecord[]; onClear: (actionId: string) => Promise<void> }) {
  const terminalStatuses = new Set(["ready", "failed", "cancelled", "pushed", "approved", "awaiting_approval"]);
  return (
    <section className="view is-visible" aria-labelledby="agentsTitle">
      <div className="view-head">
        <div>
          <h1 id="agentsTitle">Actions</h1>
          <p>Checkout workspaces and agent sessions across the PR queue.</p>
        </div>
      </div>
      <div className="runs-list">
        {actions.length === 0 ? <p className="empty-state">No actions yet.</p> : actions.map((action) => (
          <article className="run-item" key={action.id}>
            <div>
              <strong>{action.kind === "checkout" ? "Checkout" : "Agent run"} · {action.repository} #{action.pullRequestNumber}</strong>
              <p>{action.summary}</p>
              {action.workspacePath ? <span className="action-meta">Workspace: {action.workspacePath} · base {action.baseCommit?.slice(0, 12) ?? "unknown"}</span> : null}
            </div>
            <div className="action-controls"><span className="status agent">{action.status.replace("_", " ")}</span>{terminalStatuses.has(action.status) ? <button className="icon-btn" type="button" onClick={() => onClear(action.id)} aria-label={`Clear ${action.kind} action`} title="Clear action and workspace"><Trash2 size={16} /></button> : <button className="secondary-btn" type="button" disabled title="Stopping active runs is planned">Stop</button>}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ActivityView({ events }: { events: ActivityEvent[] }) {
  const sortedEvents = [...events].sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  return (
    <section className="view is-visible" aria-labelledby="activityTitle">
      <div className="view-head">
        <div>
          <h1 id="activityTitle">Activity</h1>
          <p>Operational events across PR triage, actions, sync, team, and settings.</p>
        </div>
      </div>
      <div className="activity-list">
        {sortedEvents.length === 0 ? <p className="empty-state">No activity yet.</p> : sortedEvents.map((event) => (
          <article className="activity-item" key={event.id}>
            <span className="activity-dot" aria-hidden="true" />
            <div>
              <strong>{event.message}</strong>
              <span className="activity-meta">{event.kind.replace(/_/g, " ")}{event.actionId ? ` · ${event.actionId}` : ""}</span>
            </div>
            <time dateTime={event.createdAt}>{new Date(event.createdAt).toLocaleString()}</time>
          </article>
        ))}
      </div>
    </section>
  );
}

function SettingsView(props: {
  backendId: AgentBackend["id"];
  backends: AgentBackend[];
  onBackendChange: (backendId: AgentBackend["id"]) => void;
  theme: ThemePreference;
  onThemeChange: (theme: ThemePreference) => void;
  dateRange: number | "all";
  onDateRangeChange: (dateRange: number | "all") => void;
  query: string;
  onQueryChange: (query: string) => void;
  members: TeamMember[];
  onOpenTeam: () => void;
  github?: GitHubSettings | null;
  onSaveGitHub: (input: { username?: string | null; token?: string; repositories?: RepositoryConfig[] }) => Promise<void>;
  onSyncGitHub: () => Promise<GitHubSyncResult>;
}) {
  type SettingsTab = "Team" | "Repositories" | "Integrations" | "Automation Policy" | "Search" | "Preferences";
  const [activeTab, setActiveTab] = useState<SettingsTab>("Integrations");
  const [token, setToken] = useState("");
  const [username, setUsername] = useState(props.github?.username ?? "");
  const [repoText, setRepoText] = useState(formatRepositories(props.github?.repositories ?? []));
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    setUsername(props.github?.username ?? "");
    setRepoText(formatRepositories(props.github?.repositories ?? []));
  }, [props.github]);

  async function saveGitHub(event: React.FormEvent) {
    event.preventDefault();
    setStatus("Saving GitHub settings");
    try {
      await props.onSaveGitHub({
        username: username.trim() || null,
        token: token.trim() || undefined,
        repositories: parseRepositories(repoText)
      });
      setToken("");
      setStatus("GitHub settings saved");
    } catch {
      setStatus("GitHub settings failed");
    }
  }

  async function syncNow() {
    setStatus("Syncing GitHub PRs");
    try {
      const result = await props.onSyncGitHub();
      setStatus(result.errors.length ? `Synced ${result.pullRequestsImported} PRs with ${result.errors.length} errors` : `Synced ${result.pullRequestsImported} PRs`);
    } catch {
      setStatus("GitHub sync failed");
    }
  }

  return (
    <section className="view is-visible" aria-labelledby="settingsTitle">
      <div className="view-head">
        <div>
          <h1 id="settingsTitle">Settings</h1>
          <p>Configure people, repositories, integrations, automation policy, search, and dashboard defaults.</p>
        </div>
      </div>
      <div className="settings-layout">
        <nav className="settings-tabs" aria-label="Settings sections">
          {["Team", "Repositories", "Integrations", "Automation Policy", "Search", "Preferences"].map((item) => (
            <button key={item} type="button" className={activeTab === item ? "is-active" : ""} onClick={() => setActiveTab(item as SettingsTab)}>{item}</button>
          ))}
        </nav>
        {activeTab === "Team" && (
          <div className="settings-panel is-visible">
            <h2>Team</h2>
            <p className="settings-intro">Team identity and ownership fields are managed in the Team Workspace.</p>
            <div className="settings-list">
              {props.members.map((member) => <div className="settings-list-row" key={member.id}><strong>{member.displayName}</strong><span>@{member.githubUsername || "unlinked"} · {member.availability.replace("_", " ")}</span></div>)}
            </div>
            <div className="settings-actions"><button className="secondary-btn" type="button" onClick={props.onOpenTeam}>Open Team Workspace</button></div>
          </div>
        )}
        {activeTab === "Repositories" && (
          <form className="settings-panel is-visible" onSubmit={saveGitHub}>
            <h2>Repositories</h2>
            <p className="settings-intro">Register GitHub repositories and optional local checkouts for agent runs.</p>
            <label className="field full"><span>Repository allowlist</span><textarea value={repoText} onChange={(event) => setRepoText(event.target.value)} rows={7} placeholder="owner/repo | /absolute/local/path" /></label>
            <div className="settings-actions"><button className="primary-btn" type="submit">Save repositories</button><button className="secondary-btn" type="button" onClick={syncNow}>Sync now</button>{status ? <span className="sync-status">{status}</span> : null}</div>
          </form>
        )}
        {activeTab === "Integrations" && (
          <form className="settings-panel is-visible" onSubmit={saveGitHub}>
            <h2>Integrations</h2>
            <div className="settings-grid">
              <label className="field"><span>GitHub access</span><input readOnly value="Contributor token" /></label>
              <label className="field"><span>Backend agent SDK</span><select value={props.backendId} onChange={(event) => props.onBackendChange(event.target.value as AgentBackend["id"])}>{props.backends.map((backend) => <option key={backend.id} value={backend.id}>{backend.displayName}</option>)}</select></label>
              <label className="field"><span>Agent endpoint</span><input readOnly value={props.backends.find((item) => item.id === props.backendId)?.endpoint ?? "Unavailable"} /></label>
              <label className="field"><span>GitHub username</span><input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="your-github-id" /></label>
              <label className="field"><span>Contributor token <small>{props.github?.hasToken ? "stored locally" : "not set"}</small></span><input value={token} onChange={(event) => setToken(event.target.value)} type="password" placeholder={props.github?.hasToken ? "Leave blank to keep current token" : "Fine-grained token"} /></label>
            </div>
            <div className="settings-actions"><button className="primary-btn" type="submit">Save integration settings</button>{status ? <span className="sync-status">{status}</span> : null}</div>
          </form>
        )}
        {activeTab === "Automation Policy" && (
          <div className="settings-panel is-visible"><h2>Automation Policy</h2><p className="settings-intro">Policy controls are planned for the approval-gated fix flow and are not connected yet.</p><div className="settings-notice"><strong>Planned</strong><span>Push approval, required checks, and per-action guardrails will be persisted here before any automatic push capability is added.</span></div></div>
        )}
        {activeTab === "Search" && (
          <div className="settings-panel is-visible"><h2>Search</h2><p className="settings-intro">Search is active across PR titles, branches, linked issues, summaries, comments, and English/Hebrew text.</p><label className="field full"><span>Current dashboard query</span><input value={props.query} onChange={(event) => props.onQueryChange(event.target.value)} placeholder="Search PRs, issues, comments, Hebrew or English" /></label><div className="settings-notice"><strong>Search scope</strong><span>The current release searches the loaded PR snapshot. Issue, comment, and code-result adapters are planned.</span></div></div>
        )}
        {activeTab === "Preferences" && (
          <div className="settings-panel is-visible"><h2>Preferences</h2><div className="settings-grid"><label className="field"><span>Theme</span><select value={props.theme} onChange={(event) => props.onThemeChange(event.target.value as ThemePreference)}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><label className="field"><span>PR age range</span><select value={props.dateRange} onChange={(event) => props.onDateRangeChange(event.target.value === "all" ? "all" : Number(event.target.value))}><option value="30">Last 30 days</option><option value="60">Last 60 days</option><option value="90">Last 90 days</option><option value="all">All time</option></select></label></div><p className="settings-intro">These preferences are stored locally in this browser.</p></div>
        )}
      </div>
    </section>
  );
}

function formatRepositories(repositories: RepositoryConfig[]) {
  return repositories.map((repository) => {
    const remote = `${repository.owner}/${repository.name}`;
    return repository.localPath ? `${remote} | ${repository.localPath}` : remote;
  }).join("\n");
}

function parseRepositories(value: string): RepositoryConfig[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [remote, localPath] = line.split("|").map((part) => part.trim());
    const [owner, name] = remote.split("/");
    const repoName = name || owner;
    return {
      id: `${owner}-${repoName}`.replace(/[^a-zA-Z0-9_.-]/g, "-"),
      owner: owner || "",
      name: repoName || "",
      defaultBranch: "main",
      enabled: true,
      localPath: localPath || null
    };
  }).filter((repository) => repository.owner && repository.name);
}

function PrDrawer(props: {
  pr: PullRequest;
  member?: TeamMember;
  backend: AgentBackend;
  onClose: () => void;
  onStartRun: () => void;
  onCheckout: () => void;
  checkoutMessage: string;
}) {
  const status = statusFor(props.pr);
  return (
    <>
      <aside className="drawer is-open" aria-labelledby="drawerTitle">
        <div className="drawer-head">
          <div>
            <span>{props.pr.repository} #{props.pr.number}</span>
            <h2 id="drawerTitle">{props.pr.title}</h2>
          </div>
          <button className="icon-btn" onClick={props.onClose} aria-label="Close drawer"><X size={18} /></button>
        </div>
        <div className="drawer-body">
          <section className="detail-block">
            <div className="tag-row">
              <span className={`status ${status}`}>{statusLabel(status)}</span>
              {props.pr.linkedIssueIds.map((issue) => <span className="tag" key={issue}>{issue}</span>)}
              <span className="tag">{props.member?.displayName ?? props.pr.author}</span>
            </div>
            <p>{props.pr.summary}</p>
          </section>
          <section className="detail-block">
            <h3>Operational state</h3>
            <div className="kv-grid">
              <div className="kv"><span>Review</span><strong>{props.pr.reviewState.replace("_", " ")}</strong></div>
              <div className="kv"><span>Checks</span><strong>{props.pr.checkState.replace("_", " ")}</strong></div>
              <div className="kv"><span>Age</span><strong>{props.pr.ageDays} days</strong></div>
              <div className="kv"><span>Comments</span><strong>{props.pr.unresolvedCommentCount}</strong></div>
            </div>
            <p className="drawer-meta"><strong>{props.pr.repositoryFullName ?? props.pr.repository}</strong> · {props.pr.sourceBranch} → {props.pr.baseBranch} · {props.pr.changedFilesCount} changed files</p>
          </section>
          <section className="detail-block">
            <h3>Owner context</h3>
            <p><strong>{props.member?.currentFocus}</strong></p>
            <p>{props.member?.responsibilities}</p>
            <div className="tag-row">{props.member?.expertiseTags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div>
          </section>
          <section className="detail-block">
            <h3>{props.backend.displayName} remediation plan</h3>
            <div className="timeline">
              <div className="step"><i>1</i><span>Checkout the PR into an isolated workspace</span></div>
              <div className="step"><i>2</i><span>Analyze conflicts, comments, checks, and linked issue context</span></div>
              <div className="step"><i>3</i><span>Prepare fix branch and patch summary</span></div>
              <div className="step"><i>4</i><span>Run required checks</span></div>
              <div className="step"><i>5</i><span>Request human approval before push</span></div>
            </div>
          </section>
          <section className="approval-panel">
            <strong>Approval gate</strong>
            <p>Agent work may prepare the patch. Pushing remains locked until a human approves the diff and check result.</p>
            <div className="button-row">
              <button className="secondary-btn" onClick={props.onCheckout}><FolderGit2 size={18} /><span>Checkout</span></button>
              <button className="primary-btn" onClick={props.onStartRun}><Play size={18} /><span>Prepare fix</span></button>
              <button className="secondary-btn" disabled title="GitHub write action is planned">Request review</button>
              <button className="danger-btn" disabled title="Hold policy is planned">Hold PR</button>
            </div>
            {props.checkoutMessage ? <p className="sync-status" role="status">{props.checkoutMessage}</p> : null}
          </section>
        </div>
      </aside>
      <div className="scrim is-open" onClick={props.onClose} />
    </>
  );
}

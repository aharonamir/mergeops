import { useEffect, useMemo, useRef, useState } from "react";
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
  FolderGit2,
  FileSearch,
  GitCompare,
  GitCommitHorizontal,
  ChevronDown,
  ChevronUp,
  BellRing,
  CircleAlert
} from "lucide-react";
import { approveAgentRun, cancelAgentRun, cancelSearchRun, checkBackendHealth, clearAction, clearAllActivity, clearAllAgentRuns, continueRebaseAgentRun, createAgentRun, createCheckout, createPrNote, createSearchRun, createTeamMember, deletePrNote, deleteTeamMember, inspectRecoveryAgentRun, loadActionDetails, loadAppData, loadPrAnnotations, loadReviewThreads, postReviewReplies, pushAgentRun, revalidateManualRun, reviseAgentRun, retryAgentRun, reviewPatch, selectRebaseDecision, subscribeToAgentEvents, syncGitHub, updateAgentSettings, updateGitHubSettings, updatePrTags, updateSearchSettings, updateTeamMember } from "./api";
import type { ActionRecord, ActivityEvent, AgentBackend, AgentRun, AgentRunEvent, AgentRunSummary, AgentSettings, AppData, ConflictEvidence, GitHubSettings, GitHubSyncResult, PrAnnotations, PullRequest, QueueFilter, ReplyDraft, RepositoryConfig, ReviewThread, ReviewThreadSnapshot, SearchRun, SearchSettings, TeamMember, ThemePreference, View } from "./types";
import { useLocale, type TranslationKey } from "./i18n";

const themeIcons = {
  system: Monitor,
  light: Sun,
  dark: Moon
};

const views: Array<{ id: View; label: string; icon: typeof GitPullRequest }> = [
  { id: "cockpit", label: "PR Cockpit", icon: GitPullRequest },
  { id: "search", label: "Search", icon: Search },
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

function matchesQueue(pr: PullRequest, queue: QueueFilter) {
  const status = statusFor(pr);
  return queue === "all"
    || (queue === "open" && pr.state === "open")
    || (queue === "needs_you" && pr.state === "open" && (pr.checkState === "failing" || pr.unresolvedCommentCount > 0 || pr.reviewState === "changes_requested" || pr.reviewState === "review_required"))
    || (queue === "conflict" && status === "conflict")
    || (queue === "review" && status === "review")
    || (queue === "ready" && status === "ready")
    || (queue === "merged" && pr.state === "merged")
    || (queue === "closed" && pr.state === "closed");
}

function drawerPlan(status: string) {
  if (status === "conflict") {
    return {
      title: "Recommended action: rebase and resolve conflicts",
      explanation: "This PR is blocked by merge conflicts. Prepare an isolated rebase, resolve the conflicting files, and rerun the required checks.",
      steps: ["Create an isolated checkout", "Rebase the source branch onto the base branch", "Resolve conflicts and summarize the patch", "Run required checks"],
      action: "Prepare conflict fix"
    };
  }
  if (status === "checks") {
    return {
      title: "Recommended action: repair failing checks",
      explanation: "Required checks are failing. Prepare a focused fix in an isolated workspace and verify the failing checks before review.",
      steps: ["Create an isolated checkout", "Inspect failing check output", "Prepare the smallest fix", "Run required checks"],
      action: "Prepare check fix"
    };
  }
  if (status === "review") {
    return {
      title: "Recommended action: address review feedback",
      explanation: "This PR needs reviewer attention. Inspect the unresolved comments and prepare a focused response before requesting another review.",
      steps: ["Create an isolated checkout", "Inspect comments and changed files", "Prepare the requested changes", "Run required checks"],
      action: "Prepare review fix"
    };
  }
  if (status === "ready") {
    return {
      title: "Recommended action: verify and approve",
      explanation: "The PR has passing checks and no detected merge blocker. Review the change and approve it through the repository workflow.",
      steps: ["Inspect the existing patch", "Confirm checks are passing", "Request or complete review", "Merge through GitHub"],
      action: "Prepare review"
    };
  }
  if (status === "draft") {
    return {
      title: "Draft PR: review only",
      explanation: "This PR is still a draft. Keep remediation actions disabled until the author marks it ready for review.",
      steps: ["Inspect the draft context", "Confirm the author is ready", "Review checks and comments"],
      action: null
    };
  }
  return null;
}

function actionFromRun(run: AgentRun): ActionRecord {
  return { id: run.id, kind: "agent_run", repository: run.repository, pullRequestId: run.pullRequestId, pullRequestNumber: run.pullRequestNumber, action: run.action, status: run.status, summary: run.summary, rootRunId: run.rootRunId, parentRunId: run.parentRunId, supersededByRunId: run.supersededByRunId, feedback: run.feedback, agentOutput: run.agentOutput, workspacePath: run.workspacePath, baseCommit: run.baseCommit, events: run.events, patchSummary: run.patchSummary, diff: run.diff, checks: run.checks, riskSummary: run.riskSummary, approval: run.approval, pushRef: run.pushRef, diffHash: run.diffHash, pushedCommitSha: run.pushedCommitSha, selectedReviewThreads: run.selectedReviewThreads, dispositions: run.dispositions, replyDrafts: run.replyDrafts, replyResults: run.replyResults, recoveryNote: run.recoveryNote, recoveryInspected: run.recoveryInspected, createdAt: run.createdAt };
}

function actionFromSummary(run: AgentRunSummary): ActionRecord {
  return { id: run.id, kind: "agent_run", repository: run.repository, pullRequestId: run.pullRequestId, pullRequestNumber: run.pullRequestNumber, action: run.action, status: run.status, summary: run.summary, rootRunId: run.rootRunId, parentRunId: run.parentRunId, supersededByRunId: run.supersededByRunId, workspacePath: run.workspacePath, baseCommit: run.baseCommit, diffHash: run.diffHash, pushedCommitSha: run.pushedCommitSha, eventCount: run.eventCount, checkCount: run.checkCount, conflictCount: run.conflictCount, resolvedConflictCount: run.resolvedConflictCount, blockedCommandCount: run.blockedCommandCount, hasRebaseEvidence: run.hasRebaseEvidence, recoveryInspected: run.recoveryInspected, createdAt: run.createdAt };
}

function drawerRunForPr(actions: ActionRecord[], pullRequestId: string): ActionRecord | undefined {
  const runs = actions.filter((action) => action.kind === "agent_run" && action.pullRequestId === pullRequestId);
  const writableStatuses = new Set(["queued", "running", "checks_running", "awaiting_decision", "patch_ready", "awaiting_approval", "approved"]);
  return runs.filter((action) => writableStatuses.has(action.status)).sort((left, right) => right.createdAt.localeCompare(left.createdAt))[0]
    ?? runs.sort((left, right) => right.createdAt.localeCompare(left.createdAt))[0];
}

export function App() {
  const { locale, setLocale, t } = useLocale();
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
  const [annotations, setAnnotations] = useState<PrAnnotations | null>(null);
  const [runs, setRuns] = useState<Array<AgentRun | AgentRunSummary>>([]);
  const [actions, setActions] = useState<ActionRecord[]>([]);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [activityMessage, setActivityMessage] = useState("");
  const [checkoutMessage, setCheckoutMessage] = useState("");
  const [diffAction, setDiffAction] = useState<ActionRecord | null>(null);
  const [detailsAction, setDetailsAction] = useState<ActionRecord | null>(null);
  const [details, setDetails] = useState<AgentRun | ActionRecord | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [actionsMessage, setActionsMessage] = useState("");
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    loadAppData().then((payload) => {
      setData(payload);
      setRuns(payload.agentRuns);
      setActions(payload.actions ?? payload.agentRuns.map(actionFromSummary));
      setActivity(payload.activity ?? []);
    });
  }, []);

  useEffect(() => {
    let disposed = false;
    const refreshHealth = async () => {
      const online = await checkBackendHealth();
      if (!disposed) setBackendStatus(online ? "online" : "offline");
    };
    void refreshHealth();
    const timer = window.setInterval(refreshHealth, 10000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  const hasActiveWork = actions.some((action) => ["queued", "running", "patch_ready", "checks_running", "awaiting_decision"].includes(action.status));
  const hasActiveSearch = Boolean(data?.searchRuns.some((run) => ["queued", "running"].includes(run.status)));

  useEffect(() => {
    if (!hasActiveWork) return;
    const refresh = () => { void loadAppData(false).then((payload) => { setData(payload); setRuns(payload.agentRuns); setActions(payload.actions ?? payload.agentRuns.map(actionFromSummary)); setActivity(payload.activity ?? []); }).catch(() => undefined); };
    const unsubscribe = subscribeToAgentEvents(refresh);
    const timer = window.setInterval(refresh, 5000);
    return () => { unsubscribe(); window.clearInterval(timer); };
  }, [hasActiveWork]);

  useEffect(() => {
    if (!hasActiveSearch) return;
    const timer = window.setInterval(() => { void loadAppData(false).then(setData).catch(() => undefined); }, 1800);
    return () => window.clearInterval(timer);
  }, [hasActiveSearch]);

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

  useEffect(() => {
    if (!selectedPr) {
      setAnnotations(null);
      return;
    }
    let disposed = false;
    void loadPrAnnotations(selectedPr.id).then((next) => {
      if (!disposed) setAnnotations(next);
    }).catch(() => {
      if (!disposed) setAnnotations({ pullRequestId: selectedPr.id, tags: [], notes: [] });
    });
    return () => { disposed = true; };
  }, [selectedPr]);

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
      const queueMatch = matchesQueue(pr, queue);
      const repoMatch = repo === "all" || pr.repository === repo;
      const searchTarget = `${pr.title} ${pr.repository} ${pr.sourceBranch} ${pr.linkedIssueIds.join(" ")} ${(data?.prTags?.[pr.id] ?? []).join(" ")} ${pr.summary} ${pr.searchText}`.toLowerCase();
      return queueMatch && repoMatch && (!needle || searchTarget.includes(needle));
    });
  }, [query, queue, repo, scopedPrs]);

  if (!data || !backend) {
    return <main className="loading">{t("loading")}</main>;
  }

  const ThemeIcon = themeIcons[theme];
  const repos = ["all", ...new Set(data.pullRequests.map((pr) => pr.repository))];

  async function startRun(pr: PullRequest, reviewThreadIds: string[] = []) {
    const action = reviewThreadIds.length ? "address_review" : pr.mergeable === "conflicting" ? "fix_conflicts" : "rebase";
    setCheckoutMessage("Queueing agent run...");
    try {
      const run = await createAgentRun({ backendId, pullRequestId: pr.id, action, reviewThreadIds });
      setRuns((current) => [run, ...current]);
      setActions((current) => [actionFromRun(run), ...current]);
      const refreshed = await loadAppData();
      setActivity(refreshed.activity ?? []);
      setCheckoutMessage(run.summary);
    } catch (error) {
      setCheckoutMessage(error instanceof Error ? error.message : "Could not queue agent run");
    }
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

  async function saveAgentSettings(settings: AgentSettings) {
    const updated = await updateAgentSettings(settings);
    setData((current) => current ? { ...current, agentSettings: updated } : current);
  }

  async function saveSearchSettings(settings: { backend: SearchSettings["backend"]; gitcodeRepositories: string[]; githubReadToken?: string; gitcodeReadToken?: string }) {
    const updated = await updateSearchSettings(settings);
    setData((current) => current ? { ...current, searchSettings: updated } : current);
  }

  async function startSearch(input: { query: string; kind: SearchRun["kind"]; repositoryIds: string[]; memberId?: string }) {
    const run = await createSearchRun({ ...input, backendId, locale });
    setData((current) => current ? { ...current, searchRuns: [run, ...current.searchRuns.filter((item) => item.id !== run.id)] } : current);
  }

  async function stopSearch(runId: string) {
    const run = await cancelSearchRun(runId);
    setData((current) => current ? { ...current, searchRuns: current.searchRuns.map((item) => item.id === run.id ? run : item) } : current);
  }

  async function runGitHubSync() {
    const result = await syncGitHub();
    const payload = await loadAppData();
    setData(payload);
    setRuns(payload.agentRuns);
    setActions(payload.actions ?? payload.agentRuns.map(actionFromSummary));
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
    setRuns((current) => current.filter((run) => run.id !== actionId));
    const refreshed = await loadAppData();
    setActivity(refreshed.activity ?? []);
  }

  async function removeAllAgentRuns() {
    if (!window.confirm("Clear all completed agent runs? Active runs will be kept.")) return;
    try {
      const result = await clearAllAgentRuns();
      const refreshed = await loadAppData();
      setData(refreshed);
      setRuns(refreshed.agentRuns);
      setActions(refreshed.actions ?? refreshed.agentRuns.map(actionFromSummary));
      setActivity(refreshed.activity ?? []);
      setActionsMessage(`Cleared ${result.cleared} completed agent run${result.cleared === 1 ? "" : "s"}.`);
    } catch (error) {
      setActionsMessage(error instanceof Error ? error.message : "Could not clear agent runs.");
    }
  }

  async function removeAllActivity() {
    if (!window.confirm(t("activity.clearConfirm"))) return;
    try {
      await clearAllActivity();
      setActivity([]);
      setActivityMessage(t("activity.cleared"));
    } catch (error) {
      setActivityMessage(error instanceof Error ? error.message : t("activity.clearFailed"));
    }
  }

  async function stopRun(runId: string) {
    const run = await cancelAgentRun(runId);
    setRuns((current) => current.map((item) => item.id === run.id ? run : item));
    setActions((current) => current.map((item) => item.id === run.id ? actionFromRun(run) : item));
  }

  async function approveRun(runId: string) {
    setCheckoutMessage("");
    try {
      const run = await approveAgentRun(runId);
      setRuns((current) => current.map((item) => item.id === run.id ? run : item));
      setActions((current) => current.map((item) => item.id === run.id ? actionFromRun(run) : item));
      setCheckoutMessage(run.summary);
    } catch (error) {
      setCheckoutMessage(error instanceof Error ? error.message : "Could not approve the patch.");
    }
  }

  async function pushRun(runId: string, target: "mergeops_branch" | "pr_branch" = "pr_branch") {
    setCheckoutMessage("");
    try {
      const run = await pushAgentRun(runId, target);
      setRuns((current) => current.map((item) => item.id === run.id ? run : item));
      setActions((current) => current.map((item) => item.id === run.id ? actionFromRun(run) : item));
      setCheckoutMessage(run.summary);
    } catch (error) {
      setCheckoutMessage(error instanceof Error ? error.message : "Could not push the approved patch.");
    }
  }

  async function reviseRun(runId: string, instruction: string, reason?: string) {
    const run = await reviseAgentRun(runId, { backendId, instruction, reason });
    setRuns((current) => [run, ...current]);
    setActions((current) => [actionFromRun(run), ...current]);
    const refreshed = await loadAppData();
    setActivity(refreshed.activity ?? []);
  }

  async function savePrTags(pullRequestId: string, tags: string[]) {
    const updated = await updatePrTags(pullRequestId, tags);
    setAnnotations(updated);
    setData((current) => current ? {
      ...current,
      prTags: { ...(current.prTags ?? {}), [pullRequestId]: updated.tags }
    } : current);
  }

  async function reviewRunPatch(runId: string) {
    const run = await reviewPatch(runId, backendId);
    setRuns((current) => [run, ...current]);
    setActions((current) => [actionFromRun(run), ...current]);
    const refreshed = await loadAppData();
    setActivity(refreshed.activity ?? []);
  }

  async function retryRun(runId: string) {
    const run = await retryAgentRun(runId);
    setRuns((current) => [run, ...current]);
    setActions((current) => [actionFromRun(run), ...current]);
  }

  async function continueRebase(runId: string) {
    setCheckoutMessage("");
    setActionsMessage("");
    try {
      const run = await continueRebaseAgentRun(runId);
      setRuns((current) => current.map((item) => item.id === run.id ? run : item));
      setActions((current) => current.map((item) => item.id === run.id ? actionFromRun(run) : item));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not continue the active rebase.";
      setCheckoutMessage(message);
      setActionsMessage(message);
    }
  }

  async function fixManually(runId: string) {
    setCheckoutMessage("");
    setActionsMessage("");
    try {
      const run = await revalidateManualRun(runId);
      setRuns((current) => current.map((item) => item.id === run.id ? run : item));
      setActions((current) => current.map((item) => item.id === run.id ? actionFromRun(run) : item));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not validate the manually resolved workspace.";
      setCheckoutMessage(message);
      setActionsMessage(message);
    }
  }

  async function inspectRecovery(runId: string) {
    const run = await inspectRecoveryAgentRun(runId);
    setRuns((current) => current.map((item) => item.id === run.id ? run : item));
    setActions((current) => current.map((item) => item.id === run.id ? actionFromRun(run) : item));
  }

  async function applyReviewFindings(runId: string) {
    const detail = await loadActionDetails(runId);
    const findings = "agentOutput" in detail && detail.agentOutput ? detail.agentOutput : "Review findings are recorded in the independent review run details.";
    await reviseRun(runId, `Apply the independent review findings below to the prepared patch. Preserve unrelated work and report a structured result.\n\n${findings.slice(-12000)}`, "independent review findings");
  }

  async function showRunDetails(action: ActionRecord) {
    setDetailsAction(action);
    setDetails(null);
    setDetailsLoading(true);
    try {
      setDetails(await loadActionDetails(action.id));
    } catch {
      setDetails(null);
    } finally {
      setDetailsLoading(false);
    }
  }

  async function chooseRebaseDecision(runId: string, optionId: "drop_base_sync_merge" | "manual") {
    const run = await selectRebaseDecision(runId, optionId);
    setRuns((current) => current.map((item) => item.id === run.id ? run : item));
    setActions((current) => current.map((item) => item.id === run.id ? actionFromRun(run) : item));
    setDetails(run);
  }

  return (
    <div className="app-shell">
      <aside className="side-nav" aria-label="Primary">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">MO</span>
          <div>
            <strong>MergeOps</strong>
            <span>{t("brand.subtitle")}</span>
          </div>
        </div>
        <nav className="nav-list" aria-label={t("nav.primary")}>
          {views.map((view) => {
            const Icon = view.icon;
            return (
              <button key={view.id} className={`nav-item ${activeView === view.id ? "is-active" : ""}`} onClick={() => setActiveView(view.id)}>
                <Icon size={18} />
              <span>{t(({ cockpit: "nav.cockpit", search: "nav.search", team: "nav.team", agents: "nav.actions", activity: "nav.activity", settings: "nav.settings" } as const)[view.id])}</span>
              </button>
            );
          })}
        </nav>
        <div className="language-control" aria-label={t("language.label")}>
          <span>{t("language.label")}</span>
          <div className="language-toggle" role="group" aria-label={t("language.label")}>
            <button type="button" className={locale === "en" ? "is-active" : ""} aria-pressed={locale === "en"} onClick={() => setLocale("en")}>{t("language.english")}</button>
            <button type="button" className={locale === "zh" ? "is-active" : ""} aria-pressed={locale === "zh"} onClick={() => setLocale("zh")}>{t("language.chinese")}</button>
          </div>
        </div>
        <div className={`side-status is-${backendStatus}`} role="status" aria-live="polite">
          <span className="health-label"><i className="health-dot" aria-hidden="true" />{t("backend.api")}</span>
          <strong>{backendStatus === "checking" ? t("backend.checking") : backendStatus === "online" ? t("backend.online") : t("backend.offline")}</strong>
          <small>{backendStatus === "offline" ? t("backend.unreachable") : t("backend.monitoring")}</small>
        </div>
      </aside>

      <main className="workspace">
        {activeView === "cockpit" && (
          <header className="topbar">
            <label className="search-wrap" aria-label={t("search.label")}>
              <Search size={18} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} type="search" placeholder={t("search.placeholder")} />
            </label>
            <div className="top-actions">
              <select value={repo} onChange={(event) => setRepo(event.target.value)} aria-label={t("filter.repository")}>
                {repos.map((item) => <option key={item} value={item}>{item === "all" ? t("filter.allRepos") : item}</option>)}
              </select>
              <select value={owner} onChange={(event) => setOwner(event.target.value)} aria-label={t("filter.member")}>
                <option value="all">{t("filter.allMembers")}</option>
                {data.teamMembers.map((member) => <option key={member.id} value={member.id}>{member.displayName}</option>)}
              </select>
              <select value={dateRange} onChange={(event) => setDateRange(event.target.value === "all" ? "all" : Number(event.target.value))} aria-label={t("filter.age")}>
                <option value={30}>{t("filter.lastDays", { days: 30 })}</option>
                <option value={60}>{t("filter.lastDays", { days: 60 })}</option>
                <option value={90}>{t("filter.lastDays", { days: 90 })}</option>
                <option value="all">{t("filter.allTime")}</option>
              </select>
              <button className="secondary-btn sync-btn" type="button" onClick={syncFromToolbar} disabled={syncing}>
                <RefreshCw size={16} className={syncing ? "spin" : ""} />
                {syncing ? t("sync.syncing") : t("sync.resync")}
              </button>
              {syncMessage ? <span className="sync-status">{syncMessage}</span> : null}
              <button className="icon-btn" type="button" onClick={() => setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system")} aria-label={t("theme.label", { theme })} title={t("theme.label", { theme })}>
                <ThemeIcon size={18} />
              </button>
            </div>
          </header>
        )}
        {activeView === "search" && (
          <SearchView
            searchSettings={data.searchSettings}
            repositories={data.searchSettings.backend === "github" ? (data.github?.repositories ?? []).filter((item) => item.enabled).map((item) => `${item.owner}/${item.name}`) : data.searchSettings.gitcodeRepositories}
            members={data.teamMembers}
            runs={data.searchRuns}
            backendId={backendId}
            onSearch={startSearch}
            onCancel={stopSearch}
          />
        )}

        {activeView === "cockpit" && (
          <Cockpit
            prs={filteredPrs}
            allPrs={scopedPrs}
            teamMembers={data.teamMembers}
            teamById={teamById}
            github={data.github}
            prTags={data.prTags ?? {}}
            owner={owner}
            queue={queue}
            onQueueChange={(nextQueue) => {
              setQueue(nextQueue);
              setOwner("all");
            }}
            onMemberFilter={setOwner}
            onSelectPr={setSelectedPr}
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            actions={actions}
          />
        )}
        {activeView === "team" && <TeamWorkspace members={data.teamMembers} onSaveMember={saveTeamMember} onAddMember={addTeamMember} onDeleteMember={removeTeamMember} />}
        {activeView === "agents" && <ActionsView actions={actions} onClear={removeAction} onClearAll={removeAllAgentRuns} message={actionsMessage} onStop={stopRun} onApprove={approveRun} onPush={pushRun} onReviewPatch={reviewRunPatch} onApplyReview={applyReviewFindings} onRetry={retryRun} onContinueRebase={continueRebase} onFixManually={fixManually} onShowDetails={showRunDetails} onLoadEvents={loadActionDetails} />}
        {activeView === "activity" && <ActivityView events={activity} message={activityMessage} onClearAll={removeAllActivity} />}
        {activeView === "settings" && (
          <SettingsView
            backendId={backendId}
            backends={data.agentBackends}
            onBackendChange={setBackendId}
            theme={theme}
            onThemeChange={setTheme}
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            searchSettings={data.searchSettings}
            onSaveSearchSettings={saveSearchSettings}
            members={data.teamMembers}
            onOpenTeam={() => setActiveView("team")}
            github={data.github}
            onSaveGitHub={saveGitHubSettings}
            agentSettings={data.agentSettings}
            onSaveAgentSettings={saveAgentSettings}
            onSyncGitHub={runGitHubSync}
          />
        )}
      </main>

      {selectedPr && (
          <PrDrawer
          pr={selectedPr}
          member={teamById.get(selectedPr.ownerMemberId)}
          backend={backend}
          run={drawerRunForPr(actions, selectedPr.id)}
          annotations={annotations}
          canPushPrBranch={Boolean(data.github?.hasToken && selectedPr.headRepositoryFullName)}
          onClose={() => setSelectedPr(null)}
            onStartRun={(reviewThreadIds) => startRun(selectedPr, reviewThreadIds)}
          onCheckout={() => checkoutPr(selectedPr)}
            onApproveRun={approveRun}
            onPushRun={pushRun}
          onReviewRun={reviewRunPatch}
            onReviseRun={reviseRun}
            onPostReplies={async (runId, replies) => { const updated = await postReviewReplies(runId, replies); setRuns((current) => current.map((item) => item.id === updated.id ? updated : item)); setActions((current) => current.map((item) => item.id === updated.id ? actionFromRun(updated) : item)); }}
          onRetryRun={retryRun}
          onContinueRebase={continueRebase}
          onFixManually={fixManually}
            onClearRun={removeAction}
            onInspectRecovery={inspectRecovery}
            onReviewThreadsRefreshed={async () => {
              const refreshed = await loadAppData();
              setData(refreshed);
              setRuns(refreshed.agentRuns);
              setActions(refreshed.actions ?? refreshed.agentRuns.map(actionFromSummary));
              setActivity(refreshed.activity ?? []);
              setSelectedPr((current) => current ? refreshed.pullRequests.find((item) => item.id === current.id) ?? current : null);
            }}
          onSaveTags={(tags) => savePrTags(selectedPr.id, tags)}
          onSaveNote={async (text) => setAnnotations(await createPrNote(selectedPr.id, text))}
          onDeleteNote={async (noteId) => setAnnotations(await deletePrNote(selectedPr.id, noteId))}
          checkoutMessage={checkoutMessage}
        />
      )}
      {diffAction ? <DiffDialog action={diffAction} onClose={() => setDiffAction(null)} onReviewPatch={reviewRunPatch} /> : null}
      {detailsAction ? <RunDetailsDrawer action={detailsAction} details={details} loading={detailsLoading} onClose={() => { setDetailsAction(null); setDetails(null); }} onShowDiff={setDiffAction} onChooseRebaseDecision={chooseRebaseDecision} onRetryRun={retryRun} onContinueRebase={continueRebase} onFixManually={fixManually} onInspectRecovery={inspectRecovery} /> : null}
    </div>
  );
}

function Cockpit(props: {
  prs: PullRequest[];
  allPrs: PullRequest[];
  teamMembers: TeamMember[];
  teamById: Map<string, TeamMember>;
  github?: GitHubSettings | null;
  prTags: Record<string, string[]>;
  owner: string;
  queue: QueueFilter;
  onQueueChange: (queue: QueueFilter) => void;
  onMemberFilter: (memberId: string) => void;
  onSelectPr: (pr: PullRequest) => void;
  dateRange: number | "all";
  onDateRangeChange: (range: number | "all") => void;
  actions: ActionRecord[];
}) {
  const { t } = useLocale();
  const [membersCollapsed, setMembersCollapsed] = useState(() => localStorage.getItem("mergeops.cockpit.membersCollapsed") !== "false");
  const openCount = props.allPrs.filter((pr) => pr.state === "open").length;
  const mergedCount = props.allPrs.filter((pr) => pr.state === "merged").length;
  const closedCount = props.allPrs.filter((pr) => pr.state === "closed").length;
  const conflictCount = props.allPrs.filter((pr) => statusFor(pr) === "conflict").length;
  const reviewCount = props.allPrs.filter((pr) => statusFor(pr) === "review").length;
  const readyCount = props.allPrs.filter((pr) => statusFor(pr) === "ready").length;
  const [agentActiveOnly, setAgentActiveOnly] = useState(false);
  const activePrIds = new Set(props.actions.filter((action) => ["queued", "running", "checks_running", "awaiting_decision"].includes(action.status)).map((action) => action.pullRequestId));
  const visiblePrs = agentActiveOnly ? props.prs.filter((pr) => activePrIds.has(pr.id)) : props.prs;
  const repositoryNames = props.github?.repositories.map((repository) => repository.name).join(", ");
  const lastSynced = props.github?.lastSyncedAt ? new Date(props.github.lastSyncedAt).toLocaleString() : "not synced";
  const filters: Array<{ id: QueueFilter; label: string; count: number }> = [
    { id: "all", label: t("cockpit.all"), count: props.allPrs.length },
    { id: "open", label: t("cockpit.open"), count: openCount },
    { id: "conflict", label: t("cockpit.conflicts"), count: conflictCount },
    { id: "review", label: t("cockpit.review"), count: reviewCount },
    { id: "ready", label: t("cockpit.ready"), count: readyCount },
    { id: "needs_you", label: t("cockpit.needsYou"), count: props.allPrs.filter((pr) => matchesQueue(pr, "needs_you")).length },
    { id: "merged", label: t("cockpit.merged"), count: mergedCount },
    { id: "closed", label: t("cockpit.closed"), count: closedCount }
  ];

  useEffect(() => {
    localStorage.setItem("mergeops.cockpit.membersCollapsed", String(membersCollapsed));
  }, [membersCollapsed]);

  return (
    <section className="view is-visible" aria-labelledby="cockpitTitle">
      <div className="view-head">
        <div className="cockpit-heading">
          <h1 id="cockpitTitle">{t("cockpit.title")}</h1>
          <p>
            {props.allPrs.length
              ? t(props.dateRange === "all" ? "cockpit.summaryAll" : "cockpit.summaryDays", { count: props.allPrs.length, days: props.dateRange === "all" ? "" : props.dateRange, repos: repositoryNames || "configured repositories", lastSynced })
              : t(props.dateRange === "all" ? "cockpit.emptySummaryAll" : "cockpit.emptySummaryDays", { days: props.dateRange === "all" ? "" : props.dateRange, lastSynced })}
          </p>
        </div>
      </div>
      <div className="cockpit-filters">
        <div className="saved-views" role="group" aria-label={t("cockpit.savedViews")}>
          {filters.map((filter) => (
            <button key={filter.id} className={`seg filter-chip ${filter.id} ${props.queue === filter.id ? "is-active" : ""}`} onClick={() => props.onQueueChange(filter.id)}>
              <span>{filter.label}</span><strong>{filter.count}</strong>
            </button>
          ))}
          <button type="button" className={`seg filter-chip ${agentActiveOnly ? "is-active" : ""}`} aria-pressed={agentActiveOnly} onClick={() => setAgentActiveOnly((current) => !current)}><span>{t("cockpit.agentActive")}</span><strong>{activePrIds.size}</strong></button>
        </div>
      </div>
      <div className={`member-strip-section ${membersCollapsed ? "is-collapsed" : ""}`}>
        <div className="member-strip-head">
          <span>{t("cockpit.teamMembers")}</span>
          <button
            className="member-strip-toggle"
            type="button"
            aria-expanded={!membersCollapsed}
            aria-controls="cockpitMemberStrip"
            aria-label={membersCollapsed ? t("cockpit.showMembers") : t("cockpit.hideMembers")}
            onClick={() => setMembersCollapsed((current) => !current)}
          >
            {membersCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          </button>
        </div>
        {!membersCollapsed && (
          <div className="member-strip" id="cockpitMemberStrip" role="list" aria-label={t("cockpit.teamMembers")}>
            {props.teamMembers.map((member) => {
              const owned = props.allPrs.filter((pr) => pr.ownerMemberId === member.id);
              const breakdown = {
                conflict: owned.filter((pr) => matchesQueue(pr, "conflict")).length,
                review: owned.filter((pr) => matchesQueue(pr, "review")).length,
                merged: owned.filter((pr) => matchesQueue(pr, "merged")).length,
                closed: owned.filter((pr) => matchesQueue(pr, "closed")).length
              };
              const selected = props.owner === member.id;
              return (
                <button className={`member-entry ${selected ? "is-selected" : ""}`} key={member.id} type="button" role="listitem" aria-pressed={selected} onClick={() => props.onMemberFilter(selected ? "all" : member.id)}>
                  <span className="avatar">{initials(member.displayName)}</span>
                  <span className="member-entry-copy">
                    <span className="member-entry-top"><strong>{member.displayName}</strong><small>{owned.length} {t("cockpit.prs")}</small></span>
                    {selected && <span className="member-breakdown">{t("cockpit.breakdown", breakdown)}</span>}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="table-shell">
        <div className="table-toolbar">
          <strong>{t("cockpit.livePrs")}</strong>
          <span>{t("cockpit.matchingPrs", { count: visiblePrs.length })}</span>
        </div>
        <div className="pr-table" role="table" aria-label={t("cockpit.tableLabel")}>
          <div className="pr-row pr-head" role="row">
            <span>{t("cockpit.priority")}</span><span>{t("cockpit.pr")}</span><span>{t("cockpit.owner")}</span><span>{t("cockpit.review")}</span><span>{t("cockpit.checks")}</span><span>{t("cockpit.age")}</span><span>{t("cockpit.action")}</span>
          </div>
          {visiblePrs.map((pr) => {
            const member = props.teamById.get(pr.ownerMemberId);
            const status = statusFor(pr);
            const tags = props.prTags[pr.id] ?? [];
            const needsAttention = matchesQueue(pr, "needs_you");
            return (
              <div className="pr-row" role="row" key={pr.id}>
                <div className="pr-cell"><span className={`status ${status}`}>{needsAttention ? <BellRing size={14} aria-hidden="true" /> : null}{t(({ closed: "status.closed", merged: "status.merged", draft: "status.draft", conflict: "status.conflict", checks: "status.checks", ready: "status.ready", review: "status.review" } as const)[status])}</span></div>
                <div className="pr-cell"><span className="pr-title"><strong>{pr.title}</strong><span>{pr.repository} #{pr.number} · {pr.state} · {pr.sourceBranch}</span>{tags.length ? <span className="pr-tag-row">{tags.map((tag) => <span className="tag local-tag" key={tag}>{tag}</span>)}</span> : null}</span></div>
                <div className="pr-cell">{member?.displayName ?? pr.author}</div>
                <div className="pr-cell">{pr.reviewState.replace("_", " ")}</div>
                <div className={`pr-cell checks-cell ${pr.checkState === "failing" ? "is-failing" : ""}`}>
                  {pr.checkState === "failing" ? <span className="check-indicator" title={t("checks.failed")}><CircleAlert size={15} aria-hidden="true" /><span>{t("checks.failed")}</span></span> : pr.checkState.replace("_", " ")}
                </div>
                <div className="pr-cell">{pr.ageDays}d</div>
                <div className="pr-cell"><button className="text-btn" onClick={() => props.onSelectPr(pr)}>{t("cockpit.inspect")}</button></div>
              </div>
            );
          })}
          {!visiblePrs.length && (
            <div className="empty-state">
              <strong>{t("cockpit.noMatch")}</strong>
              <span>{t("cockpit.clearFilters")}</span>
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
  const { t } = useLocale();
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
    setStatus(t("team.saveStatus"));
    try {
      if (selectedMember) {
        await onSaveMember(selectedMember.id, draftToMemberPayload(draft));
        setStatus(t("team.saved"));
      } else {
        const created = await onAddMember(draftToNewMember(draft));
        setSelectedId(created.id);
        setStatus(t("team.added"));
      }
    } catch {
      setStatus(t("team.saveFailed"));
    }
  }

  async function addMember() {
    setSelectedId("");
    setDraft(emptyMemberDraft());
    setStatus(t("team.adding"));
  }

  async function deleteMember() {
    if (!selectedMember) return;
    setStatus(t("team.deleting"));
    try {
      await onDeleteMember(selectedMember.id);
      setStatus(t("team.deleted"));
    } catch {
      setStatus(t("team.deleteFailed"));
    }
  }

  return (
    <section className="view is-visible" aria-labelledby="teamTitle">
      <div className="view-head">
        <div>
          <h1 id="teamTitle">{t("team.title")}</h1>
          <p>{t("team.subtitle", { count: members.length })}</p>
        </div>
        <button className="primary-btn" onClick={addMember}><Plus size={18} /><span>{t("team.add")}</span></button>
      </div>
      <div className="team-manager">
        <div className="member-list" aria-label="Team members">
          {members.map((member) => (
            <button key={member.id} className={`member-row ${selectedId === member.id ? "is-active" : ""}`} onClick={() => setSelectedId(member.id)}>
              <span className="avatar">{initials(member.displayName)}</span>
              <span className="member-meta"><strong>{member.displayName}</strong><span>@{member.githubUsername} · {member.availability.replace("_", " ")}</span></span>
            </button>
          ))}
          {!members.length ? <div className="empty-state compact"><strong>{t("team.noMembers")}</strong><span>{t("team.addFirst")}</span></div> : null}
        </div>
        <form className="person-card member-editor" onSubmit={saveDraft}>
          <header>
            <span className="avatar">{initials(draft.displayName || "New Member")}</span>
            <span className="member-meta">
              <strong>{selectedMember ? t("team.edit") : t("team.new")}</strong>
              <span>{selectedMember ? t("team.memberId", { id: selectedMember.id }) : t("team.createdLocally")}</span>
            </span>
          </header>
          <div className="profile-fields">
            <ProfileInput label={t("team.displayName")} value={draft.displayName} onChange={(value) => updateDraft("displayName", value)} />
            <ProfileInput label={t("team.githubUsername")} value={draft.githubUsername} onChange={(value) => updateDraft("githubUsername", value)} />
            <ProfileInput label={t("team.currentFocus")} value={draft.currentFocus} onChange={(value) => updateDraft("currentFocus", value)} />
            <ProfileInput label={t("team.responsibilities")} value={draft.responsibilities} onChange={(value) => updateDraft("responsibilities", value)} />
            <ProfileInput label={t("team.ownedRepos")} value={draft.ownedRepos} onChange={(value) => updateDraft("ownedRepos", value)} />
            <ProfileInput label={t("team.ownedPaths")} value={draft.ownedPaths} onChange={(value) => updateDraft("ownedPaths", value)} />
            <ProfileInput label={t("team.expertiseTags")} value={draft.expertiseTags} onChange={(value) => updateDraft("expertiseTags", value)} />
            <ProfileInput label={t("team.timezone")} value={draft.timezone} onChange={(value) => updateDraft("timezone", value)} />
            <label className="field">
              <span>{t("team.availability")}</span>
              <select value={draft.availability} onChange={(event) => updateDraft("availability", event.target.value)}>
                <option value="active">{t("availability.active")}</option>
                <option value="focus_mode">{t("availability.focus")}</option>
                <option value="ooo">{t("availability.ooo")}</option>
                <option value="overloaded">{t("availability.overloaded")}</option>
                <option value="inactive">{t("availability.inactive")}</option>
              </select>
            </label>
            <ProfileInput label={t("team.gitAliases")} value={draft.gitAliases} onChange={(value) => updateDraft("gitAliases", value)} full />
            <ProfileInput label={t("team.emails")} value={draft.emails} onChange={(value) => updateDraft("emails", value)} full />
          </div>
          <div className="settings-actions">
            <button className="primary-btn" type="submit"><Save size={18} /><span>{t("team.save")}</span></button>
            <button className="danger-btn" type="button" onClick={deleteMember} disabled={!selectedMember}><Trash2 size={18} /><span>{t("team.delete")}</span></button>
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

function ActionsView({ actions, onClear, onClearAll, message, onStop, onApprove, onPush, onReviewPatch, onApplyReview, onRetry, onContinueRebase, onFixManually, onShowDetails, onLoadEvents }: { actions: ActionRecord[]; onClear: (actionId: string) => Promise<void>; onClearAll: () => Promise<void>; message: string; onStop: (runId: string) => Promise<void>; onApprove: (runId: string) => Promise<void>; onPush: (runId: string) => Promise<void>; onReviewPatch: (runId: string) => Promise<void>; onApplyReview: (runId: string) => Promise<void>; onRetry: (runId: string) => Promise<void>; onContinueRebase: (runId: string) => Promise<void>; onFixManually: (runId: string) => Promise<void>; onShowDetails: (action: ActionRecord) => Promise<void>; onLoadEvents: (actionId: string) => Promise<AgentRun | ActionRecord> }) {
  const { t } = useLocale();
  const actionStatusKeys = {
    queued: "status.queued",
    running: "status.running",
    patch_ready: "status.patchReady",
    review_ready: "status.reviewReady",
    checks_running: "status.checksRunning",
    awaiting_decision: "status.awaitingDecision",
    awaiting_approval: "status.awaitingApproval",
    approved: "status.approved",
    pushed: "status.pushed",
    failed: "status.failed",
    cancelled: "status.cancelled"
  } as const;
  const terminalStatuses = new Set(["ready", "failed", "cancelled", "pushed", "approved", "awaiting_approval", "patch_ready", "review_ready", "recovery_required"]);
  const [eventPanels, setEventPanels] = useState<Record<string, { events?: AgentRunEvent[]; loading: boolean }>>({});
  const sortedActions = [...actions].sort((left, right) => right.createdAt.localeCompare(left.createdAt));

  async function loadEvents(actionId: string) {
    if (eventPanels[actionId]) return;
    setEventPanels((current) => ({ ...current, [actionId]: { loading: true } }));
    try {
      const detail = await onLoadEvents(actionId);
      setEventPanels((current) => ({ ...current, [actionId]: { events: detail.events ?? [], loading: false } }));
    } catch {
      setEventPanels((current) => ({ ...current, [actionId]: { events: [], loading: false } }));
    }
  }

  return (
    <section className="view is-visible" aria-labelledby="agentsTitle">
      <div className="view-head">
        <div>
          <h1 id="agentsTitle">{t("actions.title")}</h1>
          <p>{t("actions.subtitle")}</p>
          {message ? <p className="sync-status" role="status">{message}</p> : null}
        </div>
        <button className="secondary-btn" type="button" onClick={() => void onClearAll()} disabled={!actions.some((action) => action.kind === "agent_run" && ["failed", "cancelled", "pushed", "approved", "awaiting_approval", "patch_ready", "review_ready", "recovery_required"].includes(action.status) && (action.status !== "recovery_required" || action.recoveryInspected))}>{t("actions.clearAll")}</button>
      </div>
      <div className="runs-list">
        {sortedActions.length === 0 ? <p className="empty-state">{t("actions.noActions")}</p> : sortedActions.map((action) => {
          const eventCount = action.eventCount ?? action.events?.length ?? 0;
          const eventPanel = eventPanels[action.id];
          const events = action.events ?? eventPanel?.events;
          return <article className="run-item" key={action.id}>
            <div>
              <strong>{action.kind === "checkout" ? t("actions.checkout") : t("actions.agentRun")} · {action.repository} #{action.pullRequestNumber}</strong>
              <p>{action.summary}</p>
              <time className="action-meta" dateTime={action.createdAt}>{t("actions.startedAt", { timestamp: new Date(action.createdAt).toLocaleString() })}</time>
              {action.workspacePath ? <span className="action-meta">{t("actions.workspace", { path: action.workspacePath, base: action.baseCommit?.slice(0, 12) ?? "unknown" })}</span> : null}
              {action.parentRunId ? <span className="action-meta">{t("actions.reviewOf", { id: action.parentRunId })}</span> : null}
              {(eventCount || action.checkCount || action.hasRebaseEvidence) ? <span className="action-meta">{t("actions.eventsMeta", { events: eventCount, checks: action.checkCount ?? 0 })}{action.hasRebaseEvidence ? t("actions.conflictsMeta", { resolved: action.resolvedConflictCount ?? 0, total: action.conflictCount ?? 0 }) : ""}</span> : null}
              {eventCount ? <details className="run-events" onToggle={(event) => { if (event.currentTarget.open) void loadEvents(action.id); }}><summary>{t("actions.recordedEvents", { count: eventCount })}</summary>{eventPanel?.loading ? <p className="event-loading">{t("actions.loadingEvents")}</p> : events ? <RunEventList events={events} /> : <p className="event-loading">{t("actions.eventsUnavailable")}</p>}</details> : null}
            </div>
            <div className="action-controls"><span className={`status ${action.status === "failed" ? "is-failed" : "agent"}`}>{actionStatusKeys[action.status as keyof typeof actionStatusKeys] ? t(actionStatusKeys[action.status as keyof typeof actionStatusKeys]) : action.status.replace("_", " ")}</span><button className="secondary-btn" type="button" onClick={() => void onShowDetails(action)}><FileSearch size={16} /><span>{t("actions.runDetails")}</span></button>{action.status === "patch_ready" ? <button className="secondary-btn" type="button" onClick={() => onReviewPatch(action.id)}><FileSearch size={16} /><span>{t("actions.reviewPatch")}</span></button> : null}{action.status === "review_ready" ? <button className="primary-btn" type="button" onClick={() => void onApplyReview(action.id)}>{t("drawer.applyReviewFindings")}</button> : null}{action.status === "patch_ready" ? <button className="primary-btn" type="button" onClick={() => onApprove(action.id)}>{t("actions.approve")}</button> : null}{action.status === "approved" ? <button className="primary-btn" type="button" onClick={() => onPush(action.id)}>{t("actions.push")}</button> : null}{action.status === "failed" && ["fix_conflicts", "rebase"].includes(action.action) && action.hasRebaseEvidence ? <button className="secondary-btn" type="button" onClick={() => void onContinueRebase(action.id)}>{t("actions.continueRebase")}</button> : null}{action.status === "failed" && ["fix_conflicts", "rebase"].includes(action.action) ? <button className="secondary-btn" type="button" onClick={() => void onFixManually(action.id)}>{t("actions.fixedManually")}</button> : null}{["failed", "interrupted"].includes(action.status) ? <button className="secondary-btn" type="button" onClick={() => void onRetry(action.id)}>{t("actions.retryFresh")}</button> : null}{action.status === "recovery_required" && !action.recoveryInspected ? <button className="secondary-btn" type="button" onClick={() => void onShowDetails(action)}>{t("actions.confirmRecovery")}</button> : null}{terminalStatuses.has(action.status) && (action.status !== "recovery_required" || action.recoveryInspected) ? <button className="icon-btn" type="button" onClick={() => onClear(action.id)} aria-label={t("actions.clear", { kind: action.kind })} title={t("actions.clear", { kind: action.kind })}><Trash2 size={16} /></button> : <button className="secondary-btn" type="button" onClick={() => onStop(action.id)}>{t("actions.stop")}</button>}</div>
          </article>
        })}
      </div>
    </section>
  );
}

function RunDetailsDrawer({ action, details, loading, onClose, onShowDiff, onChooseRebaseDecision, onRetryRun, onContinueRebase, onFixManually, onInspectRecovery }: { action: ActionRecord; details: AgentRun | ActionRecord | null; loading: boolean; onClose: () => void; onShowDiff: (action: ActionRecord) => void; onChooseRebaseDecision: (runId: string, optionId: "drop_base_sync_merge" | "manual") => Promise<void>; onRetryRun: (runId: string) => Promise<void>; onContinueRebase: (runId: string) => Promise<void>; onFixManually: (runId: string) => Promise<void>; onInspectRecovery: (runId: string) => Promise<void> }) {
  const { t } = useLocale();
  const run = details && "backendId" in details ? details : null;
  const evidence = run?.rebaseEvidence;
  const detailAction: ActionRecord = run ? actionFromRun(run) : action;
  const transcript = evidence?.transcript.text || run?.agentOutput;
  const events = details?.events ?? [];
  return (
    <div className="drawer-layer" role="presentation">
      <aside className="run-details-drawer" role="dialog" aria-modal="true" aria-labelledby="runDetailsTitle">
        <header className="drawer-head"><div><span className="eyebrow">Run details</span><h2 id="runDetailsTitle">{action.repository} #{action.pullRequestNumber}</h2><span>{action.id} · {action.action.replace(/_/g, " ")}</span></div><button className="icon-btn" onClick={onClose} aria-label="Close run details"><X size={18} /></button></header>
        {loading ? <div className="drawer-loading">Loading evidence…</div> : !run ? (details ? <div className="run-details-body"><section className="detail-overview"><span className="status agent detail-status">{details.status.replace(/_/g, " ")}</span><p>{details.summary}</p><div className="detail-facts"><span>Workspace <strong>{details.workspacePath ?? "not created"}</strong></span><span>Base commit <strong>{details.baseCommit?.slice(0, 12) ?? "unknown"}</strong></span><span>Events <strong>{events.length}</strong></span></div></section><RunEventsSection events={events} /><p className="empty-state">This action has no agent-owned rebase evidence.</p></div> : <div className="drawer-loading">Details are unavailable for this run.</div>) : <div className="run-details-body">
          <section className="detail-overview"><span className={`status agent detail-status ${run.status === "failed" ? "is-failed" : ""}`}>{run.status.replace(/_/g, " ")}</span><p>{run.summary}</p>{run.status === "recovery_required" || run.status === "interrupted" ? <p className="failure-copy">{run.recoveryNote ?? "Inspect the retained workspace before reuse."}</p> : null}<div className="detail-facts"><span>Base commit <strong>{run.baseCommit?.slice(0, 12) ?? "unknown"}</strong></span><span>Workspace <strong>{run.workspacePath ?? "not created"}</strong></span><span>Checks <strong>{run.checks?.filter((check) => check.status === "passed").length ?? 0}/{run.checks?.length ?? 0} passed</strong></span></div>{run.status === "recovery_required" && !run.recoveryInspected ? <button className="secondary-btn" type="button" onClick={() => void onInspectRecovery(run.id)}>{t("actions.confirmRecovery")}</button> : null}{run.status === "failed" && ["fix_conflicts", "rebase"].includes(run.action) && run.rebaseEvidence ? <button className="secondary-btn" type="button" onClick={() => void onContinueRebase(run.id)}>{t("actions.continueRebase")}</button> : null}{run.status === "failed" && ["fix_conflicts", "rebase"].includes(run.action) ? <button className="secondary-btn" type="button" onClick={() => void onFixManually(run.id)}>{t("actions.fixedManually")}</button> : null}{["failed", "interrupted"].includes(run.status) || (run.status === "recovery_required" && run.recoveryInspected) ? <button className="secondary-btn" type="button" onClick={() => void onRetryRun(run.id)}>{t("actions.retryFresh")}</button> : null}</section>
          {run.feedback ? <section className="detail-section"><div className="section-title"><h3>Human feedback</h3><span>{run.feedback.reason ?? "uncategorized"}</span></div><p>{run.feedback.instruction}</p>{run.parentRunId ? <p className="drawer-meta">Revision of {run.parentRunId}</p> : null}</section> : null}
          <RunEventsSection events={events} />
          {evidence?.plan ? <section className="detail-section"><div className="section-title"><h3>Rebase strategy</h3><span>{evidence.plan.strategy.replace(/_/g, " ")}</span></div><p>{evidence.plan.summary}</p><code>{evidence.plan.command}</code></section> : null}
          {evidence?.decision ? <section className="detail-section"><div className="section-title"><h3>Rebase decision</h3><span>{evidence.decision.selectedOption ? "selected" : "required"}</span></div><p>{evidence.decision.question}</p>{!evidence.decision.selectedOption ? <div className="decision-options">{evidence.decision.options.map((option) => <button className={option.recommended ? "primary-btn" : "secondary-btn"} type="button" key={option.id} onClick={() => void onChooseRebaseDecision(run.id, option.id)}><span>{option.label}</span><small>{option.description}</small></button>)}</div> : null}</section> : null}
          {evidence ? <>
            <section className="detail-section"><div className="section-title"><h3>Agent-owned rebase timeline</h3><span>{evidence.baseRef ?? "base ref unavailable"} · {evidence.state}</span></div><ol className="timeline">{evidence.stages.map((stage) => <li key={`${stage.sequence}-${stage.type}`}><span className="timeline-dot" /><div><strong>{stage.type.replace(/_/g, " ")}</strong><p>{stage.message}</p><time>{new Date(stage.createdAt).toLocaleString()}</time></div></li>)}</ol></section>
            <section className="detail-section"><div className="section-title"><h3>Conflict resolutions</h3><span>{evidence.conflicts.length} captured</span></div>{evidence.conflicts.length ? evidence.conflicts.map((conflict) => <ConflictRow key={conflict.id} conflict={conflict} />) : <p className="empty-state compact">No conflicts were encountered.</p>}</section>
            {evidence.validation.length ? <section className="detail-section"><div className="section-title"><h3>Validation</h3></div><ul className="validation-list">{evidence.validation.map((message, index) => <li key={`${message}-${index}`}>{message}</li>)}</ul></section> : null}
            {evidence.blockedCommands.length ? <section className="detail-section"><div className="section-title"><h3>Blocked commands</h3></div><p className="blocked-note">{evidence.blockedCommands.map((command) => `git ${command}`).join(" · ")}</p></section> : null}
          </> : null}
          <section className="detail-section"><div className="section-title"><h3>Patch, checks, risk, and approval</h3>{detailAction.diff ? <button className="secondary-btn" type="button" onClick={() => onShowDiff(detailAction)}><GitCompare size={15} /> Show patch</button> : null}</div>{run.patchSummary ? <p>{run.patchSummary}</p> : null}{run.riskSummary ? <p className="risk-copy">Risk: {run.riskSummary}</p> : null}{run.approval ? <p>Approved by <strong>{run.approval.reviewer}</strong> on {new Date(run.approval.createdAt).toLocaleString()}.</p> : <p className="drawer-meta">No approval recorded.</p>}{run.pushRef ? <p>Pushed to <code>{run.pushRef}</code>.</p> : null}<div className="check-list">{run.checks?.map((check) => <div className="check-row" key={check.name}><span className={`check-result ${check.status}`}>{check.status}</span><strong>{check.name}</strong><span>{check.summary}</span></div>)}</div></section>
          {transcript ? <section className="detail-section"><details className="agent-output"><summary>Raw agent transcript (technical)</summary><p className="drawer-meta">Use the run events and timestamps above for the readable execution history. The transcript is retained for audit and troubleshooting.</p><pre>{transcript}</pre>{evidence?.transcript.truncated ? <small>Transcript truncated · {evidence.transcript.originalLength.toLocaleString()} chars</small> : null}</details></section> : null}
        </div>}
      </aside><button className="drawer-scrim" type="button" aria-label="Close run details" onClick={onClose} />
    </div>
  );
}

function RunEventsSection({ events }: { events: AgentRunEvent[] }) {
  return <section className="detail-section run-events-section"><div className="section-title"><h3>Run events</h3><span>{events.length} recorded</span></div>{events.length ? <RunEventList events={events} /> : <p className="empty-state compact">No events were recorded for this run.</p>}</section>;
}

function RunEventList({ events }: { events: AgentRunEvent[] }) {
  return <ol className="run-event-list">{events.map((event) => <li key={`${event.sequence}-${event.createdAt}`}><div><strong>{event.type.replace(/_/g, " ")}</strong><p>{event.message}</p></div><time dateTime={event.createdAt}>{new Date(event.createdAt).toLocaleString()}</time></li>)}</ol>;
}

type ConflictSlice = { ours: string; theirs: string; result: string };

function conflictSlices(conflict: ConflictEvidence): ConflictSlice[] {
  if (conflict.sections?.length) {
    const resolvedOutput = (conflict.resultHunk ?? conflict.result).text;
    return conflict.sections.map((section) => ({
      ours: section.ours.text,
      theirs: section.theirs.text,
      result: conflict.validationState === "passed" ? resolvedOutput : section.result.text
    }));
  }
  const captured = (conflict.resultHunk ?? conflict.result).text;
  const lines = captured.split("\n");
  const slices: ConflictSlice[] = [];
  let start = -1;
  let divider = -1;
  for (let index = 0; index < lines.length; index += 1) {
    if (lines[index].startsWith("<<<<<<<")) start = index;
    else if (start >= 0 && lines[index].startsWith("=======")) divider = index;
    else if (start >= 0 && divider >= 0 && lines[index].startsWith(">>>>>>>")) {
      slices.push({
        ours: lines.slice(start + 1, divider).join("\n"),
        theirs: lines.slice(divider + 1, index).join("\n"),
        result: lines.slice(start, index + 1).join("\n")
      });
      start = -1;
      divider = -1;
    }
  }
  return slices.length ? slices : [{
    ours: (conflict.oursHunk ?? conflict.ours).text,
    theirs: (conflict.theirsHunk ?? conflict.theirs).text,
    result: (conflict.resultHunk ?? conflict.result).text
  }];
}

function MergeCodePane({ role, label, description, text, scrollRef, onScroll }: { role: "ours" | "theirs" | "result"; label: string; description: string; text: string; scrollRef?: React.RefObject<HTMLDivElement | null>; onScroll?: () => void }) {
  const lines = text ? text.split("\n") : [""];
  return <section className={`merge-pane ${role}`} aria-label={`${label}: ${description}`}><header className="merge-pane-head"><strong>{label}</strong><span>{description}</span></header><div className="merge-code" ref={scrollRef} onScroll={onScroll}>{lines.map((line, index) => <div className="merge-line" key={`${index}-${line}`}><span aria-hidden="true">{index + 1}</span><code>{line || " "}</code></div>)}</div></section>;
}

function ConflictRow({ conflict }: { conflict: ConflictEvidence }) {
  const { t } = useLocale();
  const slices = conflictSlices(conflict);
  const [activeSlice, setActiveSlice] = useState(0);
  const oursRef = useRef<HTMLDivElement>(null);
  const theirsRef = useRef<HTMLDivElement>(null);
  const syncing = useRef(false);
  const slice = slices[activeSlice] ?? slices[0];
  const move = (direction: -1 | 1) => setActiveSlice((current) => (current + direction + slices.length) % slices.length);
  const syncScroll = (source: "ours" | "theirs") => () => {
    if (syncing.current) return;
    const sourceElement = source === "ours" ? oursRef.current : theirsRef.current;
    const targetElement = source === "ours" ? theirsRef.current : oursRef.current;
    if (!sourceElement || !targetElement) return;
    syncing.current = true;
    targetElement.scrollTop = sourceElement.scrollTop;
    requestAnimationFrame(() => { syncing.current = false; });
  };

  return <details className="conflict-row"><summary><span>{conflict.filePath}</span><span className={`classification ${conflict.classification}`}>{conflict.classification}</span><span className={`validation-state ${conflict.validationState}`}>{conflict.validationState}</span></summary><div className="conflict-meta">{conflict.commitSubject ?? t("conflict.commitUnavailable")} {conflict.commitSha ? `· ${conflict.commitSha.slice(0, 12)}` : ""}</div><div className="merge-toolbar"><p className="drawer-meta">{t("conflict.focused")}</p>{slices.length > 1 ? <div className="change-navigation" aria-label={t("conflict.changeNavigation")}><button className="icon-btn" type="button" onClick={() => move(-1)} aria-label={t("conflict.previousChange")}><ChevronUp size={16} /></button><span>{t("conflict.changeCount", { current: activeSlice + 1, total: slices.length })}</span><button className="icon-btn" type="button" onClick={() => move(1)} aria-label={t("conflict.nextChange")}><ChevronDown size={16} /></button></div> : null}</div><div className="merge-viewer"><div className="merge-sources"><MergeCodePane role="ours" label={t("conflict.ours")} description={t("conflict.oursHelp")} text={slice.ours || t("conflict.empty")} scrollRef={oursRef} onScroll={syncScroll("ours")} /><MergeCodePane role="theirs" label={t("conflict.theirs")} description={t("conflict.theirsHelp")} text={slice.theirs || t("conflict.empty")} scrollRef={theirsRef} onScroll={syncScroll("theirs")} /></div><MergeCodePane role="result" label={t("conflict.result")} description={t("conflict.resultHelp")} text={slice.result || t("conflict.deleted")} /></div><details className="full-snapshots"><summary>{t("conflict.fullSnapshots")}</summary><div className="comparison-grid">{(["ours", "theirs", "result"] as const).map((key) => <section className={`comparison-pane ${key}`} key={key}><pre>{conflict[key].text || (key === "result" ? t("conflict.deleted") : t("conflict.empty"))}</pre></section>)}</div></details>{conflict.agentExplanation ? <p className="agent-explanation">{conflict.agentExplanation}</p> : null}</details>;
}

function DiffDialog({ action, onClose, onReviewPatch }: { action: ActionRecord; onClose: () => void; onReviewPatch: (runId: string) => Promise<void> }) {
  const { t } = useLocale();
  const changedFiles = parseDiffFiles(action.diff ?? "");
  return (
    <div className="modal-layer" role="presentation">
      <section className="diff-dialog" role="dialog" aria-modal="true" aria-labelledby="diffTitle">
        <header className="diff-dialog-head">
          <div>
            <h2 id="diffTitle">Changes for {action.repository} #{action.pullRequestNumber}</h2>
            <span>{changedFiles.length} file{changedFiles.length === 1 ? "" : "s"} · {action.id}</span>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close changes dialog"><X size={18} /></button>
        </header>
        <div className="diff-dialog-body">
          <aside className="diff-file-list" aria-label="Changed files">
            {changedFiles.length ? changedFiles.map((file) => <span key={file}>{file}</span>) : <span>No file list available</span>}
          </aside>
          <pre className="diff-view">{action.diff || "No diff captured."}</pre>
        </div>
        <footer className="diff-dialog-foot">
          <button className="secondary-btn" type="button" onClick={onClose}>Close</button>
          {action.status === "patch_ready" ? <button className="primary-btn" type="button" title={t("actions.reviewPatchHelp")} onClick={() => { void onReviewPatch(action.id); onClose(); }}><FileSearch size={16} /><span>Review patch</span></button> : null}
        </footer>
      </section>
      <button className="modal-scrim" type="button" aria-label="Close changes dialog" onClick={onClose} />
    </div>
  );
}

function parseDiffFiles(diff: string) {
  return [...new Set(diff.split("\n").flatMap((line) => {
    if (!line.startsWith("diff --git ")) return [];
    const match = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
    return match ? [match[2]] : [];
  }))];
}

function ActivityView({ events, message, onClearAll }: { events: ActivityEvent[]; message: string; onClearAll: () => Promise<void> }) {
  const { t } = useLocale();
  const sortedEvents = [...events].sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  return (
    <section className="view is-visible" aria-labelledby="activityTitle">
      <div className="view-head">
        <div>
          <h1 id="activityTitle">{t("activity.title")}</h1>
          <p>{t("activity.subtitle")}</p>
        </div>
        <div className="activity-actions">
          <button className="secondary-btn" type="button" onClick={() => void onClearAll()} disabled={events.length === 0}>
            <Trash2 size={15} aria-hidden="true" />
            {t("activity.clearAll")}
          </button>
        </div>
      </div>
      {message && <p className="activity-message">{message}</p>}
      <div className="activity-list">
        {sortedEvents.length === 0 ? <p className="empty-state">{t("activity.empty")}</p> : sortedEvents.map((event) => (
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

function SearchView(props: {
  searchSettings: SearchSettings;
  repositories: string[];
  members: TeamMember[];
  runs: SearchRun[];
  backendId: AgentBackend["id"];
  onSearch: (input: { query: string; kind: SearchRun["kind"]; repositoryIds: string[]; memberId?: string }) => Promise<void>;
  onCancel: (runId: string) => Promise<void>;
}) {
  const { t, locale } = useLocale();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<SearchRun["kind"]>("pull_requests");
  const [selectedRepos, setSelectedRepos] = useState<string[] | null>(null);
  const [memberId, setMemberId] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [clearedResultId, setClearedResultId] = useState(() => window.localStorage.getItem("mergeops.search.clearedResultId"));
  const activeRun = props.runs.find((run) => ["queued", "running"].includes(run.status));
  const latestRun = props.runs[0];
  const latestCompletedRun = props.runs.find((run) => run.status === "completed");
  const resultsRun = latestCompletedRun?.id === clearedResultId ? undefined : latestCompletedRun;
  const hasToken = props.searchSettings.backend === "github" ? props.searchSettings.githubReady : props.searchSettings.gitcodeReady;
  const selected = selectedRepos ?? props.repositories;

  useEffect(() => { setSelectedRepos([]); }, [props.repositories.join("|")]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim() || !selected.length) return;
    setBusy(true);
    setError("");
    try {
      await props.onSearch({ query: query.trim(), kind, repositoryIds: selected, memberId: memberId === "all" ? undefined : memberId });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("search.failed"));
    } finally {
      setBusy(false);
    }
  }

  function clearResults() {
    if (!latestCompletedRun) return;
    window.localStorage.setItem("mergeops.search.clearedResultId", latestCompletedRun.id);
    setClearedResultId(latestCompletedRun.id);
  }

  return (
    <section className="view is-visible search-view" aria-labelledby="searchTitle">
      <div className="view-head"><div><h1 id="searchTitle">{t("search.title")}</h1><p>{t("search.subtitle")}</p></div><span className={`search-backend-chip ${props.searchSettings.backend}`}>{props.searchSettings.backend === "github" ? "GitHub" : "GitCode"}</span></div>
      <form className="search-form" onSubmit={submit}>
        <label className="search-query"><Search size={19} aria-hidden="true" /><span className="sr-only">{t("search.query")}</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("search.placeholder")} /></label>
        <button className="primary-btn" type="submit" disabled={busy || Boolean(activeRun) || !hasToken || !props.repositories.length || !query.trim()}>{busy ? t("search.starting") : t("search.submit")}</button>
        <div className="search-filters">
          <label className="field"><span>{t("search.scope")}</span><select value={kind} onChange={(event) => setKind(event.target.value as SearchRun["kind"])}><option value="pull_requests">{t("search.pullRequests")}</option><option value="issues">{t("search.issues")}</option></select></label>
          <fieldset className="search-repository-filter"><legend>{t("search.repositories")}</legend><div className="search-repository-list">{props.repositories.map((repository) => {
            const checked = selectedRepos === null || selectedRepos.includes(repository);
            return <label className={`search-repository-option ${checked ? "is-selected" : ""}`} key={repository}><input type="checkbox" checked={checked} onChange={(event) => setSelectedRepos((current) => {
            const base = current ?? props.repositories;
            const next = event.target.checked ? [...base, repository] : base.filter((item) => item !== repository);
            return next.length === props.repositories.length ? null : next;
          })} />{repository}</label>;
          })}</div></fieldset>
          <label className="field"><span>{t("search.member")}</span><select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="all">{t("search.allMembers")}</option>{props.members.filter((member) => member.githubUsername).map((member) => <option value={member.id} key={member.id}>{member.displayName}</option>)}</select></label>
        </div>
      </form>
      {!hasToken ? <p className="search-notice" role="status">{t("search.missingToken")}</p> : null}
      {!props.repositories.length ? <p className="search-notice" role="status">{t("search.noRepositories")}</p> : null}
      {error ? <p className="search-error" role="alert">{error}</p> : null}
      {activeRun ? <div className="search-progress" role="status" aria-live="polite"><span className="health-dot" /><div><strong>{activeRun.searchBackend === "github" ? "GitHub" : "GitCode"} · {activeRun.status === "queued" ? t("search.queued") : t("search.running")}</strong><span>{activeRun.query}</span></div><button className="secondary-btn" type="button" onClick={() => void props.onCancel(activeRun.id)}>{t("search.cancel")}</button></div> : null}
      {resultsRun ? <div className="search-result-heading"><div><h2>{t("search.results")}</h2><p>{resultsRun.repositoryIds.join(" · ")} · {resultsRun.searchBackend === "github" ? "GitHub" : "GitCode"} · {resultsRun.query}</p></div><div className="search-result-actions"><span>{t("search.resultCount", { count: resultsRun.results.length })}</span><button className="secondary-btn search-clear-btn" type="button" onClick={clearResults}>{t("search.clearResults")}</button></div></div> : null}
      {resultsRun?.errors.length ? <div className="search-notice" role="status"><strong>{t("search.partialResults")}</strong><ul>{resultsRun.errors.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
      {resultsRun?.results.length ? <div className="search-results" aria-label={t("search.results")}>{resultsRun.results.map((result) => <details className="search-result" key={`${result.source}-${result.kind}-${result.repository}-${result.number}`}>
        <summary><span className="search-result-kind">{result.kind === "pull_request" ? "PR" : "ISSUE"} #{result.number}</span><span className="search-result-title">{result.originalTitle}</span><span className="search-result-repo">{result.repository} · @{result.author}</span><span className={`status search-result-state ${result.state.toLowerCase()}`}>{result.state}</span><span className="search-result-reason">{result.reason[locale]}</span></summary>
        <div className="search-result-body"><p>{result.summary[locale]}</p><p><strong>{t("search.whyRelevant")}</strong> {result.reason[locale]}</p>{result.match === "confirmed" ? <span className="search-confirmed">{t("search.confirmed")}</span> : null}<div className="search-result-links"><a href={result.url} target="_blank" rel="noreferrer">{t("search.openSource")}</a>{result.linkedItems.map((item) => {
          const linkedRepository = new URL(item.url).pathname.split("/").filter(Boolean).slice(0, 2).join("/");
          return <a key={`${item.kind}-${item.number}-${item.url}`} href={item.url} target="_blank" rel="noreferrer">{item.kind === "issue" ? "Issue" : "PR"} #{item.number} · {linkedRepository}</a>;
        })}</div></div>
      </details>)}</div> : resultsRun ? <div className="empty-state compact"><strong>{t("search.empty")}</strong><span>{t("search.emptyHelp")}</span></div> : null}
      {latestCompletedRun && !resultsRun ? <div className="empty-state compact search-cleared" role="status"><strong>{t("search.cleared")}</strong><span>{t("search.clearedHelp")}</span></div> : null}
      {latestRun && latestRun.status !== "completed" && !["queued", "running"].includes(latestRun.status) ? <div className="search-error" role="status"><strong>{t("search.runStatus", { status: latestRun.status.replace(/_/g, " ") })}</strong><span>{latestRun.summary}</span>{latestRun.rawOutput ? <details><summary>{t("search.rawOutput")}</summary><pre>{latestRun.rawOutput}</pre></details> : null}</div> : null}
      {!props.runs.length ? <div className="search-welcome"><Search size={24} /><strong>{t("search.promptTitle")}</strong><span>{t("search.promptBody")}</span></div> : null}
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
  searchSettings: SearchSettings;
  onSaveSearchSettings: (settings: { backend: SearchSettings["backend"]; gitcodeRepositories: string[]; githubReadToken?: string; gitcodeReadToken?: string }) => Promise<void>;
  members: TeamMember[];
  onOpenTeam: () => void;
  github?: GitHubSettings | null;
  onSaveGitHub: (input: { username?: string | null; token?: string; repositories?: RepositoryConfig[] }) => Promise<void>;
  agentSettings: AgentSettings;
  onSaveAgentSettings: (settings: AgentSettings) => Promise<void>;
  onSyncGitHub: () => Promise<GitHubSyncResult>;
}) {
  const { t, locale } = useLocale();
  type SettingsTab = "Team" | "Repositories" | "Integrations" | "Automation Policy" | "Search" | "Preferences";
  const [activeTab, setActiveTab] = useState<SettingsTab>("Integrations");
  const [token, setToken] = useState("");
  const [username, setUsername] = useState(props.github?.username ?? "");
  const [repoText, setRepoText] = useState(formatRepositories(props.github?.repositories ?? []));
  const [runnerTimeoutSeconds, setRunnerTimeoutSeconds] = useState(props.agentSettings.runnerTimeoutSeconds);
  const [searchBackend, setSearchBackend] = useState<SearchSettings["backend"]>(props.searchSettings.backend);
  const [gitcodeRepos, setGitcodeRepos] = useState(props.searchSettings.gitcodeRepositories.join("\n"));
  const [githubSearchToken, setGithubSearchToken] = useState("");
  const [gitcodeSearchToken, setGitcodeSearchToken] = useState("");
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    setUsername(props.github?.username ?? "");
    setRepoText(formatRepositories(props.github?.repositories ?? []));
    setRunnerTimeoutSeconds(props.agentSettings.runnerTimeoutSeconds);
    setSearchBackend(props.searchSettings.backend);
    setGitcodeRepos(props.searchSettings.gitcodeRepositories.join("\n"));
  }, [props.github, props.agentSettings, props.searchSettings]);

  async function saveGitHub(event: React.FormEvent) {
    event.preventDefault();
    setStatus(locale === "zh" ? "正在保存 GitHub 设置" : "Saving GitHub settings");
    try {
      await props.onSaveGitHub({
        username: username.trim() || null,
        token: token.trim() || undefined,
        repositories: parseRepositories(repoText)
      });
      await props.onSaveAgentSettings({ runnerTimeoutSeconds });
      setToken("");
      setStatus(t("settings.saved"));
    } catch {
      setStatus("GitHub settings failed");
    }
  }

  async function syncNow() {
    setStatus(t("settings.syncing"));
    try {
      const result = await props.onSyncGitHub();
      setStatus(result.errors.length ? `${result.pullRequestsImported} PR · ${result.errors.length} ${locale === "zh" ? "个错误" : "errors"}` : `${result.pullRequestsImported} PR`);
    } catch {
      setStatus(t("settings.syncFailed"));
    }
  }

  async function saveSearch(event: React.FormEvent) {
    event.preventDefault();
    setStatus(t("search.settingsSaving"));
    try {
      await props.onSaveSearchSettings({ backend: searchBackend, gitcodeRepositories: gitcodeRepos.split(/\s+/).map((item) => item.trim()).filter(Boolean), githubReadToken: githubSearchToken.trim() || undefined, gitcodeReadToken: gitcodeSearchToken.trim() || undefined });
      setGithubSearchToken("");
      setGitcodeSearchToken("");
      setStatus(t("search.settingsSaved"));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t("search.settingsFailed"));
    }
  }

  return (
    <section className="view is-visible" aria-labelledby="settingsTitle">
      <div className="view-head">
        <div>
          <h1 id="settingsTitle">{t("settings.title")}</h1>
          <p>{t("settings.subtitle")}</p>
        </div>
      </div>
      <div className="settings-layout">
        <nav className="settings-tabs" aria-label={t("settings.sections")}>
          {["Team", "Repositories", "Integrations", "Automation Policy", "Search", "Preferences"].map((item) => {
            const labels: Record<SettingsTab, string> = { Team: t("settings.team"), Repositories: t("settings.repositories"), Integrations: t("settings.integrations"), "Automation Policy": t("settings.automation"), Search: t("settings.search"), Preferences: t("settings.preferences") };
            return <button key={item} type="button" className={activeTab === item ? "is-active" : ""} onClick={() => setActiveTab(item as SettingsTab)}>{labels[item as SettingsTab]}</button>;
          })}
        </nav>
        {activeTab === "Team" && (
          <div className="settings-panel is-visible">
            <h2>{t("settings.team")}</h2>
            <p className="settings-intro">{t("settings.teamIntro")}</p>
            <div className="settings-list">
              {props.members.map((member) => <div className="settings-list-row" key={member.id}><strong>{member.displayName}</strong><span>@{member.githubUsername || "unlinked"} · {member.availability.replace("_", " ")}</span></div>)}
            </div>
            <div className="settings-actions"><button className="secondary-btn" type="button" onClick={props.onOpenTeam}>{t("settings.openTeam")}</button></div>
          </div>
        )}
        {activeTab === "Repositories" && (
          <form className="settings-panel is-visible" onSubmit={saveGitHub}>
            <h2>{t("settings.repositories")}</h2>
          <p className="settings-intro">{t("settings.repoIntro")} <code>git diff --check</code>.</p>
            <label className="field full"><span>{t("settings.allowlist")}</span><textarea value={repoText} onChange={(event) => setRepoText(event.target.value)} rows={7} placeholder="owner/repo | /absolute/local/path | npm test, git diff --check" /></label>
            <div className="settings-actions"><button className="primary-btn" type="submit">{t("settings.saveRepos")}</button><button className="secondary-btn" type="button" onClick={syncNow}>{t("settings.syncNow")}</button>{status ? <span className="sync-status">{status}</span> : null}</div>
          </form>
        )}
        {activeTab === "Integrations" && (
          <form className="settings-panel is-visible" onSubmit={saveGitHub}>
            <h2>{t("settings.integrations")}</h2>
            <div className="settings-grid">
              <label className="field"><span>{t("settings.githubAccess")}</span><input readOnly value={t("settings.contributorToken")} /></label>
              <label className="field"><span>{t("settings.backendSdk")}</span><select value={props.backendId} onChange={(event) => props.onBackendChange(event.target.value as AgentBackend["id"])}>{props.backends.map((backend) => <option key={backend.id} value={backend.id}>{backend.displayName}</option>)}</select></label>
              <label className="field"><span>{t("settings.endpoint")}</span><input readOnly value={t("settings.localSdk")} /><small>{t("settings.localSdkHelp")}</small></label>
              <label className="field"><span>{t("settings.timeout")}</span><input type="number" min="30" max="3600" step="30" value={runnerTimeoutSeconds} onChange={(event) => setRunnerTimeoutSeconds(Number(event.target.value) || 600)} /><small>{t("settings.defaultTimeout")}</small></label>
              <label className="field"><span>{t("settings.username")}</span><input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="your-github-id" /></label>
              <label className="field"><span>{t("settings.contributorToken")} <small>{props.github?.hasToken ? t("settings.tokenStored") : t("settings.tokenMissing")}</small></span><input value={token} onChange={(event) => setToken(event.target.value)} type="password" placeholder={props.github?.hasToken ? t("settings.keepToken") : t("settings.fineToken")} /></label>
            </div>
            <div className="settings-actions"><button className="primary-btn" type="submit">{t("settings.saveIntegration")}</button>{status ? <span className="sync-status">{status}</span> : null}</div>
          </form>
        )}
        {activeTab === "Automation Policy" && (
          <div className="settings-panel is-visible"><h2>{t("settings.automation")}</h2><p className="settings-intro">{t("settings.policyIntro")}</p><div className="settings-notice"><strong>{t("settings.approvalGate")}</strong><span>{t("settings.approvalGateBody")}</span></div></div>
        )}
        {activeTab === "Search" && (
          <form className="settings-panel is-visible" onSubmit={saveSearch}>
            <h2>{t("settings.search")}</h2>
            <p className="settings-intro">{t("search.settingsIntro")}</p>
            <div className="settings-grid">
              <label className="field"><span>{t("search.backend")}</span><select value={searchBackend} onChange={(event) => setSearchBackend(event.target.value as SearchSettings["backend"])}><option value="github">GitHub</option><option value="gitcode">GitCode</option></select></label>
              <label className="field"><span>{t("search.githubCredential")}</span><input type="password" value={githubSearchToken} onChange={(event) => setGithubSearchToken(event.target.value)} placeholder={props.searchSettings.githubReady ? t("search.tokenStored") : t("search.readOnlyToken")} /><small>{props.searchSettings.githubReady ? t("search.tokenStored") : t("search.tokenMissing")}</small></label>
              <label className="field full"><span>{t("search.gitcodeRepositories")}</span><textarea rows={3} value={gitcodeRepos} onChange={(event) => setGitcodeRepos(event.target.value)} placeholder="openJiuwen/agent-core\nopenJiuwen/jiuwenswarm" /></label>
              <label className="field full"><span>{t("search.gitcodeCredential")}</span><input type="password" value={gitcodeSearchToken} onChange={(event) => setGitcodeSearchToken(event.target.value)} placeholder={props.searchSettings.gitcodeReady ? t("search.tokenStored") : t("search.readOnlyToken")} /><small>{props.searchSettings.gitcodeReady ? t("search.tokenStored") : t("search.tokenMissing")}</small></label>
            </div>
            <div className="settings-actions"><button className="primary-btn" type="submit">{t("search.saveSettings")}</button>{status ? <span className="sync-status" role="status">{status}</span> : null}</div>
          </form>
        )}
        {activeTab === "Preferences" && (
          <div className="settings-panel is-visible"><h2>{t("settings.preferences")}</h2><div className="settings-grid"><label className="field"><span>{t("settings.theme")}</span><select value={props.theme} onChange={(event) => props.onThemeChange(event.target.value as ThemePreference)}><option value="system">{t("settings.system")}</option><option value="light">{t("settings.light")}</option><option value="dark">{t("settings.dark")}</option></select></label><label className="field"><span>{t("settings.prAge")}</span><select value={props.dateRange} onChange={(event) => props.onDateRangeChange(event.target.value === "all" ? "all" : Number(event.target.value))}><option value="30">{t("filter.lastDays", { days: 30 })}</option><option value="60">{t("filter.lastDays", { days: 60 })}</option><option value="90">{t("filter.lastDays", { days: 90 })}</option><option value="all">{t("filter.allTime")}</option></select></label></div><p className="settings-intro">{t("settings.localPrefs")}</p></div>
        )}
      </div>
    </section>
  );
}

function formatRepositories(repositories: RepositoryConfig[]) {
  return repositories.map((repository) => {
    const remote = `${repository.owner}/${repository.name}`;
    const path = repository.localPath ? ` | ${repository.localPath}` : "";
    const checks = repository.requiredChecks?.filter(Boolean).join(", ") ?? "";
    return checks
      ? `${remote}${path} | ${checks}`
      : remote;
  }).join("\n");
}

function parseRepositories(value: string): RepositoryConfig[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [remote, rawLocalPath, checksText] = line.split("|").map((part) => part.trim());
    const localPath = checksText ? rawLocalPath : "";
    const parsedChecks = checksText || (rawLocalPath === "git diff --check" ? rawLocalPath : "");
    const [owner, name] = remote.split("/");
    const repoName = name || owner;
    return {
      id: `${owner}-${repoName}`.replace(/[^a-zA-Z0-9_.-]/g, "-"),
      owner: owner || "",
      name: repoName || "",
      defaultBranch: "main",
      enabled: true,
      localPath: localPath || null,
      requiredChecks: parsedChecks ? parsedChecks.split(",").map((check) => check.trim()).filter(Boolean) : ["git diff --check"]
    };
  }).filter((repository) => repository.owner && repository.name);
}

function PrDrawer(props: {
  pr: PullRequest;
  member?: TeamMember;
  backend: AgentBackend;
  run?: ActionRecord;
  annotations: PrAnnotations | null;
  canPushPrBranch: boolean;
  onClose: () => void;
  onStartRun: (reviewThreadIds: string[]) => void;
  onCheckout: () => void;
  onApproveRun: (runId: string) => Promise<void>;
  onPushRun: (runId: string, target?: "mergeops_branch" | "pr_branch") => Promise<void>;
  onReviewRun: (runId: string) => Promise<void>;
  onReviseRun: (runId: string, instruction: string, reason?: string) => Promise<void>;
  onPostReplies: (runId: string, replies: ReplyDraft[]) => Promise<void>;
  onRetryRun: (runId: string) => Promise<void>;
  onContinueRebase: (runId: string) => Promise<void>;
  onFixManually: (runId: string) => Promise<void>;
  onClearRun: (runId: string) => Promise<void>;
  onInspectRecovery: (runId: string) => Promise<void>;
  onReviewThreadsRefreshed: () => Promise<void>;
  onSaveTags: (tags: string[]) => Promise<void>;
  onSaveNote: (text: string) => Promise<void>;
  onDeleteNote: (noteId: string) => Promise<void>;
  checkoutMessage: string;
}) {
  const { t } = useLocale();
  const status = statusFor(props.pr);
  const statusKeys: Record<string, TranslationKey> = { closed: "status.closed", merged: "status.merged", draft: "status.draft", conflict: "status.conflict", checks: "status.checks", ready: "status.ready", review: "status.review" };
  const needsAttention = matchesQueue(props.pr, "needs_you");
  const plan = status === "review" && !needsAttention ? {
    title: t("drawer.reviewStatusTitle"),
    explanation: t("drawer.reviewStatusExplanation"),
    steps: [t("drawer.reviewStatusStepInspect"), t("drawer.reviewStatusStepChecks"), t("drawer.reviewStatusStepWait")],
    action: null
  } : drawerPlan(status);
  const isOpen = props.pr.state === "open";
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [reason, setReason] = useState("");
  const [tagDraft, setTagDraft] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [message, setMessage] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewThreads, setReviewThreads] = useState<ReviewThreadSnapshot | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [selectedThreadIds, setSelectedThreadIds] = useState<string[]>([]);
  const [replyDrafts, setReplyDrafts] = useState<ReplyDraft[]>([]);
  const [replySending, setReplySending] = useState(false);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const annotations = props.annotations ?? { pullRequestId: props.pr.id, tags: [], notes: [] };
  const canRevise = isOpen && !!props.run?.workspacePath && ["patch_ready", "approved", "review_ready"].includes(props.run.status);
  const unresolvedThreads = reviewThreads?.threads.filter((thread) => !thread.isResolved && !thread.isOutdated) ?? [];
  const validSelectedIds = selectedThreadIds.filter((id) => unresolvedThreads.some((thread) => thread.id === id));
  const allSelected = unresolvedThreads.length > 0 && validSelectedIds.length === unresolvedThreads.length;

  useEffect(() => { setReplyDrafts(props.run?.replyDrafts ?? []); }, [props.run?.id, props.run?.replyDrafts]);

  useEffect(() => {
    setFeedbackOpen(false);
    setFeedback("");
    setReason("");
    setTagDraft("");
    setNoteDraft("");
    setMessage("");
    setReviewOpen(false);
    setReviewThreads(null);
    setReviewLoading(false);
    setSelectedThreadIds([]);
    setReplyDrafts([]);
    setReplySending(false);
  }, [props.pr.id]);

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = validSelectedIds.length > 0 && !allSelected;
  }, [allSelected, validSelectedIds.length]);

  async function loadThreads() {
    setReviewLoading(true);
    try {
      setReviewThreads(await loadReviewThreads(props.pr.id));
      void props.onReviewThreadsRefreshed();
    }
    catch (error) { setReviewThreads({ pullRequestId: props.pr.id, fetchedAt: "", stale: true, error: error instanceof Error ? error.message : "Unable to load review threads", threads: [] }); }
    finally { setReviewLoading(false); }
  }

  function toggleReview(open: boolean) {
    setReviewOpen(open);
    if (open && !reviewThreads) void loadThreads();
  }

  function toggleThread(thread: ReviewThread) {
    if (thread.isResolved || thread.isOutdated) return;
    setSelectedThreadIds((current) => current.includes(thread.id) ? current.filter((id) => id !== thread.id) : [...current, thread.id]);
  }

  function toggleAllThreads() {
    setSelectedThreadIds(allSelected ? [] : unresolvedThreads.map((thread) => thread.id));
  }

  async function submitFeedback() {
    if (!props.run || !feedback.trim()) return;
    setMessage("");
    try {
      await props.onReviseRun(props.run.id, feedback.trim(), reason.trim() || undefined);
      setFeedback("");
      setReason("");
      setFeedbackOpen(false);
      setMessage("Revision queued. The agent will preserve the existing patch and apply your feedback.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not queue the revision.");
    }
  }

  async function addTag() {
    const tag = tagDraft.trim();
    if (!tag || annotations.tags.includes(tag)) return;
    await props.onSaveTags([...annotations.tags, tag]);
    setTagDraft("");
  }

  async function submitReplies() {
    if (!props.run || !replyDrafts.length) return;
    setReplySending(true);
    try { await props.onPostReplies(props.run.id, replyDrafts.filter((draft) => draft.status !== "posted")); setMessage("Review reply outcomes recorded."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not post replies."); }
    finally { setReplySending(false); }
  }

  async function retryCurrentRun() {
    if (!props.run) return;
    setMessage("");
    try {
      await props.onRetryRun(props.run.id);
      setMessage("Retry queued.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not queue the retry.");
    }
  }

  async function fixManuallyCurrentRun() {
    if (!props.run) return;
    setMessage("");
    try {
      await props.onFixManually(props.run.id);
      setMessage("Manual resolution validated. Review the patch, then approve it before pushing.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not validate the manual resolution.");
    }
  }

  async function discardEmptyPreparedRun() {
    if (!props.run) return;
    setMessage("");
    try {
      await props.onClearRun(props.run.id);
      setMessage("Empty prepared run discarded. You can start a new remediation run.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not discard the prepared run.");
    }
  }
  return (
    <>
      <aside className="drawer is-open" aria-labelledby="drawerTitle">
        <div className="drawer-head">
          <div>
            <span><a className="pr-link" href={`https://github.com/${props.pr.repositoryFullName ?? props.pr.repository}/pull/${props.pr.number}`} target="_blank" rel="noreferrer">{props.pr.repository} #{props.pr.number}</a></span>
            <h2 id="drawerTitle">{props.pr.title}</h2>
          </div>
          <button className="icon-btn" onClick={props.onClose} aria-label="Close drawer"><X size={18} /></button>
        </div>
        <div className="drawer-body">
          <section className="detail-block">
            <div className="tag-row">
              <span className={`status ${status}`}>{t(statusKeys[status])}</span>
              {props.pr.linkedIssueIds.map((issue) => <span className="tag" key={issue}>{issue}</span>)}
              <span className="tag">{props.member?.displayName ?? props.pr.author}</span>
              {annotations.tags.map((tag) => <span className="tag local-tag" key={tag}>{tag}</span>)}
            </div>
            <p>{props.pr.summary}</p>
          </section>
          <section className="detail-block">
            <h3>Operational state</h3>
            <div className="kv-grid">
              <div className="kv"><span>Review</span><strong>{props.pr.reviewState.replace("_", " ")}</strong></div>
              <div className="kv"><span>Checks</span>{props.pr.checkState === "failing" ? <span className="failure-copy check-indicator"><CircleAlert size={15} aria-hidden="true" />{t("checks.failed")}</span> : <strong>{props.pr.checkState.replace("_", " ")}</strong>}</div>
              <div className="kv"><span>Age</span><strong>{props.pr.ageDays} days</strong></div>
              <div className="kv"><span>Comments</span><strong>{props.pr.unresolvedCommentCount}</strong></div>
            </div>
            {props.pr.checkState === "failing" ? <div className="ci-alert" role="alert"><CircleAlert size={18} aria-hidden="true" /><span><span>{t("checks.failed")}</span><small>{t("checks.failedHelp")}</small></span></div> : null}
            <p className="drawer-meta"><strong>{props.pr.repositoryFullName ?? props.pr.repository}</strong> · {props.pr.sourceBranch} → {props.pr.baseBranch} · {props.pr.changedFilesCount} changed files</p>
          </section>
          <details className="detail-block review-feedback" open={reviewOpen} onToggle={(event) => toggleReview(event.currentTarget.open)}>
            <summary className="panel-title"><span><h3>{t("drawer.reviewFeedback")}</h3><small>{t("drawer.unresolvedCount", { count: reviewThreads?.threads.filter((thread) => !thread.isResolved && !thread.isOutdated).length ?? props.pr.unresolvedCommentCount })}</small></span><span className="review-summary-actions">{reviewThreads ? <button className="text-btn" type="button" onClick={(event) => { event.preventDefault(); void loadThreads(); }}>{t("drawer.refreshThreads")}</button> : null}</span></summary>
            {reviewLoading ? <p className="drawer-meta">{t("drawer.loadThreads")}…</p> : reviewThreads?.stale ? <p className="stale-note">{t("drawer.staleSnapshot", { error: reviewThreads.error ?? "refresh failed" })}</p> : null}
            {!reviewLoading && reviewThreads && !unresolvedThreads.length ? <p className="empty-state compact">{t("drawer.noThreads")}</p> : null}
            {unresolvedThreads.map((thread) => {
              return <article className="review-thread" key={thread.id}>
                <label className="review-thread-select"><input type="checkbox" checked={validSelectedIds.includes(thread.id)} onChange={() => toggleThread(thread)} aria-label={`${t("drawer.reviewThread")} ${thread.id}`} /><span /></label>
                <div className="review-thread-copy"><div className="review-thread-meta"><strong>{thread.author}</strong><span>{thread.authorType === "bot" ? "bot" : "human"}</span>{thread.path ? <code>{thread.path}{thread.line ? `:${thread.line}` : ""}</code> : null}<time dateTime={thread.createdAt}>{new Date(thread.createdAt).toLocaleString()}</time></div><p>{thread.excerpt || thread.body}</p><details><summary>{t("drawer.reviewThread")}</summary><pre>{thread.body}</pre>{thread.diffHunk ? <pre>{thread.diffHunk}</pre> : null}</details></div>
              </article>;
            })}
            {reviewThreads && unresolvedThreads.length ? <div className="review-selection-bar"><label><input ref={selectAllRef} type="checkbox" checked={allSelected} onChange={toggleAllThreads} /> {t("drawer.selectAllUnresolved")}</label><button className="primary-btn" type="button" disabled={!validSelectedIds.length} onClick={() => props.onStartRun(validSelectedIds)}>{t("drawer.fixSelected", { count: validSelectedIds.length })}</button></div> : null}
          </details>
          {plan ? (
            <section className="detail-block recommendation-panel">
              <div className="recommendation-head"><h3>{plan.title}</h3><span className={`status ${status}`}>{t(statusKeys[status])}</span></div>
              <p>{plan.explanation}</p>
              <div className="timeline">
                {plan.steps.map((step, index) => <div className="step" key={step}><i>{index + 1}</i><span>{step}</span></div>)}
              </div>
            </section>
          ) : (
            <section className="detail-block read-only-state">
              <h3>{t(statusKeys[status])} PR</h3>
              <p>This PR is no longer open for remediation. Checkout, agent preparation, approval, and push actions are unavailable.</p>
            </section>
          )}
          <section className="approval-panel">
            <strong>{isOpen ? "Available actions" : "Read-only state"}</strong>
            <p>{isOpen ? "Agent work prepares a patch in isolation. Pushing remains locked until a human approves the diff and check result." : "Historical agent results remain visible below, but this PR cannot start or push new remediation work."}</p>
            {isOpen ? (
              <div className="button-row">
                <button className="secondary-btn" onClick={props.onCheckout}><FolderGit2 size={18} /><span>Checkout</span></button>
                {plan?.action ? <button className="primary-btn" onClick={() => status === "review" ? toggleReview(true) : props.onStartRun([])}>{status === "review" ? <FileSearch size={18} /> : <Play size={18} />}<span>{status === "review" ? t("drawer.selectReviewComments") : plan.action}</span></button> : null}
              </div>
            ) : null}
            {props.checkoutMessage ? <p className="sync-status" role="status">{props.checkoutMessage}</p> : null}
          </section>
          <section className="detail-block notes-panel">
            <div className="panel-title"><h3>Notes & tags</h3><span>Local only</span></div>
            <div className="tag-editor">
              <input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void addTag(); } }} placeholder="Add a tag" aria-label="Add local tag" />
              <button className="secondary-btn" type="button" onClick={() => void addTag()} disabled={!tagDraft.trim()}>Add</button>
            </div>
            {annotations.tags.length ? <div className="tag-row">{annotations.tags.map((tag) => <button className="tag local-tag removable-tag" type="button" key={tag} onClick={() => void props.onSaveTags(annotations.tags.filter((item) => item !== tag))}>{tag}<X size={12} /></button>)}</div> : null}
            <textarea value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} placeholder="Leave a sticky note for this PR" aria-label="PR note" rows={3} />
            <div><button className="secondary-btn" type="button" disabled={!noteDraft.trim()} onClick={() => void props.onSaveNote(noteDraft.trim()).then(() => setNoteDraft(""))}>Save note</button></div>
            <div className="note-list">{annotations.notes.length ? annotations.notes.map((note) => <article className="sticky-note" key={note.id}><p>{note.text}</p><footer><span>{new Date(note.updatedAt).toLocaleString()}</span><button type="button" onClick={() => void props.onDeleteNote(note.id)}>Delete</button></footer></article>) : <p className="drawer-meta">No local notes yet.</p>}</div>
          </section>
          {props.run ? (
            <section className="detail-block review-panel">
              <div className="review-panel-head"><h3>Approval review</h3><span className={`status ${props.run.status === "failed" ? "is-failed" : "agent"}`}>{props.run.status.replace("_", " ")}</span></div>
              {props.run.patchSummary ? <p>{props.run.patchSummary}{props.run.riskSummary ? ` Risk: ${props.run.riskSummary}` : ""}</p> : props.run.status === "failed" ? <p className="failure-copy">{props.run.summary}</p> : <p>Patch material is still being prepared.</p>}
              {props.run.checks?.map((check) => <div className="check-row" key={check.name}><span>{check.name}</span><strong className={check.status}>{check.status}</strong></div>)}
              {props.run.diff ? <details className="diff-details"><summary>View patch diff</summary><pre>{props.run.diff}</pre></details> : null}
              <div className="button-row">
                {isOpen && props.run.status === "patch_ready" ? <button className="secondary-btn" type="button" onClick={() => void props.onReviewRun(props.run!.id)}><FileSearch size={16} />{t("drawer.runIndependentReview")}</button> : null}
                {isOpen && props.run.status === "review_ready" ? <button className="primary-btn" type="button" onClick={() => { setFeedback(`Apply the independent review findings below to the prepared patch:\n\n${props.run?.agentOutput ?? "Review findings are in the run details."}`); setFeedbackOpen(true); }}>{t("drawer.applyReviewFindings")}</button> : null}
                {isOpen && props.run.status === "patch_ready" ? <button className="primary-btn" type="button" onClick={() => props.onApproveRun(props.run!.id)}>Approve patch</button> : null}
                {isOpen && props.run.status === "patch_ready" && !props.run.diff ? <button className="secondary-btn" type="button" onClick={() => void discardEmptyPreparedRun()}>{t("drawer.discardEmptyRun")}</button> : null}
                {isOpen && props.run.status === "approved" ? <div className="push-choice"><select aria-label="Push target" defaultValue={props.canPushPrBranch ? "pr_branch" : "mergeops_branch"}>{props.canPushPrBranch ? <option value="pr_branch">Update PR branch</option> : null}<option value="mergeops_branch">New MergeOps branch</option></select><button className="primary-btn" type="button" onClick={(event) => { const select = event.currentTarget.parentElement?.querySelector("select") as HTMLSelectElement | null; void props.onPushRun(props.run!.id, select?.value === "mergeops_branch" ? "mergeops_branch" : "pr_branch"); }}>Push approved patch</button></div> : null}
                {props.run.pushRef ? <span className="action-meta">Pushed to {props.run.pushRef}</span> : null}
              </div>
              {props.run.status === "pushed" && replyDrafts.length ? <div className="reply-drafts"><div className="section-title"><h4>{t("drawer.postReplies")}</h4><span>{props.run.pushedCommitSha?.slice(0, 12)}</span></div>{replyDrafts.map((draft, index) => <label className="reply-draft" key={draft.id}><span>{t("drawer.replyDraft")} · {draft.threadId}</span><textarea value={draft.body} disabled={draft.status === "posted"} onChange={(event) => setReplyDrafts((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, body: event.target.value, status: "selected" } : item))} rows={3} />{draft.status === "posted" ? <small>{t("drawer.replyPosted")}{draft.replyUrl ? ` · ${draft.replyUrl}` : ""}</small> : draft.status === "ambiguous" ? <small className="failure-copy">{t("drawer.replyAmbiguous")}</small> : draft.error ? <small className="failure-copy">{draft.error}</small> : null}</label>)}<button className="primary-btn" type="button" disabled={replySending || !replyDrafts.some((draft) => draft.status !== "posted")} onClick={() => void submitReplies()}>{replySending ? "Posting…" : t("drawer.postReplies")}</button></div> : null}
              {props.run.dispositions?.length ? <details className="dispositions"><summary>{t("drawer.dispositions")}</summary>{props.run.dispositions.map((item) => <div className="disposition-row" key={item.threadId}><strong>{item.disposition.replace(/_/g, " ")}</strong><span>{item.explanation}</span></div>)}</details> : null}
              {props.run.status === "recovery_required" && !props.run.recoveryInspected ? <button className="secondary-btn" type="button" onClick={() => void props.onInspectRecovery(props.run!.id)}>{t("actions.confirmRecovery")}</button> : null}
              {props.run.status === "failed" || props.run.status === "interrupted" || (props.run.status === "recovery_required" && props.run.recoveryInspected) ? <button className="secondary-btn" type="button" onClick={() => void retryCurrentRun()}>{t("actions.retry")}</button> : null}
              {isOpen && props.run.status === "failed" && ["fix_conflicts", "rebase"].includes(props.run.action) && props.run.rebaseEvidence ? <button className="secondary-btn" type="button" onClick={() => void props.onContinueRebase(props.run!.id)}>{t("actions.continueRebase")}</button> : null}
              {isOpen && props.run.status === "failed" && ["fix_conflicts", "rebase"].includes(props.run.action) ? <button className="secondary-btn" type="button" onClick={() => void fixManuallyCurrentRun()}>{t("actions.fixedManually")}</button> : null}
              {canRevise ? <div className="feedback-panel"><button className="secondary-btn" type="button" onClick={() => setFeedbackOpen((value) => !value)}>Revise with feedback</button>{feedbackOpen ? <div className="feedback-form"><label>Instruction<textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Tell the agent what to change or preserve" rows={4} /></label><label>Reason <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Optional, e.g. scope correction" /></label><button className="primary-btn" type="button" disabled={!feedback.trim()} onClick={() => void submitFeedback()}>Start revision</button></div> : null}</div> : null}
              {message ? <p className="sync-status" role="status">{message}</p> : null}
            </section>
          ) : null}
        </div>
      </aside>
      <div className="scrim is-open" onClick={props.onClose} />
    </>
  );
}

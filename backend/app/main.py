import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .github_sync import sync_github_pull_requests
from .models import AgentRun, AgentSettings, AppData, CheckoutResult, CreateAgentRunRequest, CreateCheckoutRequest, CreatePatchReviewRequest, CreatePrNoteRequest, CreateRevisionRequest, CreateTeamMemberRequest, GitHubSettingsPublic, GitHubSyncResult, PrAnnotations, PushAgentRunRequest, SelectRebaseDecisionRequest, TeamMember, UpdateAgentSettingsRequest, UpdateGitHubSettingsRequest, UpdatePrNoteRequest, UpdatePrTagsRequest, UpdateTeamMemberRequest
from .store import store

agent_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mergeops-agent")
github_sync_lock = asyncio.Lock()

app = FastAPI(title="MergeOps API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5170",
        "http://localhost:5170",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/app-data")
async def get_app_data() -> AppData:
    return store.app_data()


@app.get("/api/actions/{action_id}/details")
async def get_action_details(action_id: str):
    try:
        return store.action_details(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/agent-runs")
async def post_agent_run(payload: CreateAgentRunRequest) -> AgentRun:
    try:
        run = store.queue_agent_run(payload.backendId, payload.pullRequestId, payload.action)
        agent_executor.submit(store.execute_agent_run, run.id, payload.backendId, payload.pullRequestId, payload.action)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/cancel")
async def post_agent_run_cancel(run_id: str) -> AgentRun:
    try:
        return store.cancel_agent_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/rebase-decision")
async def post_rebase_decision(run_id: str, payload: SelectRebaseDecisionRequest) -> AgentRun:
    try:
        run = store.select_rebase_decision(run_id, payload.optionId)
        if run.status == "queued":
            agent_executor.submit(store.execute_agent_run, run.id, run.backendId, run.pullRequestId, run.action)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/review")
async def post_agent_run_review(run_id: str, payload: CreatePatchReviewRequest) -> AgentRun:
    try:
        run = store.queue_patch_review(payload.backendId, run_id)
        agent_executor.submit(store.execute_patch_review, run.id, payload.backendId, run_id)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/revise")
async def post_agent_run_revision(run_id: str, payload: CreateRevisionRequest) -> AgentRun:
    try:
        run = store.queue_revision(payload.backendId, run_id, payload)
        agent_executor.submit(store.execute_agent_run, run.id, run.backendId, run.pullRequestId, run.action)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/approve")
async def post_agent_run_approve(run_id: str) -> AgentRun:
    try:
        return store.approve_agent_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/push")
async def post_agent_run_push(run_id: str, payload: PushAgentRunRequest | None = None) -> AgentRun:
    try:
        return store.push_agent_run(run_id, payload.target if payload else "mergeops_branch")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/pull-requests/{pull_request_id}/annotations", response_model=PrAnnotations)
async def get_pr_annotations(pull_request_id: str) -> PrAnnotations:
    try:
        return store.pr_annotations(pull_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/pull-requests/{pull_request_id}/annotations/tags", response_model=PrAnnotations)
async def put_pr_tags(pull_request_id: str, payload: UpdatePrTagsRequest) -> PrAnnotations:
    try:
        return store.update_pr_tags(pull_request_id, payload.tags)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/pull-requests/{pull_request_id}/annotations/notes", response_model=PrAnnotations)
async def post_pr_note(pull_request_id: str, payload: CreatePrNoteRequest) -> PrAnnotations:
    try:
        return store.create_pr_note(pull_request_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/pull-requests/{pull_request_id}/annotations/notes/{note_id}", response_model=PrAnnotations)
async def patch_pr_note(pull_request_id: str, note_id: str, payload: UpdatePrNoteRequest) -> PrAnnotations:
    try:
        return store.update_pr_note(pull_request_id, note_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/pull-requests/{pull_request_id}/annotations/notes/{note_id}", response_model=PrAnnotations)
async def delete_pr_note(pull_request_id: str, note_id: str) -> PrAnnotations:
    try:
        return store.delete_pr_note(pull_request_id, note_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/checkouts")
async def post_checkout(payload: CreateCheckoutRequest) -> CheckoutResult:
    try:
        return store.create_checkout(payload.pullRequestId)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/actions/{action_id}", status_code=204)
async def delete_action(action_id: str) -> None:
    try:
        store.clear_action(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/team-members")
async def post_team_member(payload: CreateTeamMemberRequest) -> TeamMember:
    return store.create_team_member(payload)


@app.patch("/api/team-members/{member_id}")
async def patch_team_member(member_id: str, payload: UpdateTeamMemberRequest) -> TeamMember:
    try:
        return store.update_team_member(member_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/team-members/{member_id}", status_code=204)
async def delete_team_member(member_id: str) -> None:
    try:
        store.delete_team_member(member_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/settings/github")
async def patch_github_settings(payload: UpdateGitHubSettingsRequest) -> GitHubSettingsPublic:
    return store.update_github_settings(payload)


@app.patch("/api/settings/agent")
async def patch_agent_settings(payload: UpdateAgentSettingsRequest) -> AgentSettings:
    return store.update_agent_settings(payload)


@app.post("/api/sync/github")
async def post_github_sync() -> GitHubSyncResult:
    async with github_sync_lock:
        try:
            # GitHub sync uses blocking urllib calls and may make many requests.
            # Keep that work off the event loop so health and other API calls stay responsive.
            return await asyncio.to_thread(sync_github_pull_requests, store)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

import asyncio
import json
import threading

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from .github_sync import sync_github_pull_requests
from .models import AgentRun, AgentSettings, AppData, CheckoutResult, CreateAgentRunRequest, CreateCheckoutRequest, CreatePatchReviewRequest, CreatePrNoteRequest, CreateRevisionRequest, CreateTeamMemberRequest, GitHubSettingsPublic, GitHubSyncResult, PostReviewRepliesRequest, PrAnnotations, PushAgentRunRequest, RecoveryInspectionRequest, SelectRebaseDecisionRequest, TeamMember, UpdateAgentSettingsRequest, UpdateGitHubSettingsRequest, UpdatePrNoteRequest, UpdatePrTagsRequest, UpdateTeamMemberRequest
from .store import store

github_sync_lock = threading.Lock()

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


async def _run_blocking(function, *args):
    """Run synchronous persistence/GitHub work without blocking FastAPI."""
    result: dict[str, object] = {}

    def invoke() -> None:
        try:
            result["value"] = function(*args)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(0.01)
    if "error" in result:
        raise result["error"]
    return result.get("value")


@app.on_event("startup")
async def start_execution_worker() -> None:
    store.start_worker()


@app.on_event("shutdown")
async def stop_execution_worker() -> None:
    store.stop_worker()


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
        run = await _run_blocking(store.queue_agent_run, payload.backendId, payload.pullRequestId, payload.action, payload.reviewThreadIds)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/cancel")
async def post_agent_run_cancel(run_id: str) -> AgentRun:
    try:
        return await _run_blocking(store.cancel_agent_run, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/rebase-decision")
async def post_rebase_decision(run_id: str, payload: SelectRebaseDecisionRequest) -> AgentRun:
    try:
        run = await _run_blocking(store.select_rebase_decision, run_id, payload.optionId)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/review")
async def post_agent_run_review(run_id: str, payload: CreatePatchReviewRequest) -> AgentRun:
    try:
        run = await _run_blocking(store.queue_patch_review, payload.backendId, run_id)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/revise")
async def post_agent_run_revision(run_id: str, payload: CreateRevisionRequest) -> AgentRun:
    try:
        run = await _run_blocking(store.queue_revision, payload.backendId, run_id, payload)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/approve")
async def post_agent_run_approve(run_id: str) -> AgentRun:
    try:
        return await _run_blocking(store.approve_agent_run, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/push")
async def post_agent_run_push(run_id: str, payload: PushAgentRunRequest | None = None) -> AgentRun:
    try:
        return await _run_blocking(store.push_agent_run, run_id, payload.target if payload else "mergeops_branch")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/retry")
async def post_agent_run_retry(run_id: str) -> AgentRun:
    try:
        return await _run_blocking(store.retry_agent_run, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/review-replies")
async def post_agent_run_review_replies(run_id: str, payload: PostReviewRepliesRequest) -> AgentRun:
    try:
        return await _run_blocking(store.post_review_replies, run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/agent-runs/{run_id}/inspect-recovery")
async def post_agent_run_recovery_inspection(run_id: str, payload: RecoveryInspectionRequest) -> AgentRun:
    try:
        return await _run_blocking(store.inspect_recovery, run_id, payload.confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/agent-runs/events")
async def get_agent_run_events(last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    try:
        cursor = int(last_event_id or "0")
    except ValueError:
        cursor = 0

    async def stream():
        nonlocal cursor
        idle_ticks = 0
        while idle_ticks < 600:
            events = store.ledger.events_after(cursor)
            if events:
                for event in events:
                    cursor = int(event["sequence"])
                    yield f"id: {cursor}\nevent: agent-run\ndata: {json.dumps(event)}\n\n"
                idle_ticks = 0
            else:
                idle_ticks += 1
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/pull-requests/{pull_request_id}/review-threads")
async def get_review_threads(pull_request_id: str):
    try:
        return await _run_blocking(store.get_review_threads, pull_request_id, True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    try:
        # GitHub sync uses blocking urllib calls and may make many requests.
        # Keep that work off the event loop so health and other API calls stay responsive.
        return await _run_sync_in_thread()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _run_sync_in_thread() -> GitHubSyncResult:
    result_box: dict[str, object] = {}

    def run() -> None:
        with github_sync_lock:
            try:
                result = sync_github_pull_requests(store)
            except Exception as exc:
                result_box["error"] = exc
            else:
                result_box["result"] = result

    threading.Thread(target=run, name="mergeops-github-sync", daemon=True).start()
    while "result" not in result_box and "error" not in result_box:
        await asyncio.sleep(0.01)
    if "error" in result_box:
        raise result_box["error"]  # type: ignore[misc]
    return result_box["result"]  # type: ignore[return-value]


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

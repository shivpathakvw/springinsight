"""SpringInsight Web Application — FastAPI backend."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..agents.registry import AGENT_REGISTRY, get_enabled_agents
from ..agents.runner import run_agent_async

def get_agent_registry():
    return AGENT_REGISTRY
from ..agents.config import (
    get_agents_with_config,
    load_agent_config,
    save_agent_config,
    is_agent_enabled,
)
from ..context.loader import ProjectContext, load_context
from ..context.global_context import (
    load_global_context,
    save_global_context,
    load_effective_context,
    DEFAULT_GLOBAL_CONTEXT,
)
from ..db.database import get_db, init_db
from ..db.models import AgentRun, Finding, Run
from ..utils.env import load_env
from ..utils.github import resolve_project_path
from ..github.config import (
    load_github_config,
    save_github_config,
    add_watched_repo,
    remove_watched_repo,
    get_github_token,
)
from ..github.pr_scanner import verify_token, parse_pr_url, scan_pr as github_scan_pr, start_poller
from .scanner import (
    ScanState, _active_scans, run_scan_background,
    BatchScanState, _active_batch_scans, run_batch_scan_background,
)
from ..utils.cost_estimator import count_project_files, estimate_scan_cost, select_agents_within_budget
from ..utils.batch_scanner import (
    detect_large_project, create_batch_plan, LARGE_PROJECT_THRESHOLD,
)
from ..rag.indexer import Indexer as RagIndexer
from ..rag.searcher import Searcher as RagSearcher
from ..springteam.orchestrator import get_orchestrator
from ..springteam.models import SpringTeamDB, ALL_SKILLS

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _data_dir() -> Path:
    env = os.environ.get("SPRINGINSIGHT_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # Use the same global directory as the CLI so both share the same database
    return Path.home() / ".springinsight"


# ── Application lifespan ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "repos").mkdir(exist_ok=True)
    (data_dir / "runs").mkdir(exist_ok=True)
    load_env(data_dir)
    init_db(data_dir)
    application.state.data_dir = data_dir

    # Start GitHub PR poller in background if token is configured
    token = get_github_token()
    if token:
        import logging
        logging.getLogger(__name__).info("GitHub token found — starting PR poller")
        asyncio.create_task(start_poller(data_dir, web_ui_url="http://localhost:8765"))

    yield


# ── FastAPI instance ───────────────────────────────────────────────────────────

app = FastAPI(
    title="SpringInsight",
    description="Autonomous multi-agent codebase intelligence for Java / Spring Boot",
    version="0.3.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── Template helpers ──────────────────────────────────────────────────────────

def _score_color(score: Optional[float]) -> str:
    if score is None:
        return "gray"
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"


templates.env.globals["score_color"] = _score_color


# ── UI Routes ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Dashboard — recent scans + new scan form."""
    runs: list[Run] = []
    run_finding_counts: dict[str, int] = {}

    try:
        from sqlalchemy import func as sqlfunc
        with get_db() as db:
            runs = db.query(Run).order_by(Run.started_at.desc()).limit(20).all()
            # Compute findings counts BEFORE expunge to avoid lazy-load crash
            for r in runs:
                cnt = db.query(sqlfunc.count(Finding.id)).filter(
                    Finding.run_id == r.id
                ).scalar() or 0
                run_finding_counts[r.id] = cnt
            db.expunge_all()
    except Exception:
        pass

    live_runs = [
        s for s in _active_scans.values()
        if s.status in ("pending", "running")
    ]

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "db_runs": runs,
            "live_runs": live_runs,
            "run_finding_counts": run_finding_counts,
        },
    )


@app.get("/scans/{run_id}", response_class=HTMLResponse)
async def scan_live(request: Request, run_id: str):
    state = _active_scans.get(run_id)
    if state and state.status in ("pending", "running"):
        return templates.TemplateResponse(
            request,
            "run.html",
            {"run_id": run_id, "initial_state": state.to_dict()},
        )
    return RedirectResponse(f"/scans/{run_id}/report", status_code=302)


@app.get("/scans/{run_id}/report", response_class=HTMLResponse)
async def scan_report(request: Request, run_id: str):
    state = _active_scans.get(run_id)
    if state and state.status in ("pending", "running"):
        return RedirectResponse(f"/scans/{run_id}", status_code=302)

    try:
        with get_db() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            agent_runs = db.query(AgentRun).filter(AgentRun.run_id == run_id).all()
            findings = (
                db.query(Finding)
                .filter(Finding.run_id == run_id)
                .order_by(Finding.severity)
                .all()
            )
            db.expunge_all()
    except HTTPException:
        raise
    except Exception as exc:
        if state:
            return templates.TemplateResponse(
                request,
                "run.html",
                {"run_id": run_id, "initial_state": state.to_dict()},
            )
        raise HTTPException(status_code=404, detail="Run not found") from exc

    from collections import Counter
    severity_counts = Counter(f.severity for f in findings)

    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "run": run,
            "agent_runs": agent_runs,
            "findings": findings,
            "severity_counts": dict(severity_counts),
            "severity_order": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"],
        },
    )


# ── Agent Configuration UI ────────────────────────────────────────────────────

@app.get("/settings/agents", response_class=HTMLResponse)
async def settings_agents(request: Request):
    """Agent enable/disable configuration page."""
    agents_with_config = get_agents_with_config()

    # Compute cost estimates per model tier
    # Sonnet: ~$3/$15 per M tokens, Haiku: ~$0.25/$1.25, Opus: ~$15/$75
    model_cost_label = {
        "haiku": "~$0.03 avg",
        "sonnet": "~$0.25 avg",
        "opus": "~$1.50 avg",
    }

    for a in agents_with_config:
        model_key = "haiku"
        if "haiku" in a["model"]:
            model_key = "haiku"
        elif "sonnet" in a["model"]:
            model_key = "sonnet"
        elif "opus" in a["model"]:
            model_key = "opus"
        a["cost_label"] = model_cost_label.get(model_key, "")
        a["model_short"] = model_key.capitalize()

    # Current config (for JS initialisation)
    current_config = load_agent_config()
    # Fill in defaults for all agents
    full_config = {a["id"]: current_config.get(a["id"], True) for a in agents_with_config}

    return templates.TemplateResponse(
        request,
        "agents.html",
        {"agents": agents_with_config, "config_json": full_config},
    )


# ── JSON API Routes ───────────────────────────────────────────────────────────

@app.post("/api/scan")
async def api_start_scan(request: Request):
    """Start a new scan.

    Accepts JSON:
      {
        repo_url: str,
        agents?: "all" | list[str],
        budget?: float,          # max USD spend — auto-selects cheapest agents
        budget_strategy?: "value" | "security" | "phase1",
        use_scope?: bool,        # agent-specific file filtering (default: true)
        use_incremental?: bool,  # skip unchanged files (default: true)
        max_files?: int | null,  # override per-agent file cap
      }
    """
    body = await request.json()
    repo_url: str = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)

    requested_agents: str | list = body.get("agents", "all")
    branch: str | None = body.get("branch") or None  # e.g. "main", "feature/xyz"
    budget: float | None = body.get("budget")
    budget_strategy: str = body.get("budget_strategy", "value")
    use_scope: bool = body.get("use_scope", True)
    use_incremental: bool = body.get("use_incremental", True)
    max_files: int | None = body.get("max_files")

    data_dir = request.app.state.data_dir

    try:
        project_path, source_type, source_url = resolve_project_path(repo_url, data_dir, branch=branch)
    except Exception as exc:
        return JSONResponse({"error": f"Cannot resolve project: {exc}"}, status_code=400)

    try:
        ctx = load_context(project_path)
    except Exception:
        ctx = ProjectContext()
        ctx.name = project_path.name
        ctx.base_path = str(project_path)

    # Filter by both requested and enabled-in-config
    agents = get_enabled_agents(requested_agents)
    # Apply user's enable/disable config
    agent_config = load_agent_config()
    if agent_config:
        agents = [a for a in agents if agent_config.get(a.id, True)]

    if not agents:
        return JSONResponse({"error": "No enabled agents found. Check Settings → Agents."}, status_code=400)

    # Apply budget cap — auto-select cheapest agents that fit
    estimate_info: dict = {}
    if budget is not None:
        try:
            java_count, cfg_count = count_project_files(project_path)
            agents, estimate = select_agents_within_budget(
                agents, budget, java_count, cfg_count, strategy=budget_strategy
            )
            if not agents:
                return JSONResponse(
                    {"error": f"Budget ${budget:.2f} is too low to run any agents."},
                    status_code=400,
                )
            estimate_info = {
                "total_usd": estimate.total_usd,
                "agents_selected": len(agents),
                "java_files": java_count,
            }
        except Exception:
            pass  # Don't block scan if estimation fails

    run_id = uuid.uuid4().hex[:8]

    try:
        with get_db() as db:
            run = Run(
                id=run_id,
                project_name=ctx.name,
                project_path=str(project_path),
                source_type=source_type,
                source_url=source_url,
                status="running",
                agents_requested=[a.id for a in agents],
                agents_completed=[],
                git_branch=branch or ctx.name,
            )
            db.add(run)
    except Exception:
        pass

    state = ScanState(
        run_id=run_id,
        repo_url=repo_url,
        project_name=ctx.name,
        agents={a.id: "pending" for a in agents},
        agent_names={a.id: a.name for a in agents},
        agent_models={a.id: a.model for a in agents},
    )
    _active_scans[run_id] = state

    asyncio.create_task(
        run_scan_background(
            state, ctx, project_path, data_dir, agents,
            use_file_scope=use_scope,
            use_incremental=use_incremental,
            max_files=max_files,
        )
    )

    response_body = {
        "run_id": run_id,
        "project_name": ctx.name,
        "branch": branch,
        "agents": [a.id for a in agents],
        "redirect": f"/scans/{run_id}",
    }
    if estimate_info:
        response_body["estimate"] = estimate_info

    return JSONResponse(response_body)


@app.post("/api/scan/analyze")
async def api_scan_analyze(request: Request):
    """Analyze a project and return large-project / batch info before starting a scan.

    Accepts JSON: {repo_url: str}
    Returns: {is_large, java_files, threshold, batch_plan?}
    """
    body = await request.json()
    repo_url: str = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)

    data_dir = request.app.state.data_dir
    try:
        project_path, _, _ = resolve_project_path(repo_url, data_dir)
    except Exception:
        # If we can't resolve the path (e.g. GitHub URL not yet cloned),
        # return a benign "not large" response so the UI stays clean.
        return JSONResponse({
            "is_large": False,
            "java_files": 0,
            "threshold": LARGE_PROJECT_THRESHOLD,
            "note": "project not yet available locally",
        })

    if not project_path.exists():
        return JSONResponse({
            "is_large": False,
            "java_files": 0,
            "threshold": LARGE_PROJECT_THRESHOLD,
        })

    is_large, java_count = detect_large_project(project_path)
    result: dict = {
        "is_large": is_large,
        "java_files": java_count,
        "threshold": LARGE_PROJECT_THRESHOLD,
    }
    if is_large:
        try:
            plan = create_batch_plan(project_path)
            result["batch_plan"] = plan.to_dict()
        except Exception as exc:
            logger.warning("Batch plan failed: %s", exc)

    return JSONResponse(result)


@app.post("/api/scan/batch")
async def api_start_batch_scan(request: Request):
    """Start a batched scan of a large project.

    Accepts JSON: {repo_url, batch_size?, use_scope?, use_incremental?}
    Returns: {batch_scan_id, batch_count, redirect}
    """
    body = await request.json()
    repo_url: str = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)

    use_scope: bool = body.get("use_scope", True)
    use_incremental: bool = body.get("use_incremental", True)
    batch_size: int = int(body.get("batch_size", 150))
    branch: str | None = body.get("branch") or None

    data_dir = request.app.state.data_dir
    try:
        project_path, source_type, source_url = resolve_project_path(repo_url, data_dir, branch=branch)
    except Exception as exc:
        return JSONResponse({"error": f"Cannot resolve project: {exc}"}, status_code=400)

    try:
        ctx = load_context(project_path)
    except Exception:
        ctx = ProjectContext()
        ctx.name = project_path.name
        ctx.base_path = str(project_path)

    agents = get_enabled_agents("all")
    agent_config = load_agent_config()
    if agent_config:
        agents = [a for a in agents if agent_config.get(a.id, True)]
    if not agents:
        return JSONResponse({"error": "No enabled agents."}, status_code=400)

    # Create batch plan
    try:
        plan = create_batch_plan(project_path, batch_size=batch_size)
    except Exception as exc:
        return JSONResponse({"error": f"Batch planning failed: {exc}"}, status_code=500)

    batch_scan_id = uuid.uuid4().hex[:8]

    batch_state = BatchScanState(
        batch_scan_id=batch_scan_id,
        project_name=ctx.name,
        repo_url=repo_url,
        total_java_files=plan.total_java_files,
        batches=plan.to_dict()["batches"],
        strategy=plan.strategy,
    )
    _active_batch_scans[batch_scan_id] = batch_state

    asyncio.create_task(
        run_batch_scan_background(
            batch_state, ctx, project_path, data_dir, agents,
            use_file_scope=use_scope,
            use_incremental=use_incremental,
        )
    )

    return JSONResponse({
        "batch_scan_id": batch_scan_id,
        "project_name": ctx.name,
        "batch_count": plan.batch_count,
        "total_java_files": plan.total_java_files,
        "strategy": plan.strategy,
        "redirect": f"/scans/batch/{batch_scan_id}",
    })


@app.get("/scans/batch/{batch_scan_id}", response_class=HTMLResponse)
async def batch_scan_view(request: Request, batch_scan_id: str):
    """Live progress page for a batch scan."""
    batch_state = _active_batch_scans.get(batch_scan_id)
    if not batch_state:
        raise HTTPException(status_code=404, detail="Batch scan not found")
    return templates.TemplateResponse(
        request,
        "batch_run.html",
        {
            "batch_scan_id": batch_scan_id,
            "initial_state": batch_state.to_dict(),
        },
    )


@app.get("/api/batch-scans/{batch_scan_id}")
async def api_get_batch_scan(batch_scan_id: str, request: Request):
    batch_state = _active_batch_scans.get(batch_scan_id)
    if not batch_state:
        raise HTTPException(status_code=404, detail="Batch scan not found")
    return JSONResponse(batch_state.to_dict())


@app.get("/api/batch-scans/{batch_scan_id}/stream")
async def api_batch_scan_stream(batch_scan_id: str, request: Request):
    """SSE stream for a batch scan — replays history then live events."""
    batch_state = _active_batch_scans.get(batch_scan_id)
    if not batch_state:
        raise HTTPException(status_code=404, detail="Batch scan not found")

    queue = batch_state.subscribe()

    async def _event_gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") == "batch_complete":
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            batch_state.unsubscribe(queue)

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/scan/estimate")
async def api_scan_estimate(request: Request):
    """Estimate scan cost for a project without starting a scan.

    Accepts JSON: {repo_url: str, agents?: "all" | list[str]}
    Returns a per-agent cost breakdown and total.
    """
    body = await request.json()
    repo_url: str = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)

    requested_agents: str | list = body.get("agents", "all")
    data_dir = request.app.state.data_dir

    try:
        project_path, _, _ = resolve_project_path(repo_url, data_dir)
    except Exception as exc:
        return JSONResponse({"error": f"Cannot resolve project: {exc}"}, status_code=400)

    agents = get_enabled_agents(requested_agents)
    agent_config = load_agent_config()
    if agent_config:
        agents = [a for a in agents if agent_config.get(a.id, True)]

    if not agents:
        return JSONResponse({"error": "No enabled agents."}, status_code=400)

    try:
        java_count, cfg_count = count_project_files(project_path)
    except Exception:
        java_count, cfg_count = 0, 5

    estimate = estimate_scan_cost(agents, java_count, cfg_count)

    return JSONResponse({
        "total_usd": estimate.total_usd,
        "java_files": java_count,
        "config_files": cfg_count,
        "agent_count": estimate.agent_count,
        "breakdown": estimate.breakdown,
        "per_agent": [
            {
                "id": a.id,
                "name": a.name,
                "model": a.model,
                "phase": a.phase,
                "cost_usd": estimate.per_agent.get(a.id, 0.0),
            }
            for a in agents
        ],
    })


@app.post("/api/settings/agents")
async def api_save_agent_config(request: Request):
    """Save agent enabled/disabled config. Body: {agent_id: bool, ...}"""
    body = await request.json()
    # Validate — only known agents
    valid = {aid: bool(v) for aid, v in body.items() if aid in AGENT_REGISTRY}
    save_agent_config(valid)
    return JSONResponse({"saved": len(valid), "config": valid})


@app.get("/api/runs")
async def api_list_runs(request: Request, limit: int = 20):
    rows = []
    try:
        from sqlalchemy import func as sqlfunc
        with get_db() as db:
            runs = db.query(Run).order_by(Run.started_at.desc()).limit(limit).all()
            for r in runs:
                cnt = db.query(sqlfunc.count(Finding.id)).filter(
                    Finding.run_id == r.id
                ).scalar() or 0
                rows.append(
                    {
                        "id": r.id,
                        "project_name": r.project_name,
                        "status": r.status,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "score_overall": r.score_overall,
                        "source_url": r.source_url,
                        "findings_count": cnt,
                    }
                )
    except Exception:
        pass

    for s in _active_scans.values():
        if not any(r["id"] == s.run_id for r in rows):
            rows.insert(
                0,
                {
                    "id": s.run_id,
                    "project_name": s.project_name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "score_overall": None,
                    "source_url": s.repo_url,
                    "findings_count": s.findings_count,
                },
            )
    return JSONResponse(rows)


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str, request: Request):
    state = _active_scans.get(run_id)
    if state:
        return JSONResponse(state.to_dict())

    try:
        with get_db() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            return JSONResponse(
                {
                    "run_id": run.id,
                    "project_name": run.project_name,
                    "status": run.status,
                    "scores": {
                        "overall": run.score_overall,
                        "security": run.score_security,
                        "code_quality": run.score_code_quality,
                        "architecture": run.score_architecture,
                    },
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                }
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/findings")
async def api_get_findings(
    run_id: str,
    request: Request,
    severity: Optional[str] = None,
    agent: Optional[str] = None,
):
    try:
        with get_db() as db:
            q = db.query(Finding).filter(Finding.run_id == run_id)
            if severity:
                q = q.filter(Finding.severity == severity.upper())
            if agent:
                q = q.filter(Finding.agent_id == agent.upper())
            findings = q.order_by(Finding.severity).all()
            data = [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "category": f.category,
                    "file": f.file_path,
                    "line": f.line_number,
                    "problem": f.problem,
                    "fix": f.fix_description,
                    "agent_id": f.agent_id,
                }
                for f in findings
            ]
    except Exception:
        data = []
    return JSONResponse(data)


@app.get("/api/runs/{run_id}/stream")
async def api_stream_run(run_id: str, request: Request):
    """Server-Sent Events endpoint for live scan progress."""
    state = _active_scans.get(run_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail="Active scan not found. It may have completed — check /api/runs/{run_id}",
        )

    q = state.subscribe()

    async def _event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("run_complete", "scan_failed"):
                        break
                except asyncio.TimeoutError:
                    yield 'data: {"type":"heartbeat"}\n\n'
        finally:
            state.unsubscribe(q)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.5.0"}


# ── Reverse Engineering ───────────────────────────────────────────────────────

@app.get("/reverse", response_class=HTMLResponse)
async def reverse_page(request: Request):
    """Reverse Engineering UI — A18 agent launcher."""
    return templates.TemplateResponse(request, "reverse.html", {})


# ── CodeSearch (Pillar 2 RAG) ─────────────────────────────────────────────────

def _rag_indexer(data_dir: Path) -> RagIndexer:
    return RagIndexer(
        db_path=str(data_dir / "springinsight.db"),
        chroma_dir=str(data_dir / "chroma"),
    )

def _rag_searcher(data_dir: Path) -> RagSearcher:
    return RagSearcher(
        db_path=str(data_dir / "springinsight.db"),
        chroma_dir=str(data_dir / "chroma"),
    )


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    """CodeSearch UI — semantic natural-language search over a Spring Boot codebase."""
    return templates.TemplateResponse(request, "search.html", {})


@app.get("/api/search/status")
async def api_search_status(project_path: str = ""):
    """Return indexing status for a project."""
    data_dir = _data_dir()
    indexer = _rag_indexer(data_dir)
    resolved = str(Path(project_path).resolve()) if project_path else ""
    if not resolved:
        return {"status": "no_project"}
    status = indexer.get_status(resolved)
    return status


@app.get("/api/search/index")
async def api_search_index(request: Request):
    """
    SSE stream: index a project.
    Query params: repo_url (git URL or local path)
    Events: { "type": "progress", "data": {...} }
             { "type": "done", "data": {...} }
             { "type": "error", "data": {"message": "..."} }
    """
    repo_url = request.query_params.get("repo_url", "").strip()
    if not repo_url:
        async def _err():
            yield "data: " + '{"type":"error","data":{"message":"repo_url is required"}}\n\n'
        return StreamingResponse(_err(), media_type="text/event-stream")

    data_dir = _data_dir()

    async def _event_gen():
        import json as _json
        from ..utils.github import resolve_project_path as _resolve

        try:
            # Resolve repo (clone if git URL, resolve if local path)
            project_path = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _resolve(repo_url, str(data_dir / "repos"))
            )
        except Exception as e:
            yield f"data: {_json.dumps({'type':'error','data':{'message':str(e)}})}\n\n"
            return

        indexer = _rag_indexer(data_dir)
        try:
            async for progress in indexer.index(project_path):
                payload = _json.dumps({
                    "type": "done" if progress.phase == "done" else
                            "error" if progress.phase == "error" else "progress",
                    "data": progress.to_dict(),
                })
                yield f"data: {payload}\n\n"
                if progress.phase in ("done", "error"):
                    return
        except Exception as e:
            import traceback
            yield f"data: {_json.dumps({'type':'error','data':{'message':str(e)}})}\n\n"

    return StreamingResponse(_event_gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.get("/api/search/ask")
async def api_search_ask(request: Request):
    """
    SSE stream: semantic search + Claude answer.
    Query params: project_path, query
    Events:
      data: {"type":"sources","data":[...]}
      data: {"type":"token","data":"<text>"}
      data: {"type":"done"}
      data: {"type":"error","data":{"message":"..."}}
    """
    project_path = request.query_params.get("project_path", "").strip()
    query = request.query_params.get("query", "").strip()

    if not query:
        async def _err():
            import json as _j
            yield f"data: {_j.dumps({'type':'error','data':{'message':'query is required'}})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    data_dir = _data_dir()
    if not project_path:
        project_path = str(data_dir)

    async def _event_gen():
        import json as _json
        searcher = _rag_searcher(data_dir)
        try:
            async for token in searcher.stream_search(project_path, query):
                if token.startswith("sources:"):
                    sources_json = token[len("sources:"):]
                    yield f"data: {_json.dumps({'type':'sources','data':_json.loads(sources_json)})}\n\n"
                elif token == "DONE":
                    yield f"data: {_json.dumps({'type':'done'})}\n\n"
                    return
                elif token.startswith("ERROR:"):
                    msg = token[6:]
                    yield f"data: {_json.dumps({'type':'error','data':{'message':msg}})}\n\n"
                    return
                else:
                    yield f"data: {_json.dumps({'type':'token','data':token})}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'type':'error','data':{'message':str(e)}})}\n\n"

    return StreamingResponse(_event_gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.get("/api/search/graph/{fqn:path}")
async def api_search_graph(fqn: str, project_path: str = ""):
    """Return a node + its direct neighbours from the code graph."""
    data_dir = _data_dir()
    from ..rag.code_graph import CodeGraph
    graph = CodeGraph(str(data_dir / "springinsight.db"))
    resolved = str(Path(project_path).resolve()) if project_path else ""
    if resolved:
        nodes = graph.search_by_name(resolved, fqn.split(".")[-1])
        if nodes:
            node = nodes[0]
            neighbours = graph.get_neighbours(node["id"], depth=1)
            return {"node": node, "neighbours": neighbours}
    return {"node": None, "neighbours": []}


# ── SpringTeam (Pillar 3 Multi-Agent Task Framework) ──────────────────────────

def _team_db(data_dir: Path) -> SpringTeamDB:
    return SpringTeamDB(str(data_dir / "springinsight.db"))

def _team_orch(data_dir: Path):
    return get_orchestrator(str(data_dir / "springinsight.db"))


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    """SpringTeam Kanban board."""
    return templates.TemplateResponse(request, "tasks.html", {})


@app.get("/api/team/tasks")
async def api_team_tasks(project_path: str = ""):
    """Return all tasks grouped by status for the Kanban view."""
    data_dir = _data_dir()
    db = _team_db(data_dir)
    resolved = str(Path(project_path).resolve()) if project_path else str(data_dir)
    grouped = db.list_all_tasks(resolved)
    stats = db.get_project_stats(resolved)
    return {"tasks": grouped, "stats": stats}


@app.post("/api/team/tasks")
async def api_create_task(request: Request):
    """Create a new task, optionally auto-routing to the right agent."""
    import json as _json
    data_dir = _data_dir()
    body = await request.json()
    project_path = body.get("project_path") or str(data_dir)
    description  = body.get("description", "").strip()
    skill        = body.get("skill") or None
    priority     = int(body.get("priority", 5))
    context      = body.get("context") or {}

    if not description:
        return {"error": "description is required"}, 400

    orch = _team_orch(data_dir)
    orch.project_path = str(Path(project_path).resolve())
    task_id = await orch.submit(
        request=description,
        project_path=project_path,
        skill=skill,
        priority=priority,
        context=context,
    )
    return {"task_id": task_id, "task": orch.db.get_task(task_id)}


@app.get("/api/team/tasks/{task_id}")
async def api_get_task(task_id: str):
    """Get task detail including messages and output."""
    data_dir = _data_dir()
    db = _team_db(data_dir)
    task = db.get_task(task_id)
    if not task:
        return {"error": "not found"}
    messages = db.get_messages(task_id)
    return {"task": task, "messages": messages}


@app.post("/api/team/tasks/{task_id}/approve")
async def api_approve_task(task_id: str):
    data_dir = _data_dir()
    orch = _team_orch(data_dir)
    ok = orch.approve_task(task_id)
    return {"ok": ok}


@app.post("/api/team/tasks/{task_id}/reject")
async def api_reject_task(task_id: str, request: Request):
    data_dir = _data_dir()
    body = await request.json()
    feedback = body.get("feedback", "")
    orch = _team_orch(data_dir)
    ok = orch.reject_task(task_id, feedback)
    return {"ok": ok}


@app.delete("/api/team/tasks/{task_id}")
async def api_delete_task(task_id: str):
    data_dir = _data_dir()
    db = _team_db(data_dir)
    db.delete_task(task_id)
    return {"ok": True}


@app.post("/api/team/start")
async def api_team_start(request: Request):
    """Start agent workers for a project."""
    body = await request.json()
    data_dir = _data_dir()
    project_path = body.get("project_path") or str(data_dir)
    skills = body.get("skills") or ALL_SKILLS
    orch = _team_orch(data_dir)
    await orch.start(project_path=project_path, skills=skills)
    return {"ok": True, "agents": skills}


@app.post("/api/team/stop")
async def api_team_stop():
    """Stop all agent workers."""
    data_dir = _data_dir()
    orch = _team_orch(data_dir)
    await orch.stop()
    return {"ok": True}


@app.get("/api/team/agents")
async def api_team_agents():
    """Return current agent status."""
    data_dir = _data_dir()
    db = _team_db(data_dir)
    return {"agents": db.get_agents()}


@app.get("/api/team/activity")
async def api_team_activity(project_path: str = "", limit: int = 30):
    """Return recent activity feed."""
    data_dir = _data_dir()
    db = _team_db(data_dir)
    resolved = str(Path(project_path).resolve()) if project_path else str(data_dir)
    activity = db.get_recent_activity(resolved, limit=limit)
    return {"activity": activity}


@app.get("/api/team/stream")
async def api_team_stream(request: Request):
    """
    SSE stream for live Kanban updates.
    Events: task_created, task_updated, task_log, message, system
    """
    data_dir = _data_dir()
    orch = _team_orch(data_dir)

    async def _event_gen():
        import json as _json
        q = orch.subscribe()
        try:
            # Send initial state
            project_path = request.query_params.get("project_path", "")
            resolved = str(Path(project_path).resolve()) if project_path else str(data_dir)
            db = _team_db(data_dir)
            grouped = db.list_all_tasks(resolved)
            stats = db.get_project_stats(resolved)
            yield f"event: init\ndata: {_json.dumps({'tasks': grouped, 'stats': stats})}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: {event['type']}\ndata: {_json.dumps(event['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {{}}\n\n"
        finally:
            orch.unsubscribe(q)

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── Settings: Project Context ─────────────────────────────────────────────────

@app.get("/settings/context", response_class=HTMLResponse)
async def settings_context(request: Request):
    """Global project context configuration page."""
    ctx = load_global_context()
    return templates.TemplateResponse(
        request, "context.html", {"context_json": ctx}
    )


@app.post("/api/settings/context")
async def api_save_context(request: Request):
    """Save global project context. Body: full context dict."""
    body = await request.json()
    save_global_context(body)
    return JSONResponse({"saved": True})


@app.post("/api/settings/context/reset")
async def api_reset_context(request: Request):
    """Reset global context to defaults."""
    save_global_context(DEFAULT_GLOBAL_CONTEXT.copy())
    return JSONResponse({"reset": True})


@app.get("/api/settings/context")
async def api_get_context(request: Request):
    """Return current global context as JSON."""
    return JSONResponse(load_global_context())


# ── Settings: GitHub PR Integration ───────────────────────────────────────────

@app.get("/settings/github", response_class=HTMLResponse)
async def settings_github(request: Request):
    """GitHub PR integration configuration page."""
    cfg = load_github_config()
    return templates.TemplateResponse(
        request, "github.html", {"config_json": cfg}
    )


@app.get("/api/settings/github/status")
async def api_github_status(request: Request):
    """Return whether a GitHub token is configured (used by dashboard)."""
    cfg = load_github_config()
    token = cfg.get("github_token")
    return JSONResponse({
        "connected": bool(token),
        "github_user": cfg.get("github_user"),
        "watched_repos": len(cfg.get("watched_repos", [])),
    })


@app.post("/api/settings/github/connect")
async def api_github_connect(request: Request):
    """Verify and save a GitHub token."""
    body = await request.json()
    token = body.get("token", "").strip()
    if not token:
        return JSONResponse({"error": "token is required"}, status_code=400)

    try:
        user_info = await verify_token(token)
    except Exception as exc:
        return JSONResponse({"error": f"Token verification failed: {exc}"}, status_code=400)

    cfg = load_github_config()
    cfg["token"] = token
    cfg["github_user"] = user_info.get("login", "")
    cfg["connected"] = True
    save_github_config(cfg)

    # Start poller if not already running
    data_dir = request.app.state.data_dir
    asyncio.create_task(start_poller(data_dir))

    return JSONResponse({"github_user": cfg["github_user"], "connected": True})


@app.post("/api/settings/github/disconnect")
async def api_github_disconnect(request: Request):
    """Remove GitHub token."""
    cfg = load_github_config()
    cfg["token"] = ""
    cfg["github_user"] = ""
    cfg["connected"] = False
    save_github_config(cfg)
    return JSONResponse({"disconnected": True})


@app.post("/api/settings/github/repos")
async def api_github_add_repo(request: Request):
    """Add a repo to the watched list."""
    body = await request.json()
    repo = body.get("repo", "").strip()
    if not repo or "/" not in repo:
        return JSONResponse({"error": "repo must be owner/name format"}, status_code=400)
    updated = add_watched_repo(repo)
    return JSONResponse({"watched_repos": updated})


@app.delete("/api/settings/github/repos/{full_name:path}")
async def api_github_remove_repo(full_name: str, request: Request):
    """Remove a repo from the watched list."""
    remove_watched_repo(full_name)
    return JSONResponse({"removed": full_name})


@app.post("/api/settings/github")
async def api_save_github_settings(request: Request):
    """Save GitHub polling/comment settings."""
    body = await request.json()
    cfg = load_github_config()
    cfg.update({
        "poll_interval_minutes": body.get("poll_interval_minutes", 5),
        "comment_threshold": body.get("comment_threshold", "MEDIUM"),
        "auto_comment": body.get("auto_comment", True),
        "fail_pr_on_critical": body.get("fail_pr_on_critical", False),
    })
    save_github_config(cfg)
    return JSONResponse({"saved": True})


@app.post("/api/github/scan-pr")
async def api_scan_pr(request: Request):
    """Trigger an immediate scan for a specific GitHub PR URL.

    Accepts JSON: {pr_url: str}

    Returns {run_id, pr_number, pr_title, head_ref, java_files, redirect}
    so the caller can redirect straight to the live scan page.
    """
    body = await request.json()
    pr_url = body.get("pr_url", "").strip()
    if not pr_url:
        return JSONResponse({"error": "pr_url is required"}, status_code=400)

    parsed = parse_pr_url(pr_url)
    if not parsed:
        return JSONResponse({"error": "Invalid GitHub PR URL. Expected: https://github.com/owner/repo/pull/123"}, status_code=400)

    full_name, pr_number = parsed
    token = get_github_token()
    if not token:
        return JSONResponse(
            {"error": "GitHub not connected — add your token in Settings → GitHub PR first"},
            status_code=400,
        )

    from ..github.pr_scanner import get_pr_changed_files
    import httpx

    # Fetch PR metadata directly (supports open AND closed/merged PRs)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{full_name}/pulls/{pr_number}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if resp.status_code == 404:
                return JSONResponse({"error": f"PR #{pr_number} not found in {full_name}"}, status_code=404)
            resp.raise_for_status()
            pr = resp.json()
    except httpx.HTTPStatusError as exc:
        return JSONResponse({"error": f"GitHub API error: {exc.response.status_code}"}, status_code=500)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    head_sha = pr["head"]["sha"]
    head_ref = pr["head"]["ref"]
    clone_url = pr["head"]["repo"]["clone_url"]
    pr_title = pr.get("title", f"PR #{pr_number}")

    try:
        changed_files_info = await get_pr_changed_files(token, full_name, pr_number)
        # changed_files_info is a list of dicts with keys: filename, status, additions, etc.
        java_files = [
            f["filename"] for f in changed_files_info
            if isinstance(f, dict) and f.get("filename", "").endswith(".java")
            and f.get("status") != "removed"
        ]
    except Exception as exc:
        return JSONResponse({"error": f"Could not fetch changed files: {exc}"}, status_code=500)

    data_dir = request.app.state.data_dir
    run_id = await github_scan_pr(
        full_name=full_name,
        pr_number=pr_number,
        head_sha=head_sha,
        clone_url=clone_url,
        head_ref=head_ref,
        changed_java_files=java_files,
        data_dir=data_dir,
    )

    if not run_id:
        return JSONResponse({"error": "Failed to start PR scan"}, status_code=500)

    return JSONResponse({
        "run_id": run_id,
        "pr_number": pr_number,
        "pr_title": pr_title,
        "head_ref": head_ref,
        "java_files": len(java_files),
        "redirect": f"/scans/{run_id}",
    })


# ── PDF Export ────────────────────────────────────────────────────────────────

@app.get("/api/runs/{run_id}/export/pdf")
async def export_run_pdf(run_id: str, request: Request):
    """Generate and return a PDF report for a completed scan run."""
    try:
        with get_db() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")

            findings = db.query(Finding).filter(Finding.run_id == run_id)\
                .order_by(Finding.severity).all()
            agent_runs = db.query(AgentRun).filter(AgentRun.run_id == run_id).all()

            # Eagerly load everything we need before session closes
            run_data = {
                "id": run.id,
                "project_name": run.project_name,
                "status": run.status,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "duration_seconds": run.duration_seconds,
                "git_branch": run.git_branch,
                "git_commit": run.git_commit,
                "score_overall": run.score_overall,
                "score_security": run.score_security,
                "score_code_quality": run.score_code_quality,
                "score_architecture": run.score_architecture,
                "score_api_design": run.score_api_design,
                "score_production_readiness": run.score_production_readiness,
                "score_test_coverage": run.score_test_coverage,
            }

            findings_data = [
                type("F", (), {
                    "severity": f.severity,
                    "category": f.category,
                    "subcategory": f.subcategory,
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                    "method_name": f.method_name,
                    "problem": f.problem,
                    "fix_description": f.fix_description,
                    "fix_code": f.fix_code,
                    "cve_ids": f.cve_ids or [],
                    "agent_id": f.agent_id,
                })()
                for f in findings
            ]

            agent_runs_data = [
                type("AR", (), {
                    "agent_id": ar.agent_id,
                    "agent_name": ar.agent_name,
                    "model": ar.model,
                    "status": ar.status,
                    "findings_count": ar.findings_count,
                    "duration_seconds": ar.duration_seconds,
                })()
                for ar in agent_runs
            ]

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Build a simple proxy object for the PDF generator
    run_obj = type("Run", (), run_data)()

    try:
        from ..utils.pdf_export import generate_pdf_report
        pdf_bytes = generate_pdf_report(run_obj, findings_data, agent_runs_data)
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="PDF export requires reportlab. Install: pip install reportlab"
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc

    filename = f"springinsight-{run_obj.project_name}-{run_id[:8]}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Reverse Engineering (A18) ─────────────────────────────────────────────────

@app.get("/api/reverse/run")
async def reverse_run_stream(
    repo_url: str,
    mode: str = "high-level",
    focus: str = "",
    request: Request = None,
):
    """Stream A18 reverse engineering agent execution via SSE."""
    import uuid as _uuid
    from datetime import datetime as _dt

    if mode not in ("high-level", "in-depth"):
        return JSONResponse({"error": "mode must be high-level or in-depth"}, status_code=400)

    async def _event_stream():
        run_id = None
        try:
            work_path = get_data_dir()
            ctx = load_global_context()

            # Resolve project
            try:
                project_path, source_type, source_url = resolve_project_path(repo_url, work_path)
            except Exception as e:
                yield f"event: failed\ndata: {json.dumps({'error': str(e)})}\n\n"
                return

            yield f"event: log\ndata: {json.dumps({'message': f'Project resolved: {project_path.name}'})}\n\n"
            yield f"event: log\ndata: {json.dumps({'message': f'Mode: {mode}' + (f' | Target: {focus}' if focus else '')})}\n\n"

            # Build run
            short_id = str(_uuid.uuid4())[:8]
            full_run_id = f"{_dt.utcnow().strftime('%Y-%m-%d')}-{short_id}"
            run_dir = work_path / ".springinsight" / "runs" / full_run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            run_id = full_run_id

            # Init DB and create run record
            init_db(work_path)
            with get_db() as db:
                db.add(Run(
                    id=full_run_id,
                    project_name=ctx.name,
                    project_path=str(project_path),
                    source_type=source_type,
                    source_url=source_url,
                    agents_requested=["A18"],
                    context_snapshot=ctx._raw,
                ))

            agent = get_agent_registry().get("A18")
            if not agent:
                yield f"event: failed\ndata: {json.dumps({'error': 'A18 agent not found in registry'})}\n\n"
                return

            # Build extra_scope with mode + focus
            focus_line = f"REVERSE_TARGET  : {focus}" if focus.strip() else "REVERSE_TARGET  : (full project)"
            extra_scope = (
                f"REVERSE_MODE    : {mode}\n"
                f"{focus_line}\n"
                f"EXPECTED_OUTPUT : {'ARCHITECTURE.md' if mode == 'high-level' else 'TECHNICAL-REFERENCE.md'}"
            )

            log_queue: asyncio.Queue = asyncio.Queue()

            def log_cb(agent_id: str, msg: str):
                log_queue.put_nowait(msg)

            # Start agent as background task
            agent_task = asyncio.create_task(
                run_agent_async(
                    agent=agent,
                    ctx=ctx,
                    project_path=str(project_path),
                    run_dir=run_dir,
                    run_id=full_run_id,
                    extra_scope=extra_scope,
                    log_callback=log_cb,
                    use_file_scope=False,
                    use_incremental=False,
                )
            )

            # Stream log messages while agent runs
            while not agent_task.done():
                try:
                    msg = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                    yield f"event: log\ndata: {json.dumps({'message': msg})}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: log\ndata: {json.dumps({'message': 'Analysing…'})}\n\n"

            # Drain remaining logs
            while not log_queue.empty():
                msg = log_queue.get_nowait()
                yield f"event: log\ndata: {json.dumps({'message': msg})}\n\n"

            result = agent_task.result()

            # Persist to DB
            findings = result.get("findings", [])
            with get_db() as db:
                db.add(AgentRun(
                    run_id=full_run_id,
                    agent_id="A18",
                    agent_name=agent.name,
                    model=agent.model,
                    status=result["status"],
                    started_at=result.get("started_at"),
                    completed_at=result.get("completed_at"),
                    findings_count=len(findings),
                    error_message=result.get("error"),
                    output_json_path=result.get("output_json"),
                    output_md_path=result.get("output_md"),
                ))
                for f in findings:
                    db.add(Finding(
                        run_id=full_run_id,
                        agent_id="A18",
                        severity=f.get("severity", "INFO"),
                        category=f.get("category", "Reverse Engineering"),
                        subcategory=f.get("subcategory"),
                        file_path=f.get("file"),
                        line_number=f.get("line"),
                        class_name=f.get("class_name"),
                        method_name=f.get("method_name"),
                        problem=f.get("problem", ""),
                        impact=f.get("impact"),
                        fix_description=f.get("fix"),
                        fix_code=f.get("fix_code"),
                        actionable=f.get("actionable", False),
                        effort_hours=f.get("effort_hours"),
                    ))
                run_rec = db.query(Run).filter(Run.id == full_run_id).first()
                if run_rec:
                    run_rec.completed_at = _dt.utcnow()
                    run_rec.status = "complete" if result["status"] == "complete" else "failed"
                    run_rec.agents_completed = ["A18"] if result["status"] == "complete" else []

            if result["status"] == "failed":
                yield f"event: failed\ndata: {json.dumps({'error': result.get('error', 'unknown'), 'run_id': full_run_id})}\n\n"
            else:
                yield f"event: complete\ndata: {json.dumps({'run_id': full_run_id, 'findings': findings, 'mode': mode})}\n\n"

        except Exception as exc:
            logger.exception("Reverse engineering stream error")
            payload = {"error": str(exc)}
            if run_id:
                payload["run_id"] = run_id
            yield f"event: failed\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

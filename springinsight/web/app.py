"""SpringInsight Web Application — FastAPI backend.

Start with:
    springinsight web --port 8080

Or programmatically:
    import uvicorn
    from springinsight.web.app import app
    uvicorn.run(app, host="0.0.0.0", port=8080)
"""

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
from ..context.loader import ProjectContext, load_context
from ..db.database import get_db, init_db
from ..db.models import AgentRun, Finding, Run
from ..utils.env import load_env
from ..utils.github import resolve_project_path
from .scanner import ScanState, _active_scans, run_scan_background

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _data_dir() -> Path:
    env = os.environ.get("SPRINGINSIGHT_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".springinsight" / "web"


# ── Application lifespan ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "repos").mkdir(exist_ok=True)
    (data_dir / "runs").mkdir(exist_ok=True)
    # Load .env for ANTHROPIC_API_KEY
    load_env(data_dir)
    # Initialize SQLite
    init_db(data_dir)
    application.state.data_dir = data_dir
    yield
    # Cleanup: nothing required


# ── FastAPI instance ───────────────────────────────────────────────────────────

app = FastAPI(
    title="SpringInsight",
    description="Autonomous multi-agent codebase intelligence for Java / Spring Boot",
    version="0.1.0",
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
    try:
        with get_db() as db:
            runs = db.query(Run).order_by(Run.started_at.desc()).limit(20).all()
            db.expunge_all()
    except Exception:
        pass

    # Merge any live scans not yet in DB
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
        },
    )


@app.get("/scans/{run_id}", response_class=HTMLResponse)
async def scan_live(request: Request, run_id: str):
    """Live scan progress page (redirects to report if already done)."""
    state = _active_scans.get(run_id)
    if state and state.status in ("pending", "running"):
        return templates.TemplateResponse(
            request,
            "run.html",
            {"run_id": run_id, "initial_state": state.to_dict()},
        )
    # Already finished — go straight to the report
    return RedirectResponse(f"/scans/{run_id}/report", status_code=302)


@app.get("/scans/{run_id}/report", response_class=HTMLResponse)
async def scan_report(request: Request, run_id: str):
    """Full report page for a completed scan."""
    # Check live state first (may still be running)
    state = _active_scans.get(run_id)
    if state and state.status in ("pending", "running"):
        return RedirectResponse(f"/scans/{run_id}", status_code=302)

    try:
        with get_db() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            agent_runs = (
                db.query(AgentRun).filter(AgentRun.run_id == run_id).all()
            )
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
        # If DB isn't ready yet or scan is very fresh, use in-memory state
        if state:
            return templates.TemplateResponse(
                request,
                "run.html",
                {"run_id": run_id, "initial_state": state.to_dict()},
            )
        raise HTTPException(status_code=404, detail="Run not found") from exc

    # Group findings by severity
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


# ── JSON API Routes ───────────────────────────────────────────────────────────

@app.post("/api/scan")
async def api_start_scan(request: Request):
    """Start a new scan. Accepts JSON: {repo_url, agents?}"""
    body = await request.json()
    repo_url: str = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)

    requested_agents: str | list = body.get("agents", "all")
    data_dir = request.app.state.data_dir

    # Resolve project path (clone GitHub repos automatically)
    try:
        project_path, source_type, source_url = resolve_project_path(
            repo_url, data_dir
        )
    except Exception as exc:
        return JSONResponse({"error": f"Cannot resolve project: {exc}"}, status_code=400)

    # Load or create context
    try:
        ctx = load_context(project_path)
    except Exception:
        ctx = ProjectContext()
        ctx.name = project_path.name
        ctx.base_path = str(project_path)

    # Resolve agents to run
    agents = get_enabled_agents(requested_agents)
    if not agents:
        return JSONResponse({"error": "No enabled agents found"}, status_code=400)

    run_id = uuid.uuid4().hex[:8]

    # Persist initial Run record
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
                git_branch=ctx.name,
            )
            db.add(run)
    except Exception:
        pass  # Non-fatal — we continue with in-memory state

    # Build in-memory scan state
    state = ScanState(
        run_id=run_id,
        repo_url=repo_url,
        project_name=ctx.name,
        agents={a.id: "pending" for a in agents},
        agent_names={a.id: a.name for a in agents},
        agent_models={a.id: a.model for a in agents},
    )
    _active_scans[run_id] = state

    # Launch background coroutine (fire and forget)
    asyncio.create_task(
        run_scan_background(state, ctx, project_path, data_dir, agents)
    )

    return JSONResponse(
        {
            "run_id": run_id,
            "project_name": ctx.name,
            "agents": [a.id for a in agents],
            "redirect": f"/scans/{run_id}",
        }
    )


@app.get("/api/runs")
async def api_list_runs(request: Request, limit: int = 20):
    """List recent runs."""
    rows = []
    try:
        with get_db() as db:
            runs = db.query(Run).order_by(Run.started_at.desc()).limit(limit).all()
            for r in runs:
                rows.append(
                    {
                        "id": r.id,
                        "project_name": r.project_name,
                        "status": r.status,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "score_overall": r.score_overall,
                        "source_url": r.source_url,
                    }
                )
    except Exception:
        pass

    # Also include live scans not yet in DB
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
                },
            )
    return JSONResponse(rows)


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str, request: Request):
    """Get live or persisted run state."""
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
    """Get findings for a run with optional filters."""
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
        raise HTTPException(status_code=404, detail="Active scan not found. It may have completed — check /api/runs/{run_id}")

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
                    # Heartbeat keeps the connection alive through proxies
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
    return {"status": "ok", "version": "0.1.0"}

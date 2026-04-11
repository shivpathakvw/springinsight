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
from ..agents.config import (
    get_agents_with_config,
    load_agent_config,
    save_agent_config,
    is_agent_enabled,
)
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
    """Start a new scan. Accepts JSON: {repo_url, agents?}"""
    body = await request.json()
    repo_url: str = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)

    requested_agents: str | list = body.get("agents", "all")
    data_dir = request.app.state.data_dir

    try:
        project_path, source_type, source_url = resolve_project_path(repo_url, data_dir)
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
                git_branch=ctx.name,
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
    return {"status": "ok", "version": "0.3.0"}

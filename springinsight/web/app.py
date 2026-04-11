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
from .scanner import ScanState, _active_scans, run_scan_background
from ..utils.cost_estimator import count_project_files, estimate_scan_cost, select_agents_within_budget

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
    budget: float | None = body.get("budget")
    budget_strategy: str = body.get("budget_strategy", "value")
    use_scope: bool = body.get("use_scope", True)
    use_incremental: bool = body.get("use_incremental", True)
    max_files: int | None = body.get("max_files")

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
        "agents": [a.id for a in agents],
        "redirect": f"/scans/{run_id}",
    }
    if estimate_info:
        response_body["estimate"] = estimate_info

    return JSONResponse(response_body)


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
    return {"status": "ok", "version": "0.4.0"}


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
    """Manually trigger a scan for a specific GitHub PR URL."""
    body = await request.json()
    pr_url = body.get("pr_url", "").strip()
    if not pr_url:
        return JSONResponse({"error": "pr_url is required"}, status_code=400)

    parsed = parse_pr_url(pr_url)
    if not parsed:
        return JSONResponse({"error": "Invalid GitHub PR URL format"}, status_code=400)

    full_name, pr_number = parsed
    token = get_github_token()
    if not token:
        return JSONResponse({"error": "GitHub not connected — set token in Settings → GitHub PR"}, status_code=400)

    from ..github.pr_scanner import get_pr_changed_files, list_open_prs
    try:
        prs = await list_open_prs(token, full_name)
        pr = next((p for p in prs if p["number"] == pr_number), None)
        if not pr:
            return JSONResponse({"error": f"PR #{pr_number} not found or not open"}, status_code=404)

        changed_files = await get_pr_changed_files(token, full_name, pr_number)
        java_files = [f for f in changed_files if f.endswith(".java")]
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    data_dir = request.app.state.data_dir
    run_id = await github_scan_pr(
        full_name=full_name,
        pr_number=pr_number,
        head_sha=pr["head"]["sha"],
        clone_url=pr["head"]["repo"]["clone_url"],
        head_ref=pr["head"]["ref"],
        changed_java_files=java_files,
        data_dir=data_dir,
    )

    if not run_id:
        return JSONResponse({"error": "Failed to start PR scan"}, status_code=500)

    return JSONResponse({
        "run_id": run_id,
        "pr_number": pr_number,
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

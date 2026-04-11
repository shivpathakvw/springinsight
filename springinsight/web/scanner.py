"""Background scanner — runs agents asynchronously and streams progress via SSE.

Each scan is represented by a ``ScanState`` object that holds:
  - Live agent status dict (pending/running/complete/failed)
  - An event log for replay by late SSE subscribers
  - A list of asyncio Queues (one per connected browser tab)

The ``run_scan_background`` coroutine is launched as an asyncio task by the
FastAPI application and drives the entire scan lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..agents.registry import AGENT_REGISTRY, AgentMeta
from ..agents.runner import run_agents_parallel
from ..context.loader import ProjectContext
from ..utils.scoring import calculate_scores

logger = logging.getLogger(__name__)

# Global in-memory registry of active and recently completed scans.
# Keyed by run_id (8-char hex string).
_active_scans: dict[str, "ScanState"] = {}


@dataclass
class ScanState:
    """Live state for a single scan — shared between the background task and SSE endpoints."""

    run_id: str
    repo_url: str
    project_name: str = ""
    status: str = "pending"                          # pending | running | complete | failed
    agents: dict[str, str] = field(default_factory=dict)    # agent_id -> status
    agent_names: dict[str, str] = field(default_factory=dict)   # agent_id -> human name
    agent_models: dict[str, str] = field(default_factory=dict)  # agent_id -> model
    findings_count: int = 0
    scores: dict = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None

    # Internal — not serialized
    _event_log: list = field(default_factory=list, repr=False)
    _subscribers: list = field(default_factory=list, repr=False)

    # ── Pub/sub ────────────────────────────────────────────────────────────────

    def push_event(self, event: dict) -> None:
        """Broadcast an event to all subscribers and append to history."""
        event.setdefault("timestamp", datetime.utcnow().isoformat())
        self._event_log.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Slow subscriber — drop event rather than block

    def subscribe(self) -> asyncio.Queue:
        """Create a subscriber queue pre-filled with the event history."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        for evt in self._event_log:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                break
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "repo_url": self.repo_url,
            "project_name": self.project_name,
            "status": self.status,
            "agents": self.agents,
            "agent_names": self.agent_names,
            "agent_models": self.agent_models,
            "findings_count": self.findings_count,
            "scores": self.scores,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


# ── Background runner ──────────────────────────────────────────────────────────

async def run_scan_background(
    state: ScanState,
    ctx: ProjectContext,
    project_path: Path,
    work_dir: Path,
    agents: list[AgentMeta],
) -> None:
    """Coroutine launched as a background asyncio task.

    Drives the full scan lifecycle, updating *state* and broadcasting SSE
    events at each stage.
    """
    state.status = "running"
    state.push_event(
        {
            "type": "scan_started",
            "agent_count": len(agents),
            "agents": [
                {"id": a.id, "name": a.name, "model": a.model, "phase": a.phase}
                for a in agents
            ],
        }
    )

    def _on_progress(agent_id: str, status: str) -> None:
        """Called by run_agents_parallel when an agent's status changes."""
        state.agents[agent_id] = status
        agent_meta = AGENT_REGISTRY.get(agent_id)
        state.push_event(
            {
                "type": "agent_update",
                "agent_id": agent_id,
                "agent_name": agent_meta.name if agent_meta else agent_id,
                "status": status,
            }
        )

    run_dir = work_dir / "runs" / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        results = await run_agents_parallel(
            agents=agents,
            ctx=ctx,
            project_path=str(project_path),
            run_dir=run_dir,
            run_id=state.run_id,
            parallelism=3,
            progress_callback=_on_progress,
        )
    except Exception as exc:
        logger.exception("Scan %s crashed: %s", state.run_id, exc)
        state.status = "failed"
        state.error = str(exc)
        state.completed_at = datetime.utcnow().isoformat()
        state.push_event({"type": "scan_failed", "error": str(exc)})
        # Persist failure to DB
        _persist_to_db(state, work_dir, [], [])
        return

    # Flatten all findings from all agents
    all_findings: list[dict] = []
    agent_results_map: dict[str, dict] = {}
    for result in results:
        agent_id = result["agent_id"]
        agent_results_map[agent_id] = result
        all_findings.extend(result.get("findings", []))
        # Emit findings-discovered event for each agent
        if result.get("findings"):
            state.push_event(
                {
                    "type": "findings_update",
                    "agent_id": agent_id,
                    "count": len(result["findings"]),
                    "total": len(all_findings),
                }
            )

    scores = calculate_scores(all_findings)
    state.findings_count = len(all_findings)
    state.scores = {k: round(float(v), 1) for k, v in scores.items()}
    state.status = "complete"
    state.completed_at = datetime.utcnow().isoformat()

    state.push_event(
        {
            "type": "run_complete",
            "findings_count": len(all_findings),
            "scores": state.scores,
            "completed_at": state.completed_at,
        }
    )

    logger.info(
        "Scan %s complete — %d findings, overall score: %.0f",
        state.run_id,
        len(all_findings),
        scores.get("overall", 0),
    )

    # Persist to SQLite
    _persist_to_db(state, work_dir, all_findings, list(agent_results_map.values()))


def _persist_to_db(
    state: ScanState,
    work_dir: Path,
    all_findings: list[dict],
    agent_results: list[dict],
) -> None:
    """Write scan results to the SQLite database."""
    try:
        from ..db.database import get_db
        from ..db.models import Run, AgentRun, Finding as FindingModel
        from datetime import timezone

        def _parse_dt(iso: str | None):
            if not iso:
                return None
            try:
                return datetime.fromisoformat(iso)
            except ValueError:
                return None

        with get_db() as db:
            run = db.query(Run).filter(Run.id == state.run_id).first()
            if run:
                run.status = state.status
                run.completed_at = _parse_dt(state.completed_at)
                run.score_overall = state.scores.get("overall")
                run.score_security = state.scores.get("security")
                run.score_code_quality = state.scores.get("code_quality")
                run.score_architecture = state.scores.get("architecture")
                run.score_api_design = state.scores.get("api_design")
                run.score_test_coverage = state.scores.get("test_coverage")
                run.score_production_readiness = state.scores.get("production_readiness")
                run.agents_completed = [
                    r["agent_id"] for r in agent_results if r.get("status") == "complete"
                ]

            # Persist agent runs
            for r in agent_results:
                dur = None
                if r.get("started_at") and r.get("completed_at"):
                    try:
                        dur = (r["completed_at"] - r["started_at"]).total_seconds()
                    except Exception:
                        pass
                agent_run = AgentRun(
                    run_id=state.run_id,
                    agent_id=r["agent_id"],
                    agent_name=state.agent_names.get(r["agent_id"], r["agent_id"]),
                    model=state.agent_models.get(r["agent_id"], ""),
                    status=r.get("status", "unknown"),
                    started_at=r.get("started_at"),
                    completed_at=r.get("completed_at"),
                    findings_count=len(r.get("findings", [])),
                    error_message=r.get("error"),
                )
                db.add(agent_run)

            # Persist findings
            for f in all_findings:
                finding = FindingModel(
                    run_id=state.run_id,
                    agent_id=f.get("agent_id", ""),
                    severity=f.get("severity", "INFO"),
                    category=f.get("category", ""),
                    subcategory=f.get("subcategory", ""),
                    file_path=f.get("file"),
                    line_number=f.get("line"),
                    class_name=f.get("class_name"),
                    method_name=f.get("method_name"),
                    problem=f.get("problem", ""),
                    code_snippet=f.get("fix_code"),
                    impact=f.get("impact"),
                    fix_description=f.get("fix"),
                    fix_code=f.get("fix_code"),
                    artifact_id=f.get("artifact_id"),
                    version=f.get("version"),
                    cve_ids=f.get("cve_ids", []),
                    cvss_score=f.get("cvss_score"),
                    actionable=f.get("actionable", True),
                    effort_hours=f.get("effort_hours"),
                    status="open",
                )
                db.add(finding)

    except Exception as exc:
        logger.error("Failed to persist scan %s to DB: %s", state.run_id, exc)

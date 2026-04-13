"""Background scanner — runs agents asynchronously and streams progress via SSE.

Each scan is represented by a ``ScanState`` object that holds:
  - Live agent status dict (pending/running/complete/failed)
  - Per-agent log messages and file stats
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

# Global registry of active batch scans.
# Keyed by batch_scan_id (8-char hex string).
_active_batch_scans: dict[str, "BatchScanState"] = {}

# Max log lines kept per agent in memory
MAX_AGENT_LOGS = 200


@dataclass
class ScanState:
    """Live state for a single scan — shared between the background task and SSE endpoints."""

    run_id: str
    repo_url: str
    project_name: str = ""
    status: str = "pending"                          # pending | running | complete | failed
    agents: dict[str, str] = field(default_factory=dict)    # agent_id -> status
    agent_names: dict[str, str] = field(default_factory=dict)
    agent_models: dict[str, str] = field(default_factory=dict)
    agent_findings: dict[str, int] = field(default_factory=dict)  # agent_id -> count
    agent_java_files: dict[str, int] = field(default_factory=dict)  # agent_id -> file count
    agent_start_times: dict[str, str] = field(default_factory=dict)  # agent_id -> ISO timestamp
    agent_end_times: dict[str, str] = field(default_factory=dict)
    agent_logs: dict[str, list] = field(default_factory=dict)    # agent_id -> [log lines]
    findings_count: int = 0
    total_java_files: int = 0
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
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
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

    def add_agent_log(self, agent_id: str, message: str) -> None:
        """Append a log line to per-agent history (bounded)."""
        if agent_id not in self.agent_logs:
            self.agent_logs[agent_id] = []
        logs = self.agent_logs[agent_id]
        logs.append(message)
        if len(logs) > MAX_AGENT_LOGS:
            logs.pop(0)

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
            "agent_findings": self.agent_findings,
            "agent_java_files": self.agent_java_files,
            "agent_start_times": self.agent_start_times,
            "agent_end_times": self.agent_end_times,
            "agent_logs": self.agent_logs,
            "findings_count": self.findings_count,
            "total_java_files": self.total_java_files,
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
    use_file_scope: bool = True,
    use_incremental: bool = True,
    max_files: int | None = None,
    batch_scope_block: str = "",   # non-empty when called from a batch scan
) -> None:
    """Coroutine launched as a background asyncio task."""
    state.status = "running"

    # Count total Java files once
    try:
        state.total_java_files = sum(
            1 for _ in project_path.rglob("*.java") if ".git" not in str(_)
        )
    except Exception:
        pass

    state.push_event(
        {
            "type": "scan_started",
            "agent_count": len(agents),
            "total_java_files": state.total_java_files,
            "agents": [
                {"id": a.id, "name": a.name, "model": a.model, "phase": a.phase}
                for a in agents
            ],
        }
    )

    def _on_progress(agent_id: str, status: str) -> None:
        """Called by run_agents_parallel when an agent's status changes."""
        state.agents[agent_id] = status
        now = datetime.utcnow().isoformat()
        if status == "running":
            state.agent_start_times[agent_id] = now
        elif status in ("complete", "failed"):
            state.agent_end_times[agent_id] = now

        agent_meta = AGENT_REGISTRY.get(agent_id)
        state.push_event(
            {
                "type": "agent_update",
                "agent_id": agent_id,
                "agent_name": agent_meta.name if agent_meta else agent_id,
                "status": status,
                "java_files": state.agent_java_files.get(agent_id, 0),
                "started_at": state.agent_start_times.get(agent_id),
            }
        )

    def _on_log(agent_id: str, message: str) -> None:
        """Called by the runner for each verbose log line from an agent."""
        state.add_agent_log(agent_id, message)
        state.push_event(
            {
                "type": "agent_log",
                "agent_id": agent_id,
                "message": message,
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
            log_callback=_on_log,
            use_file_scope=use_file_scope,
            use_incremental=use_incremental,
            max_files=max_files,
            batch_scope_block=batch_scope_block,
        )
    except Exception as exc:
        logger.exception("Scan %s crashed: %s", state.run_id, exc)
        state.status = "failed"
        state.error = str(exc)
        state.completed_at = datetime.utcnow().isoformat()
        state.push_event({"type": "scan_failed", "error": str(exc)})
        _persist_to_db(state, work_dir, [], [])
        return

    # Flatten all findings from all agents
    all_findings: list[dict] = []
    agent_results_map: dict[str, dict] = {}
    for result in results:
        agent_id = result["agent_id"]
        agent_results_map[agent_id] = result
        findings = result.get("findings", [])
        all_findings.extend(findings)

        # Update per-agent file stats
        state.agent_java_files[agent_id] = result.get("java_files", 0)
        state.agent_findings[agent_id] = len(findings)

        # Emit error detail for failed agents so the UI can show WHY they failed
        if result.get("status") == "failed" and result.get("error"):
            state.push_event(
                {
                    "type": "agent_error",
                    "agent_id": agent_id,
                    "error": result["error"],
                }
            )

        # Emit findings-discovered event for each agent
        if findings:
            state.push_event(
                {
                    "type": "findings_update",
                    "agent_id": agent_id,
                    "count": len(findings),
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
            "agent_findings": state.agent_findings,
        }
    )

    logger.info(
        "Scan %s complete — %d findings, overall score: %.0f",
        state.run_id,
        len(all_findings),
        scores.get("overall", 0),
    )

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

        def _parse_dt(iso_or_dt):
            if iso_or_dt is None:
                return None
            if isinstance(iso_or_dt, datetime):
                return iso_or_dt
            try:
                return datetime.fromisoformat(str(iso_or_dt))
            except (ValueError, TypeError):
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
                agent_run = AgentRun(
                    run_id=state.run_id,
                    agent_id=r["agent_id"],
                    agent_name=state.agent_names.get(r["agent_id"], r["agent_id"]),
                    model=state.agent_models.get(r["agent_id"], ""),
                    status=r.get("status", "unknown"),
                    started_at=_parse_dt(r.get("started_at")),
                    completed_at=_parse_dt(r.get("completed_at")),
                    files_processed=r.get("java_files", 0),
                    findings_count=len(r.get("findings", [])),
                    error_message=r.get("error"),
                )
                db.add(agent_run)

            # Persist findings — only use valid FindingModel columns
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
                    code_snippet=f.get("code_snippet"),
                    impact=f.get("impact"),
                    fix_description=f.get("fix"),
                    fix_code=f.get("fix_code"),
                    dependency_group_id=f.get("dependency_group_id"),
                    dependency_artifact_id=f.get("dependency_artifact_id"),
                    dependency_version=f.get("dependency_version") or f.get("version"),
                    cve_ids=f.get("cve_ids", []),
                    cvss_score=f.get("cvss_score"),
                    actionable=f.get("actionable", True),
                    effort_hours=f.get("effort_hours"),
                    status="open",
                )
                db.add(finding)

    except Exception as exc:
        logger.error("Failed to persist scan %s to DB: %s", state.run_id, exc)


# ══════════════════════════════════════════════════════════════════════════════
# Batch scan orchestrator
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BatchScanState:
    """Tracks the overall state of a multi-batch scan of a large project."""

    batch_scan_id: str
    project_name: str
    repo_url: str
    total_java_files: int
    batches: list[dict]                    # [{id, name, description, include_paths, java_file_count}]
    strategy: str                          # maven | gradle | dir | package | slice
    status: str = "pending"               # pending | running | complete | failed
    current_batch_index: int = 0
    current_run_id: Optional[str] = None  # run_id of the batch currently scanning
    completed_run_ids: list[str] = field(default_factory=list)
    total_findings: int = 0
    aggregate_scores: dict = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None

    # Internal pub/sub
    _event_log: list = field(default_factory=list, repr=False)
    _subscribers: list = field(default_factory=list, repr=False)

    def push_event(self, event: dict) -> None:
        event.setdefault("timestamp", datetime.utcnow().isoformat())
        self._event_log.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=4000)
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

    def to_dict(self) -> dict:
        return {
            "batch_scan_id": self.batch_scan_id,
            "project_name": self.project_name,
            "repo_url": self.repo_url,
            "total_java_files": self.total_java_files,
            "batches": self.batches,
            "strategy": self.strategy,
            "status": self.status,
            "current_batch_index": self.current_batch_index,
            "current_run_id": self.current_run_id,
            "completed_run_ids": self.completed_run_ids,
            "total_findings": self.total_findings,
            "aggregate_scores": self.aggregate_scores,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


async def run_batch_scan_background(
    batch_state: BatchScanState,
    ctx: ProjectContext,
    project_path: Path,
    work_dir: Path,
    agents: list[AgentMeta],
    use_file_scope: bool = True,
    use_incremental: bool = True,
) -> None:
    """
    Orchestrate a multi-batch scan:
    • Runs each batch sequentially (one at a time) to avoid memory overload.
    • Each batch creates its own ScanState and run_id so the existing live-scan
      SSE and report infrastructure works without changes.
    • Aggregates findings/scores across all batches into the BatchScanState.
    • Forwards batch-level SSE events to the parent BatchScanState subscribers.
    """
    import uuid as _uuid
    from ..utils.batch_scanner import ScanBatch

    batch_state.status = "running"
    batches = batch_state.batches
    total_batches = len(batches)

    batch_state.push_event({
        "type": "batch_started",
        "total_batches": total_batches,
        "strategy": batch_state.strategy,
        "total_java_files": batch_state.total_java_files,
    })

    all_scores_list: list[dict] = []

    for batch_index, batch_dict in enumerate(batches):
        batch_id_label = batch_dict["id"]
        batch_name = batch_dict["name"]
        include_paths = batch_dict.get("include_paths", [])

        run_id = _uuid.uuid4().hex[:8]
        batch_state.current_batch_index = batch_index
        batch_state.current_run_id = run_id

        batch_state.push_event({
            "type": "batch_item_started",
            "batch_index": batch_index,
            "total_batches": total_batches,
            "batch_id": batch_id_label,
            "batch_name": batch_name,
            "run_id": run_id,
            "include_paths": include_paths,
        })

        # Build the batch scope prompt block
        batch_scope = ScanBatch(
            id=batch_id_label,
            name=batch_name,
            description=batch_dict.get("description", ""),
            include_paths=include_paths,
        )
        batch_scope_block = batch_scope.to_batch_scope_block(
            str(project_path), batch_index + 1, total_batches
        )

        # Persist a Run record for this batch sub-scan
        try:
            from ..db.database import get_db
            from ..db.models import Run
            with get_db() as db:
                run = Run(
                    id=run_id,
                    project_name=f"{batch_state.project_name} [{batch_id_label}]",
                    project_path=str(project_path),
                    source_type="batch",
                    source_url=batch_state.repo_url,
                    status="running",
                    agents_requested=[a.id for a in agents],
                    agents_completed=[],
                    git_branch=f"batch-scan/{batch_state.batch_scan_id}",
                )
                db.add(run)
        except Exception as exc:
            logger.warning("Batch DB insert failed for %s: %s", run_id, exc)

        # Build a sub-ScanState and register it
        sub_state = ScanState(
            run_id=run_id,
            repo_url=batch_state.repo_url,
            project_name=f"{batch_state.project_name} [{batch_name}]",
            agents={a.id: "pending" for a in agents},
            agent_names={a.id: a.name for a in agents},
            agent_models={a.id: a.model for a in agents},
        )
        _active_scans[run_id] = sub_state

        # Bridge sub-scan events to the parent batch stream
        def _bridge_event(evt: dict, _run_id: str = run_id, _batch_idx: int = batch_index):
            bridged = {**evt, "run_id": _run_id, "batch_index": _batch_idx, "batch_name": batch_name}
            batch_state.push_event(bridged)

        # Monkey-patch push_event to also forward to parent
        original_push = sub_state.push_event.__func__  # noqa
        def _patched_push(self, event, _bridge=_bridge_event):
            original_push(self, event)
            _bridge(event)
        import types
        sub_state.push_event = types.MethodType(_patched_push, sub_state)

        try:
            await run_scan_background(
                sub_state,
                ctx,
                project_path,
                work_dir,
                agents,
                use_file_scope=use_file_scope,
                use_incremental=use_incremental,
                batch_scope_block=batch_scope_block,
            )
        except Exception as exc:
            logger.error("Batch %s scan failed: %s", batch_id_label, exc)
            batch_state.push_event({
                "type": "batch_item_failed",
                "batch_index": batch_index,
                "batch_id": batch_id_label,
                "run_id": run_id,
                "error": str(exc),
            })
            # Continue with remaining batches

        batch_state.completed_run_ids.append(run_id)
        batch_state.total_findings += sub_state.findings_count
        if sub_state.scores:
            all_scores_list.append(sub_state.scores)

        batch_state.push_event({
            "type": "batch_item_complete",
            "batch_index": batch_index,
            "total_batches": total_batches,
            "batch_id": batch_id_label,
            "batch_name": batch_name,
            "run_id": run_id,
            "findings": sub_state.findings_count,
            "total_findings_so_far": batch_state.total_findings,
        })

    # Aggregate scores (average across batches)
    if all_scores_list:
        keys = set().union(*all_scores_list)
        batch_state.aggregate_scores = {
            k: round(sum(s.get(k, 0) for s in all_scores_list) / len(all_scores_list), 1)
            for k in keys
        }

    batch_state.status = "complete"
    batch_state.completed_at = datetime.utcnow().isoformat()
    batch_state.current_run_id = None

    batch_state.push_event({
        "type": "batch_complete",
        "total_findings": batch_state.total_findings,
        "aggregate_scores": batch_state.aggregate_scores,
        "completed_run_ids": batch_state.completed_run_ids,
        "completed_at": batch_state.completed_at,
    })

    logger.info(
        "Batch scan %s complete — %d batches, %d total findings",
        batch_state.batch_scan_id,
        total_batches,
        batch_state.total_findings,
    )

"""
springinsight.springteam.models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQLite schema + data-access layer for SpringTeam.

Tables:
  springteam_tasks     — the work queue
  springteam_messages  — inter-agent communication bus
  springteam_agents    — agent slot registry (who is working on what)
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS springteam_tasks (
    id              TEXT PRIMARY KEY,
    project_path    TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    required_skill  TEXT,
    status          TEXT DEFAULT 'pending',
    priority        INTEGER DEFAULT 5,
    parent_task_id  TEXT,
    depends_on      TEXT DEFAULT '[]',
    assigned_agent  TEXT,
    created_at      REAL,
    claimed_at      REAL,
    started_at      REAL,
    completed_at    REAL,
    context         TEXT DEFAULT '{}',
    output          TEXT,
    output_type     TEXT,
    error           TEXT,
    run_log         TEXT
);

CREATE INDEX IF NOT EXISTS idx_st_tasks_project ON springteam_tasks (project_path);
CREATE INDEX IF NOT EXISTS idx_st_tasks_status  ON springteam_tasks (project_path, status);
CREATE INDEX IF NOT EXISTS idx_st_tasks_skill   ON springteam_tasks (required_skill, status);

CREATE TABLE IF NOT EXISTS springteam_messages (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    from_agent   TEXT NOT NULL,
    to_agent     TEXT,
    message_type TEXT NOT NULL,
    content      TEXT NOT NULL,
    created_at   REAL
);

CREATE INDEX IF NOT EXISTS idx_st_msg_task ON springteam_messages (task_id);
CREATE INDEX IF NOT EXISTS idx_st_msg_time ON springteam_messages (created_at);

CREATE TABLE IF NOT EXISTS springteam_agents (
    id              TEXT PRIMARY KEY,
    agent_type      TEXT NOT NULL,
    status          TEXT DEFAULT 'idle',
    current_task_id TEXT,
    last_heartbeat  REAL,
    capabilities    TEXT DEFAULT '[]'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_st_agent_type ON springteam_agents (agent_type);
"""

# ---------------------------------------------------------------------------
# Status / skill constants
# ---------------------------------------------------------------------------

class TaskStatus:
    PENDING     = "pending"
    CLAIMED     = "claimed"
    IN_PROGRESS = "in_progress"
    REVIEW      = "review"
    DONE        = "done"
    BLOCKED     = "blocked"
    FAILED      = "failed"

class AgentSkill:
    PLANNER      = "planner"
    CODER        = "coder"
    TESTER       = "tester"
    REVIEWER     = "reviewer"
    DB_OPTIMIZER = "db_optimizer"
    DOCUMENTER   = "documenter"

ALL_SKILLS = [
    AgentSkill.PLANNER, AgentSkill.CODER, AgentSkill.TESTER,
    AgentSkill.REVIEWER, AgentSkill.DB_OPTIMIZER, AgentSkill.DOCUMENTER,
]

SKILL_LABELS = {
    AgentSkill.PLANNER:      "Planner",
    AgentSkill.CODER:        "Coder",
    AgentSkill.TESTER:       "Tester",
    AgentSkill.REVIEWER:     "Reviewer",
    AgentSkill.DB_OPTIMIZER: "DB Optimizer",
    AgentSkill.DOCUMENTER:   "Documenter",
}

SKILL_COLORS = {
    AgentSkill.PLANNER:      "#a78bfa",  # violet
    AgentSkill.CODER:        "#60a5fa",  # blue
    AgentSkill.TESTER:       "#34d399",  # emerald
    AgentSkill.REVIEWER:     "#fb923c",  # orange
    AgentSkill.DB_OPTIMIZER: "#f472b6",  # pink
    AgentSkill.DOCUMENTER:   "#facc15",  # yellow
}

# ---------------------------------------------------------------------------
# Data-access layer
# ---------------------------------------------------------------------------

class SpringTeamDB:
    """All read/write operations for SpringTeam."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_tables()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_tables(self):
        with self._conn() as c:
            c.executescript(_DDL)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def create_task(
        self,
        project_path: str,
        title: str,
        description: str,
        required_skill: Optional[str] = None,
        priority: int = 5,
        parent_task_id: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        context: Optional[Dict] = None,
    ) -> str:
        task_id = str(uuid.uuid4())[:8]
        with self._conn() as c:
            c.execute(
                """INSERT INTO springteam_tasks
                   (id, project_path, title, description, required_skill,
                    priority, parent_task_id, depends_on, context, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, project_path, title, description,
                    required_skill, priority, parent_task_id,
                    json.dumps(depends_on or []),
                    json.dumps(context or {}),
                    time.time(),
                ),
            )
        return task_id

    def get_task(self, task_id: str) -> Optional[Dict]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM springteam_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return _row(row)

    def list_tasks(self, project_path: str, status: Optional[str] = None) -> List[Dict]:
        with self._conn() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM springteam_tasks WHERE project_path = ? AND status = ? "
                    "ORDER BY priority ASC, created_at ASC",
                    (project_path, status),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM springteam_tasks WHERE project_path = ? "
                    "ORDER BY priority ASC, created_at ASC",
                    (project_path,),
                ).fetchall()
        return [_row(r) for r in rows]

    def list_all_tasks(self, project_path: str) -> Dict[str, List[Dict]]:
        """Return tasks grouped by status — for the Kanban view."""
        all_tasks = self.list_tasks(project_path)
        grouped: Dict[str, List[Dict]] = {s: [] for s in [
            TaskStatus.PENDING, TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS,
            TaskStatus.REVIEW, TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED,
        ]}
        for t in all_tasks:
            grouped.setdefault(t["status"], []).append(t)
        return grouped

    def claim_task(self, task_id: str, agent_type: str) -> bool:
        """Atomically claim a task for an agent. Returns False if already claimed."""
        with self._conn() as c:
            result = c.execute(
                "UPDATE springteam_tasks SET status = ?, assigned_agent = ?, claimed_at = ? "
                "WHERE id = ? AND status = ?",
                (TaskStatus.CLAIMED, agent_type, time.time(), task_id, TaskStatus.PENDING),
            )
            return result.rowcount > 0

    def update_task_status(self, task_id: str, status: str, **kwargs):
        fields = {"status": status}
        if status == TaskStatus.IN_PROGRESS:
            fields["started_at"] = time.time()
        elif status in (TaskStatus.DONE, TaskStatus.FAILED):
            fields["completed_at"] = time.time()
        fields.update(kwargs)
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [task_id]
        with self._conn() as c:
            c.execute(f"UPDATE springteam_tasks SET {cols} WHERE id = ?", vals)

    def append_run_log(self, task_id: str, line: str):
        with self._conn() as c:
            c.execute(
                "UPDATE springteam_tasks SET run_log = COALESCE(run_log, '') || ? WHERE id = ?",
                (line + "\n", task_id),
            )

    def get_claimable_tasks(self, project_path: str, skill: str) -> List[Dict]:
        """Return pending tasks whose deps are satisfied and match the skill."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM springteam_tasks WHERE project_path = ? AND status = ? "
                "AND (required_skill = ? OR required_skill IS NULL) "
                "ORDER BY priority ASC, created_at ASC LIMIT 5",
                (project_path, TaskStatus.PENDING, skill),
            ).fetchall()
        ready = []
        for row in [_row(r) for r in rows]:
            # _row() already parsed depends_on from JSON → list; never call json.loads again
            deps = row.get("depends_on") or []
            if isinstance(deps, str):          # safety net for legacy rows
                deps = json.loads(deps)
            if not deps:
                ready.append(row)
                continue
            # Check all deps are DONE
            with self._conn() as c:
                for dep_id in deps:
                    dep = c.execute(
                        "SELECT status FROM springteam_tasks WHERE id = ?", (dep_id,)
                    ).fetchone()
                    if not dep or dep["status"] != TaskStatus.DONE:
                        break
                else:
                    ready.append(row)
        return ready

    def delete_task(self, task_id: str):
        with self._conn() as c:
            c.execute("DELETE FROM springteam_tasks WHERE id = ?", (task_id,))
            c.execute("DELETE FROM springteam_messages WHERE task_id = ?", (task_id,))

    def get_kanban_counts(self, project_path: str) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) as c FROM springteam_tasks "
                "WHERE project_path = ? GROUP BY status",
                (project_path,),
            ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def post_message(
        self,
        task_id: str,
        from_agent: str,
        content: str,
        message_type: str = "status_update",
        to_agent: Optional[str] = None,
    ) -> str:
        msg_id = str(uuid.uuid4())[:8]
        with self._conn() as c:
            c.execute(
                "INSERT INTO springteam_messages (id, task_id, from_agent, to_agent, message_type, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, task_id, from_agent, to_agent, message_type, content, time.time()),
            )
        return msg_id

    def get_messages(self, task_id: str) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM springteam_messages WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
        return [_row(r) for r in rows]

    def get_recent_activity(self, project_path: str, limit: int = 50) -> List[Dict]:
        """Get recent messages across all tasks for the activity feed."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT m.*, t.title as task_title, t.required_skill
                   FROM springteam_messages m
                   JOIN springteam_tasks t ON m.task_id = t.id
                   WHERE t.project_path = ?
                   ORDER BY m.created_at DESC LIMIT ?""",
                (project_path, limit),
            ).fetchall()
        return [_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def register_agent(self, agent_type: str, capabilities: Optional[List[str]] = None):
        agent_id = f"agent-{agent_type}"
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO springteam_agents (id, agent_type, status, capabilities, last_heartbeat) "
                "VALUES (?, ?, 'idle', ?, ?)",
                (agent_id, agent_type, json.dumps(capabilities or [agent_type]), time.time()),
            )

    def set_agent_status(self, agent_type: str, status: str, task_id: Optional[str] = None):
        with self._conn() as c:
            c.execute(
                "UPDATE springteam_agents SET status = ?, current_task_id = ?, last_heartbeat = ? "
                "WHERE agent_type = ?",
                (status, task_id, time.time(), agent_type),
            )

    def get_agents(self) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM springteam_agents ORDER BY agent_type").fetchall()
        return [_row(r) for r in rows]

    def heartbeat(self, agent_type: str):
        with self._conn() as c:
            c.execute(
                "UPDATE springteam_agents SET last_heartbeat = ? WHERE agent_type = ?",
                (time.time(), agent_type),
            )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_project_stats(self, project_path: str) -> Dict:
        counts = self.get_kanban_counts(project_path)
        agents = self.get_agents()
        return {
            "tasks": counts,
            "total": sum(counts.values()),
            "agents": [
                {"type": a["agent_type"], "status": a["status"],
                 "task": a.get("current_task_id")}
                for a in agents
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(row) -> Optional[Dict]:
    if row is None:
        return None
    d = dict(row)
    # Parse JSON fields
    for jf in ("depends_on", "context", "capabilities"):
        if jf in d and d[jf]:
            try:
                d[jf] = json.loads(d[jf])
            except Exception:
                pass
    return d

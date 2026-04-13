"""
springinsight.springteam.orchestrator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The SpringTeam execution engine.

Responsibilities:
  1. Accept user tasks (via create_task)
  2. Run Planner agent to decompose complex requests into sub-tasks
  3. Spawn per-skill agent workers (asyncio tasks)
  4. Workers poll the task queue for claimable work
  5. Execute work via `claude --print` with the skill's system prompt
  6. Dependency management: unblock tasks when their deps complete
  7. SSE event broadcast: push live updates to the web UI

Usage:
    orch = Orchestrator(db_path="~/.springinsight/springinsight.db")
    await orch.start(project_path="./my-spring-app")
    task_id = await orch.submit("Add cursor pagination to UserController")
    # web UI subscribes to SSE stream; orch.events is an asyncio.Queue
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from .models import SpringTeamDB, TaskStatus, AgentSkill, ALL_SKILLS, _row
from .skills import AGENT_PROMPTS, AGENT_MODELS, classify_task

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSE Event helpers
# ---------------------------------------------------------------------------

def _sse(event_type: str, data: Any) -> str:
    """Format a server-sent event."""
    payload = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event_type}\ndata: {payload}\n\n"


# ---------------------------------------------------------------------------
# Coordination workflow templates
# ---------------------------------------------------------------------------

COORDINATION_TEMPLATES = {
    "implement-and-test": {
        "trigger_skill": AgentSkill.CODER,
        "followup": [AgentSkill.TESTER, AgentSkill.REVIEWER],
    },
    "fix-and-validate": {
        "trigger_skill": AgentSkill.CODER,
        "followup": [AgentSkill.TESTER],
    },
    "db-optimize-and-test": {
        "trigger_skill": AgentSkill.DB_OPTIMIZER,
        "followup": [AgentSkill.TESTER],
    },
    "document-from-code": {
        "trigger_skill": AgentSkill.DOCUMENTER,
        "followup": [],
    },
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Central controller for SpringTeam agent workers.
    One orchestrator instance per web server / CLI session.
    """

    POLL_INTERVAL = 3.0    # seconds between queue polls per worker
    MAX_RETRIES   = 2

    def __init__(self, db_path: str):
        self.db = SpringTeamDB(db_path)
        self.project_path: Optional[str] = None
        self._workers: Dict[str, asyncio.Task] = {}
        self._running = False
        self._event_queues: List[asyncio.Queue] = []   # one per SSE subscriber

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, project_path: str, skills: Optional[List[str]] = None):
        """Start agent workers for the given project."""
        self.project_path = str(Path(project_path).resolve())
        self._running = True
        skills = skills or ALL_SKILLS

        # Register agent slots in DB
        for skill in skills:
            self.db.register_agent(skill)

        # Spawn one worker coroutine per skill
        for skill in skills:
            if skill not in self._workers or self._workers[skill].done():
                task = asyncio.create_task(self._worker(skill), name=f"worker-{skill}")
                self._workers[skill] = task
                log.info(f"[SpringTeam] Worker started: {skill}")

        self._broadcast("system", {
            "message": f"SpringTeam started — {len(skills)} agents online",
            "agents": skills,
            "project": self.project_path,
        })

    async def stop(self):
        """Gracefully stop all workers."""
        self._running = False
        for skill, task in self._workers.items():
            if not task.done():
                task.cancel()
                log.info(f"[SpringTeam] Worker stopped: {skill}")
        self._workers.clear()
        self._broadcast("system", {"message": "SpringTeam stopped"})

    def is_running(self) -> bool:
        return self._running and any(not t.done() for t in self._workers.values())

    # ------------------------------------------------------------------
    # Task submission
    # ------------------------------------------------------------------

    async def submit(
        self,
        request: str,
        project_path: Optional[str] = None,
        skill: Optional[str] = None,
        priority: int = 5,
        context: Optional[Dict] = None,
    ) -> str:
        """
        Submit a task or complex request.
        - If skill is provided: create single task with that skill
        - If request is complex (no skill): run Planner to decompose
        - Returns the (first) task ID
        """
        pp = project_path or self.project_path or "."
        pp = str(Path(pp).resolve())

        if skill:
            task_id = self.db.create_task(
                project_path=pp,
                title=request[:80],
                description=request,
                required_skill=skill,
                priority=priority,
                context=context,
            )
            self.db.post_message(task_id, "system", f"Task created for {skill} agent", "status_update")
            self._broadcast("task_created", self._task_payload(task_id))
            return task_id

        # Auto-classify
        detected_skill = await classify_task(request)

        # If planner or complex request → decompose
        if detected_skill == AgentSkill.PLANNER:
            return await self._plan_and_create(request, pp, priority, context)

        # Simple task
        task_id = self.db.create_task(
            project_path=pp,
            title=request[:80],
            description=request,
            required_skill=detected_skill,
            priority=priority,
            context=context,
        )
        self.db.post_message(task_id, "system",
                             f"Auto-routed to {detected_skill} agent", "status_update")
        self._broadcast("task_created", self._task_payload(task_id))
        return task_id

    async def _plan_and_create(
        self, request: str, project_path: str, priority: int, context: Optional[Dict]
    ) -> str:
        """Run Planner agent, parse sub-tasks, create them with dependencies."""
        # Create a planning task first (visible in UI)
        plan_task_id = self.db.create_task(
            project_path=project_path,
            title=f"[Planning] {request[:60]}",
            description=request,
            required_skill=AgentSkill.PLANNER,
            priority=1,  # always highest
            context=context,
        )
        self.db.update_task_status(plan_task_id, TaskStatus.IN_PROGRESS)
        self._broadcast("task_created", self._task_payload(plan_task_id))

        try:
            subtasks_json = await self._run_planner(request, project_path)
        except Exception as e:
            self.db.update_task_status(plan_task_id, TaskStatus.FAILED, error=str(e))
            self._broadcast("task_updated", self._task_payload(plan_task_id))
            return plan_task_id

        self.db.update_task_status(plan_task_id, TaskStatus.DONE,
                                   output=json.dumps(subtasks_json), output_type="plan")
        self._broadcast("task_updated", self._task_payload(plan_task_id))

        # ID mapping: plan uses index-based refs like "task-0", "task-1"
        id_map: Dict[str, str] = {}
        created_ids: List[str] = []

        for i, st in enumerate(subtasks_json):
            # Resolve index-based depends_on to real task IDs
            deps = [id_map.get(d, d) for d in st.get("depends_on", []) if d in id_map]
            tid = self.db.create_task(
                project_path=project_path,
                title=st.get("title", f"Sub-task {i+1}"),
                description=st.get("description", ""),
                required_skill=st.get("required_skill", AgentSkill.CODER),
                priority=st.get("priority", priority),
                parent_task_id=plan_task_id,
                depends_on=deps,
                context=st.get("context", {}),
            )
            id_map[f"task-{i}"] = tid
            created_ids.append(tid)
            self.db.post_message(tid, "planner",
                                 f"Sub-task created from planning request", "status_update")
            self._broadcast("task_created", self._task_payload(tid))

        self.db.post_message(
            plan_task_id, "planner",
            f"Decomposed into {len(created_ids)} sub-tasks: {', '.join(created_ids)}",
            "completion",
        )
        return plan_task_id

    async def _run_planner(self, request: str, project_path: str) -> List[Dict]:
        """Run Planner agent to get JSON sub-task list."""
        prompt = (
            f"{AGENT_PROMPTS[AgentSkill.PLANNER]}\n\n"
            f"PROJECT: {project_path}\n\n"
            f"USER REQUEST:\n{request}\n\n"
            f"Decompose this into sub-tasks. Return ONLY the JSON array, no other text."
        )
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "--model", AGENT_MODELS[AgentSkill.PLANNER],
            "--allowedTools", "Bash,Read,Glob,Grep",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=prompt.encode())
        output = stdout.decode().strip()

        # Extract JSON from output
        match = re.search(r'\[\s*\{.*?\}\s*\]', output, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Fallback: create single coder task
        return [{"title": request[:80], "description": request,
                 "required_skill": AgentSkill.CODER, "priority": 5, "depends_on": []}]

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def _worker(self, skill: str):
        """Continuously poll queue and execute matching tasks."""
        log.info(f"[{skill}] Worker starting")
        consecutive_errors = 0

        while self._running:
            try:
                await self._poll_and_execute(skill)
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                log.error(f"[{skill}] Worker error #{consecutive_errors}: {e}")
                if consecutive_errors > 10:
                    log.error(f"[{skill}] Too many errors, worker pausing 30s")
                    await asyncio.sleep(30)
                    consecutive_errors = 0
            await asyncio.sleep(self.POLL_INTERVAL)

        self.db.set_agent_status(skill, "idle")
        log.info(f"[{skill}] Worker stopped")

    async def _poll_and_execute(self, skill: str):
        """Find one claimable task and execute it."""
        if not self.project_path:
            return

        tasks = self.db.get_claimable_tasks(self.project_path, skill)
        if not tasks:
            self.db.heartbeat(skill)
            return

        task = tasks[0]
        task_id = task["id"]

        # Claim atomically
        if not self.db.claim_task(task_id, skill):
            return   # another worker beat us to it

        self.db.set_agent_status(skill, "working", task_id)
        self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS)
        self._broadcast("task_updated", self._task_payload(task_id))

        self.db.post_message(task_id, skill,
                             f"{skill.capitalize()} agent claimed task", "status_update")
        self._broadcast("message", {
            "task_id": task_id,
            "from": skill,
            "content": f"Starting work on: {task['title']}",
            "type": "status_update",
        })

        try:
            output, output_type = await self._execute_task(task, skill)
            self.db.update_task_status(
                task_id, TaskStatus.REVIEW,
                output=output, output_type=output_type,
            )
            self.db.post_message(task_id, skill,
                                 f"Work complete. Output: {output[:200]}...",
                                 "completion")
            self._broadcast("task_updated", self._task_payload(task_id))
            self._broadcast("message", {
                "task_id": task_id,
                "from": skill,
                "content": f"✓ Completed: {task['title']}",
                "type": "completion",
            })

            # Trigger coordination workflows
            await self._trigger_followups(task, skill, output)

        except Exception as e:
            log.exception(f"[{skill}] Task {task_id} failed")
            self.db.update_task_status(task_id, TaskStatus.FAILED, error=str(e))
            self.db.post_message(task_id, skill, f"Error: {str(e)[:300]}", "blocker")
            self._broadcast("task_updated", self._task_payload(task_id))
        finally:
            self.db.set_agent_status(skill, "idle")

    async def _execute_task(self, task: Dict, skill: str) -> tuple[str, str]:
        """Run claude with the skill prompt + task description."""
        task_id = task["id"]
        project_path = task["project_path"]
        description = task["description"]
        context = task.get("context") or {}

        # Build the full prompt
        system_prompt = AGENT_PROMPTS[skill]
        user_block = (
            f"PROJECT: {project_path}\n\n"
            f"TASK:\n{description}\n"
        )
        if context:
            if context.get("files"):
                user_block += f"\nFOCUS FILES:\n" + "\n".join(f"- {f}" for f in context["files"])
            if context.get("notes"):
                user_block += f"\nNOTES:\n{context['notes']}"

        # Check for parent task output (handoff context)
        parent_id = task.get("parent_task_id")
        if parent_id:
            deps = task.get("depends_on") or []
            for dep_id in deps:
                dep_task = self.db.get_task(dep_id)
                if dep_task and dep_task.get("output"):
                    user_block += f"\n\nOUTPUT FROM PREVIOUS TASK ({dep_id}):\n{dep_task['output'][:2000]}"

        full_prompt = f"<system>\n{system_prompt}\n</system>\n\n{user_block}"
        model = AGENT_MODELS[skill]

        # Stream output and capture
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "--model", model,
            "--allowedTools", "Bash,Read,Write,Glob,Grep",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        proc.stdin.write(full_prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        output_parts = []
        while True:
            chunk = await proc.stdout.read(512)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            output_parts.append(text)
            # Log every ~1KB to the task
            if sum(len(p) for p in output_parts) % 1024 < 512:
                self.db.append_run_log(task_id, text)
            self._broadcast("task_log", {"task_id": task_id, "chunk": text})

        await proc.wait()
        output = "".join(output_parts).strip()

        # Infer output type from skill
        output_type_map = {
            AgentSkill.CODER:        "code_diff",
            AgentSkill.TESTER:       "test_file",
            AgentSkill.REVIEWER:     "review_comment",
            AgentSkill.DB_OPTIMIZER: "code_diff",
            AgentSkill.DOCUMENTER:   "doc_update",
            AgentSkill.PLANNER:      "plan",
        }
        return output, output_type_map.get(skill, "text")

    async def _trigger_followups(self, task: Dict, completed_skill: str, output: str):
        """Auto-create follow-up tasks based on coordination templates."""
        for template in COORDINATION_TEMPLATES.values():
            if template["trigger_skill"] != completed_skill:
                continue
            if not template["followup"]:
                continue

            # Only auto-trigger if no explicit sub-tasks already exist for this parent
            parent_id = task.get("parent_task_id") or task["id"]
            existing = self.db.list_tasks(self.project_path, status=None)
            followup_skills = {t["required_skill"] for t in existing
                               if t.get("parent_task_id") == parent_id}

            for follow_skill in template["followup"]:
                if follow_skill not in followup_skills:
                    desc = (
                        f"Follow-up for: {task['title']}\n\n"
                        f"The {completed_skill} agent has completed the implementation.\n"
                        f"Here is what was done:\n{output[:500]}\n\n"
                        f"Please perform your {follow_skill} responsibilities on this work."
                    )
                    fid = self.db.create_task(
                        project_path=self.project_path,
                        title=f"[{follow_skill.capitalize()}] {task['title'][:60]}",
                        description=desc,
                        required_skill=follow_skill,
                        priority=task.get("priority", 5),
                        parent_task_id=parent_id,
                        depends_on=[task["id"]],
                    )
                    self.db.post_message(fid, "system",
                                         f"Auto-created by {completed_skill} completion", "status_update")
                    self._broadcast("task_created", self._task_payload(fid))

    # ------------------------------------------------------------------
    # SSE broadcast
    # ------------------------------------------------------------------

    def _broadcast(self, event_type: str, data: Any):
        """Push an event to all active SSE subscribers."""
        for q in list(self._event_queues):
            try:
                q.put_nowait({"type": event_type, "data": data})
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to SSE events. Returns a queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._event_queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._event_queues.remove(q)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _task_payload(self, task_id: str) -> Dict:
        t = self.db.get_task(task_id)
        if not t:
            return {"id": task_id}
        return {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "required_skill": t["required_skill"],
            "priority": t["priority"],
            "assigned_agent": t["assigned_agent"],
            "created_at": t["created_at"],
            "started_at": t.get("started_at"),
            "completed_at": t.get("completed_at"),
            "parent_task_id": t.get("parent_task_id"),
            "depends_on": t.get("depends_on") or [],
            "has_output": bool(t.get("output")),
        }

    # ------------------------------------------------------------------
    # Quick task management (for web UI)
    # ------------------------------------------------------------------

    def approve_task(self, task_id: str) -> bool:
        """Move a REVIEW task to DONE."""
        task = self.db.get_task(task_id)
        if task and task["status"] == TaskStatus.REVIEW:
            self.db.update_task_status(task_id, TaskStatus.DONE)
            self.db.post_message(task_id, "user", "Approved by user", "completion")
            self._broadcast("task_updated", self._task_payload(task_id))
            return True
        return False

    def reject_task(self, task_id: str, feedback: str = "") -> bool:
        """Return a REVIEW task to PENDING for rework."""
        task = self.db.get_task(task_id)
        if task and task["status"] == TaskStatus.REVIEW:
            self.db.update_task_status(task_id, TaskStatus.PENDING,
                                       assigned_agent=None, claimed_at=None)
            msg = f"Rejected by user. Feedback: {feedback}" if feedback else "Rejected by user, please rework."
            self.db.post_message(task_id, "user", msg, "status_update")
            self._broadcast("task_updated", self._task_payload(task_id))
            return True
        return False


# ---------------------------------------------------------------------------
# Global orchestrator singleton (per web server process)
# ---------------------------------------------------------------------------

_orchestrator: Optional[Orchestrator] = None


def get_orchestrator(db_path: str) -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(db_path)
    return _orchestrator

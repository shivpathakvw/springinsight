"""
springinsight team — CLI for SpringTeam (Pillar 3 multi-agent task framework).

Commands:
  springinsight team task "<description>"    # Create a task (auto-routed)
  springinsight team list                    # List all tasks
  springinsight team status <task-id>        # Show task detail
  springinsight team start                   # Start agent workers
  springinsight team stop                    # Stop all agents
  springinsight team logs <task-id>          # Show task run log
  springinsight team approve <task-id>       # Approve a task in REVIEW
  springinsight team reject <task-id>        # Reject a task, send back for rework
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import click

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_work_dir() -> str:
    return os.environ.get("SPRINGINSIGHT_WORK_DIR", str(Path.home() / ".springinsight"))


def _db_path(work_dir: str) -> str:
    p = os.path.join(work_dir, "springinsight.db")
    os.makedirs(work_dir, exist_ok=True)
    return p


STATUS_ICONS = {
    "pending":     "⚪",
    "claimed":     "🟡",
    "in_progress": "🔵",
    "review":      "🟠",
    "done":        "✅",
    "blocked":     "🔴",
    "failed":      "❌",
}

SKILL_ICONS = {
    "planner":      "🗺️ ",
    "coder":        "👨‍💻",
    "tester":       "🧪",
    "reviewer":     "👁️ ",
    "db_optimizer": "🗄️ ",
    "documenter":   "📝",
}


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

@click.group("team")
def team_cmd():
    """SpringTeam: multi-agent task execution framework for Spring Boot projects."""
    pass


# ---------------------------------------------------------------------------
# task sub-command
# ---------------------------------------------------------------------------

@team_cmd.command("task")
@click.argument("description", nargs=-1, required=True)
@click.option("--project", "-p", type=click.Path(exists=True), default=".",
              help="Spring Boot project path (default: current dir)")
@click.option("--skill", "-s", default=None,
              type=click.Choice(["planner","coder","tester","reviewer","db_optimizer","documenter"]),
              help="Force a specific agent skill (default: auto-route)")
@click.option("--priority", default=5, help="Priority 1 (urgent) to 10 (low)")
@click.option("--work-dir", default=None)
def task_cmd(description, project, skill, priority, work_dir):
    """
    Create a task for the agent team.

    \b
    Examples:
      springinsight team task "Add cursor-based pagination to UserController"
      springinsight team task "Fix N+1 in OrderRepository" --skill db_optimizer
      springinsight team task "Write tests for PaymentService" --skill tester
      springinsight team task "Add pagination, tests, and docs" --skill planner
    """
    work_dir = work_dir or _get_work_dir()
    project_path = str(Path(project).resolve())
    desc = " ".join(description)

    from ..springteam.orchestrator import Orchestrator
    orch = Orchestrator(db_path=_db_path(work_dir))

    async def _run():
        orch.project_path = project_path
        task_id = await orch.submit(
            request=desc,
            project_path=project_path,
            skill=skill,
            priority=priority,
        )
        task = orch.db.get_task(task_id)
        detected_skill = task.get("required_skill", "?")
        status_icon = STATUS_ICONS.get(task.get("status", ""), "·")
        skill_icon = SKILL_ICONS.get(detected_skill, "·")

        click.echo(f"\n  ✅ Task created")
        click.echo(f"     ID       : {click.style(task_id, fg='cyan', bold=True)}")
        click.echo(f"     Title    : {task['title']}")
        click.echo(f"     Agent    : {skill_icon} {detected_skill}")
        click.echo(f"     Status   : {status_icon} {task['status']}")
        click.echo(f"     Priority : {priority}")
        click.echo()
        click.echo("  Run  springinsight team start  to execute tasks.")
        click.echo(f"  Run  springinsight team status {task_id}  to monitor.")
        click.echo()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# list sub-command
# ---------------------------------------------------------------------------

@team_cmd.command("list")
@click.option("--project", "-p", type=click.Path(exists=True), default=".", help="Project path")
@click.option("--status", default=None, help="Filter by status")
@click.option("--work-dir", default=None)
def list_cmd(project, status, work_dir):
    """List all tasks in the queue."""
    work_dir = work_dir or _get_work_dir()
    project_path = str(Path(project).resolve())

    from ..springteam.models import SpringTeamDB

    db = SpringTeamDB(db_path=_db_path(work_dir))
    tasks = db.list_tasks(project_path, status=status)

    if not tasks:
        click.echo("\n  No tasks found. Create one with:  springinsight team task \"...\"\n")
        return

    click.echo(f"\n  {'ID':<10} {'STATUS':<14} {'SKILL':<14} {'PRI':<5} {'TITLE'}")
    click.echo("  " + "─" * 70)

    for t in tasks:
        icon = STATUS_ICONS.get(t["status"], "·")
        skill_icon = SKILL_ICONS.get(t["required_skill"] or "", "·")
        status_str = f"{icon} {t['status']}"
        click.echo(
            f"  {t['id']:<10} {status_str:<14} {skill_icon} {(t['required_skill'] or '?'):<12} "
            f"{t['priority']:<5} {t['title'][:45]}"
        )
    click.echo()


# ---------------------------------------------------------------------------
# status sub-command
# ---------------------------------------------------------------------------

@team_cmd.command("status")
@click.argument("task_id")
@click.option("--work-dir", default=None)
def status_cmd(task_id, work_dir):
    """Show detailed status and messages for a task."""
    work_dir = work_dir or _get_work_dir()

    from ..springteam.models import SpringTeamDB

    db = SpringTeamDB(db_path=_db_path(work_dir))
    task = db.get_task(task_id)

    if not task:
        click.echo(f"\n  ❌ Task {task_id} not found.\n")
        sys.exit(1)

    import datetime as dt
    def _ts(t):
        return dt.datetime.fromtimestamp(t).strftime("%H:%M:%S") if t else "-"

    icon = STATUS_ICONS.get(task["status"], "·")
    skill_icon = SKILL_ICONS.get(task.get("required_skill") or "", "·")

    click.echo(f"\n  Task: {click.style(task_id, fg='cyan', bold=True)}")
    click.echo(f"  {'─'*60}")
    click.echo(f"  Title    : {task['title']}")
    click.echo(f"  Status   : {icon} {task['status']}")
    click.echo(f"  Agent    : {skill_icon} {task.get('required_skill') or 'unassigned'}")
    click.echo(f"  Priority : {task['priority']}")
    click.echo(f"  Created  : {_ts(task.get('created_at'))}")
    click.echo(f"  Started  : {_ts(task.get('started_at'))}")
    click.echo(f"  Done     : {_ts(task.get('completed_at'))}")

    if task.get("error"):
        click.echo(f"\n  ❌ Error:\n  {task['error'][:400]}")

    # Messages
    messages = db.get_messages(task_id)
    if messages:
        click.echo(f"\n  Agent Messages:")
        for m in messages:
            ts = _ts(m.get("created_at"))
            from_icon = SKILL_ICONS.get(m["from_agent"], "·")
            click.echo(f"    {ts}  {from_icon} [{m['from_agent']}] {m['content'][:80]}")

    # Output preview
    if task.get("output"):
        click.echo(f"\n  Output ({task.get('output_type', '?')}):")
        click.echo("  " + "─" * 60)
        click.echo(task["output"][:800])
        if len(task["output"]) > 800:
            click.echo("  ... (truncated)")

    click.echo()


# ---------------------------------------------------------------------------
# start sub-command
# ---------------------------------------------------------------------------

@team_cmd.command("start")
@click.option("--project", "-p", type=click.Path(exists=True), default=".",
              help="Spring Boot project path")
@click.option("--agents", "-a", default="all",
              help="Comma-separated agents to start (default: all)")
@click.option("--work-dir", default=None)
def start_cmd(project, agents, work_dir):
    """
    Start agent workers and process the task queue.

    \b
    Examples:
      springinsight team start
      springinsight team start --agents coder,tester
      springinsight team start --project ./my-spring-app
    """
    work_dir = work_dir or _get_work_dir()
    project_path = str(Path(project).resolve())

    from ..springteam.models import ALL_SKILLS
    from ..springteam.orchestrator import Orchestrator

    if agents == "all":
        skills = ALL_SKILLS
    else:
        skills = [a.strip() for a in agents.split(",")]

    orch = Orchestrator(db_path=_db_path(work_dir))

    click.echo(f"\n  🚀 Starting SpringTeam agents…")
    click.echo(f"     Project : {project_path}")
    click.echo(f"     Agents  : {', '.join(skills)}")
    click.echo(f"\n  Press Ctrl+C to stop.\n")

    async def _run():
        await orch.start(project_path=project_path, skills=skills)
        try:
            # Print live activity
            while orch.is_running():
                tasks = orch.db.list_tasks(project_path)
                in_progress = [t for t in tasks if t["status"] == "in_progress"]
                pending = [t for t in tasks if t["status"] == "pending"]
                done = [t for t in tasks if t["status"] == "done"]
                click.echo(
                    f"\r  ⟳  {len(in_progress)} working  |  "
                    f"{len(pending)} pending  |  {len(done)} done     ",
                    nl=False,
                )
                await asyncio.sleep(2)
        except KeyboardInterrupt:
            pass
        finally:
            await orch.stop()
            click.echo("\n\n  Agents stopped.\n")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# logs sub-command
# ---------------------------------------------------------------------------

@team_cmd.command("logs")
@click.argument("task_id")
@click.option("--work-dir", default=None)
def logs_cmd(task_id, work_dir):
    """Show the raw run log for a task."""
    work_dir = work_dir or _get_work_dir()

    from ..springteam.models import SpringTeamDB

    db = SpringTeamDB(db_path=_db_path(work_dir))
    task = db.get_task(task_id)

    if not task:
        click.echo(f"\n  ❌ Task {task_id} not found.\n")
        sys.exit(1)

    click.echo(f"\n  Log for task {task_id}: {task['title']}\n")
    click.echo("─" * 70)
    click.echo(task.get("run_log") or "(no log yet)")
    click.echo()


# ---------------------------------------------------------------------------
# approve / reject sub-commands
# ---------------------------------------------------------------------------

@team_cmd.command("approve")
@click.argument("task_id")
@click.option("--work-dir", default=None)
def approve_cmd(task_id, work_dir):
    """Approve a task that is in REVIEW state, marking it DONE."""
    work_dir = work_dir or _get_work_dir()

    from ..springteam.orchestrator import Orchestrator

    orch = Orchestrator(db_path=_db_path(work_dir))
    if orch.approve_task(task_id):
        click.echo(f"\n  ✅ Task {task_id} approved and marked DONE.\n")
    else:
        task = orch.db.get_task(task_id)
        status = task["status"] if task else "not found"
        click.echo(f"\n  ⚠️  Cannot approve — current status: {status}\n")


@team_cmd.command("reject")
@click.argument("task_id")
@click.option("--feedback", "-f", default="", help="Feedback for the agent")
@click.option("--work-dir", default=None)
def reject_cmd(task_id, feedback, work_dir):
    """Reject a task in REVIEW, sending it back for rework."""
    work_dir = work_dir or _get_work_dir()

    from ..springteam.orchestrator import Orchestrator

    orch = Orchestrator(db_path=_db_path(work_dir))
    if orch.reject_task(task_id, feedback):
        click.echo(f"\n  🔄 Task {task_id} sent back for rework.\n")
    else:
        click.echo(f"\n  ⚠️  Cannot reject — task not in REVIEW state.\n")

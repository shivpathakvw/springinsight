"""Agent runner — executes SpringInsight agents via the Claude Code CLI.

Each agent is a SKILL.md file given to `claude --print` as a structured
prompt. The agent uses Bash/Read/Glob tools to discover and analyze files,
then writes:
  - JSON findings  → <run_dir>/raw/<agent_id>-findings.json
  - Markdown report → <run_dir>/agents/<agent_id>-report.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from ..context.loader import ProjectContext, render_context_block
from .registry import AgentMeta, resolve_skill_path

logger = logging.getLogger(__name__)

# Model identifiers
MODEL_IDS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

# Allowed tools for agent execution
AGENT_TOOLS = "Bash,Read,Write,Glob,Grep"

# Timeout per agent in seconds (10 minutes)
AGENT_TIMEOUT = 600


def _check_claude_cli() -> bool:
    """Verify the claude CLI is available on PATH."""
    return shutil.which("claude") is not None


def _build_agent_prompt(
    agent: AgentMeta,
    ctx: ProjectContext,
    project_path: str,
    output_json_path: Path,
    output_md_path: Path,
    run_id: str,
    extra_scope: str = "",
) -> str:
    """Assemble the full prompt sent to claude for an agent run."""
    skill_path = resolve_skill_path(agent)
    if not skill_path.exists():
        raise FileNotFoundError(f"SKILL.md not found: {skill_path}")

    skill_content = skill_path.read_text(encoding="utf-8")
    context_block = render_context_block(ctx, project_path)

    scope_block = f"""
=== EXECUTION PARAMETERS ===
Run ID         : {run_id}
Agent ID       : {agent.id}
Agent Name     : {agent.name}
Project Path   : {project_path}
Output JSON    : {output_json_path}
Output Report  : {output_md_path}
{extra_scope}
=== BEGIN ANALYSIS ===
Execute the full analysis now following ALL instructions in the SKILL.md above.
Do NOT skip any steps. Write your complete findings to the paths specified above.
"""

    return f"{skill_content}\n\n{context_block}\n\n{scope_block}"


def _count_java_files(project_path: str) -> int:
    """Count .java source files in a project directory."""
    try:
        p = Path(project_path)
        return sum(1 for _ in p.rglob("*.java") if ".git" not in str(_))
    except Exception:
        return 0


async def run_agent_async(
    agent: AgentMeta,
    ctx: ProjectContext,
    project_path: str,
    run_dir: Path,
    run_id: str,
    extra_scope: str = "",
    timeout: int = AGENT_TIMEOUT,
    log_callback=None,   # log_callback(agent_id, message: str)
) -> dict:
    """Run a single agent asynchronously. Returns execution metadata."""
    raw_dir = run_dir / "raw"
    md_dir = run_dir / "agents"
    raw_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    output_json = raw_dir / f"{agent.id}-findings.json"
    output_md = md_dir / f"{agent.id}-{agent.name.lower().replace(' ', '-')}.md"

    prompt = _build_agent_prompt(
        agent=agent,
        ctx=ctx,
        project_path=project_path,
        output_json_path=output_json,
        output_md_path=output_md,
        run_id=run_id,
        extra_scope=extra_scope,
    )

    started_at = datetime.utcnow()

    def _log(msg: str) -> None:
        logger.info("[%s] %s", agent.id, msg)
        if log_callback:
            log_callback(agent.id, msg)

    if not _check_claude_cli():
        return {
            "agent_id": agent.id,
            "status": "failed",
            "error": "claude CLI not found on PATH. Install Claude Code: npm install -g @anthropic-ai/claude-code",
            "started_at": started_at,
            "completed_at": datetime.utcnow(),
            "output_json": None,
            "output_md": None,
            "findings": [],
            "java_files": 0,
        }

    java_files = _count_java_files(project_path)
    _log(f"Found {java_files} Java source files to analyze")

    try:
        process = await asyncio.create_subprocess_exec(
            "claude",
            "--model", agent.model,
            "--allowedTools", AGENT_TOOLS,
            "--print",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_path,
        )

        # Heartbeat task — emits progress every 15s while the agent is running
        heartbeat_interval = 15
        _heartbeat_count = [0]

        async def _heartbeat():
            while True:
                await asyncio.sleep(heartbeat_interval)
                _heartbeat_count[0] += 1
                elapsed = _heartbeat_count[0] * heartbeat_interval
                _log(f"Still analyzing… ({elapsed}s elapsed)")

        heartbeat_task = asyncio.create_task(_heartbeat())

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except (TimeoutError, asyncio.TimeoutError):
            heartbeat_task.cancel()
            process.kill()
            await process.communicate()
            _log(f"Timed out after {timeout}s")
            return {
                "agent_id": agent.id,
                "status": "failed",
                "error": f"Agent timed out after {timeout}s",
                "started_at": started_at,
                "completed_at": datetime.utcnow(),
                "output_json": None,
                "output_md": None,
                "findings": [],
                "java_files": java_files,
            }
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="replace").strip()
            logger.warning("Agent %s failed (rc=%d): %s", agent.id, process.returncode, error_msg[:200])
            _log(f"Failed after {duration:.0f}s — exit code {process.returncode}")
            return {
                "agent_id": agent.id,
                "status": "failed",
                "error": error_msg[:500],
                "started_at": started_at,
                "completed_at": completed_at,
                "output_json": None,
                "output_md": None,
                "findings": [],
                "java_files": java_files,
            }

        # Try to load the JSON findings the agent wrote.
        # Agents write either a plain array or {"findings": [...]} — handle both.
        findings = []
        if output_json.exists():
            try:
                raw_data = json.loads(output_json.read_text(encoding="utf-8"))
                if isinstance(raw_data, list):
                    findings = raw_data
                elif isinstance(raw_data, dict):
                    findings = raw_data.get("findings", [])
            except json.JSONDecodeError as e:
                logger.warning("Agent %s wrote invalid JSON: %s", agent.id, e)

        # Severity breakdown for the log
        crit = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high = sum(1 for f in findings if f.get("severity") == "HIGH")
        med  = sum(1 for f in findings if f.get("severity") == "MEDIUM")
        _log(
            f"Complete in {duration:.0f}s — {len(findings)} finding(s)"
            + (f" [{crit} CRITICAL, {high} HIGH, {med} MEDIUM]" if findings else "")
        )

        return {
            "agent_id": agent.id,
            "status": "complete",
            "error": None,
            "started_at": started_at,
            "completed_at": completed_at,
            "output_json": str(output_json) if output_json.exists() else None,
            "output_md": str(output_md) if output_md.exists() else None,
            "findings": findings,
            "java_files": java_files,
            "stdout_preview": stdout.decode(errors="replace")[:500],
        }

    except Exception as exc:
        logger.exception("Unexpected error running agent %s", agent.id)
        _log(f"Unexpected error: {exc}")
        return {
            "agent_id": agent.id,
            "status": "failed",
            "error": str(exc),
            "started_at": started_at,
            "completed_at": datetime.utcnow(),
            "output_json": None,
            "output_md": None,
            "findings": [],
            "java_files": java_files if "java_files" in dir() else 0,
        }


async def run_agents_parallel(
    agents: list[AgentMeta],
    ctx: ProjectContext,
    project_path: str,
    run_dir: Path,
    run_id: str,
    parallelism: int = 6,
    progress_callback=None,
    log_callback=None,
) -> list[dict]:
    """Run multiple agents with bounded parallelism.

    progress_callback(agent_id, status) is called on start + completion.
    log_callback(agent_id, message)    is called for verbose log lines.
    """
    semaphore = asyncio.Semaphore(parallelism)

    async def _run_with_sem(agent: AgentMeta) -> dict:
        async with semaphore:
            if progress_callback:
                progress_callback(agent.id, "running")
            result = await run_agent_async(
                agent, ctx, project_path, run_dir, run_id,
                log_callback=log_callback,
            )
            if progress_callback:
                progress_callback(agent.id, result["status"])
            return result

    tasks = [_run_with_sem(agent) for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)

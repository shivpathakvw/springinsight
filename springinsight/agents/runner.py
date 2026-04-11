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


async def run_agent_async(
    agent: AgentMeta,
    ctx: ProjectContext,
    project_path: str,
    run_dir: Path,
    run_id: str,
    extra_scope: str = "",
    timeout: int = AGENT_TIMEOUT,
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
        }

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

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return {
                "agent_id": agent.id,
                "status": "failed",
                "error": f"Agent timed out after {timeout}s",
                "started_at": started_at,
                "completed_at": datetime.utcnow(),
                "output_json": None,
                "output_md": None,
                "findings": [],
            }

        completed_at = datetime.utcnow()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="replace").strip()
            logger.warning("Agent %s failed (rc=%d): %s", agent.id, process.returncode, error_msg[:200])
            return {
                "agent_id": agent.id,
                "status": "failed",
                "error": error_msg[:500],
                "started_at": started_at,
                "completed_at": completed_at,
                "output_json": None,
                "output_md": None,
                "findings": [],
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

        return {
            "agent_id": agent.id,
            "status": "complete",
            "error": None,
            "started_at": started_at,
            "completed_at": completed_at,
            "output_json": str(output_json) if output_json.exists() else None,
            "output_md": str(output_md) if output_md.exists() else None,
            "findings": findings,
            "stdout_preview": stdout.decode(errors="replace")[:500],
        }

    except Exception as exc:
        logger.exception("Unexpected error running agent %s", agent.id)
        return {
            "agent_id": agent.id,
            "status": "failed",
            "error": str(exc),
            "started_at": started_at,
            "completed_at": datetime.utcnow(),
            "output_json": None,
            "output_md": None,
            "findings": [],
        }


async def run_agents_parallel(
    agents: list[AgentMeta],
    ctx: ProjectContext,
    project_path: str,
    run_dir: Path,
    run_id: str,
    parallelism: int = 6,
    progress_callback=None,
) -> list[dict]:
    """Run multiple agents with bounded parallelism.

    progress_callback(agent_id, status) is called on start + completion.
    """
    semaphore = asyncio.Semaphore(parallelism)
    results = []

    async def _run_with_sem(agent: AgentMeta) -> dict:
        async with semaphore:
            if progress_callback:
                progress_callback(agent.id, "running")
            result = await run_agent_async(agent, ctx, project_path, run_dir, run_id)
            if progress_callback:
                progress_callback(agent.id, result["status"])
            return result

    tasks = [_run_with_sem(agent) for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)

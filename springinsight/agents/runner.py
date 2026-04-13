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
from ..utils.file_cache import get_unchanged_files, update_cache
from ..utils.file_scope import compute_scope
from .registry import AgentMeta, resolve_skill_path

logger = logging.getLogger(__name__)

# Global registry of active subprocesses: run_id -> agent_id -> Process
# Used by stop_agent() to kill a specific agent on demand.
_active_procs: dict[str, dict[str, "asyncio.subprocess.Process"]] = {}


def _register_proc(run_id: str, agent_id: str, proc) -> None:
    _active_procs.setdefault(run_id, {})[agent_id] = proc


def _unregister_proc(run_id: str, agent_id: str) -> None:
    procs = _active_procs.get(run_id, {})
    procs.pop(agent_id, None)
    if not procs:
        _active_procs.pop(run_id, None)


async def stop_agent(run_id: str, agent_id: str) -> bool:
    """Kill the subprocess for a specific running agent. Returns True if it was alive."""
    proc = _active_procs.get(run_id, {}).get(agent_id)
    if proc is None or proc.returncode is not None:
        return False
    try:
        proc.terminate()
        # Give it 2s to exit gracefully, then kill hard
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
    except Exception:
        pass
    _unregister_proc(run_id, agent_id)
    return True


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


def _find_claude_cli() -> str | None:
    """Find the claude CLI binary, searching PATH and common npm/nvm install locations.

    Python venvs modify PATH and often drop npm's global bin directory.
    We probe well-known locations so SpringInsight works even when `claude`
    is not on the activated venv PATH.
    """
    # 1. Standard PATH lookup (fastest path — works when env is set up correctly)
    found = shutil.which("claude")
    if found:
        return found

    candidates: list[Path] = [
        # npm --global prefix defaults on macOS / Linux
        Path.home() / ".npm-global" / "bin" / "claude",
        # npm prefix when set via 'npm config set prefix'
        Path.home() / ".local" / "bin" / "claude",
        # Homebrew (Apple Silicon + Intel)
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
        # System fallback
        Path("/usr/bin/claude"),
    ]

    # nvm: walk the versions tree, try the three most-recent node installs
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.exists():
        try:
            for v in sorted(nvm_dir.iterdir(), reverse=True)[:3]:
                candidates.insert(0, v / "bin" / "claude")
        except Exception:
            pass

    # volta: managed toolchain directory
    volta_bin = Path.home() / ".volta" / "bin" / "claude"
    candidates.insert(0, volta_bin)

    # fnm / asdf node shims
    for extra in [
        Path.home() / ".fnm" / "aliases" / "default" / "bin" / "claude",
        Path.home() / ".asdf" / "shims" / "claude",
    ]:
        candidates.insert(0, extra)

    for p in candidates:
        try:
            if p.exists() and os.access(str(p), os.X_OK):
                return str(p)
        except Exception:
            continue

    return None


def _check_claude_cli() -> bool:
    """Verify the claude CLI is available (legacy shim — use _find_claude_cli directly)."""
    return _find_claude_cli() is not None


def _build_agent_prompt(
    agent: AgentMeta,
    ctx: ProjectContext,
    project_path: str,
    output_json_path: Path,
    output_md_path: Path,
    run_id: str,
    extra_scope: str = "",
    file_scope_block: str = "",
    batch_scope_block: str = "",   # injected when running inside a batch scan
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
{batch_scope_block}
{file_scope_block}
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
    use_file_scope: bool = True,   # enable agent-specific file filtering
    use_incremental: bool = True,  # skip unchanged files via FileCache
    max_files: int | None = None,  # override per-agent file cap
    batch_scope_block: str = "",   # non-empty when running inside a batch scan
) -> dict:
    """Run a single agent asynchronously. Returns execution metadata."""
    raw_dir = run_dir / "raw"
    md_dir = run_dir / "agents"
    raw_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    output_json = raw_dir / f"{agent.id}-findings.json"
    output_md = md_dir / f"{agent.id}-{agent.name.lower().replace(' ', '-')}.md"

    started_at = datetime.utcnow()
    project_path_obj = Path(project_path)

    def _log(msg: str) -> None:
        logger.info("[%s] %s", agent.id, msg)
        if log_callback:
            log_callback(agent.id, msg)

    claude_bin = _find_claude_cli()
    if not claude_bin:
        _error = (
            "claude CLI not found. Searched PATH and common npm/nvm locations. "
            "Install Claude Code: npm install -g @anthropic-ai/claude-code  "
            "then make sure it is executable in your terminal (run: claude --version)."
        )
        _log(f"ERROR: {_error}")
        return {
            "agent_id": agent.id,
            "status": "failed",
            "error": _error,
            "started_at": started_at,
            "completed_at": datetime.utcnow(),
            "output_json": None,
            "output_md": None,
            "findings": [],
            "java_files": 0,
        }

    java_files = _count_java_files(project_path)
    _log(f"Found {java_files} Java source files | claude binary: {claude_bin}")

    # ── Compute file scope (agent-specific filtering + incremental cache) ──
    file_scope_block = ""
    scope_obj = None
    if use_file_scope:
        try:
            skip_files: set[str] = set()
            if use_incremental:
                skip_files = get_unchanged_files(project_path_obj, agent.id)
                if skip_files:
                    _log(f"Incremental: {len(skip_files)} unchanged file(s) will be skipped")

            scope_obj = compute_scope(
                agent_id=agent.id,
                project_path=project_path_obj,
                max_files=max_files,
                skip_files=skip_files,
            )
            file_scope_block = scope_obj.to_prompt_block(project_path)
            _log(f"Scope: {scope_obj.savings_summary()}")
        except Exception as exc:
            logger.warning("[%s] Scope computation failed: %s", agent.id, exc)
            file_scope_block = ""

    try:
        prompt = _build_agent_prompt(
            agent=agent,
            ctx=ctx,
            project_path=project_path,
            output_json_path=output_json,
            output_md_path=output_md,
            run_id=run_id,
            extra_scope=extra_scope,
            file_scope_block=file_scope_block,
            batch_scope_block=batch_scope_block,
        )

        process = await asyncio.create_subprocess_exec(
            claude_bin,          # resolved path — works inside venvs
            "--model", agent.model,
            "--allowedTools", AGENT_TOOLS,
            "--print",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_path,
        )
        _register_proc(run_id, agent.id, process)

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
            _unregister_proc(run_id, agent.id)

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

        # ── Update file hash cache after successful run ──────────────────
        if use_incremental and use_file_scope:
            try:
                all_java = list(project_path_obj.rglob("*.java"))
                saved = update_cache(project_path_obj, all_java, run_id)
                if saved:
                    logger.debug("[%s] FileCache updated: %d entries", agent.id, saved)
            except Exception as exc:
                logger.debug("[%s] FileCache update failed: %s", agent.id, exc)

        scope_savings = scope_obj.savings_summary() if scope_obj else "scope disabled"

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
            "scope_savings": scope_savings,
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
            "java_files": java_files,   # always assigned before the try block
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
    use_file_scope: bool = True,
    use_incremental: bool = True,
    max_files: int | None = None,
    batch_scope_block: str = "",   # injected for batch scans
) -> list[dict]:
    """Run multiple agents with bounded parallelism.

    progress_callback(agent_id, status) is called on start + completion.
    log_callback(agent_id, message)    is called for verbose log lines.
    use_file_scope: inject agent-specific file lists (reduces tokens).
    use_incremental: skip unchanged files via FileCache.
    max_files: override per-agent file cap (None = use defaults).
    batch_scope_block: extra prompt constraint limiting analysis to batch paths.
    """
    semaphore = asyncio.Semaphore(parallelism)

    async def _run_with_sem(agent: AgentMeta) -> dict:
        async with semaphore:
            if progress_callback:
                progress_callback(agent.id, "running")
            result = await run_agent_async(
                agent, ctx, project_path, run_dir, run_id,
                log_callback=log_callback,
                use_file_scope=use_file_scope,
                use_incremental=use_incremental,
                max_files=max_files,
                batch_scope_block=batch_scope_block,
            )
            if progress_callback:
                progress_callback(agent.id, result["status"])
            return result

    tasks = [_run_with_sem(agent) for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)

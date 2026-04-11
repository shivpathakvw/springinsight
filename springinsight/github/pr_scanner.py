"""GitHub PR scanning and auto-comment engine.

Flow:
1. ``poll_watched_repos()``  → lists open PRs via GitHub API
2. For each PR: skip if already scanned at same commit SHA
3. Clone PR branch → run agents on changed Java files
4. Post formatted comment to PR
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import (
    add_watched_repo,
    get_github_token,
    load_github_config,
    load_pr_scan_history,
    mark_pr_scanned,
    save_github_config,
    was_pr_scanned,
)

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


# ── GitHub API helpers ─────────────────────────────────────────────────────────

def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def verify_token(token: str) -> dict[str, Any]:
    """Verify a GitHub token and return user info. Raises on failure."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{GITHUB_API}/user", headers=_headers(token))
        resp.raise_for_status()
        return resp.json()


async def list_open_prs(token: str, full_name: str) -> list[dict]:
    """Return open PRs for owner/repo."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{full_name}/pulls",
            headers=_headers(token),
            params={"state": "open", "per_page": 50},
        )
        if resp.status_code == 404:
            logger.warning("Repo not found or no access: %s", full_name)
            return []
        resp.raise_for_status()
        return resp.json()


async def get_pr_changed_files(token: str, full_name: str, pr_number: int) -> list[dict]:
    """Return list of changed file info dicts in a PR.

    Each dict has keys: filename, status (added|modified|removed|renamed), patch, additions, deletions.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{full_name}/pulls/{pr_number}/files",
            headers=_headers(token),
            params={"per_page": 300},
        )
        resp.raise_for_status()
        return resp.json()


def build_pr_scope_block(
    changed_java_files: list[str],
    clone_dir: Path,
    full_name: str,
    pr_number: int,
    pr_branch: str,
) -> str:
    """Build the =PR SCAN SCOPE= block injected into every agent prompt.

    Tells agents to ONLY analyze the changed files and skip everything else.
    This is the primary fix for the "PR scans entire codebase" bug.
    """
    abs_paths = []
    for rel in changed_java_files:
        abs_path = clone_dir / rel
        # Use the absolute path if it exists, otherwise fall back to relative path
        if abs_path.exists():
            abs_paths.append(str(abs_path))
        else:
            # File was deleted in this PR — still mention it for context but mark as removed
            abs_paths.append(f"{clone_dir / rel}  [REMOVED IN THIS PR]")

    file_list = "\n".join(f"  - {p}" for p in abs_paths) if abs_paths else "  (none)"

    return f"""
=== PR SCAN SCOPE ===
⚠️  CRITICAL — This is a Pull Request scan.
    Repository : {full_name}
    PR         : #{pr_number}
    Branch     : {pr_branch}

YOU MUST ONLY ANALYZE THE FOLLOWING {len(changed_java_files)} CHANGED JAVA FILE(S).
Every other file in the repository is OUT OF SCOPE — skip them completely.

Changed Java Files:
{file_list}

ABSOLUTE RULES:
  1. Only read / analyse files from the list above.
  2. Do NOT glob for *.java across the project — only examine the files listed.
  3. Do NOT report findings on files outside this list.
  4. Focus your analysis on what changed: correctness, security, performance.
  5. Removed files (marked [REMOVED IN THIS PR]) should only be mentioned if they
     leave behind a dangling dependency or caller.
=== END PR SCOPE ===
"""


async def post_pr_comment(token: str, full_name: str, pr_number: int, body: str) -> dict:
    """Post a comment on a GitHub PR. Returns the created comment."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{full_name}/issues/{pr_number}/comments",
            headers=_headers(token),
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()


async def update_pr_comment(token: str, full_name: str, comment_id: int, body: str) -> None:
    """Update an existing PR comment (used to avoid duplicate comments on re-runs)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{GITHUB_API}/repos/{full_name}/issues/comments/{comment_id}",
            headers=_headers(token),
            json={"body": body},
        )
        resp.raise_for_status()


# ── PR URL parsing ─────────────────────────────────────────────────────────────

def parse_pr_url(pr_url: str) -> tuple[str, int] | None:
    """Parse a GitHub PR URL into (owner/repo, pr_number). Returns None on failure."""
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_url.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


# ── Comment builder ───────────────────────────────────────────────────────────

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🔵",
    "INFO": "⚪",
}

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def build_pr_comment(
    findings: list[dict],
    run_id: str,
    project_name: str,
    changed_files_count: int,
    score: int | None,
    web_ui_url: str = "http://localhost:8765",
    threshold: str = "MEDIUM",
) -> str:
    """Build the Markdown comment body for a PR."""
    threshold_order = SEVERITY_ORDER.index(threshold) if threshold in SEVERITY_ORDER else 3

    counts: dict[str, int] = {}
    for f in findings:
        sev = f.get("severity", "INFO").upper()
        counts[sev] = counts.get(sev, 0) + 1

    total = sum(counts.values())
    critical = counts.get("CRITICAL", 0)

    # Summary table
    lines = [
        "## ⚡ SpringInsight Analysis",
        f"_Automated scan of **{changed_files_count}** changed Java file(s) in `{project_name}`_",
        "",
        "| Severity | Count |",
        "|----------|-------|",
    ]
    for sev in SEVERITY_ORDER:
        n = counts.get(sev, 0)
        if n > 0:
            lines.append(f"| {SEVERITY_EMOJI.get(sev, '')} {sev} | {n} |")

    if total == 0:
        lines.append("| ✅ No issues | — |")

    lines.append("")

    # Top findings (above threshold)
    notable = [
        f for f in findings
        if SEVERITY_ORDER.index(f.get("severity", "INFO").upper()) <= threshold_order
    ][:10]

    if notable:
        lines.append("### Notable Findings")
        for f in notable:
            sev = f.get("severity", "INFO").upper()
            emoji = SEVERITY_EMOJI.get(sev, "")
            loc = f.get("file", "")
            if f.get("line"):
                loc += f":{f['line']}"
            lines.append(f"\n**{emoji} {sev} — {f.get('category', '')}**")
            lines.append(f"`{loc}` — {f.get('problem', '')[:120]}")
            if f.get("fix"):
                lines.append(f"> 💡 {f['fix'][:150]}")

    lines.append("")
    if score is not None:
        score_bar = "█" * (score // 10) + "░" * (10 - score // 10)
        lines.append(f"**Overall Score:** `{score_bar}` {score}/100")
        lines.append("")

    lines.append(f"[📊 View full report →]({web_ui_url}/scans/{run_id})")
    lines.append("")
    lines.append(
        "_Powered by [SpringInsight](https://springinsight.dev) v0.4.0 — "
        "autonomous multi-agent codebase intelligence_"
    )

    return "\n".join(lines)


# ── Core PR scan orchestrator ─────────────────────────────────────────────────

# Agents that are useful for a focused PR review (exclude full-project agents
# that need the entire codebase: LLD, Architecture, Dead Code, Docs, Dep Graph)
PR_AGENT_IDS = {"A01", "A02", "A03", "A04", "A09", "A11", "A12", "A13", "A14"}


async def scan_pr(
    full_name: str,
    pr_number: int,
    head_sha: str,
    clone_url: str,
    head_ref: str,
    changed_java_files: list[str],
    data_dir: Path,
    web_ui_url: str = "http://localhost:8765",
) -> str | None:
    """Clone PR branch, run focused scan on changed files only, post comment.

    Key fix: passes a PR scope block to agents so they ONLY analyse the
    changed Java files — not the entire cloned repository.

    Returns run_id or None.
    """
    token = get_github_token()
    if not token:
        logger.error("No GitHub token configured")
        return None

    cfg = load_github_config()
    threshold = cfg.get("comment_threshold", "MEDIUM")
    auto_comment = cfg.get("auto_comment", True)

    # Import here to avoid circular imports
    from ..agents.config import get_agents_with_config
    from ..agents.registry import AGENT_REGISTRY, get_enabled_agents
    from ..context.global_context import load_effective_context
    from ..context.loader import ProjectContext
    from ..db.database import get_db, init_db
    from ..db.models import Finding, Run
    from ..web.scanner import ScanState, _active_scans, run_scan_background

    # Clone the PR branch into a temp dir
    clone_dir = data_dir / "pr-clones" / f"{full_name.replace('/', '_')}-pr-{pr_number}"
    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    if clone_dir.exists():
        shutil.rmtree(clone_dir)

    # Build authenticated clone URL
    auth_clone_url = clone_url.replace("https://", f"https://{token}@")
    try:
        logger.info("Cloning %s branch %s for PR #%d", full_name, head_ref, pr_number)
        subprocess.run(
            ["git", "clone", "--depth=1", "--branch", head_ref, auth_clone_url, str(clone_dir)],
            check=True, capture_output=True, timeout=120,
        )
    except Exception as exc:
        logger.error("Clone failed for %s PR #%d: %s", full_name, pr_number, exc)
        return None

    # Build context
    ctx = load_effective_context(clone_dir)
    ctx.name = full_name.split("/")[-1]
    ctx.base_path = str(clone_dir)

    # Get only PR-relevant agents (skip full-project agents like LLD, Architecture, Dead Code)
    all_agents = get_enabled_agents("all")
    agents = [a for a in all_agents if a.id in PR_AGENT_IDS]
    if not agents:
        agents = all_agents  # fallback: use all if none match

    # Build the PR scope block — restricts every agent to only changed files
    pr_scope_block = build_pr_scope_block(
        changed_java_files=changed_java_files,
        clone_dir=clone_dir,
        full_name=full_name,
        pr_number=pr_number,
        pr_branch=head_ref,
    )

    import uuid
    run_id = str(uuid.uuid4())
    init_db(data_dir)

    try:
        with get_db() as db:
            run = Run(
                id=run_id,
                project_name=ctx.name,
                project_path=str(clone_dir),
                source_type="github_pr",
                source_url=f"https://github.com/{full_name}/pull/{pr_number}",
                status="running",
                agents_requested=[a.id for a in agents],
                agents_completed=[],
                git_branch=head_ref,
                git_commit=head_sha,
            )
            db.add(run)
    except Exception as exc:
        logger.error("DB insert failed: %s", exc)

    state = ScanState(
        run_id=run_id,
        repo_url=f"https://github.com/{full_name}",
        project_name=ctx.name,
        agents={a.id: "pending" for a in agents},
        agent_names={a.id: a.name for a in agents},
        agent_models={a.id: a.model for a in agents},
    )
    _active_scans[run_id] = state

    # Run scan in background — pass pr_scope_block so agents ONLY analyse changed files
    asyncio.create_task(run_scan_background(
        state, ctx, clone_dir, data_dir, agents,
        use_file_scope=False,      # PR scope block overrides file scope
        use_incremental=False,     # Always fresh scan for PRs
        batch_scope_block=pr_scope_block,
    ))

    # Mark PR as scanned (before comment, to prevent re-triggering)
    mark_pr_scanned(full_name, pr_number, head_sha, run_id)

    # Wait for scan to complete (up to 20 mins) then post comment
    async def _wait_and_comment():
        for _ in range(240):  # 240 * 5s = 20 min
            await asyncio.sleep(5)
            if state.status in ("complete", "failed", "partial"):
                break

        if not auto_comment:
            return

        # Gather findings
        try:
            with get_db() as db:
                findings = db.query(Finding).filter(Finding.run_id == run_id).all()
                run_obj = db.query(Run).filter(Run.id == run_id).first()
                score = run_obj.score_overall if run_obj else None
                findings_data = [
                    {
                        "severity": f.severity,
                        "category": f.category,
                        "file": f.file_path,
                        "line": f.line_number,
                        "problem": f.problem,
                        "fix": f.fix_description,
                    }
                    for f in findings
                ]
        except Exception:
            findings_data = []
            score = None

        comment_body = build_pr_comment(
            findings=findings_data,
            run_id=run_id,
            project_name=ctx.name,
            changed_files_count=len(changed_java_files),
            score=score,
            web_ui_url=web_ui_url,
            threshold=threshold,
        )

        try:
            await post_pr_comment(token, full_name, pr_number, comment_body)
            logger.info("Posted PR comment for %s PR #%d", full_name, pr_number)
        except Exception as exc:
            logger.error("Failed to post PR comment: %s", exc)

    asyncio.create_task(_wait_and_comment())
    return run_id


# ── Poller ─────────────────────────────────────────────────────────────────────

async def poll_once(data_dir: Path, web_ui_url: str = "http://localhost:8765") -> int:
    """Poll all watched repos for new PRs. Returns number of scans queued."""
    token = get_github_token()
    if not token:
        return 0

    cfg = load_github_config()
    watched = cfg.get("watched_repos", [])
    queued = 0

    for repo in watched:
        full_name = repo["full_name"]
        try:
            prs = await list_open_prs(token, full_name)
        except Exception as exc:
            logger.warning("Failed to list PRs for %s: %s", full_name, exc)
            continue

        for pr in prs:
            pr_number = pr["number"]
            head_sha = pr["head"]["sha"]
            head_ref = pr["head"]["ref"]
            clone_url = pr["head"]["repo"]["clone_url"]

            if was_pr_scanned(full_name, pr_number, head_sha):
                continue

            # Get changed Java files (returns list of file-info dicts)
            try:
                all_changed = await get_pr_changed_files(token, full_name, pr_number)
            except Exception:
                all_changed = []

            java_files = [
                f["filename"] for f in all_changed
                if isinstance(f, dict) and f.get("filename", "").endswith(".java")
                and f.get("status") != "removed"  # skip deleted files (nothing to scan)
            ]
            if not java_files:
                # Mark as scanned so we don't keep checking
                mark_pr_scanned(full_name, pr_number, head_sha, "no-java-files")
                continue

            logger.info(
                "Queuing scan: %s PR #%d (%d Java files changed)",
                full_name, pr_number, len(java_files)
            )
            run_id = await scan_pr(
                full_name=full_name,
                pr_number=pr_number,
                head_sha=head_sha,
                clone_url=clone_url,
                head_ref=head_ref,
                changed_java_files=java_files,
                data_dir=data_dir,
                web_ui_url=web_ui_url,
            )
            if run_id:
                queued += 1
                repo["prs_scanned"] = repo.get("prs_scanned", 0) + 1

        repo["last_polled"] = datetime.utcnow().isoformat()

    cfg["watched_repos"] = watched
    save_github_config(cfg)
    return queued


async def start_poller(data_dir: Path, web_ui_url: str = "http://localhost:8765") -> None:
    """Background task that polls watched repos on an interval."""
    logger.info("GitHub PR poller started")
    while True:
        try:
            cfg = load_github_config()
            interval = max(1, cfg.get("poll_interval_minutes", 5))
            n = await poll_once(data_dir, web_ui_url)
            if n:
                logger.info("GitHub poller: queued %d PR scan(s)", n)
        except Exception as exc:
            logger.error("GitHub poller error: %s", exc)
        await asyncio.sleep(interval * 60)

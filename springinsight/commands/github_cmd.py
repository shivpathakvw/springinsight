"""springinsight github — GitHub PR integration CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..github.config import (
    GITHUB_CONFIG_PATH,
    add_watched_repo,
    get_github_token,
    load_github_config,
    load_pr_scan_history,
    remove_watched_repo,
    save_github_config,
)

console = Console()


def _run_async(coro):
    """Run an async coroutine from a sync Click command."""
    return asyncio.run(coro)


@click.group("github")
def github_cmd():
    """GitHub PR integration — auto-scan pull requests and post findings.

    \b
    Quick start:
      springinsight github connect --token ghp_xxxx
      springinsight github watch myorg/my-spring-service
      springinsight github poll       # manually trigger scan now
      springinsight github scan-pr https://github.com/org/repo/pull/42

    The Web UI (springinsight web) will auto-start the poller when a token is
    configured. No separate daemon needed.
    """


@github_cmd.command("connect")
@click.option("--token", "-t", required=True, help="GitHub Personal Access Token (ghp_xxx).")
def github_connect(token: str):
    """Connect SpringInsight to GitHub with a Personal Access Token.

    The token needs 'repo' scope to read PRs and post comments.
    Stored locally at ~/.springinsight/github.json.

    \b
    Create a token at: https://github.com/settings/tokens
    Required scopes: repo (for private repos) or public_repo (for public repos)
    """
    from ..github.pr_scanner import verify_token

    async def _verify():
        return await verify_token(token)

    try:
        user_info = _run_async(_verify())
    except Exception as exc:
        console.print(f"[red]✗ Token verification failed:[/red] {exc}")
        raise SystemExit(1)

    cfg = load_github_config()
    cfg["token"] = token
    cfg["github_user"] = user_info.get("login", "")
    cfg["connected"] = True
    save_github_config(cfg)

    console.print(f"[green]✓[/green] Connected to GitHub as [bold orange1]{cfg['github_user']}[/bold orange1]")
    console.print(f"[dim]Config saved to {GITHUB_CONFIG_PATH}[/dim]")


@github_cmd.command("disconnect")
def github_disconnect():
    """Remove GitHub token and disconnect."""
    cfg = load_github_config()
    cfg["token"] = ""
    cfg["github_user"] = ""
    cfg["connected"] = False
    save_github_config(cfg)
    console.print("[green]✓[/green] Disconnected from GitHub.")


@github_cmd.command("watch")
@click.argument("repo", metavar="OWNER/REPO")
def github_watch(repo: str):
    """Watch a repository for new pull requests.

    \b
    Example:
      springinsight github watch myorg/backend-service
    """
    if "/" not in repo:
        console.print("[red]Error:[/red] Repo must be in owner/name format.")
        raise SystemExit(1)

    updated = add_watched_repo(repo)
    console.print(f"[green]✓[/green] Now watching [bold orange1]{repo}[/bold orange1]")
    console.print(f"[dim]{len(updated)} repo(s) total in watchlist[/dim]")


@github_cmd.command("unwatch")
@click.argument("repo", metavar="OWNER/REPO")
def github_unwatch(repo: str):
    """Stop watching a repository."""
    remove_watched_repo(repo)
    console.print(f"[green]✓[/green] Removed [bold]{repo}[/bold] from watchlist.")


@github_cmd.command("repos")
def github_repos():
    """List all watched repositories."""
    cfg = load_github_config()
    repos = cfg.get("watched_repos", [])

    if not repos:
        console.print("[dim]No repositories in watchlist.[/dim]")
        console.print("Add one with: springinsight github watch owner/repo")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Repository", style="bold orange1")
    table.add_column("PRs Scanned", justify="right")
    table.add_column("Last Polled")

    for r in repos:
        last = r.get("last_polled", "—") or "—"
        if last and last != "—":
            # Truncate to readable format
            last = last[:16].replace("T", " ")
        table.add_row(r["full_name"], str(r.get("prs_scanned", 0)), last)

    console.print(table)


@github_cmd.command("scan-pr")
@click.argument("pr_url", metavar="PR_URL")
@click.option("--comment/--no-comment", default=True, help="Post results as PR comment (default: yes).")
def github_scan_pr(pr_url: str, comment: bool):
    """Scan a specific PR and post findings.

    \b
    Example:
      springinsight github scan-pr https://github.com/myorg/service/pull/42
      springinsight github scan-pr https://github.com/org/repo/pull/7 --no-comment
    """
    from ..github.pr_scanner import (
        get_pr_changed_files,
        list_open_prs,
        parse_pr_url,
        scan_pr,
    )
    from ..db.database import init_db

    parsed = parse_pr_url(pr_url)
    if not parsed:
        console.print("[red]Error:[/red] Invalid GitHub PR URL.")
        raise SystemExit(1)

    full_name, pr_number = parsed
    token = get_github_token()
    if not token:
        console.print("[red]Error:[/red] GitHub not connected.")
        console.print("  Run: springinsight github connect --token ghp_xxxx")
        raise SystemExit(1)

    async def _run():
        prs = await list_open_prs(token, full_name)
        pr = next((p for p in prs if p["number"] == pr_number), None)
        if not pr:
            console.print(f"[red]Error:[/red] PR #{pr_number} not found or not open.")
            return None
        changed_files = await get_pr_changed_files(token, full_name, pr_number)
        java_files = [f for f in changed_files if f.endswith(".java")]
        console.print(f"[dim]Found {len(java_files)} changed Java files in PR #{pr_number}[/dim]")
        data_dir = Path.home() / ".springinsight"
        init_db(data_dir)
        run_id = await scan_pr(
            full_name=full_name,
            pr_number=pr_number,
            head_sha=pr["head"]["sha"],
            clone_url=pr["head"]["repo"]["clone_url"],
            head_ref=pr["head"]["ref"],
            changed_java_files=java_files,
            data_dir=data_dir,
        )
        return run_id

    console.print(f"[bold]Scanning[/bold] {full_name} PR #{pr_number}…")
    run_id = _run_async(_run())
    if run_id:
        console.print(f"[green]✓[/green] Scan queued — run ID: [bold orange1]{run_id}[/bold orange1]")
        console.print(f"[dim]View progress: springinsight web → http://localhost:8765/scans/{run_id}[/dim]")
    else:
        console.print("[red]✗[/red] Failed to start scan.")


@github_cmd.command("poll")
def github_poll():
    """Manually trigger a poll cycle for all watched repos."""
    from ..github.pr_scanner import poll_once
    from ..db.database import init_db

    data_dir = Path.home() / ".springinsight"
    init_db(data_dir)

    console.print("[dim]Polling watched repositories…[/dim]")

    async def _run():
        return await poll_once(data_dir)

    n = _run_async(_run())
    if n:
        console.print(f"[green]✓[/green] Queued [bold]{n}[/bold] PR scan(s).")
    else:
        console.print("[dim]No new or updated PRs found.[/dim]")


@github_cmd.command("history")
@click.option("--limit", "-n", default=20, help="Number of entries to show.")
def github_history(limit: int):
    """Show PR scan history."""
    history = load_pr_scan_history()
    if not history:
        console.print("[dim]No PR scans recorded yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Repo / PR", style="bold orange1")
    table.add_column("Commit SHA", style="dim")
    table.add_column("Run ID", style="dim")
    table.add_column("Scanned At")

    items = list(history.items())[-limit:]
    for key, entry in reversed(items):
        sha = entry.get("commit_sha", "—")[:8]
        run_id = entry.get("run_id", "—")[:8]
        scanned_at = entry.get("scanned_at", "—")[:16].replace("T", " ")
        table.add_row(key, sha, run_id, scanned_at)

    console.print(table)


@github_cmd.command("status")
def github_status():
    """Show GitHub integration status."""
    cfg = load_github_config()
    history = load_pr_scan_history()

    if cfg.get("connected"):
        console.print(f"[green]●[/green] Connected as [bold orange1]{cfg['github_user']}[/bold orange1]")
    else:
        console.print("[dim]○ Not connected[/dim]")
        console.print("  Connect: springinsight github connect --token ghp_xxxx")

    console.print(f"  Watched repos: [bold]{len(cfg.get('watched_repos', []))}[/bold]")
    console.print(f"  PRs scanned:   [bold]{len(history)}[/bold] total")
    console.print(f"  Poll interval: [bold]{cfg.get('poll_interval_minutes', 5)}[/bold] minutes")
    console.print(f"  Auto-comment:  [bold]{'yes' if cfg.get('auto_comment', True) else 'no'}[/bold]")
    console.print(f"  Threshold:     [bold]{cfg.get('comment_threshold', 'MEDIUM')}[/bold]")

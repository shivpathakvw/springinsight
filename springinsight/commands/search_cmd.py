"""
springinsight search — CLI for CodeSearch (Pillar 2 RAG).

Commands:
  springinsight search index <project>     # Build / rebuild semantic index
  springinsight search ask   <question>    # Ask a natural-language question
  springinsight search status              # Show index stats

<project> can be:
  - A local path              ./my-spring-app
  - A GitHub / GitLab URL     https://github.com/org/repo
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import click


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_work_dir() -> str:
    return os.environ.get("SPRINGINSIGHT_WORK_DIR", str(Path.home() / ".springinsight"))


def _chroma_dir(work_dir: str) -> str:
    d = os.path.join(work_dir, "chroma")
    os.makedirs(d, exist_ok=True)
    return d


def _db_path(work_dir: str) -> str:
    return os.path.join(work_dir, "springinsight.db")


def _resolve(source: str, work_dir: str) -> str:
    """
    Resolve *source* to an absolute local path.

    Accepts:
      - Any local filesystem path (relative or absolute, git repo or plain dir)
      - A GitHub / GitLab / Bitbucket URL  →  cloned into <work_dir>/repos/

    Returns the resolved absolute path as a string.
    """
    from ..utils.github import is_github_url, clone_or_update_repo

    if is_github_url(source):
        click.echo(f"  🌐 GitHub URL detected — cloning repo…")
        repo_path = clone_or_update_repo(source, Path(work_dir))
        click.echo(f"  📂 Cloned to: {repo_path}")
        return str(repo_path)

    # Local path (git repo or plain directory)
    p = Path(source).expanduser().resolve()
    if not p.exists():
        raise click.ClickException(f"Project path does not exist: {p}")
    return str(p)


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

@click.group("search")
def search_cmd():
    """CodeSearch: semantic natural-language search over your Spring Boot codebase."""
    pass


# ---------------------------------------------------------------------------
# index sub-command
# ---------------------------------------------------------------------------

@search_cmd.command("index")
@click.argument("project", default=".")
@click.option("--work-dir", default=None, help="SpringInsight work directory (default: ~/.springinsight)")
@click.option("--force", is_flag=True, default=False, help="Re-index even if already indexed")
def index_cmd(project, work_dir, force):
    """
    Index a Spring Boot project for semantic code search.

    PROJECT can be a local path or a GitHub URL.

    \b
    Examples:
      springinsight search index ./my-spring-app
      springinsight search index .
      springinsight search index https://github.com/spring-petclinic/spring-petclinic
    """
    work_dir = work_dir or _get_work_dir()
    project_path = _resolve(project, work_dir)

    click.echo(f"  📂 Project  : {project_path}")
    click.echo(f"  🗄️  DB       : {_db_path(work_dir)}")
    click.echo(f"  🔮 Chroma   : {_chroma_dir(work_dir)}")

    from ..rag.indexer import Indexer

    indexer = Indexer(db_path=_db_path(work_dir), chroma_dir=_chroma_dir(work_dir))

    if not force and indexer.is_indexed(project_path):
        state = indexer.get_status(project_path)
        import datetime
        ts = datetime.datetime.fromtimestamp(state.get("last_indexed", 0)).strftime("%Y-%m-%d %H:%M")
        click.echo(f"\n  ✅ Already indexed ({ts}, {state.get('chunk_count', 0)} chunks).")
        click.echo("     Use --force to re-index.\n")
        return

    click.echo()

    async def _run():
        start = time.time()
        async for progress in indexer.index(project_path):
            phase = progress.phase
            if phase == "done":
                icon = "✅"
            elif phase == "error":
                icon = "❌"
            elif phase == "scan":
                icon = "🔍"
            elif phase == "graph":
                icon = "🕸️ "
            elif phase == "embed":
                icon = "🔮"
            else:
                icon = "  "

            pct_str = f" [{progress.done}/{progress.total}]" if progress.total else ""
            click.echo(f"  {icon} {progress.message}{pct_str}")

            if phase in ("done", "error"):
                elapsed = time.time() - start
                click.echo(f"\n  ⏱️  Completed in {elapsed:.1f}s\n")
                if phase == "error":
                    sys.exit(1)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# ask sub-command
# ---------------------------------------------------------------------------

@search_cmd.command("ask")
@click.argument("question", nargs=-1, required=True)
@click.option("--project", "-p", default=".",
              help="Spring Boot project path or GitHub URL (default: current dir)")
@click.option("--work-dir", default=None, help="SpringInsight work directory")
@click.option("--top-k", default=10, help="Number of vector results to retrieve (default: 10)")
def ask_cmd(question, project, work_dir, top_k):
    """
    Ask a natural-language question about your indexed Spring Boot codebase.

    --project accepts a local path or a GitHub URL (must be indexed first).

    \b
    Examples:
      springinsight search ask "which classes handle payment retry?"
      springinsight search ask "how is JWT validation implemented?" -p ./my-app
      springinsight search ask "list all @Scheduled jobs" -p https://github.com/org/repo
    """
    work_dir = work_dir or _get_work_dir()
    project_path = _resolve(project, work_dir)
    q = " ".join(question)

    from ..rag.searcher import Searcher

    searcher = Searcher(db_path=_db_path(work_dir), chroma_dir=_chroma_dir(work_dir))

    click.echo(f"\n  🔍 Query: {q}")
    click.echo(f"  📂 Project: {project_path}\n")

    async def _run():
        result = await searcher.search(project_path, q, top_k=top_k)

        if result.error:
            click.echo(f"  ❌ {result.error}")
            click.echo("     Run:  springinsight search index <project>  first.\n")
            sys.exit(1)

        click.echo("─" * 70)
        click.echo(result.answer)
        click.echo("─" * 70)

        if result.sources:
            click.echo("\n  📋 Sources:")
            for i, src in enumerate(result.sources[:6], 1):
                score_bar = "█" * int(src.score * 10) + "░" * (10 - int(src.score * 10))
                click.echo(f"    {i}. [{score_bar}] {src.node_type.upper()}: {src.simple_name}")
                click.echo(f"       {src.file_path}:{src.line_start}")
        click.echo()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# status sub-command
# ---------------------------------------------------------------------------

@search_cmd.command("status")
@click.option("--project", "-p", default=".",
              help="Spring Boot project path or GitHub URL")
@click.option("--work-dir", default=None)
def status_cmd(project, work_dir):
    """Show index status and statistics for a project."""
    work_dir = work_dir or _get_work_dir()
    project_path = _resolve(project, work_dir)

    from ..rag.indexer import Indexer

    indexer = Indexer(db_path=_db_path(work_dir), chroma_dir=_chroma_dir(work_dir))
    status = indexer.get_status(project_path)

    if status.get("status") == "not_indexed":
        click.echo(f"\n  ⚪ Not indexed: {project_path}")
        click.echo("     Run:  springinsight search index <project>\n")
        return

    import datetime
    ts = datetime.datetime.fromtimestamp(status.get("last_indexed", 0)).strftime("%Y-%m-%d %H:%M:%S")
    click.echo(f"\n  ✅ Index status for: {project_path}")
    click.echo(f"     Last indexed : {ts}")
    click.echo(f"     Files        : {status.get('file_count', 0)}")
    click.echo(f"     Chunks       : {status.get('chunk_count', 0)}")
    click.echo(f"     Graph nodes  : {status.get('nodes', 0)}")
    click.echo(f"     Graph edges  : {status.get('edges', 0)}")
    by_type = status.get("by_type", {})
    if by_type:
        click.echo("     Node types   :")
        for ntype, count in sorted(by_type.items()):
            click.echo(f"       {ntype:<12} {count}")
    click.echo()

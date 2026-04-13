"""
springinsight search — CLI for CodeSearch (Pillar 2 RAG).

Commands:
  springinsight search index <project>          # Build / rebuild semantic index
  springinsight search ask   <question>         # Ask a natural-language question
  springinsight search status                   # Show index stats

  Add --verbose / -v to any command for full debug output.

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
        click.echo(f"  🌐 GitHub URL detected — cloning / updating repo…")
        repo_path = clone_or_update_repo(source, Path(work_dir))
        click.echo(f"  📂 Local path  : {repo_path}")
        return str(repo_path)

    p = Path(source).expanduser().resolve()
    if not p.exists():
        raise click.ClickException(f"Project path does not exist: {p}")
    return str(p)


def _dim(s: str) -> str:
    """Gray ANSI text for less important output."""
    return f"\033[2m{s}\033[0m"


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _cyan(s: str) -> str:
    return f"\033[36m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def _score_bar(score: float, width: int = 10) -> str:
    filled = round(score * width)
    return "█" * filled + "░" * (width - filled)


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
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show verbose debug output")
def index_cmd(project, work_dir, force, verbose):
    """
    Index a Spring Boot project for semantic code search.

    PROJECT can be a local path or a GitHub URL.

    \b
    Examples:
      springinsight search index ./my-spring-app
      springinsight search index . --verbose
      springinsight search index https://github.com/spring-petclinic/spring-petclinic
    """
    work_dir = work_dir or _get_work_dir()
    project_path = _resolve(project, work_dir)

    db  = _db_path(work_dir)
    chroma = _chroma_dir(work_dir)

    click.echo(f"\n  📂 Project  : {project_path}")
    click.echo(f"  🗄️  DB       : {db}")
    click.echo(f"  🔮 Chroma   : {chroma}")

    if verbose:
        click.echo(f"  {_dim('⚙️  Model    : all-MiniLM-L6-v2  (384-dim cosine)')}")
        click.echo(f"  {_dim('⚙️  Batch sz : 64 chunks per embedding call')}")
        click.echo(f"  {_dim('⚙️  Graph    : SQLite code_nodes + code_edges')}")

    from ..rag.indexer import Indexer

    indexer = Indexer(db_path=db, chroma_dir=chroma)

    if not force and indexer.is_indexed(project_path):
        state = indexer.get_status(project_path)
        import datetime
        ts = datetime.datetime.fromtimestamp(state.get("last_indexed", 0)).strftime("%Y-%m-%d %H:%M")
        click.echo(f"\n  ✅ Already indexed ({ts}, {state.get('chunk_count', 0)} chunks).")
        if verbose:
            _print_index_status_verbose(state)
        click.echo("     Use --force to re-index.\n")
        return

    click.echo()

    phase_times: dict = {}
    phase_start = [time.time()]

    async def _run():
        start = time.time()
        last_phase = [None]

        async for progress in indexer.index(project_path):
            phase = progress.phase

            # Track phase transitions for timing
            if phase != last_phase[0]:
                if last_phase[0] is not None:
                    phase_times[last_phase[0]] = time.time() - phase_start[0]
                phase_start[0] = time.time()
                last_phase[0] = phase

            icon = {
                "done": "✅", "error": "❌",
                "scan": "🔍", "graph": "🕸️ ",
                "embed": "🔮",
            }.get(phase, "  ")

            pct_str = f" [{progress.done}/{progress.total}]" if progress.total else ""

            if verbose:
                # Show every progress event with timing
                elapsed = time.time() - start
                click.echo(f"  {icon} {progress.message}{pct_str}  {_dim(f'{elapsed:.1f}s')}")
            else:
                # Only show phase changes and final lines
                if progress.done == 0 or phase in ("done", "error"):
                    click.echo(f"  {icon} {progress.message}{pct_str}")

            if phase in ("done", "error"):
                phase_times[phase] = time.time() - phase_start[0]
                elapsed = time.time() - start
                click.echo()

                if verbose:
                    _print_phase_timing(phase_times, elapsed)
                    # After indexing, show chunk type breakdown from graph
                    _print_chunk_breakdown(indexer, project_path, verbose)
                else:
                    click.echo(f"  ⏱️  Completed in {elapsed:.1f}s\n")

                if phase == "error":
                    sys.exit(1)

    asyncio.run(_run())


def _print_phase_timing(phase_times: dict, total: float):
    click.echo(f"  ⏱️  Phase timings:")
    names = {"scan": "🔍 Scan", "graph": "🕸️  Graph", "embed": "🔮 Embed", "done": "✅ Done"}
    for ph, name in names.items():
        if ph in phase_times:
            t = phase_times[ph]
            bar_len = max(1, round(t / total * 20))
            bar = "▓" * bar_len + "░" * (20 - bar_len)
            click.echo(f"     {name:<12} {_dim(bar)}  {t:.2f}s  ({t/total*100:.0f}%)")
    click.echo(f"     {'Total':<12}                        {total:.2f}s\n")


def _print_chunk_breakdown(indexer, project_path: str, verbose: bool):
    try:
        status = indexer.get_status(project_path)
        by_type = status.get("by_type", {})
        if not by_type:
            return
        click.echo(f"  📊 Chunk breakdown by type:")
        total_chunks = sum(by_type.values())
        for ctype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            bar = "█" * round(count / total_chunks * 20)
            pct = count / total_chunks * 100
            click.echo(f"     {ctype:<12} {count:>5}  {_dim(bar)}  {pct:.0f}%")
        click.echo(f"     {'TOTAL':<12} {total_chunks:>5}\n")
    except Exception:
        pass


def _print_index_status_verbose(state: dict):
    by_type = state.get("by_type", {})
    if by_type:
        click.echo(f"\n  📊 Indexed chunk types:")
        for ctype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            click.echo(f"     {ctype:<12} {count}")
    nodes = state.get("nodes", 0)
    edges = state.get("edges", 0)
    click.echo(f"  🕸️  Graph      : {nodes} nodes, {edges} edges")


# ---------------------------------------------------------------------------
# ask sub-command
# ---------------------------------------------------------------------------

@search_cmd.command("ask")
@click.argument("question", nargs=-1, required=True)
@click.option("--project", "-p", default=".",
              help="Spring Boot project path or GitHub URL (default: current dir)")
@click.option("--work-dir", default=None, help="SpringInsight work directory")
@click.option("--top-k", default=10, help="Number of vector results to retrieve (default: 10)")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show debug output: scores, graph expansion, context size")
def ask_cmd(question, project, work_dir, top_k, verbose):
    """
    Ask a natural-language question about your indexed Spring Boot codebase.

    --project accepts a local path or a GitHub URL (must be indexed first).

    \b
    Examples:
      springinsight search ask "which classes handle payment retry?"
      springinsight search ask "how is JWT validation implemented?" --verbose
      springinsight search ask "list all @Scheduled jobs" -p ./my-app -v
      springinsight search ask "explain auth flow" -p https://github.com/org/repo
    """
    work_dir = work_dir or _get_work_dir()
    project_path = _resolve(project, work_dir)
    q = " ".join(question)

    from ..rag.searcher import Searcher

    searcher = Searcher(db_path=_db_path(work_dir), chroma_dir=_chroma_dir(work_dir))

    click.echo(f"\n  🔍 Query   : {_cyan(q)}")
    click.echo(f"  📂 Project : {project_path}")
    if verbose:
        click.echo(f"  {_dim(f'⚙️  top-k    : {top_k} vector results + graph expansion')}")
        click.echo(f"  {_dim(f'⚙️  max ctx  : 12,000 chars sent to Claude Sonnet')}")
    click.echo()

    async def _run():
        wall_start = time.time()
        result = await searcher.search(project_path, q, top_k=top_k)

        if result.error:
            click.echo(f"  ❌ {result.error}")
            click.echo("     Run:  springinsight search index <project>  first.\n")
            sys.exit(1)

        if verbose:
            _print_ask_debug(result, wall_start)

        # Answer
        click.echo("─" * 72)
        click.echo(result.answer)
        click.echo("─" * 72)

        # Sources
        click.echo("\n  📋 Sources  (top results):")
        for i, src in enumerate(result.sources[:top_k], 1):
            bar = _score_bar(src.score)
            dim_loc = _dim(f"{src.file_path}:{src.line_start}")
            if verbose:
                click.echo(f"    {i:>2}. [{_green(bar)}] {src.score:.3f}  "
                           f"{src.node_type.upper():<8}  {src.simple_name}")
                click.echo(f"         {dim_loc}")
                if src.snippet:
                    snippet_lines = src.snippet.strip().splitlines()[:3]
                    for sl in snippet_lines:
                        click.echo(f"         {_dim(sl)}")
                click.echo()
            else:
                click.echo(f"    {i:>2}. [{bar}] {src.node_type.upper()}: {src.simple_name}")
                click.echo(f"         {dim_loc}")

        if verbose:
            total_wall = time.time() - wall_start
            click.echo(f"\n  ⏱️  Wall time: {total_wall:.2f}s  "
                       f"(embed: {result.embed_time:.3f}s  "
                       f"search: {result.search_time:.3f}s  "
                       f"claude: {total_wall - result.embed_time - result.search_time:.2f}s)")
        click.echo()

    asyncio.run(_run())


def _print_ask_debug(result, wall_start: float):
    """Print verbose debug block before the answer."""
    sep = _dim("─" * 72)
    click.echo(f"  {sep}")
    click.echo(f"  {_dim('DEBUG — CodeSearch pipeline')}")
    click.echo(f"  {sep}")
    click.echo(f"  {_dim(f'Collection size  : {result.collection_size} chunks indexed')}")
    click.echo(f"  {_dim(f'Embed query      : {result.embed_time*1000:.0f} ms  (all-MiniLM-L6-v2)')}")
    click.echo(f"  {_dim(f'Vector search    : {result.search_time*1000:.0f} ms  → {len(result.sources)} results returned')}")
    click.echo(f"  {_dim(f'Graph expansion  : {result.graph_expansion_count} neighbour nodes added to context')}")
    click.echo(f"  {_dim(f'Context window   : {result.context_chars:,} chars / 12,000 max  ({result.context_blocks} blocks)')}")
    click.echo()

    click.echo(f"  {_dim('Vector search results (ranked by cosine similarity):')}")
    for i, src in enumerate(result.sources, 1):
        bar = _score_bar(src.score)
        line1 = f"{i:>2}. [{bar}] {src.score:.3f}  {src.node_type.upper():<9} {src.simple_name}"
        line2 = f"{src.file_path}:{src.line_start}"
        click.echo(f"    {_dim(line1)}")
        click.echo(f"        {_dim(line2)}")

    click.echo()
    click.echo(f"  {_dim('Sending context to Claude Sonnet → streaming answer...')}")
    click.echo(f"  {sep}\n")


# ---------------------------------------------------------------------------
# status sub-command
# ---------------------------------------------------------------------------

@search_cmd.command("status")
@click.option("--project", "-p", default=".",
              help="Spring Boot project path or GitHub URL")
@click.option("--work-dir", default=None)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show full breakdown")
def status_cmd(project, work_dir, verbose):
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
        total = sum(by_type.values())
        for ntype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            bar = "█" * round(count / total * 15) if verbose else ""
            pct = f"  {count/total*100:.0f}%" if verbose else ""
            click.echo(f"       {ntype:<12} {count:>5}{pct}  {_dim(bar)}")

    if verbose:
        click.echo(f"\n     DB path      : {_db_path(work_dir)}")
        click.echo(f"     Chroma path  : {_chroma_dir(work_dir)}")
        click.echo(f"     Work dir     : {work_dir}")

    click.echo()

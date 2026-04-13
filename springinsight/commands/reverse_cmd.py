"""springinsight reverse — reverse engineer a Spring Boot codebase into documentation.

Runs the A18 Reverse Engineering agent in either high-level or in-depth mode.

High-level mode (default):
  Produces ARCHITECTURE.md — feature catalogue, module map, integration inventory,
  Spring bean wiring summary, data model overview. Ideal for architects and new joiners.

In-depth mode:
  Produces TECHNICAL-REFERENCE.md — full call graphs, transaction boundary analysis,
  Mermaid sequence diagrams, event flows, configuration deep-dive, exception handling chains.
  Ideal for senior developers, code reviewers, and security auditors.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text

from ..agents.registry import AGENT_REGISTRY
from ..agents.runner import run_agent_async
from ..context.loader import load_context
from ..db.database import get_db, init_db
from ..db.models import AgentRun, Finding, Run
from ..utils.github import resolve_project_path

console = Console()


@click.command("reverse")
@click.argument("target", required=False, default=None, metavar="[PATH_OR_URL]")
@click.option("--project", "-p", default=None, help="Project path or GitHub URL")
@click.option("--work-dir", "-w", default=".", help="SpringInsight working directory")
@click.option(
    "--mode", "-m",
    type=click.Choice(["high-level", "in-depth"], case_sensitive=False),
    default="high-level",
    show_default=True,
    help=(
        "Analysis depth.\n\n"
        "high-level: feature catalogue, module map, integration inventory, "
        "Spring bean wiring, data model overview (~3–5 pages).\n\n"
        "in-depth: full call graphs per endpoint, transaction boundary traces, "
        "Mermaid sequence diagrams, event flows, config deep-dive, "
        "exception handling chains (~15–40 pages)."
    ),
)
@click.option(
    "--focus", "-f", default=None, metavar="TARGET",
    help=(
        "Scope in-depth analysis to a specific class, package, or endpoint. "
        "Examples: --focus OrderService  --focus com.example.orders  "
        "--focus 'POST /api/orders'"
    ),
)
@click.option("--no-db", is_flag=True, help="Skip saving to SQLite DB")
@click.option("--output", "-o", default=None, metavar="FILE",
              help="Write documentation to this file (default: auto-named in run directory)")
def reverse_cmd(
    target: str | None,
    project: str | None,
    work_dir: str,
    mode: str,
    focus: str | None,
    no_db: bool,
    output: str | None,
):
    """Reverse engineer a Spring Boot codebase into structured documentation.

    Runs the A18 Reverse Engineering agent in one of two modes:

    \b
    HIGH-LEVEL (default):
      Produces ARCHITECTURE.md — feature catalogue, module map, API surface,
      integration inventory, Spring bean wiring. ~3–5 pages.
      Best for: architects, tech leads, new team members.

    \b
    IN-DEPTH:
      Produces TECHNICAL-REFERENCE.md — full call graphs per endpoint,
      @Transactional boundary analysis, Mermaid sequence diagrams, event flows,
      config deep-dive, exception handling chains. ~15–40 pages.
      Best for: senior developers, reviewers, security auditors.

    \b
    Examples:
      springinsight reverse ./my-app
      springinsight reverse ./my-app --mode in-depth
      springinsight reverse ./my-app --mode in-depth --focus OrderService
      springinsight reverse ./my-app --mode in-depth --focus "POST /api/orders"
      springinsight reverse https://github.com/org/repo --mode high-level
    """
    project = target or project
    work_path = Path(work_dir).expanduser().resolve()

    # ── Load context ────────────────────────────────────────────────────────
    ctx = load_context(work_path)
    if not ctx.base_path and not project:
        console.print(
            "[red]No project configured.[/red] "
            "Run [bold]springinsight init[/bold] first, or pass a path/URL."
        )
        raise click.Abort()

    source = project or ctx.base_path

    # ── Resolve project path ─────────────────────────────────────────────────
    try:
        with console.status("Resolving project…"):
            project_path, source_type, source_url = resolve_project_path(source, work_path)
    except Exception as e:
        console.print(f"[red]Error resolving project:[/red] {e}")
        raise click.Abort()

    # ── Get A18 agent ───────────────────────────────────────────────────────
    agent = AGENT_REGISTRY.get("A18")
    if not agent:
        console.print("[red]A18 Reverse Engineering agent not found in registry.[/red]")
        raise click.Abort()

    # ── Build run ID and directories ─────────────────────────────────────────
    run_id = str(uuid.uuid4())[:8]
    full_run_id = f"{datetime.utcnow().strftime('%Y-%m-%d')}-{run_id}"
    run_dir = work_path / ".springinsight" / "runs" / full_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── Determine output path ────────────────────────────────────────────────
    if output:
        custom_output = Path(output).expanduser().resolve()
        custom_output.parent.mkdir(parents=True, exist_ok=True)
    else:
        custom_output = None

    # ── Build mode-specific extra_scope block ────────────────────────────────
    mode_upper = mode.upper().replace("-", "_")  # HIGH_LEVEL or IN_DEPTH
    focus_line = f"REVERSE_TARGET  : {focus}" if focus else "REVERSE_TARGET  : (full project)"
    extra_scope = (
        f"REVERSE_MODE    : {mode}\n"
        f"{focus_line}\n"
        f"EXPECTED_OUTPUT : {'ARCHITECTURE.md' if mode == 'high-level' else 'TECHNICAL-REFERENCE.md'}"
    )

    # ── Init DB ──────────────────────────────────────────────────────────────
    if not no_db:
        init_db(work_path)
        with get_db() as db:
            run_record = Run(
                id=full_run_id,
                project_name=ctx.name,
                project_path=str(project_path),
                source_type=source_type,
                source_url=source_url,
                agents_requested=["A18"],
                context_snapshot=ctx._raw,
            )
            db.add(run_record)

    # ── Print header ─────────────────────────────────────────────────────────
    mode_label = "High-Level" if mode == "high-level" else "In-Depth"
    focus_label = f" · Target: [bold]{focus}[/bold]" if focus else ""
    console.print()
    console.print(Panel.fit(
        f"[bold yellow]SpringInsight[/bold yellow] — Reverse Engineering\n"
        f"  Project : [bold]{project_path.name}[/bold] ({source_type})\n"
        f"  Mode    : [bold cyan]{mode_label}[/bold cyan]{focus_label}\n"
        f"  Agent   : A18 (claude-opus-4-6)\n"
        f"  Run ID  : [dim]{full_run_id}[/dim]",
        border_style="cyan"
    ))
    console.print()

    if mode == "in-depth" and not focus:
        console.print(
            "[dim]ℹ Tip: Use [bold]--focus ClassName[/bold] to restrict in-depth analysis "
            "to a specific class, package, or endpoint for faster results.[/dim]"
        )
        console.print()

    # ── Run A18 agent ─────────────────────────────────────────────────────────
    started_at = datetime.utcnow()

    log_lines: list[str] = []

    def log_cb(agent_id: str, msg: str) -> None:
        log_lines.append(msg)

    spinner_text = Text()

    async def _run():
        return await run_agent_async(
            agent=agent,
            ctx=ctx,
            project_path=str(project_path),
            run_dir=run_dir,
            run_id=full_run_id,
            extra_scope=extra_scope,
            log_callback=log_cb,
            use_file_scope=False,   # A18 needs full project visibility
            use_incremental=False,  # always fresh for documentation
        )

    with Live(console=console, refresh_per_second=2) as live:
        elapsed_seconds = [0]

        async def _run_with_display():
            task = asyncio.create_task(_run())
            while not task.done():
                elapsed_seconds[0] += 1
                last_log = log_lines[-1] if log_lines else "Starting analysis…"
                live.update(
                    Text(f"  ⚡ [A18] {last_log}  ({elapsed_seconds[0]}s elapsed)", style="yellow")
                )
                await asyncio.sleep(1)
            live.update(Text("  ✅ Analysis complete", style="green"))
            return await task

        result = asyncio.run(_run_with_display())

    # ── Handle custom output path ─────────────────────────────────────────────
    output_md = result.get("output_md")
    if custom_output and output_md and Path(output_md).exists():
        import shutil
        shutil.copy2(output_md, custom_output)
        output_md = str(custom_output)
        console.print(f"[dim]Documentation copied to {custom_output}[/dim]")

    # ── Persist results to DB ─────────────────────────────────────────────────
    findings = result.get("findings", [])
    completed_at = datetime.utcnow()

    if not no_db:
        with get_db() as db:
            ar = AgentRun(
                run_id=full_run_id,
                agent_id="A18",
                agent_name=agent.name,
                model=agent.model,
                status=result["status"],
                started_at=result.get("started_at"),
                completed_at=result.get("completed_at"),
                findings_count=len(findings),
                error_message=result.get("error"),
                output_json_path=result.get("output_json"),
                output_md_path=output_md,
            )
            db.add(ar)

            for f in findings:
                db.add(Finding(
                    run_id=full_run_id,
                    agent_id="A18",
                    severity=f.get("severity", "INFO"),
                    category=f.get("category", "Reverse Engineering"),
                    subcategory=f.get("subcategory"),
                    file_path=f.get("file"),
                    line_number=f.get("line"),
                    class_name=f.get("class_name"),
                    method_name=f.get("method_name"),
                    problem=f.get("problem", ""),
                    impact=f.get("impact"),
                    fix_description=f.get("fix"),
                    fix_code=f.get("fix_code"),
                    actionable=f.get("actionable", False),
                    effort_hours=f.get("effort_hours"),
                ))

            run_rec = db.query(Run).filter(Run.id == full_run_id).first()
            if run_rec:
                run_rec.completed_at = completed_at
                run_rec.status = "complete" if result["status"] == "complete" else "failed"
                run_rec.agents_completed = ["A18"] if result["status"] == "complete" else []

    # ── Print summary ─────────────────────────────────────────────────────────
    console.print()
    duration = (completed_at - started_at).total_seconds()

    if result["status"] == "failed":
        console.print(Panel.fit(
            f"[red]❌ A18 failed after {duration:.0f}s[/red]\n\n"
            f"  Error: {result.get('error', 'unknown')[:200]}",
            border_style="red"
        ))
        raise click.Abort()

    # Count findings by severity
    gaps = [f for f in findings if f.get("severity") in ("MEDIUM", "HIGH")]
    info_count = sum(1 for f in findings if f.get("severity") == "INFO")

    doc_type = "ARCHITECTURE.md" if mode == "high-level" else "TECHNICAL-REFERENCE.md"

    summary_lines = [
        f"[green]✓ {doc_type} generated in {duration:.0f}s[/green]\n",
        f"  Mode    : {mode_label}",
    ]
    if focus:
        summary_lines.append(f"  Target  : {focus}")
    summary_lines += [
        f"  Features: {info_count} documented",
        f"  Issues  : {len(gaps)} documentation gap(s) found",
        f"\n  Report  : [bold]{output_md or run_dir / 'agents' / 'A18-reverse-engineering.md'}[/bold]",
        f"  UI      : [bold yellow]springinsight web[/bold yellow]",
    ]

    console.print(Panel.fit(
        "\n".join(summary_lines),
        border_style="green"
    ))

    # Print documentation gaps if any
    if gaps:
        console.print()
        console.print(f"[yellow]Documentation gaps found:[/yellow]")
        for g in gaps[:8]:
            sev_color = "red" if g.get("severity") == "HIGH" else "yellow"
            console.print(
                f"  [{sev_color}]{g.get('severity')}[/{sev_color}] "
                f"{g.get('class_name', g.get('file', '?'))} — {g.get('problem', '')[:90]}"
            )
        if len(gaps) > 8:
            console.print(f"  [dim]… and {len(gaps) - 8} more (see full report)[/dim]")

    console.print()

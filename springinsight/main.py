"""SpringInsight CLI entry point."""

from __future__ import annotations

import click
from rich.console import Console

from . import __version__
from .commands import context_cmd, github_cmd, init_cmd, report_cmd, run_cmd, web_cmd
from .commands.mcp_cmd import mcp_cmd
from .commands.reverse_cmd import reverse_cmd
from .utils.env import load_env as _load_env

# Load .env from CWD / home directory on startup so ANTHROPIC_API_KEY is
# available to all `claude --print` subprocesses without manual export.
_load_env()

console = Console()

BANNER = """
[bold yellow]
  ███████╗██████╗ ██████╗ ██╗███╗   ██╗ ██████╗
  ██╔════╝██╔══██╗██╔══██╗██║████╗  ██║██╔════╝
  ███████╗██████╔╝██████╔╝██║██╔██╗ ██║██║  ███╗
  ╚════██║██╔═══╝ ██╔══██╗██║██║╚██╗██║██║   ██║
  ███████║██║     ██║  ██║██║██║ ╚████║╚██████╔╝
  ╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝ ╚═════╝
     [dim]INSIGHT[/dim]
[/bold yellow]
[dim]Autonomous multi-agent codebase intelligence for Java / Spring Boot[/dim]
"""


@click.group()
@click.version_option(version=__version__, prog_name="springinsight")
def cli():
    """SpringInsight — Autonomous codebase intelligence for Java / Spring Boot.

    Run agents to scan your project for code quality, security, CVEs,
    dead code, config issues, and more.

    Quick start:\n
      springinsight init --project /path/to/project\n
      springinsight run\n
      springinsight report
    """
    pass


# Register subcommands
cli.add_command(init_cmd, name="init")
cli.add_command(run_cmd, name="run")
cli.add_command(report_cmd, name="report")
cli.add_command(web_cmd, name="web")
cli.add_command(mcp_cmd, name="mcp")
cli.add_command(context_cmd, name="context")
cli.add_command(github_cmd, name="github")
cli.add_command(reverse_cmd, name="reverse")


# ── findings subcommand ─────────────────────────────────────────────────────
@cli.command("findings")
@click.option("--work-dir", "-w", default=".", help="SpringInsight working directory")
@click.option("--severity", "-s", default=None, help="Filter by severity (CRITICAL,HIGH,...)")
@click.option("--run-id", "-r", default=None, help="Specific run ID")
@click.option("--status", default="open", help="Filter by status (open|fixed|acknowledged|all)")
@click.pass_context
def findings_cmd(ctx, work_dir, severity, run_id, status):
    """List findings from the latest run.

    Examples:\n
      springinsight findings\n
      springinsight findings --severity CRITICAL,HIGH\n
      springinsight findings --status all
    """
    from pathlib import Path
    from .db.database import get_db, init_db
    from .db.models import Finding, Run

    work_path = Path(work_dir).expanduser().resolve()
    init_db(work_path)

    with get_db() as db:
        if run_id:
            run = db.query(Run).filter(Run.id == run_id).first()
        else:
            run = db.query(Run).order_by(Run.started_at.desc()).first()

        if not run:
            console.print("[yellow]No runs found.[/yellow]")
            return

        q = db.query(Finding).filter(Finding.run_id == run.id)
        if severity:
            sevs = [s.strip().upper() for s in severity.split(",")]
            q = q.filter(Finding.severity.in_(sevs))
        if status != "all":
            q = q.filter(Finding.status == status)

        findings = q.order_by(Finding.severity).all()

    console.print(f"\n[bold]Findings[/bold] from run [bold]{run.id}[/bold] ({len(findings)} results)\n")
    for f in findings:
        from .commands.report_cmd import SEV_COLORS
        sev_color = SEV_COLORS.get(f.severity, "white")
        loc = f"{f.file_path}:{f.line_number}" if f.line_number else (f.file_path or "?")
        console.print(f"  [{sev_color}]{f.severity}[/{sev_color}]  [{f.agent_id}]  {loc}")
        console.print(f"    {f.problem}")
        if f.fix_description:
            console.print(f"    [dim]Fix: {f.fix_description[:80]}[/dim]")
        console.print()


# ── history subcommand ──────────────────────────────────────────────────────
@cli.command("history")
@click.option("--work-dir", "-w", default=".", help="SpringInsight working directory")
@click.option("--limit", "-n", default=10, help="Number of runs to show")
def history_cmd(work_dir, limit):
    """Show run history with scores.

    Example: springinsight history --limit 5
    """
    from pathlib import Path
    from rich.table import Table
    from .db.database import get_db, init_db
    from .db.models import Run

    work_path = Path(work_dir).expanduser().resolve()
    init_db(work_path)

    with get_db() as db:
        runs = db.query(Run).order_by(Run.started_at.desc()).limit(limit).all()

    if not runs:
        console.print("[yellow]No runs found.[/yellow]")
        return

    table = Table(title="Run History", show_header=True, header_style="bold yellow")
    table.add_column("Run ID", style="bold", width=22)
    table.add_column("Project", width=20)
    table.add_column("Date", width=17)
    table.add_column("Status", width=10)
    table.add_column("Overall", justify="center", width=10)
    table.add_column("Security", justify="center", width=10)
    table.add_column("Findings", justify="right", width=10)

    for run in runs:
        status_str = "[green]✅[/green]" if run.status == "complete" else "[red]❌[/red]"
        overall = f"{run.score_overall}/100" if run.score_overall is not None else "—"
        security = f"{run.score_security}/100" if run.score_security is not None else "—"
        finding_count = len(run.findings) if run.findings else 0
        date_str = run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "?"

        table.add_row(run.id, run.project_name[:18], date_str, status_str, overall, security, str(finding_count))

    console.print()
    console.print(table)
    console.print()


# ── agents subcommand ───────────────────────────────────────────────────────
@cli.command("agents")
def agents_cmd():
    """List all available agents with their status (enabled/phase)."""
    from rich.table import Table
    from .agents.registry import AGENT_REGISTRY, PHASE_ORDER

    table = Table(title="Available Agents", show_header=True, header_style="bold yellow")
    table.add_column("ID", style="bold", width=6)
    table.add_column("Name", width=28)
    table.add_column("Model", width=10)
    table.add_column("Phase", justify="center", width=7)
    table.add_column("Status", width=12)
    table.add_column("Description", width=50)

    for phase_num in sorted(PHASE_ORDER.keys()):
        for agent_id in PHASE_ORDER[phase_num]:
            agent = AGENT_REGISTRY.get(agent_id)
            if not agent:
                continue
            model_short = agent.model.split("-")[1] if "-" in agent.model else agent.model
            status = "[green]✅ ready[/green]" if agent.enabled else "[dim]🔜 soon[/dim]"
            table.add_row(
                agent.id, agent.name, model_short, str(phase_num), status, agent.description[:48]
            )

    console.print()
    console.print(table)
    console.print()
    console.print("[dim]Phase 1 — Haiku  (fast scan):      A03, A10, A12[/dim]")
    console.print("[dim]Phase 2 — Sonnet (deep analysis):  A01, A02, A04, A09, A11, A13, A14, A15, A16, A17[/dim]")
    console.print("[dim]Phase 3 — Opus   (architecture):   A05, A08, A18 (Reverse Engineering)[/dim]")
    console.print("[dim]Phase 4 — Sonnet (generation):     A06, A07[/dim]")
    console.print()
    console.print("[dim]Run A18 directly: [bold]springinsight reverse ./my-app[/bold][/dim]\n")


if __name__ == "__main__":
    cli()

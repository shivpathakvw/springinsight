"""springinsight report — show run summary in terminal."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..db.database import get_db, init_db
from ..db.models import AgentRun, Finding, Run

console = Console()

SEV_COLORS = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "dim"}


@click.command("report")
@click.option("--work-dir", "-w", default=".", help="SpringInsight working directory")
@click.option("--run-id", "-r", default=None, help="Specific run ID (defaults to latest)")
@click.option("--severity", "-s", default=None, help="Filter findings by severity (CRITICAL,HIGH,...)")
@click.option("--agent", "-a", default=None, help="Filter findings by agent ID")
@click.option("--export", "-e", default=None, help="Export MASTER-REPORT.md to this path")
@click.option("--findings-only", is_flag=True, help="Show only findings table, no scores")
def report_cmd(work_dir: str, run_id: str | None, severity: str | None, agent: str | None, export: str | None, findings_only: bool):
    """Display the latest (or specified) run report.

    Examples:\n
      springinsight report\n
      springinsight report --severity CRITICAL,HIGH\n
      springinsight report --run-id 2026-04-11-abc123\n
      springinsight report --export /tmp/report.md
    """
    work_path = Path(work_dir).expanduser().resolve()
    init_db(work_path)

    with get_db() as db:
        # Get run
        if run_id:
            run = db.query(Run).filter(Run.id == run_id).first()
        else:
            run = db.query(Run).order_by(Run.started_at.desc()).first()

        if not run:
            console.print("[yellow]No runs found.[/yellow] Run [bold]springinsight run[/bold] first.")
            return

        # Get findings
        q = db.query(Finding).filter(Finding.run_id == run.id)
        if severity:
            sevs = [s.strip().upper() for s in severity.split(",")]
            q = q.filter(Finding.severity.in_(sevs))
        if agent:
            q = q.filter(Finding.agent_id == agent.upper())
        findings = q.order_by(Finding.severity).all()

        # Get agent runs
        agent_runs = db.query(AgentRun).filter(AgentRun.run_id == run.id).all()

    # ── Header ────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel.fit(
        f"[bold yellow]SpringInsight Report[/bold yellow]\n"
        f"  Project : [bold]{run.project_name}[/bold]\n"
        f"  Run ID  : [bold]{run.id}[/bold]\n"
        f"  Date    : {run.started_at.strftime('%Y-%m-%d %H:%M UTC') if run.started_at else '?'}\n"
        f"  Status  : {'[green]complete[/green]' if run.status == 'complete' else '[red]' + run.status + '[/red]'}\n"
        f"  Source  : {run.project_path}",
        border_style="yellow"
    ))

    if not findings_only:
        # ── Scores ────────────────────────────────────────────────────────
        score_table = Table(title="Quality Scores", show_header=True, header_style="bold")
        score_table.add_column("Dimension", style="bold", width=30)
        score_table.add_column("Score", justify="center", width=12)
        score_table.add_column("Bar", width=30)

        score_fields = [
            ("Overall", run.score_overall),
            ("Security", run.score_security),
            ("Code Quality", run.score_code_quality),
            ("Architecture", run.score_architecture),
            ("API Design", run.score_api_design),
            ("Test Coverage", run.score_test_coverage),
            ("Production Readiness", run.score_production_readiness),
        ]
        for label, score in score_fields:
            if score is None:
                continue
            color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
            bar_filled = int((score / 100) * 20)
            bar = f"[{color}]{'█' * bar_filled}[/{color}]{'░' * (20 - bar_filled)}"
            score_table.add_row(label, f"[{color}]{score}/100[/{color}]", bar)
        console.print()
        console.print(score_table)

        # ── Agent Summary ─────────────────────────────────────────────────
        if agent_runs:
            ar_table = Table(title="Agent Results", show_header=True, header_style="bold")
            ar_table.add_column("Agent", style="bold", width=26)
            ar_table.add_column("Model", width=10)
            ar_table.add_column("Status", width=12)
            ar_table.add_column("Findings", justify="right", width=10)
            ar_table.add_column("Duration", justify="right", width=10)

            for ar in sorted(agent_runs, key=lambda x: x.agent_id):
                status_str = "[green]✅ done[/green]" if ar.status == "complete" else "[red]❌ failed[/red]"
                dur = ""
                if ar.duration_seconds is not None:
                    dur = f"{ar.duration_seconds:.0f}s"
                model_short = ar.model.split("-")[1] if ar.model and "-" in ar.model else ar.model or "?"
                ar_table.add_row(
                    f"{ar.agent_id} {ar.agent_name}",
                    model_short,
                    status_str,
                    str(ar.findings_count or 0),
                    dur,
                )
            console.print()
            console.print(ar_table)

    # ── Findings table ─────────────────────────────────────────────────────
    if findings:
        f_table = Table(
            title=f"Findings ({len(findings)} total{' — filtered' if severity or agent else ''})",
            show_header=True, header_style="bold", show_lines=False
        )
        f_table.add_column("#", width=4)
        f_table.add_column("Sev", width=10)
        f_table.add_column("Agent", width=5)
        f_table.add_column("Category", width=16)
        f_table.add_column("File / Location", width=35)
        f_table.add_column("Problem", width=55)

        for i, f in enumerate(findings[:50], 1):
            sev_color = SEV_COLORS.get(f.severity, "white")
            location = f.file_path or ""
            if f.line_number:
                location += f":{f.line_number}"
            if len(location) > 33:
                location = "…" + location[-32:]
            problem = (f.problem or "")[:53]
            if len(f.problem or "") > 53:
                problem += "…"
            f_table.add_row(
                str(i),
                f"[{sev_color}]{f.severity}[/{sev_color}]",
                f.agent_id or "?",
                f.category or "",
                location,
                problem,
            )

        if len(findings) > 50:
            console.print(f"[dim](showing first 50 of {len(findings)} findings)[/dim]")
        console.print()
        console.print(f_table)
    else:
        console.print()
        console.print("[green]No findings match the current filter.[/green]")

    # ── Export ─────────────────────────────────────────────────────────────
    if export:
        run_dir = work_path / ".springinsight" / "runs" / run.id
        report_src = run_dir / "MASTER-REPORT.md"
        if report_src.exists():
            import shutil
            shutil.copy(str(report_src), export)
            console.print(f"\n[green]Report exported to:[/green] {export}")
        else:
            console.print(f"\n[yellow]Report file not found at {report_src}[/yellow]")

    console.print()

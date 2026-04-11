"""springinsight run — execute agents against a Spring Boot project."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..agents.registry import AGENT_REGISTRY, get_enabled_agents
from ..agents.runner import run_agents_parallel
from ..context.loader import load_context, render_context_block
from ..db.database import get_db, init_db
from ..db.models import AgentRun, Finding, Run
from ..utils.github import resolve_project_path
from ..utils.scoring import calculate_scores

console = Console()

# Severity colors for Rich
SEV_COLORS = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
    "INFO": "dim",
}


def _build_progress_table(agent_states: dict[str, dict]) -> Table:
    """Build a Rich table showing real-time agent progress."""
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Agent", style="bold", width=28)
    table.add_column("Model", width=10)
    table.add_column("Status", width=12)
    table.add_column("Findings", justify="right", width=10)
    table.add_column("Duration", justify="right", width=10)

    status_icons = {
        "pending":  "[dim]⏳ waiting[/dim]",
        "running":  "[yellow]⚡ running[/yellow]",
        "complete": "[green]✅ done[/green]",
        "failed":   "[red]❌ failed[/red]",
    }

    for agent_id, state in agent_states.items():
        agent = AGENT_REGISTRY.get(agent_id)
        if not agent:
            continue
        status = state.get("status", "pending")
        findings = state.get("findings_count", "-")
        duration = ""
        if state.get("started_at") and state.get("completed_at"):
            secs = (state["completed_at"] - state["started_at"]).total_seconds()
            duration = f"{secs:.0f}s"
        elif state.get("started_at"):
            secs = (datetime.utcnow() - state["started_at"]).total_seconds()
            duration = f"{secs:.0f}s…"

        model_short = agent.model.split("-")[1] if "-" in agent.model else agent.model
        table.add_row(
            f"[{SEV_COLORS.get('INFO', 'white')}]{agent_id}[/] {agent.name}",
            model_short,
            status_icons.get(status, status),
            str(findings) if findings != "-" else "-",
            duration,
        )
    return table


@click.command("run")
@click.argument("target", required=False, default=None, metavar="[PATH_OR_URL]")
@click.option("--work-dir", "-w", default=".", help="SpringInsight working directory (contains context.yaml)")
@click.option("--project", "-p", default=None, help="Project path or GitHub URL (same as positional argument)")
@click.option("--agents", "-a", default="all", help="Comma-separated agent IDs to run, or 'all'")
@click.option("--phase", default=None, type=int, help="Run only agents from a specific phase (1-4)")
@click.option("--parallel", default=None, type=int, help="Max concurrent agents (overrides context.yaml)")
@click.option("--no-db", is_flag=True, help="Skip saving findings to SQLite (print only)")
def run_cmd(target: str | None, work_dir: str, project: str | None, agents: str, phase: int | None, parallel: int | None, no_db: bool):
    """Run SpringInsight agents against a Spring Boot project.

    TARGET can be a local path or a GitHub URL (positional or --project flag).
    If omitted, uses the base_path from context.yaml.

    Examples:\n
      springinsight run\n
      springinsight run /path/to/service\n
      springinsight run https://github.com/org/repo\n
      springinsight run https://github.com/org/repo --agents A03,A10,A12\n
      springinsight run --phase 1\n
      springinsight run --project https://github.com/org/repo
    """
    # Positional argument takes precedence over --project flag
    project = target or project
    work_path = Path(work_dir).expanduser().resolve()

    # ── Load context ────────────────────────────────────────────────────────
    ctx = load_context(work_path)
    if not ctx.base_path and not project:
        console.print(
            "[red]No project configured.[/red] Run [bold]springinsight init[/bold] first, "
            "or pass [bold]--project[/bold]."
        )
        raise click.Abort()

    # ── Resolve project path ────────────────────────────────────────────────
    source = project or ctx.base_path
    try:
        with console.status("Resolving project…"):
            project_path, source_type, source_url = resolve_project_path(source, work_path)
    except Exception as e:
        console.print(f"[red]Error resolving project:[/red] {e}")
        raise click.Abort()

    # ── Determine which agents to run ───────────────────────────────────────
    if phase is not None:
        from ..agents.registry import PHASE_ORDER
        requested_ids = PHASE_ORDER.get(phase, [])
    elif agents.lower() == "all":
        requested_ids = None  # get_enabled_agents handles "all"
    else:
        requested_ids = [a.strip().upper() for a in agents.split(",")]

    agents_to_run = get_enabled_agents(requested_ids or "all")

    if not agents_to_run:
        console.print("[yellow]No enabled agents found for the requested selection.[/yellow]")
        console.print("Available agents: A03, A10, A12 (Phase 1) — A01, A02, A04, A09, A11, A13, A14 (Phase 2)")
        raise click.Abort()

    # ── Init DB ─────────────────────────────────────────────────────────────
    if not no_db:
        init_db(work_path)

    # ── Create run record ───────────────────────────────────────────────────
    run_id = str(uuid.uuid4())[:8]  # short ID
    full_run_id = f"{datetime.utcnow().strftime('%Y-%m-%d')}-{run_id}"

    run_dir = work_path / ".springinsight" / "runs" / full_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Persist run record to DB
    if not no_db:
        with get_db() as db:
            run_record = Run(
                id=full_run_id,
                project_name=ctx.name,
                project_path=str(project_path),
                source_type=source_type,
                source_url=source_url,
                agents_requested=[a.id for a in agents_to_run],
                context_snapshot=ctx._raw,
            )
            db.add(run_record)

    # ── Print header ────────────────────────────────────────────────────────
    console.print()
    console.print(Panel.fit(
        f"[bold yellow]SpringInsight[/bold yellow] — Run [bold]{full_run_id}[/bold]\n"
        f"  Project : [bold]{project_path.name}[/bold] ({source_type})\n"
        f"  Agents  : {', '.join(a.id for a in agents_to_run)}\n"
        f"  Output  : [dim]{run_dir}[/dim]",
        border_style="yellow"
    ))
    console.print()

    # ── Track agent state for live display ──────────────────────────────────
    agent_states: dict[str, dict] = {
        a.id: {"status": "pending", "findings_count": 0}
        for a in agents_to_run
    }

    def progress_cb(agent_id: str, status: str):
        agent_states[agent_id]["status"] = status
        if status == "running":
            agent_states[agent_id]["started_at"] = datetime.utcnow()
        elif status in ("complete", "failed"):
            agent_states[agent_id]["completed_at"] = datetime.utcnow()

    # ── Run agents ──────────────────────────────────────────────────────────
    parallelism = parallel or ctx.parallelism

    all_findings: list[dict] = []

    with Live(console=console, refresh_per_second=2) as live:
        async def _run():
            results = await run_agents_parallel(
                agents=agents_to_run,
                ctx=ctx,
                project_path=str(project_path),
                run_dir=run_dir,
                run_id=full_run_id,
                parallelism=parallelism,
                progress_callback=progress_cb,
            )
            return results

        def _update_live():
            live.update(_build_progress_table(agent_states))

        # Patch asyncio loop to update display
        async def _run_with_display():
            task = asyncio.create_task(_run())
            while not task.done():
                _update_live()
                await asyncio.sleep(0.5)
            _update_live()
            return await task

        results = asyncio.run(_run_with_display())

    # ── Process results ─────────────────────────────────────────────────────
    completed_at = datetime.utcnow()

    for result in results:
        agent_id = result["agent_id"]
        agent_meta = AGENT_REGISTRY[agent_id]
        findings = result.get("findings", [])
        all_findings.extend(findings)
        agent_states[agent_id]["findings_count"] = len(findings)

        if not no_db:
            with get_db() as db:
                # Persist AgentRun
                ar = AgentRun(
                    run_id=full_run_id,
                    agent_id=agent_id,
                    agent_name=agent_meta.name,
                    model=agent_meta.model,
                    status=result["status"],
                    started_at=result.get("started_at"),
                    completed_at=result.get("completed_at"),
                    findings_count=len(findings),
                    error_message=result.get("error"),
                    output_json_path=result.get("output_json"),
                    output_md_path=result.get("output_md"),
                )
                db.add(ar)

                # Persist findings
                for f in findings:
                    finding = Finding(
                        run_id=full_run_id,
                        agent_id=agent_id,
                        severity=f.get("severity", "LOW"),
                        category=f.get("category", "General"),
                        subcategory=f.get("subcategory"),
                        file_path=f.get("file"),
                        line_number=f.get("line"),
                        class_name=f.get("class_name"),
                        method_name=f.get("method_name"),
                        problem=f.get("problem", ""),
                        code_snippet=f.get("code_snippet"),
                        impact=f.get("impact"),
                        fix_description=f.get("fix"),
                        fix_code=f.get("fix_code"),
                        dependency_group_id=f.get("group_id"),
                        dependency_artifact_id=f.get("artifact_id"),
                        dependency_version=f.get("version"),
                        cve_ids=f.get("cve_ids", []),
                        cvss_score=f.get("cvss_score"),
                        license_type=f.get("license_type"),
                        actionable=f.get("actionable", True),
                        effort_hours=f.get("effort_hours"),
                    )
                    db.add(finding)

    # ── Calculate scores & update run ───────────────────────────────────────
    scores = calculate_scores(all_findings)
    if not no_db:
        with get_db() as db:
            run_record = db.query(Run).filter(Run.id == full_run_id).first()
            if run_record:
                run_record.completed_at = completed_at
                run_record.status = "complete"
                run_record.agents_completed = [r["agent_id"] for r in results if r["status"] == "complete"]
                run_record.score_overall = scores["overall"]
                run_record.score_security = scores["security"]
                run_record.score_code_quality = scores["code_quality"]
                run_record.score_architecture = scores["architecture"]
                run_record.score_api_design = scores["api_design"]
                run_record.score_test_coverage = scores["test_coverage"]
                run_record.score_production_readiness = scores["production_readiness"]

    # ── Write master report ─────────────────────────────────────────────────
    _write_master_report(run_dir, full_run_id, ctx.name, agents_to_run, results, all_findings, scores)

    # ── Print summary ───────────────────────────────────────────────────────
    _print_summary(full_run_id, results, all_findings, scores, run_dir)


def _write_master_report(run_dir, run_id, project_name, agents, results, findings, scores):
    """Write MASTER-REPORT.md consolidating all agent outputs."""
    lines = [
        f"# SpringInsight Report — {project_name}",
        f"**Run ID:** {run_id}  ",
        f"**Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Scores",
        "| Dimension | Score |",
        "|---|---|",
    ]
    for k, v in scores.items():
        icon = "🟢" if v >= 80 else "🟡" if v >= 60 else "🔴"
        lines.append(f"| {k.replace('_', ' ').title()} | {icon} {v}/100 |")

    lines += ["", "## Findings by Severity", ""]
    sev_counts = {}
    for f in findings:
        s = f.get("severity", "LOW")
        sev_counts[s] = sev_counts.get(s, 0) + 1

    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        count = sev_counts.get(sev, 0)
        if count:
            lines.append(f"- **{sev}**: {count}")

    lines += ["", "## Agent Results", ""]
    for result in results:
        agent = AGENT_REGISTRY.get(result["agent_id"])
        status_icon = "✅" if result["status"] == "complete" else "❌"
        lines.append(f"### {status_icon} {result['agent_id']} — {agent.name if agent else '?'}")
        if result.get("output_md"):
            try:
                md_content = Path(result["output_md"]).read_text(encoding="utf-8")
                lines.append(md_content)
            except Exception:
                lines.append("*(report file not found)*")
        lines.append("")

    report_path = run_dir / "MASTER-REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")


def _print_summary(run_id, results, findings, scores, run_dir):
    """Print the post-run summary to terminal."""
    console.print()

    # Score table
    score_table = Table(title="Scores", show_header=True, header_style="bold yellow")
    score_table.add_column("Dimension", style="bold")
    score_table.add_column("Score", justify="center", width=10)
    for k, v in scores.items():
        color = "green" if v >= 80 else "yellow" if v >= 60 else "red"
        score_table.add_row(k.replace("_", " ").title(), f"[{color}]{v}/100[/{color}]")
    console.print(score_table)

    # Findings summary
    sev_counts = {}
    for f in findings:
        s = f.get("severity", "LOW")
        sev_counts[s] = sev_counts.get(s, 0) + 1

    console.print()
    console.print("[bold]Findings[/bold]")
    for sev, color in [("CRITICAL", "bold red"), ("HIGH", "red"), ("MEDIUM", "yellow"), ("LOW", "cyan")]:
        count = sev_counts.get(sev, 0)
        if count:
            console.print(f"  [{color}]{sev}[/{color}] : {count}")

    # Top critical findings
    critical_findings = [f for f in findings if f.get("severity") == "CRITICAL"]
    if critical_findings:
        console.print()
        console.print("[bold red]🔴 Critical Issues:[/bold red]")
        for f in critical_findings[:5]:
            console.print(f"  • {f.get('file', '?')} — {f.get('problem', '')[:80]}")

    # Agent summary
    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        console.print()
        console.print(f"[yellow]⚠ {len(failed)} agent(s) failed:[/yellow]")
        for r in failed:
            console.print(f"  {r['agent_id']}: {r.get('error', 'unknown error')[:100]}")

    console.print()
    console.print(Panel.fit(
        f"[green]✓ Run complete![/green] [bold]{run_id}[/bold]\n\n"
        f"  Report: [bold]{run_dir / 'MASTER-REPORT.md'}[/bold]\n"
        f"  View:   [bold yellow]springinsight report[/bold yellow]\n"
        f"  UI:     [bold yellow]springinsight web[/bold yellow]",
        border_style="green"
    ))
    console.print()

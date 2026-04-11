"""springinsight init — interactive project context setup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from ..context.loader import ModuleInfo, ProjectContext, save_context
from ..db.database import init_db

console = Console()


def _detect_build_tool(path: Path) -> str:
    if (path / "pom.xml").exists():
        return "maven"
    if (path / "build.gradle").exists() or (path / "build.gradle.kts").exists():
        return "gradle"
    return "maven"


def _detect_spring_boot_version(path: Path) -> str:
    """Try to extract Spring Boot version from pom.xml."""
    try:
        import xml.etree.ElementTree as ET
        pom = path / "pom.xml"
        if pom.exists():
            tree = ET.parse(str(pom))
            root = tree.getroot()
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            # Check parent
            parent = root.find("m:parent", ns)
            if parent is not None:
                artifact = parent.find("m:artifactId", ns)
                version = parent.find("m:version", ns)
                if artifact is not None and "spring-boot" in (artifact.text or ""):
                    return version.text if version is not None else "3.x"
            # Check properties
            for prop in root.findall(".//m:spring-boot.version", ns):
                return prop.text or "3.x"
    except Exception:
        pass
    return "3.x"


def _detect_modules(path: Path) -> list[ModuleInfo]:
    """Detect Maven submodules from root pom.xml."""
    modules = []
    try:
        import xml.etree.ElementTree as ET
        pom = path / "pom.xml"
        if pom.exists():
            tree = ET.parse(str(pom))
            root = tree.getroot()
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            for mod_el in root.findall(".//m:module", ns):
                mod_path = mod_el.text or ""
                if mod_path:
                    modules.append(ModuleInfo(
                        name=mod_path.split("/")[-1],
                        path=mod_path,
                        role="",
                    ))
    except Exception:
        pass
    return modules


def _get_git_info(path: Path) -> tuple[str, str]:
    """Return (branch, commit) from git."""
    try:
        branch = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True
        ).stdout.strip()
        return branch, commit
    except Exception:
        return "", ""


@click.command("init")
@click.option("--work-dir", "-w", default=".", help="SpringInsight working directory (where context.yaml is stored)")
@click.option("--project", "-p", default=None, help="Path or GitHub URL of the Spring Boot project to analyze")
@click.option("--yes", "-y", is_flag=True, help="Non-interactive: accept all auto-detected defaults")
def init_cmd(work_dir: str, project: str | None, yes: bool):
    """Initialize SpringInsight for a project.

    Creates .springinsight/context.yaml with project details.
    Supports local paths and GitHub URLs.

    Examples:\n
      springinsight init\n
      springinsight init --project /path/to/my-service\n
      springinsight init --project https://github.com/org/repo
    """
    work_path = Path(work_dir).expanduser().resolve()
    work_path.mkdir(parents=True, exist_ok=True)

    console.print()
    console.print(Panel.fit(
        "[bold yellow]SpringInsight[/bold yellow] — Codebase Intelligence for Java / Spring Boot\n"
        "[dim]Initializing project context...[/dim]",
        border_style="yellow"
    ))
    console.print()

    # ── Determine project path ─────────────────────────────────────────────
    if project is None:
        if yes:
            project = str(work_path)
        else:
            project = Prompt.ask(
                "  [cyan]Project path or GitHub URL[/cyan]",
                default=str(work_path)
            )

    # Resolve path (GitHub or local)
    from ..utils.github import is_github_url, resolve_project_path
    try:
        with console.status("Resolving project path..."):
            project_path, source_type, source_url = resolve_project_path(project, work_path)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise click.Abort()

    console.print(f"  [green]✓[/green] Project path: [bold]{project_path}[/bold]")

    # ── Auto-detect ────────────────────────────────────────────────────────
    build_tool = _detect_build_tool(project_path)
    sb_version = _detect_spring_boot_version(project_path)
    modules = _detect_modules(project_path)
    branch, commit = _get_git_info(project_path)

    if modules:
        console.print(f"  [green]✓[/green] Detected {len(modules)} Maven modules: {', '.join(m.name for m in modules[:5])}")
    console.print(f"  [green]✓[/green] Build tool: {build_tool} | Spring Boot: {sb_version}")
    if branch:
        console.print(f"  [green]✓[/green] Git: {branch} @ {commit}")

    # ── Interactive questions ──────────────────────────────────────────────
    ctx = ProjectContext()
    ctx.base_path = str(project_path)

    if yes:
        ctx.name = project_path.name
        ctx.description = f"Spring Boot project at {project_path.name}"
        ctx.build_tool = build_tool
        ctx.spring_boot_version = sb_version
        ctx.modules = modules
    else:
        console.print()
        console.print("[bold]Project Details[/bold]")
        ctx.name = Prompt.ask("  Project name", default=project_path.name)
        ctx.description = Prompt.ask("  Description", default=f"Spring Boot project: {ctx.name}")

        console.print()
        console.print("[bold]Tech Stack[/bold]")
        ctx.java_version = int(Prompt.ask("  Java version", default="17"))
        ctx.spring_boot_version = Prompt.ask("  Spring Boot version", default=sb_version)
        ctx.build_tool = Prompt.ask("  Build tool [maven/gradle]", default=build_tool)
        ctx.database = Prompt.ask("  Database [mysql/postgresql/oracle/h2]", default="mysql")
        ctx.orm = Prompt.ask("  ORM [hibernate/mybatis/none]", default="hibernate")
        ctx.auth = Prompt.ask("  Auth [jwt/oauth2/keycloak/session/basic]", default="jwt")
        ctx.cache = Prompt.ask("  Cache [redis/caffeine/hazelcast/none]", default="none")
        ctx.messaging = Prompt.ask("  Messaging [rabbitmq/kafka/activemq/none]", default="none")

        console.print()
        console.print("[bold]Multi-Tenancy[/bold]")
        ctx.multi_tenancy = Confirm.ask("  Is this a multi-tenant application?", default=False)
        if ctx.multi_tenancy:
            ctx.tenant_filter_class = Prompt.ask(
                "  Tenant filter class name", default="TenantFilter"
            )
            ctx.base_entity = Prompt.ask("  Base entity class for tenant-scoped data", default="BaseEntity")

        console.print()
        console.print("[bold]Modules[/bold]")
        if modules:
            console.print(f"  Auto-detected {len(modules)} modules. Add descriptions? (optional)")
            if Confirm.ask("  Describe modules?", default=False):
                for m in modules:
                    m.role = Prompt.ask(f"    Role of '{m.name}'", default="")
        ctx.modules = modules

        console.print()
        console.print("[bold]Custom Rules[/bold]")
        console.print("  [dim]Add project-specific rules for agents (e.g. 'GET endpoints must never mutate state')[/dim]")
        rules = []
        while Confirm.ask("  Add a custom rule?", default=False):
            rule = Prompt.ask("  Rule")
            if rule:
                rules.append(rule)
        ctx.custom_rules = rules

    # ── Save context.yaml ──────────────────────────────────────────────────
    si_dir = work_path / ".springinsight"
    si_dir.mkdir(parents=True, exist_ok=True)
    ctx_path = save_context(ctx, work_path)

    # ── Initialize DB ──────────────────────────────────────────────────────
    init_db(work_path)

    # ── Create runs output dir ─────────────────────────────────────────────
    (work_path / ".springinsight" / "runs").mkdir(parents=True, exist_ok=True)

    console.print()
    console.print(Panel.fit(
        f"[green]✓ SpringInsight initialized![/green]\n\n"
        f"  Context: [bold]{ctx_path}[/bold]\n"
        f"  Database: [bold]{work_path / '.springinsight' / 'springinsight.db'}[/bold]\n\n"
        f"  Next: [bold yellow]springinsight run[/bold yellow] [dim]--work-dir {work_dir}[/dim]",
        border_style="green"
    ))
    console.print()

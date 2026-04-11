"""springinsight context — manage global project context and custom rules."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..context.global_context import (
    DEFAULT_GLOBAL_CONTEXT,
    GLOBAL_CONTEXT_PATH,
    get_global_custom_rules,
    load_global_context,
    save_global_context,
    set_global_custom_rules,
)

console = Console()


@click.group("context")
def context_cmd():
    """Manage global project context — custom rules, tech stack hints.

    Context is injected into every agent prompt as MUST-APPLY constraints.
    Per-project context.yaml takes precedence over global settings.

    Storage: ~/.springinsight/global-context.yaml
    """


@context_cmd.command("show")
def ctx_show():
    """Show the current global context."""
    ctx = load_global_context()

    console.print("\n[bold orange1]⚡ SpringInsight Global Context[/bold orange1]")
    console.print(f"[dim]Path: {GLOBAL_CONTEXT_PATH}[/dim]\n")

    # Tech stack
    tech = ctx.get("tech_stack", {})
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold orange1", width=24)
    table.add_column(style="white")
    table.add_row("Java Version", str(tech.get("java_version", "17")))
    table.add_row("Spring Boot", tech.get("spring_boot_version", "3.x"))
    table.add_row("Build Tool", tech.get("build_tool", "maven"))
    table.add_row("Database", tech.get("database", "mysql"))
    table.add_row("Auth", tech.get("auth", "jwt"))
    table.add_row("API Type", tech.get("api_type", "rest"))
    console.print(Panel(table, title="Tech Stack Defaults", border_style="dim"))

    # Custom rules
    rules = ctx.get("patterns", {}).get("custom_rules", [])
    if rules:
        rules_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        rules_table.add_column("#", style="dim", width=4)
        rules_table.add_column("Rule", style="white")
        for i, rule in enumerate(rules):
            rules_table.add_row(str(i), rule)
        console.print(Panel(rules_table, title=f"Custom Rules ({len(rules)})", border_style="green"))
    else:
        console.print(Panel("[dim]No custom rules defined.[/dim]", title="Custom Rules", border_style="dim"))

    # Exclusions
    excl_paths = ctx.get("exclusions", {}).get("paths", [])
    console.print(f"\n[dim]Excluded paths: {', '.join(excl_paths)}[/dim]")


@context_cmd.command("add-rule")
@click.argument("rule", metavar="RULE_TEXT")
def ctx_add_rule(rule: str):
    """Add a custom rule that all agents must follow.

    \b
    Examples:
      springinsight context add-rule "Never use field injection"
      springinsight context add-rule "All REST endpoints need @PreAuthorize"
    """
    rules = get_global_custom_rules()
    if rule in rules:
        console.print(f"[yellow]Rule already exists:[/yellow] {rule}")
        return
    rules.append(rule)
    set_global_custom_rules(rules)
    console.print(f"[green]✓[/green] Added rule #{len(rules) - 1}: {rule}")


@context_cmd.command("remove-rule")
@click.argument("index", type=int, metavar="INDEX")
def ctx_remove_rule(index: int):
    """Remove a custom rule by its index (see 'context show')."""
    rules = get_global_custom_rules()
    if index < 0 or index >= len(rules):
        console.print(f"[red]Error:[/red] No rule at index {index}. Use 'context show' to list rules.")
        raise SystemExit(1)
    removed = rules.pop(index)
    set_global_custom_rules(rules)
    console.print(f"[green]✓[/green] Removed rule: {removed}")


@context_cmd.command("list-rules")
def ctx_list_rules():
    """List all custom rules (shortcut for 'context show')."""
    rules = get_global_custom_rules()
    if not rules:
        console.print("[dim]No custom rules defined. Add one with:[/dim]")
        console.print('  springinsight context add-rule "Your rule here"')
        return
    for i, rule in enumerate(rules):
        console.print(f"  [bold orange1]{i}[/bold orange1]  {rule}")


@context_cmd.command("set")
@click.argument("key", metavar="KEY")
@click.argument("value", metavar="VALUE")
def ctx_set(key: str, value: str):
    """Set a tech-stack context value.

    \b
    Available keys:
      java-version     (e.g. 17, 21)
      spring-boot      (e.g. 3.2.x)
      build-tool       (maven | gradle)
      database         (mysql | postgresql | oracle | mongodb | h2)
      auth             (jwt | oauth2 | keycloak | session | basic)
      api-type         (rest | graphql | grpc | mixed)

    \b
    Examples:
      springinsight context set java-version 21
      springinsight context set spring-boot 3.3.x
      springinsight context set database postgresql
    """
    ctx = load_global_context()
    ctx.setdefault("tech_stack", {})

    key_map = {
        "java-version": "java_version",
        "java_version": "java_version",
        "spring-boot": "spring_boot_version",
        "spring_boot": "spring_boot_version",
        "build-tool": "build_tool",
        "build_tool": "build_tool",
        "database": "database",
        "auth": "auth",
        "api-type": "api_type",
        "api_type": "api_type",
    }
    yaml_key = key_map.get(key.lower())
    if not yaml_key:
        console.print(f"[red]Unknown key:[/red] {key}")
        console.print(f"[dim]Valid keys: {', '.join(sorted(set(key_map.keys())))}[/dim]")
        raise SystemExit(1)

    if yaml_key == "java_version":
        try:
            value = int(value)
        except ValueError:
            pass

    ctx["tech_stack"][yaml_key] = value
    save_global_context(ctx)
    console.print(f"[green]✓[/green] Set [bold]{key}[/bold] = [bold orange1]{value}[/bold orange1]")


@context_cmd.command("reset")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def ctx_reset(yes: bool):
    """Reset global context to factory defaults."""
    if not yes:
        click.confirm("Reset global context to defaults?", abort=True)
    save_global_context(DEFAULT_GLOBAL_CONTEXT.copy())
    console.print("[green]✓[/green] Global context reset to defaults.")


@context_cmd.command("edit")
def ctx_edit():
    """Open global-context.yaml in your $EDITOR."""
    import subprocess
    import os

    # Ensure file exists
    if not GLOBAL_CONTEXT_PATH.exists():
        save_global_context(DEFAULT_GLOBAL_CONTEXT.copy())

    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(GLOBAL_CONTEXT_PATH)])
    console.print(f"[green]✓[/green] Saved: {GLOBAL_CONTEXT_PATH}")


@context_cmd.command("export")
@click.option("--format", "fmt", default="yaml", type=click.Choice(["yaml", "json"]),
              help="Output format (default: yaml)")
def ctx_export(fmt: str):
    """Export current global context to stdout."""
    ctx = load_global_context()
    if fmt == "json":
        console.print(json.dumps(ctx, indent=2))
    else:
        import yaml
        console.print(yaml.dump(ctx, default_flow_style=False, allow_unicode=True))

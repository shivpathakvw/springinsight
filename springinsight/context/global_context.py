"""Global project context management.

SpringInsight supports two levels of context:
1. Per-project: ``context.yaml`` at the project root — most specific
2. Global default: ``~/.springinsight/global-context.yaml`` — applies to all projects
   when no per-project context file exists (or when global rules should be merged).

Global context lets users define organisation-wide coding standards,
custom rules, and stack hints from the Web UI without editing YAML by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .loader import ProjectContext, load_context

GLOBAL_CONTEXT_PATH = Path.home() / ".springinsight" / "global-context.yaml"

DEFAULT_GLOBAL_CONTEXT: dict = {
    "project": {
        "name": "Default",
        "description": "",
    },
    "tech_stack": {
        "java_version": 17,
        "spring_boot_version": "3.x",
        "build_tool": "maven",
        "database": "mysql",
        "orm": "hibernate",
        "auth": "jwt",
        "api_type": "rest",
    },
    "patterns": {
        "multi_tenancy": False,
        "custom_rules": [],
    },
    "exclusions": {
        "packages": ["*.generated.*", "*.test.*"],
        "paths": ["*/target/*", "*/build/*"],
    },
}


def load_global_context() -> dict:
    """Return the raw global context dict (creates default if missing)."""
    if not GLOBAL_CONTEXT_PATH.exists():
        return DEFAULT_GLOBAL_CONTEXT.copy()
    try:
        raw = yaml.safe_load(GLOBAL_CONTEXT_PATH.read_text(encoding="utf-8")) or {}
        return raw
    except Exception:
        return DEFAULT_GLOBAL_CONTEXT.copy()


def save_global_context(ctx: dict) -> None:
    """Persist global context to ``~/.springinsight/global-context.yaml``."""
    GLOBAL_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONTEXT_PATH.write_text(yaml.dump(ctx, default_flow_style=False, allow_unicode=True), encoding="utf-8")


def get_global_custom_rules() -> list[str]:
    """Return the list of custom rules from global context."""
    ctx = load_global_context()
    return ctx.get("patterns", {}).get("custom_rules", [])


def set_global_custom_rules(rules: list[str]) -> None:
    """Replace the global custom rules list."""
    ctx = load_global_context()
    ctx.setdefault("patterns", {})["custom_rules"] = rules
    save_global_context(ctx)


def merge_global_into_project(project_ctx: ProjectContext) -> ProjectContext:
    """Merge global custom rules into a project context (project rules win)."""
    global_rules = get_global_custom_rules()
    if global_rules:
        # Append global rules that aren't already in the project's list
        existing = set(project_ctx.custom_rules)
        for rule in global_rules:
            if rule not in existing:
                project_ctx.custom_rules.append(rule)
    return project_ctx


def load_effective_context(project_path: Path) -> ProjectContext:
    """Load context, merging global rules into per-project context."""
    ctx = load_context(project_path)
    return merge_global_into_project(ctx)

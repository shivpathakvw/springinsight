"""Agent-specific file pre-filtering.

Each agent only needs a subset of the codebase. Sending irrelevant files
wastes tokens and adds noise. This module computes the relevant file list
per agent based on Spring Boot patterns and injects it into the prompt.

Token savings per agent (rough estimates):
  A03 CVE Scanner     : skips ALL .java files → ~60% token reduction
  A12 Config Review   : skips ALL .java files → ~60% token reduction
  A04 JPA Review      : reads only @Entity/@Repository → ~70% reduction
  A13 API Auditor     : reads only @RestController → ~65% reduction
  A02 Security        : skips test classes → ~30% reduction
  A14 Concurrency     : reads only @Service/@Component → ~50% reduction
  A10 Dead Code       : needs full scope (cross-reference analysis)
  A01 Code Review     : configurable max-files sample
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# ── File discovery helpers ─────────────────────────────────────────────────────

EXCLUDE_DIRS = frozenset([
    "target", "build", ".git", "node_modules", "generated-sources",
    ".springinsight", "__pycache__",
])


def _walk_java(project_path: Path) -> Iterator[Path]:
    for p in project_path.rglob("*.java"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        yield p


def _walk_config(project_path: Path) -> Iterator[Path]:
    patterns = [
        "*.properties", "*.yml", "*.yaml",
        "Dockerfile", "Dockerfile.*",
        "docker-compose*.yml", "docker-compose*.yaml",
        "*.xml",           # includes pom.xml
        "*.gradle",
        "*.gradle.kts",
        ".env.example",
        "*.toml",
    ]
    seen: set[Path] = set()
    for pat in patterns:
        for p in project_path.rglob(pat):
            if p in seen:
                continue
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            seen.add(p)
            yield p


def _walk_dependency_files(project_path: Path) -> Iterator[Path]:
    """Only build/dependency descriptor files (for CVE scanner)."""
    for name in ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
                 "settings.gradle.kts", "gradle.properties"):
        for p in project_path.rglob(name):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            yield p


# ── Spring annotation matchers ────────────────────────────────────────────────

_ANNOTATION_CACHE: dict[Path, frozenset[str]] = {}


def _file_annotations(path: Path) -> frozenset[str]:
    """Return the set of Spring annotations found in a Java file (cached)."""
    if path in _ANNOTATION_CACHE:
        return _ANNOTATION_CACHE[path]
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        annotations = frozenset(re.findall(r"@(\w+)", text))
    except OSError:
        annotations = frozenset()
    _ANNOTATION_CACHE[path] = annotations
    return annotations


def _matches_any(annotations: frozenset[str], targets: set[str]) -> bool:
    return bool(annotations & targets)


# ── Per-agent scope definitions ────────────────────────────────────────────────

# Spring annotations that identify relevant files per agent
AGENT_SCOPE_ANNOTATIONS: dict[str, set[str]] = {
    "A01": set(),                    # full scope (deep code review)
    "A02": {                         # security: controllers, configs, filters
        "RestController", "Controller", "RequestMapping", "Configuration",
        "EnableWebSecurity", "SecurityFilterChain", "PreAuthorize",
        "PostAuthorize", "Secured", "RolesAllowed",
    },
    "A03": set(),                    # CVE: no .java needed, uses pom.xml/gradle
    "A04": {                         # JPA: entities, repos, services with queries
        "Entity", "Table", "Repository", "Query", "NamedQuery",
        "OneToMany", "ManyToOne", "ManyToMany", "OneToOne", "JoinColumn",
        "Transactional", "PersistenceContext",
    },
    "A09": set(),                    # PR review: full scope
    "A10": set(),                    # Dead code: needs full cross-ref
    "A11": {                         # Performance: services, repos, caches
        "Service", "Repository", "Cacheable", "CacheEvict", "CachePut",
        "Scheduled", "Async",
    },
    "A12": set(),                    # Config: only config files, no .java
    "A13": {                         # API: only controllers and DTOs
        "RestController", "Controller", "RequestMapping", "GetMapping",
        "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping",
        "RequestBody", "ResponseBody", "ResponseEntity", "ControllerAdvice",
        "ExceptionHandler",
    },
    "A14": {                         # Concurrency: services, async, scheduled
        "Service", "Component", "Transactional", "Async", "Scheduled",
        "Lock", "Synchronized",
    },
    "A15": set(),                    # Dependency graph: full scope
    "A05": set(),                    # Architecture: full scope
    "A06": set(),                    # Test gen: full scope
    "A07": set(),                    # Docs: full scope
    "A08": set(),                    # LLD: full scope
}

# Whether an agent needs config files at all
AGENT_NEEDS_CONFIG: dict[str, bool] = {
    "A03": True,   # pom.xml, build.gradle only
    "A12": True,   # config/infra review
    "A01": False,
    "A02": True,   # security.yml, etc.
    "A04": True,   # persistence.xml, application.properties (datasource)
    "A05": False,
    "A06": False,
    "A07": False,
    "A08": False,
    "A09": False,
    "A10": False,
    "A11": True,   # application.properties (cache, thread pool)
    "A13": False,
    "A14": False,
    "A15": False,
}

# Agents that need NO .java files (only config/build files)
AGENTS_NO_JAVA = frozenset(["A03", "A12"])

# Max Java files per agent (prevents enormous context windows)
# None = no limit
AGENT_MAX_JAVA_FILES: dict[str, int | None] = {
    "A01": 150,
    "A02": 120,
    "A03": 0,       # no java files
    "A04": 80,
    "A09": 100,
    "A10": 200,
    "A11": 80,
    "A12": 0,       # no java files
    "A13": 60,
    "A14": 80,
    "A15": 200,
    "A05": 200,
    "A06": 100,
    "A07": 150,
    "A08": 150,
}


def compute_scope(
    agent_id: str,
    project_path: Path,
    max_files: int | None = None,
    skip_files: set[str] | None = None,
) -> "AgentScope":
    """Compute the focused file list for a given agent.

    Args:
        agent_id:     e.g. 'A04'
        project_path: root of the project
        max_files:    override the per-agent default max
        skip_files:   relative paths to skip (incremental scan cache)

    Returns:
        AgentScope with .java_files, .config_files, .skipped_count
    """
    skip = skip_files or set()
    annotations_required = AGENT_SCOPE_ANNOTATIONS.get(agent_id, set())
    needs_config = AGENT_NEEDS_CONFIG.get(agent_id, False)
    no_java = agent_id in AGENTS_NO_JAVA
    effective_max = max_files if max_files is not None else AGENT_MAX_JAVA_FILES.get(agent_id)

    java_files: list[str] = []
    skipped_unchanged = 0
    skipped_irrelevant = 0

    if not no_java:
        for f in _walk_java(project_path):
            try:
                rel = str(f.relative_to(project_path))
            except ValueError:
                rel = str(f)

            # Skip unchanged (incremental)
            if rel in skip:
                skipped_unchanged += 1
                continue

            # Skip if annotations don't match (when scope is narrow)
            if annotations_required:
                ann = _file_annotations(f)
                if not _matches_any(ann, annotations_required):
                    skipped_irrelevant += 1
                    continue

            java_files.append(rel)

        # Sort by path depth (shallower = more central) then alpha
        java_files.sort(key=lambda x: (x.count("/"), x))

        # Apply file cap — prefer shallower (more architectural) files
        if effective_max and len(java_files) > effective_max:
            truncated = len(java_files) - effective_max
            java_files = java_files[:effective_max]
            skipped_irrelevant += truncated

    config_files: list[str] = []
    if needs_config or agent_id in AGENTS_NO_JAVA:
        gen = _walk_dependency_files(project_path) if agent_id == "A03" else _walk_config(project_path)
        for f in gen:
            try:
                rel = str(f.relative_to(project_path))
            except ValueError:
                rel = str(f)
            config_files.append(rel)

    total_skipped = skipped_unchanged + skipped_irrelevant
    logger.info(
        "[%s] Scope: %d Java files, %d config files "
        "(%d skipped-cache, %d skipped-irrelevant)",
        agent_id, len(java_files), len(config_files),
        skipped_unchanged, skipped_irrelevant,
    )

    return AgentScope(
        agent_id=agent_id,
        java_files=java_files,
        config_files=config_files,
        skipped_unchanged=skipped_unchanged,
        skipped_irrelevant=skipped_irrelevant,
    )


class AgentScope:
    """Computed file scope for one agent."""

    def __init__(
        self,
        agent_id: str,
        java_files: list[str],
        config_files: list[str],
        skipped_unchanged: int = 0,
        skipped_irrelevant: int = 0,
    ):
        self.agent_id = agent_id
        self.java_files = java_files
        self.config_files = config_files
        self.skipped_unchanged = skipped_unchanged
        self.skipped_irrelevant = skipped_irrelevant

    @property
    def total_files(self) -> int:
        return len(self.java_files) + len(self.config_files)

    @property
    def total_skipped(self) -> int:
        return self.skipped_unchanged + self.skipped_irrelevant

    def to_prompt_block(self, project_path: str) -> str:
        """Render a SCOPE block to inject into the agent prompt."""
        lines = ["=== FILE SCOPE (optimised — focus ONLY on these files) ==="]

        if self.skipped_unchanged > 0:
            lines.append(
                f"INCREMENTAL SCAN: {self.skipped_unchanged} file(s) UNCHANGED since last scan "
                f"— DO NOT analyse them again, no findings needed for those files."
            )
        if self.skipped_irrelevant > 0:
            lines.append(
                f"SCOPE FILTER: {self.skipped_irrelevant} file(s) are outside this agent's "
                f"concern — skip them entirely."
            )

        if self.java_files:
            lines.append(f"\nJava files to analyse ({len(self.java_files)} files):")
            for f in self.java_files[:200]:  # hard cap in prompt
                lines.append(f"  {project_path}/{f}")
        else:
            lines.append("\nNo Java files required for this agent.")

        if self.config_files:
            lines.append(f"\nConfig / build files to analyse ({len(self.config_files)} files):")
            for f in self.config_files[:50]:
                lines.append(f"  {project_path}/{f}")

        lines.append(
            "\nIMPORTANT: Do NOT read files not listed above. "
            "This scope has been pre-computed to minimise token usage."
        )
        lines.append("=== END FILE SCOPE ===")
        return "\n".join(lines)

    def savings_summary(self) -> str:
        total = self.total_files + self.total_skipped
        if total == 0:
            return "no files"
        pct = int(self.total_skipped / total * 100)
        return (
            f"{self.total_files} files in scope, "
            f"{self.total_skipped} skipped ({pct}% reduction)"
        )

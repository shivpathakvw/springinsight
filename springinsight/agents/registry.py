"""Agent registry — metadata for all SpringInsight agents.

Phase 1 agents use Haiku (fast, cheap pattern matching).
Phase 2+ agents use Sonnet/Opus (deep analysis).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentMeta:
    id: str                              # A03, A10, A12
    name: str                            # human-readable name
    model: str                           # claude model identifier
    phase: int                           # 1 | 2 | 3 | 4
    skill_file: str                      # relative path to SKILL.md within skills/
    description: str = ""
    requires: list[str] = field(default_factory=list)  # agent IDs that must complete first
    enabled: bool = True


# ---------------------------------------------------------------------------
# Full agent registry — all phases defined here.
# Phase 1 agents are active; Phase 2-4 are defined but not yet implemented.
# ---------------------------------------------------------------------------
AGENT_REGISTRY: dict[str, AgentMeta] = {

    # ── Phase 1: Fast Haiku agents ─────────────────────────────────────────
    "A03": AgentMeta(
        id="A03",
        name="CVE & License Scanner",
        model="claude-haiku-4-5-20251001",
        phase=1,
        skill_file="a03-cve-license/SKILL.md",
        description=(
            "Scans all pom.xml / build.gradle for dependency versions, "
            "known CVEs, and license compatibility issues."
        ),
    ),
    "A10": AgentMeta(
        id="A10",
        name="Dead Code Detector",
        model="claude-haiku-4-5-20251001",
        phase=1,
        skill_file="a10-dead-code/SKILL.md",
        description=(
            "Finds unused Java classes, methods, fields, and imports "
            "across the project using cross-reference analysis."
        ),
    ),
    "A12": AgentMeta(
        id="A12",
        name="Config & Infra Review",
        model="claude-haiku-4-5-20251001",
        phase=1,
        skill_file="a12-config-review/SKILL.md",
        description=(
            "Reviews application.properties, YAML, Docker, and CI/CD files "
            "for security misconfigs and production-readiness gaps."
        ),
    ),

    # ── Phase 2: Deep Sonnet agents ────────────────────────────────────────
    "A01": AgentMeta(
        id="A01",
        name="Deep Code Review",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a01-code-review/SKILL.md",
        description="Comprehensive Java code quality review across all modules.",
    ),
    "A02": AgentMeta(
        id="A02",
        name="Security Scanner",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a02-security-scanner/SKILL.md",
        description="OWASP Top 10 focused security scan.",
    ),
    "A04": AgentMeta(
        id="A04",
        name="Database & JPA Review",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a04-database-review/SKILL.md",
        description="JPA entities, repositories, native queries, N+1, schema analysis.",
    ),
    "A11": AgentMeta(
        id="A11",
        name="Performance Analyzer",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a11-performance/SKILL.md",
        description="Caching gaps, N+1, unbounded queries, thread pool sizing.",
    ),
    "A13": AgentMeta(
        id="A13",
        name="API Design Auditor",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a13-api-auditor/SKILL.md",
        description="REST compliance, OpenAPI coverage, pagination, error shapes.",
    ),
    "A14": AgentMeta(
        id="A14",
        name="Concurrency & TXN Audit",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a14-concurrency/SKILL.md",
        description="@Transactional correctness, @Async safety, locking patterns.",
    ),

    # ── Phase 2: Additional analysis agents ───────────────────────────────
    "A15": AgentMeta(
        id="A15",
        name="Dependency Graph",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a15-dependency-graph/SKILL.md",
        description=(
            "Builds import + Spring bean wiring graph, detects circular deps, "
            "hot spots, God classes. Outputs Mermaid diagrams and JSON model."
        ),
    ),

    # ── Phase 3: Opus + generation agents ──────────────────────────────────
    "A05": AgentMeta(
        id="A05",
        name="Architecture Review",
        model="claude-opus-4-6",
        phase=3,
        skill_file="a05-architecture/SKILL.md",
        description=(
            "SOLID at architecture level, layer violations, coupling matrix, "
            "microservices fitness score, ADR generation for critical decisions."
        ),
        requires=["A01", "A02", "A04"],
    ),
    "A08": AgentMeta(
        id="A08",
        name="LLD Generator",
        model="claude-opus-4-6",
        phase=3,
        skill_file="a08-lld/SKILL.md",
        description=(
            "Class diagrams, ER diagrams, sequence diagrams, component maps, "
            "API surface table and Spring bean wiring — all in Mermaid."
        ),
    ),
    "A06": AgentMeta(
        id="A06",
        name="Test Generator",
        model="claude-sonnet-4-6",
        phase=4,
        skill_file="a06-test-generator/SKILL.md",
        description=(
            "Generates JUnit 5 + Mockito unit tests and @WebMvcTest controller tests "
            "for uncovered critical paths found by A01 and A02."
        ),
        requires=["A01", "A02"],
    ),
    "A07": AgentMeta(
        id="A07",
        name="Feature Documentation",
        model="claude-sonnet-4-6",
        phase=4,
        skill_file="a07-feature-docs/SKILL.md",
        description=(
            "Feature specs, REST API reference, developer onboarding guide, "
            "sequence diagrams, and common developer task walkthroughs."
        ),
        requires=["A08"],
    ),
    "A09": AgentMeta(
        id="A09",
        name="PR Review",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a09-pr-review/SKILL.md",
        description="Git diff analysis, blast radius, breaking change detection.",
    ),

    # ── Phase 3: Reverse Engineering ──────────────────────────────────────
    "A18": AgentMeta(
        id="A18",
        name="Reverse Engineering",
        model="claude-opus-4-6",
        phase=3,
        skill_file="a18-reverse-engineer/SKILL.md",
        description=(
            "Reads the codebase and produces structured documentation explaining what "
            "the application does and how it works. Two modes: 'high-level' (feature "
            "catalogue, module map, integration inventory — for architects and new joiners) "
            "and 'in-depth' (full call graphs, transaction traces, Mermaid sequence diagrams, "
            "event flows, config deep-dive — for senior engineers and auditors). "
            "Also flags documentation gaps and transaction safety issues."
        ),
        requires=["A01", "A04"],  # benefits from code review + DB analysis context
    ),

    # ── Phase 2: Enterprise / NFR agents ──────────────────────────────────
    "A16": AgentMeta(
        id="A16",
        name="Spring Boot Upgrade Advisor",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a16-upgrade-advisor/SKILL.md",
        description=(
            "Detects the current Spring Boot version, identifies deprecated APIs, "
            "breaking changes, and produces a step-by-step migration guide to the "
            "latest stable release (3.5.x / 4.0). Covers Java baseline, Jakarta EE "
            "namespace, removed properties, and changed auto-configurations."
        ),
    ),
    "A17": AgentMeta(
        id="A17",
        name="NFR Optimizer",
        model="claude-sonnet-4-6",
        phase=2,
        skill_file="a17-nfr-optimizer/SKILL.md",
        description=(
            "Focuses on non-functional requirements: identifies concurrency bottlenecks "
            "(thread pool sizing, @Async misuse, virtual-thread opportunities), caching "
            "gaps (missing @Cacheable, unbounded cache, eviction strategy), connection-pool "
            "tuning (HikariCP, Feign, RestClient), GC pressure, memory leaks, and startup "
            "time optimisation. Outputs prioritised remediation list with estimated impact."
        ),
    ),
}

# Ordered list for phase-based execution
PHASE_ORDER = {
    1: ["A03", "A10", "A12"],
    2: ["A01", "A02", "A04", "A09", "A11", "A13", "A14", "A15", "A16", "A17"],
    3: ["A05", "A08", "A18"],
    4: ["A06", "A07"],
}


def get_agent(agent_id: str) -> AgentMeta | None:
    return AGENT_REGISTRY.get(agent_id)


def get_enabled_agents(requested: list[str] | str = "all") -> list[AgentMeta]:
    """Return the list of enabled agents to run."""
    if requested == "all":
        return [a for a in AGENT_REGISTRY.values() if a.enabled]
    return [AGENT_REGISTRY[aid] for aid in requested if aid in AGENT_REGISTRY and AGENT_REGISTRY[aid].enabled]


def resolve_skill_path(agent: AgentMeta) -> Path:
    """Resolve the absolute path to the agent's SKILL.md.

    Resolution order:
    1. User-customized: ~/.springinsight/skills/<skill_file>
    2. Installed package: <package>/skills/<skill_file>  (pip install)
    3. Development repo root: <repo>/skills/<skill_file>  (editable install / clone)
    """
    # 1 — user override (allows custom / patched SKILL.md files)
    user_override = Path.home() / ".springinsight" / "skills" / agent.skill_file
    if user_override.exists():
        return user_override

    # 2 — installed package: skills/ lives inside springinsight/ package directory
    #     This is the layout when installed via `pip install springinsight`
    pkg_internal = Path(__file__).parent.parent / "skills" / agent.skill_file
    if pkg_internal.exists():
        return pkg_internal

    # 3 — editable install / cloned repo: skills/ at project root
    repo_skills = Path(__file__).parent.parent.parent / "skills" / agent.skill_file
    return repo_skills

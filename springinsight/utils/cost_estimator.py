"""Cost estimation and budget enforcement for SpringInsight scans.

Estimates the dollar cost of running a set of agents against a project,
based on file count and per-model pricing. Allows users to set a hard
budget cap and automatically select the best agent set that fits within it.

Pricing (as of 2025, per million tokens):
  Haiku  4.5:  $0.80 input / $4.00 output
  Sonnet 4.6:  $3.00 input / $15.00 output
  Opus   4.6:  $15.00 input / $75.00 output

Average tokens per file analysed (empirically observed):
  ~800 input tokens / Java file (file content + context)
  ~200 output tokens / Java file (findings + report)
  Config files: ~400 input tokens each
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..agents.registry import AGENT_REGISTRY, AgentMeta

# ── Model pricing (per million tokens) ────────────────────────────────────────

PRICING: dict[str, dict[str, float]] = {
    "haiku": {"input": 0.80,  "output": 4.00},
    "sonnet": {"input": 3.00,  "output": 15.00},
    "opus":   {"input": 15.00, "output": 75.00},
}

# Tokens consumed per file analysed (input + output combined)
TOKENS_PER_JAVA_FILE: dict[str, float] = {
    "haiku":  1_000,   # lighter analysis
    "sonnet": 2_500,   # deep analysis with fix recommendations
    "opus":   4_000,   # architectural reasoning
}

TOKENS_PER_CONFIG_FILE: dict[str, float] = {
    "haiku":  600,
    "sonnet": 1_200,
    "opus":   2_000,
}

# Base overhead per agent (SKILL.md prompt + context block + output structure)
BASE_TOKENS: dict[str, float] = {
    "haiku":  3_000,
    "sonnet": 8_000,
    "opus":   15_000,
}


def _model_key(model_str: str) -> str:
    if "haiku" in model_str:
        return "haiku"
    if "sonnet" in model_str:
        return "sonnet"
    if "opus" in model_str:
        return "opus"
    return "sonnet"


def estimate_agent_cost(
    agent: AgentMeta,
    java_file_count: int,
    config_file_count: int = 0,
) -> float:
    """Estimate USD cost for running one agent against a project."""
    mk = _model_key(agent.model)
    pricing = PRICING[mk]

    input_tokens = (
        BASE_TOKENS[mk]
        + java_file_count * TOKENS_PER_JAVA_FILE[mk] * 0.7   # ~70% input
        + config_file_count * TOKENS_PER_CONFIG_FILE[mk] * 0.7
    )
    output_tokens = (
        java_file_count * TOKENS_PER_JAVA_FILE[mk] * 0.3    # ~30% output
        + config_file_count * TOKENS_PER_CONFIG_FILE[mk] * 0.3
    )

    cost = (
        input_tokens / 1_000_000 * pricing["input"]
        + output_tokens / 1_000_000 * pricing["output"]
    )
    return round(cost, 4)


def estimate_scan_cost(
    agents: list[AgentMeta],
    java_file_count: int,
    config_file_count: int = 5,
) -> "CostEstimate":
    """Estimate total cost for a set of agents."""
    per_agent: dict[str, float] = {}
    total = 0.0

    for agent in agents:
        # Agents that skip java files are much cheaper
        from .file_scope import AGENTS_NO_JAVA
        java_count = 0 if agent.id in AGENTS_NO_JAVA else java_file_count
        cfg_count = config_file_count if agent.id in AGENTS_NO_JAVA else (config_file_count // 2)

        cost = estimate_agent_cost(agent, java_count, cfg_count)
        per_agent[agent.id] = cost
        total += cost

    return CostEstimate(
        total_usd=round(total, 3),
        per_agent=per_agent,
        java_file_count=java_file_count,
        agent_count=len(agents),
    )


@dataclass
class CostEstimate:
    total_usd: float
    per_agent: dict[str, float]
    java_file_count: int
    agent_count: int

    def format_table(self) -> str:
        """Format a human-readable cost table."""
        lines = [
            f"  {'Agent':<32} {'Model':<10} {'Est. Cost':>10}",
            "  " + "─" * 54,
        ]
        for agent_id, cost in sorted(self.per_agent.items(), key=lambda x: -x[1]):
            agent = AGENT_REGISTRY.get(agent_id)
            if not agent:
                continue
            mk = _model_key(agent.model)
            lines.append(f"  {agent_id} {agent.name:<26} {mk.capitalize():<10} ${cost:>8.3f}")
        lines.append("  " + "─" * 54)
        lines.append(f"  {'TOTAL':<42} ${self.total_usd:>8.3f}")
        return "\n".join(lines)

    @property
    def breakdown(self) -> str:
        h = sum(v for aid, v in self.per_agent.items()
                if AGENT_REGISTRY.get(aid) and "haiku" in (AGENT_REGISTRY[aid].model))
        s = sum(v for aid, v in self.per_agent.items()
                if AGENT_REGISTRY.get(aid) and "sonnet" in (AGENT_REGISTRY[aid].model))
        o = sum(v for aid, v in self.per_agent.items()
                if AGENT_REGISTRY.get(aid) and "opus" in (AGENT_REGISTRY[aid].model))
        parts = []
        if h:
            parts.append(f"Haiku ${h:.3f}")
        if s:
            parts.append(f"Sonnet ${s:.3f}")
        if o:
            parts.append(f"Opus ${o:.3f}")
        return " + ".join(parts)


def select_agents_within_budget(
    agents: list[AgentMeta],
    budget_usd: float,
    java_file_count: int,
    config_file_count: int = 5,
    strategy: str = "value",
) -> tuple[list[AgentMeta], "CostEstimate"]:
    """Select agents that fit within a dollar budget.

    Strategy:
      'value'    — prefer lower phases (more signal per dollar)
      'security' — prioritise security-focused agents (A02, A03, A12)
      'phase1'   — only Phase 1 agents

    Returns (selected_agents, estimate).
    """
    from .file_scope import AGENTS_NO_JAVA

    # Compute cost per agent
    candidates: list[tuple[AgentMeta, float]] = []
    for agent in agents:
        java_count = 0 if agent.id in AGENTS_NO_JAVA else java_file_count
        cfg_count = config_file_count if agent.id in AGENTS_NO_JAVA else (config_file_count // 2)
        cost = estimate_agent_cost(agent, java_count, cfg_count)
        candidates.append((agent, cost))

    # Prioritise by strategy
    SECURITY_AGENTS = {"A02", "A03", "A12"}
    PRIORITY_ORDER = {"A03": 0, "A12": 1, "A10": 2, "A02": 3, "A04": 4,
                      "A01": 5, "A11": 6, "A13": 7, "A14": 8, "A15": 9,
                      "A09": 10, "A05": 11, "A06": 12, "A07": 13, "A08": 14}

    if strategy == "security":
        candidates.sort(key=lambda x: (
            0 if x[0].id in SECURITY_AGENTS else 1,
            PRIORITY_ORDER.get(x[0].id, 99),
        ))
    elif strategy == "phase1":
        candidates = [(a, c) for a, c in candidates if a.phase == 1]
    else:  # 'value' — phase order
        candidates.sort(key=lambda x: (x[0].phase, PRIORITY_ORDER.get(x[0].id, 99)))

    selected: list[AgentMeta] = []
    running_cost = 0.0

    for agent, cost in candidates:
        if running_cost + cost <= budget_usd:
            selected.append(agent)
            running_cost += cost

    estimate = estimate_scan_cost(selected, java_file_count, config_file_count)
    return selected, estimate


def count_project_files(project_path: Path) -> tuple[int, int]:
    """Return (java_count, config_count) for a project directory."""
    excl = frozenset(["target", "build", ".git", "node_modules", "generated-sources"])
    java_count = sum(
        1 for p in project_path.rglob("*.java")
        if not any(part in excl for part in p.parts)
    )
    config_patterns = ["*.properties", "*.yml", "*.yaml", "*.xml", "*.gradle", "*.gradle.kts"]
    config_count = 0
    for pat in config_patterns:
        for p in project_path.rglob(pat):
            if not any(part in excl for part in p.parts):
                config_count += 1

    return java_count, config_count

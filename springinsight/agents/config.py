"""Agent enable/disable configuration.

Config is persisted at ~/.springinsight/agent_config.json as a simple dict:
    {"A01": true, "A02": true, "A03": false, ...}

Agents not listed default to enabled=True.
"""

from __future__ import annotations

import json
from pathlib import Path

from .registry import AGENT_REGISTRY, AgentMeta

CONFIG_PATH = Path.home() / ".springinsight" / "agent_config.json"


def load_agent_config() -> dict[str, bool]:
    """Load the agent enabled/disabled config. Returns {agent_id: bool}."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_agent_config(config: dict[str, bool]) -> None:
    """Persist the agent config to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def is_agent_enabled(agent_id: str) -> bool:
    """Return True if the agent is enabled (default: True if not configured)."""
    config = load_agent_config()
    return config.get(agent_id, True)


def get_agents_with_config() -> list[dict]:
    """Return all agents with their enabled/disabled state and metadata."""
    config = load_agent_config()
    result = []
    for agent_id, agent in sorted(AGENT_REGISTRY.items(), key=lambda x: x[0]):
        result.append({
            "id": agent_id,
            "name": agent.name,
            "model": agent.model,
            "phase": agent.phase,
            "description": agent.description if hasattr(agent, "description") else "",
            "enabled": config.get(agent_id, True),
        })
    return result


def get_enabled_agent_ids() -> set[str] | None:
    """Return set of enabled agent IDs, or None if all are enabled (no config)."""
    config = load_agent_config()
    if not config:
        return None  # None == "all enabled"
    return {aid for aid, enabled in config.items() if enabled}

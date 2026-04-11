"""SpringInsight MCP Server.

Exposes SpringInsight scan capabilities as MCP tools so Claude Code, Cursor,
Cline, and any other MCP-compatible IDE assistant can call them directly.

Usage:
  # Start the MCP server (stdio transport)
  springinsight mcp

  # In Claude Code / Cursor — add to your mcp config:
  # {
  #   "mcpServers": {
  #     "springinsight": {
  #       "command": "springinsight",
  #       "args": ["mcp"]
  #     }
  #   }
  # }

Available tools:
  scan_project          — scan a local path or GitHub URL
  get_scan_status       — poll a running scan
  get_findings          — list findings, with optional severity filter
  get_agent_report      — get the full markdown report from one agent
  list_recent_scans     — show the last N completed scans with scores
  enable_agents         — enable/disable specific agents before a scan
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ── Try to import the MCP SDK ─────────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        CallToolResult,
        ListToolsResult,
        TextContent,
        Tool,
    )
    import mcp.types as mcp_types
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def _no_mcp_error():
    print(
        "ERROR: 'mcp' package not installed.\n"
        "Install it with:  pip install 'springinsight[mcp]'\n"
        "or:               pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)


# ── Tool implementations ──────────────────────────────────────────────────────

def _scan_project(project: str, agents: str = "all", phase: int | None = None) -> dict:
    """Run springinsight scan via CLI and return the run summary."""
    from ..db.database import init_db, get_db
    from ..db.models import Run

    init_db()

    cmd = ["springinsight", "run", project]
    if agents and agents != "all":
        cmd += ["--agents", agents]
    if phase:
        cmd += ["--phase", str(phase)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=900,
        )
        # Read the latest run from DB
        with get_db() as db:
            run = db.query(Run).order_by(Run.started_at.desc()).first()
            if run:
                return {
                    "run_id": run.id,
                    "project_name": run.project_name,
                    "status": run.status,
                    "score_overall": run.score_overall,
                    "score_security": run.score_security,
                    "agents_completed": run.agents_completed or [],
                    "stdout_tail": result.stdout[-1000:] if result.stdout else "",
                }
    except subprocess.TimeoutExpired:
        return {"error": "Scan timed out after 15 minutes"}
    except Exception as exc:
        return {"error": str(exc)}

    return {"error": "Scan produced no results"}


def _get_scan_status(run_id: str) -> dict:
    from ..db.database import init_db, get_db
    from ..db.models import Run, AgentRun

    init_db()
    with get_db() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": f"Run {run_id!r} not found"}
        agent_runs = db.query(AgentRun).filter(AgentRun.run_id == run_id).all()
        return {
            "run_id": run.id,
            "project_name": run.project_name,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "score_overall": run.score_overall,
            "score_security": run.score_security,
            "score_code_quality": run.score_code_quality,
            "score_architecture": run.score_architecture,
            "agents_completed": run.agents_completed or [],
            "agent_details": [
                {
                    "id": ar.agent_id,
                    "name": ar.agent_name,
                    "status": ar.status,
                    "findings": ar.findings_count,
                    "files": ar.files_processed,
                }
                for ar in agent_runs
            ],
        }


def _get_findings(run_id: str | None = None, severity: str | None = None, limit: int = 50) -> dict:
    from ..db.database import init_db, get_db
    from ..db.models import Run, Finding

    init_db()
    with get_db() as db:
        if run_id:
            run = db.query(Run).filter(Run.id == run_id).first()
        else:
            run = db.query(Run).order_by(Run.started_at.desc()).first()

        if not run:
            return {"error": "No runs found"}

        q = db.query(Finding).filter(Finding.run_id == run.id)
        if severity:
            sevs = [s.strip().upper() for s in severity.split(",")]
            q = q.filter(Finding.severity.in_(sevs))
        findings = q.order_by(Finding.severity).limit(limit).all()

        return {
            "run_id": run.id,
            "project_name": run.project_name,
            "total_shown": len(findings),
            "findings": [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "category": f.category,
                    "agent_id": f.agent_id,
                    "file": f.file_path,
                    "line": f.line_number,
                    "problem": f.problem,
                    "fix": f.fix_description,
                    "effort_hours": f.effort_hours,
                }
                for f in findings
            ],
        }


def _get_agent_report(run_id: str | None = None, agent_id: str | None = None) -> dict:
    """Return the markdown report written by a specific agent."""
    from ..db.database import init_db, get_db
    from ..db.models import Run, AgentRun

    init_db()
    with get_db() as db:
        if run_id:
            run = db.query(Run).filter(Run.id == run_id).first()
        else:
            run = db.query(Run).order_by(Run.started_at.desc()).first()

        if not run:
            return {"error": "No runs found"}

        q = db.query(AgentRun).filter(AgentRun.run_id == run.id)
        if agent_id:
            q = q.filter(AgentRun.agent_id == agent_id.upper())
        agent_run = q.first()

        if not agent_run:
            return {"error": f"Agent run not found (agent_id={agent_id})"}

        if agent_run.output_md_path and Path(agent_run.output_md_path).exists():
            content = Path(agent_run.output_md_path).read_text(encoding="utf-8")
            return {
                "run_id": run.id,
                "agent_id": agent_run.agent_id,
                "agent_name": agent_run.agent_name,
                "status": agent_run.status,
                "report": content,
            }

        return {"error": f"No report found for {agent_run.agent_id}"}


def _list_recent_scans(limit: int = 10) -> dict:
    from ..db.database import init_db, get_db
    from ..db.models import Run
    from sqlalchemy import func

    init_db()
    with get_db() as db:
        from ..db.models import Finding
        runs = db.query(Run).order_by(Run.started_at.desc()).limit(limit).all()
        result = []
        for r in runs:
            cnt = db.query(func.count(Finding.id)).filter(Finding.run_id == r.id).scalar() or 0
            result.append({
                "run_id": r.id,
                "project_name": r.project_name,
                "source_url": r.source_url,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "score_overall": r.score_overall,
                "score_security": r.score_security,
                "findings_count": cnt,
                "agents_completed": len(r.agents_completed or []),
            })
    return {"scans": result, "count": len(result)}


def _enable_agents(enabled: list[str], disabled: list[str]) -> dict:
    from ..agents.config import load_agent_config, save_agent_config
    from ..agents.registry import AGENT_REGISTRY

    config = load_agent_config()
    for aid in enabled:
        if aid.upper() in AGENT_REGISTRY:
            config[aid.upper()] = True
    for aid in disabled:
        if aid.upper() in AGENT_REGISTRY:
            config[aid.upper()] = False
    save_agent_config(config)

    enabled_ids = [k for k, v in config.items() if v]
    disabled_ids = [k for k, v in config.items() if not v]
    return {
        "saved": True,
        "enabled_count": len([a for a in AGENT_REGISTRY if config.get(a, True)]),
        "disabled": disabled_ids,
    }


# ── MCP Server bootstrap ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "scan_project",
        "description": (
            "Scan a Java/Spring Boot project for security vulnerabilities, dead code, "
            "CVEs, misconfigurations, and code quality issues using SpringInsight's "
            "multi-agent analysis engine. Pass a local directory path or a GitHub URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Local directory path (/path/to/project) or GitHub URL (https://github.com/owner/repo)"
                },
                "agents": {
                    "type": "string",
                    "default": "all",
                    "description": "Comma-separated agent IDs to run, or 'all'. E.g. 'A03,A10,A12' for a quick scan."
                },
                "phase": {
                    "type": "integer",
                    "description": "Run only agents from a specific phase (1=fast, 2=deep, 3=architecture, 4=generators)"
                },
            },
            "required": ["project"],
        },
    },
    {
        "name": "get_scan_status",
        "description": "Get the status, scores, and per-agent details for a scan run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run ID from scan_project output"}
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_findings",
        "description": (
            "Get findings (vulnerabilities, code smells, CVEs, etc.) from a scan. "
            "Optionally filter by severity. Returns up to 50 findings by default."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run ID (omit for latest scan)"},
                "severity": {
                    "type": "string",
                    "description": "Filter: CRITICAL, HIGH, MEDIUM, LOW, or comma-separated e.g. 'CRITICAL,HIGH'"
                },
                "limit": {"type": "integer", "default": 50, "description": "Max findings to return"},
            },
        },
    },
    {
        "name": "get_agent_report",
        "description": "Get the full Markdown report written by a specific agent (e.g. security analysis, dead code, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run ID (omit for latest)"},
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID: A01 (code review), A02 (security), A03 (CVE), A04 (JPA), A05 (architecture), A06 (tests), A07 (docs), A08 (LLD), A09 (PR review), A10 (dead code), A11 (performance), A12 (config), A13 (API), A14 (concurrency), A15 (dependency graph)"
                },
            },
        },
    },
    {
        "name": "list_recent_scans",
        "description": "List recent SpringInsight scans with their scores and finding counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "description": "Number of scans to return"}
            },
        },
    },
    {
        "name": "enable_agents",
        "description": "Enable or disable specific agents for future scans to control cost and scope.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Agent IDs to enable e.g. ['A03','A10','A12']"
                },
                "disabled": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Agent IDs to disable e.g. ['A05','A08']"
                },
            },
        },
    },
]


def _dispatch_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call and return a JSON string result."""
    try:
        if name == "scan_project":
            result = _scan_project(**arguments)
        elif name == "get_scan_status":
            result = _get_scan_status(**arguments)
        elif name == "get_findings":
            result = _get_findings(**arguments)
        elif name == "get_agent_report":
            result = _get_agent_report(**arguments)
        elif name == "list_recent_scans":
            result = _list_recent_scans(**arguments)
        elif name == "enable_agents":
            result = _enable_agents(
                enabled=arguments.get("enabled", []),
                disabled=arguments.get("disabled", []),
            )
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result, indent=2, default=str)


def run_server() -> None:
    """Start the MCP server using stdio transport."""
    if not HAS_MCP:
        _no_mcp_error()

    server = Server("springinsight")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        text = _dispatch_tool(name, arguments)
        return [TextContent(type="text", text=text)]

    import asyncio

    async def _main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_main())

"""MCP server command — ``springinsight mcp``."""

from __future__ import annotations

import sys
import click


@click.command("mcp")
@click.option("--transport", default="stdio", type=click.Choice(["stdio"]), show_default=True,
              help="MCP transport protocol (only stdio supported currently)")
def mcp_cmd(transport: str):
    """Start SpringInsight as an MCP server.

    Exposes SpringInsight scan capabilities as MCP tools, compatible with
    Claude Code, Cursor, Cline, and any MCP-aware IDE assistant.

    \b
    Add to your MCP config (e.g. ~/.config/claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "springinsight": {
          "command": "springinsight",
          "args": ["mcp"]
        }
      }
    }

    \b
    Available tools once connected:
      scan_project        — scan a local path or GitHub URL
      get_scan_status     — poll a running scan by run_id
      get_findings        — list findings with optional severity filter
      get_agent_report    — get full markdown report from any agent
      list_recent_scans   — show recent scans with scores
      enable_agents       — enable/disable agents to control cost
    """
    try:
        from ..mcp.server import run_server
    except ImportError as exc:
        click.echo(
            click.style("✗ MCP dependencies missing. ", fg="red")
            + "Install with:\n\n  pip install 'springinsight[mcp]'\n",
            err=True,
        )
        sys.exit(1)

    run_server()

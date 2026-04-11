"""Web UI server command — ``springinsight web``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click


@click.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address")
@click.option("--port", default=8080, show_default=True, help="Port to listen on")
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on source changes (dev mode)")
@click.option(
    "--data-dir",
    default=None,
    type=click.Path(),
    help="Directory for scans, repos, and DB (default: ~/.springinsight/web)",
)
@click.option("--open", "open_browser", is_flag=True, default=False, help="Open browser after start")
def web_cmd(host: str, port: int, reload: bool, data_dir: str | None, open_browser: bool):
    """Start the SpringInsight Web UI.

    \b
    Examples:
      springinsight web
      springinsight web --port 9000 --open
      springinsight web --data-dir /tmp/si-data --reload
    """
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        click.echo(
            click.style("✗ uvicorn not installed. ", fg="red")
            + "Install web extras:\n\n  pip install 'springinsight[web]'\n",
            err=True,
        )
        sys.exit(1)

    if data_dir:
        os.environ["SPRINGINSIGHT_DATA_DIR"] = str(Path(data_dir).expanduser().resolve())

    url = f"http://{host}:{port}"
    click.echo(
        click.style("⚡ SpringInsight Web UI", fg="bright_yellow", bold=True)
        + f"\n  URL:      {click.style(url, fg='cyan', underline=True)}"
        + f"\n  Data dir: {os.environ.get('SPRINGINSIGHT_DATA_DIR', '~/.springinsight/web')}"
        + ("\n  Mode:     development (auto-reload)" if reload else "")
        + "\n"
        + click.style("  Press Ctrl+C to stop.\n", dim=True)
    )

    if open_browser:
        import threading, webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn
    uvicorn.run(
        "springinsight.web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="warning",
    )

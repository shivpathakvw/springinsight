"""Web UI server command — ``springinsight web``."""

from __future__ import annotations

import logging
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
    help="Directory for scans, repos, and DB (default: ~/.springinsight)",
)
@click.option("--open", "open_browser", is_flag=True, default=False, help="Open browser after start")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show agent progress and scan logs in the terminal")
def web_cmd(host: str, port: int, reload: bool, data_dir: str | None, open_browser: bool, verbose: bool):
    """Start the SpringInsight Web UI.

    \b
    Examples:
      springinsight web
      springinsight web --port 9000 --open
      springinsight web --verbose          # show live agent progress in terminal
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

    # Configure logging level based on --verbose
    log_level_str = "info" if verbose else "warning"
    if verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
        # Show agent runner logs in the terminal
        logging.getLogger("springinsight.agents.runner").setLevel(logging.INFO)
        logging.getLogger("springinsight.web.scanner").setLevel(logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    url = f"http://{host}:{port}"
    click.echo(
        click.style("⚡ SpringInsight Web UI", fg="bright_yellow", bold=True)
        + f"\n  URL:      {click.style(url, fg='cyan', underline=True)}"
        + f"\n  Data dir: {os.environ.get('SPRINGINSIGHT_DATA_DIR', '~/.springinsight')}"
        + ("\n  Mode:     verbose  (agent logs → terminal)" if verbose else "")
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
        log_level=log_level_str,
    )

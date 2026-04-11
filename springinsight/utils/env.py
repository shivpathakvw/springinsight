"""Environment and .env file loader for SpringInsight.

Loads ANTHROPIC_API_KEY (and other variables) from a .env file so the
``claude --print`` subprocess can access the API key without it being
hard-coded in any config file.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(work_dir: Path | str | None = None) -> None:
    """Load a .env file into os.environ.

    Search order:
      1. ``{work_dir}/.env``
      2. ``~/.springinsight/.env``
      3. ``./.env`` (current working directory)

    Only sets variables that are NOT already set in the environment so that
    shell exports always take precedence.

    ``python-dotenv`` is optional — if it is not installed, a minimal
    built-in parser is used instead.
    """
    candidates: list[Path] = []
    if work_dir:
        candidates.append(Path(work_dir).expanduser().resolve() / ".env")
    candidates.append(Path.home() / ".springinsight" / ".env")
    candidates.append(Path.cwd() / ".env")

    env_file: Path | None = next((p for p in candidates if p.exists()), None)
    if env_file is None:
        return

    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_file, override=False)
    except ImportError:
        # Fallback: minimal parser (handles VAR=value and export VAR=value)
        _parse_env_file(env_file)


def _parse_env_file(path: Path) -> None:
    """Minimal .env parser — no dependency on python-dotenv."""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip leading `export ` (shell syntax)
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # Only set if not already in environment
        if key and key not in os.environ:
            os.environ[key] = value


def get_api_key() -> str | None:
    """Return the Anthropic API key from the environment, or None."""
    return os.environ.get("ANTHROPIC_API_KEY")

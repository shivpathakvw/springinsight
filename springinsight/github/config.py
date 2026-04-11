"""GitHub integration configuration.

Config is persisted at ~/.springinsight/github.json:
{
  "token": "ghp_...",
  "github_user": "mylogin",
  "watched_repos": [
    {"full_name": "owner/repo", "last_polled": "...", "prs_scanned": 5}
  ],
  "poll_interval_minutes": 5,
  "comment_threshold": "MEDIUM",
  "auto_comment": true,
  "fail_pr_on_critical": false
}

PR scan history is in ~/.springinsight/pr-scans.json:
{
  "<owner/repo>:<pr_number>": {"commit_sha": "...", "run_id": "...", "scanned_at": "..."}
}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

GITHUB_CONFIG_PATH = Path.home() / ".springinsight" / "github.json"
PR_SCAN_HISTORY_PATH = Path.home() / ".springinsight" / "pr-scans.json"


def load_github_config() -> dict[str, Any]:
    """Load GitHub integration config."""
    if not GITHUB_CONFIG_PATH.exists():
        return {
            "connected": False,
            "token": "",
            "github_user": "",
            "watched_repos": [],
            "poll_interval_minutes": 5,
            "comment_threshold": "MEDIUM",
            "auto_comment": True,
            "fail_pr_on_critical": False,
        }
    try:
        data = json.loads(GITHUB_CONFIG_PATH.read_text(encoding="utf-8"))
        data["connected"] = bool(data.get("token"))
        return data
    except Exception:
        return load_github_config.__wrapped__() if hasattr(load_github_config, "__wrapped__") else {
            "connected": False, "token": "", "github_user": "",
            "watched_repos": [], "poll_interval_minutes": 5,
            "comment_threshold": "MEDIUM", "auto_comment": True,
            "fail_pr_on_critical": False,
        }


def save_github_config(cfg: dict[str, Any]) -> None:
    """Persist config to disk."""
    GITHUB_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    GITHUB_CONFIG_PATH.write_text(json.dumps(cfg, indent=2, default=str), encoding="utf-8")


def get_github_token() -> str | None:
    """Return stored GitHub token or None."""
    cfg = load_github_config()
    return cfg.get("token") or None


def add_watched_repo(full_name: str) -> list[dict]:
    """Add a repo to the watched list. Returns updated list."""
    cfg = load_github_config()
    repos: list[dict] = cfg.get("watched_repos", [])
    if not any(r["full_name"] == full_name for r in repos):
        repos.append({"full_name": full_name, "last_polled": None, "prs_scanned": 0})
    cfg["watched_repos"] = repos
    save_github_config(cfg)
    return repos


def remove_watched_repo(full_name: str) -> None:
    """Remove a repo from the watched list."""
    cfg = load_github_config()
    cfg["watched_repos"] = [r for r in cfg.get("watched_repos", []) if r["full_name"] != full_name]
    save_github_config(cfg)


def load_pr_scan_history() -> dict[str, dict]:
    """Load PR scan history dict."""
    if not PR_SCAN_HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(PR_SCAN_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def mark_pr_scanned(full_name: str, pr_number: int, commit_sha: str, run_id: str) -> None:
    """Record that a PR has been scanned at a given commit SHA."""
    history = load_pr_scan_history()
    key = f"{full_name}:{pr_number}"
    history[key] = {
        "commit_sha": commit_sha,
        "run_id": run_id,
        "scanned_at": datetime.utcnow().isoformat(),
    }
    PR_SCAN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    PR_SCAN_HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")


def was_pr_scanned(full_name: str, pr_number: int, head_sha: str) -> bool:
    """Return True if this PR at the given commit has already been scanned."""
    history = load_pr_scan_history()
    key = f"{full_name}:{pr_number}"
    entry = history.get(key)
    if not entry:
        return False
    return entry.get("commit_sha") == head_sha

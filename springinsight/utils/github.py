"""GitHub URL detection and repo cloning utilities."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Regex to match GitHub (and GitLab) URLs
_GITHUB_RE = re.compile(
    r"^https?://(github\.com|gitlab\.com|bitbucket\.org)/"
    r"(?P<owner>[^/]+)/(?P<repo>[^/\s.]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def is_github_url(value: str) -> bool:
    """Return True if value looks like a GitHub/GitLab/Bitbucket URL."""
    return bool(_GITHUB_RE.match(value.strip()))


def _extract_repo_name(url: str) -> str:
    m = _GITHUB_RE.match(url.strip())
    if not m:
        # Fallback: last path segment without .git
        return url.rstrip("/").split("/")[-1].removesuffix(".git")
    return m.group("repo")


def clone_or_update_repo(url: str, work_dir: Path) -> Path:
    """Clone a remote repo into {work_dir}/.springinsight/repos/<name>.

    If the directory already exists, run `git pull` to update it.
    Returns the absolute path to the cloned repository.
    """
    repos_dir = work_dir / ".springinsight" / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    repo_name = _extract_repo_name(url)
    repo_path = repos_dir / repo_name

    if repo_path.exists():
        # Update existing clone
        result = subprocess.run(
            ["git", "-C", str(repo_path), "pull", "--ff-only"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            # Non-fatal: use existing checkout
            pass
    else:
        # Fresh clone
        result = subprocess.run(
            ["git", "clone", "--depth", "50", url, str(repo_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git clone failed for {url}:\n{result.stderr.strip()}"
            )

    return repo_path.resolve()


def resolve_project_path(source: str, work_dir: Path) -> tuple[Path, str, str]:
    """Resolve source (path or URL) to an absolute local path.

    Returns:
        (project_path, source_type, source_url)
        source_type: "local" | "github"
        source_url:  original URL if GitHub, else ""
    """
    if is_github_url(source):
        project_path = clone_or_update_repo(source, work_dir)
        return project_path, "github", source
    else:
        project_path = Path(source).expanduser().resolve()
        if not project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {project_path}")
        return project_path, "local", ""

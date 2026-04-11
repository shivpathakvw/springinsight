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


def clone_or_update_repo(url: str, work_dir: Path, branch: str | None = None) -> Path:
    """Clone a remote repo into {work_dir}/.springinsight/repos/<name[-branch]>.

    If the directory already exists, run ``git pull`` to update it.
    Supports cloning a specific branch via *branch*.
    Returns the absolute path to the cloned repository.
    """
    repos_dir = work_dir / ".springinsight" / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    repo_name = _extract_repo_name(url)
    # Separate directories per branch so switching branches doesn't clobber state
    dir_name = f"{repo_name}__{branch}" if branch else repo_name
    repo_path = repos_dir / dir_name

    if repo_path.exists():
        # Update existing clone
        subprocess.run(
            ["git", "-C", str(repo_path), "pull", "--ff-only"],
            capture_output=True, text=True
        )
        # Non-fatal: use existing checkout if pull fails
    else:
        # Fresh clone
        cmd = ["git", "clone", "--depth", "50"]
        if branch:
            cmd += ["--branch", branch, "--single-branch"]
        cmd += [url, str(repo_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"git clone failed for {url} (branch={branch or 'default'}):\n"
                f"{result.stderr.strip()}"
            )

    return repo_path.resolve()


def resolve_project_path(
    source: str,
    work_dir: Path,
    branch: str | None = None,
) -> tuple[Path, str, str]:
    """Resolve source (path or URL) to an absolute local path.

    Args:
        source:   GitHub/GitLab URL or local filesystem path.
        work_dir: Base directory where cloned repos are stored.
        branch:   Optional branch name to check out (GitHub URLs only).

    Returns:
        (project_path, source_type, source_url)
        source_type: "local" | "github"
        source_url:  original URL if GitHub, else ""
    """
    if is_github_url(source):
        project_path = clone_or_update_repo(source, work_dir, branch=branch)
        return project_path, "github", source
    else:
        project_path = Path(source).expanduser().resolve()
        if not project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {project_path}")
        return project_path, "local", ""

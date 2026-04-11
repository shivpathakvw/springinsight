"""Incremental scanning support — hash-based file cache.

On repeat scans of the same project, files whose SHA-256 hash hasn't changed
since the last successful run are skipped by agents. This can cut token usage
by 80-90% on CI/PR workflows where only a handful of files change per commit.

How it works
────────────
1. Before a scan, ``get_unchanged_files(project_path, agent_id)`` returns the
   set of file paths that haven't changed since the agent last ran on them.
2. This set is injected into the agent prompt as a ``SKIP_FILES`` block.
3. After a successful scan, ``update_cache(project_path, files, agent_id)``
   records the new hashes.

The cache is stored in the global SQLite DB via the ``FileCache`` ORM model.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..db.database import get_db
from ..db.models import FileCache

logger = logging.getLogger(__name__)

HASH_CHUNK = 65_536  # 64 KB read chunks


def _sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(HASH_CHUNK):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _iter_java_files(project_path: Path, exclude_paths: list[str] | None = None) -> Iterator[Path]:
    """Yield all .java files under project_path, respecting exclusions."""
    exclude_paths = exclude_paths or ["/target/", "/build/", "/.git/", "/node_modules/", "/generated-sources/"]
    for p in project_path.rglob("*.java"):
        path_str = str(p)
        if any(excl in path_str for excl in exclude_paths):
            continue
        yield p


def _iter_config_files(project_path: Path) -> Iterator[Path]:
    """Yield config files relevant to config/infra agents."""
    patterns = ["*.properties", "*.yml", "*.yaml", "Dockerfile*", "*.xml", "*.gradle", "*.toml"]
    exclude = ["/target/", "/build/", "/.git/"]
    for pattern in patterns:
        for p in project_path.rglob(pattern):
            if any(e in str(p) for e in exclude):
                continue
            yield p


# ── Public API ─────────────────────────────────────────────────────────────────

def get_unchanged_files(
    project_path: Path,
    agent_id: str,
    file_paths: list[Path] | None = None,
) -> set[str]:
    """Return relative paths of files that haven't changed since last agent run.

    These can be passed to agents as SKIP_FILES to avoid re-analysing them.
    Returns an empty set if no cache exists (first run) or on any error.
    """
    try:
        with get_db() as db:
            cached = db.query(FileCache).filter(
                FileCache.project_path == str(project_path),
                FileCache.last_run_id.isnot(None),
            ).all()
            cache_map: dict[str, str] = {c.file_path: c.file_hash for c in cached}
    except Exception:
        return set()

    if not cache_map:
        return set()

    unchanged: set[str] = set()
    files = file_paths or list(_iter_java_files(project_path))

    for f in files:
        try:
            rel = str(f.relative_to(project_path))
        except ValueError:
            rel = str(f)

        cached_hash = cache_map.get(rel)
        if cached_hash and _sha256(f) == cached_hash:
            unchanged.add(rel)

    logger.debug(
        "[%s] Incremental scan: %d/%d files unchanged (will skip)",
        agent_id, len(unchanged), len(files)
    )
    return unchanged


def update_cache(
    project_path: Path,
    file_paths: list[Path],
    run_id: str,
) -> int:
    """Record current hashes for a list of files. Returns number of entries saved."""
    project_str = str(project_path)
    saved = 0

    try:
        with get_db() as db:
            for f in file_paths:
                try:
                    rel = str(f.relative_to(project_path))
                except ValueError:
                    rel = str(f)

                file_hash = _sha256(f)
                if not file_hash:
                    continue

                existing = db.query(FileCache).filter(
                    FileCache.project_path == project_str,
                    FileCache.file_path == rel,
                ).first()

                if existing:
                    existing.file_hash = file_hash
                    existing.last_analyzed_at = datetime.utcnow()
                    existing.last_run_id = run_id
                else:
                    db.add(FileCache(
                        project_path=project_str,
                        file_path=rel,
                        file_hash=file_hash,
                        last_analyzed_at=datetime.utcnow(),
                        last_run_id=run_id,
                    ))
                saved += 1
    except Exception as exc:
        logger.warning("File cache update failed: %s", exc)

    return saved


def invalidate_cache(project_path: Path) -> int:
    """Clear all cache entries for a project (force full re-scan)."""
    try:
        with get_db() as db:
            deleted = db.query(FileCache).filter(
                FileCache.project_path == str(project_path)
            ).delete()
            return deleted
    except Exception:
        return 0


def cache_stats(project_path: Path) -> dict:
    """Return cache statistics for a project."""
    try:
        with get_db() as db:
            total = db.query(FileCache).filter(
                FileCache.project_path == str(project_path)
            ).count()
            return {"cached_files": total, "project_path": str(project_path)}
    except Exception:
        return {"cached_files": 0, "project_path": str(project_path)}

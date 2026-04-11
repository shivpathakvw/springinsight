"""Intelligent batch splitting for large Spring Boot projects.

When a project has more than LARGE_PROJECT_THRESHOLD Java files the scanner
would consume excessive memory and tokens running all 15 agents over the full
tree at once.  This module detects large projects and splits them into
manageable batches using a priority-ordered strategy:

  1. Maven multi-module  (each pom.xml submodule → one batch)
  2. Gradle subprojects  (settings.gradle include() statements)
  3. Top-level source dirs (services/, modules/, apps/, …)
  4. Java package groups  (com.example.auth, com.example.billing, …)
  5. File-count slices    (raw 150-file chunks — last resort)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LARGE_PROJECT_THRESHOLD = 1000   # Java files before we offer batching
DEFAULT_BATCH_SIZE      = 150    # Target Java files per batch
_SKIP_DIRS = {".git", "target", "build", ".gradle", "node_modules", ".idea", ".mvn", "__pycache__"}


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ScanBatch:
    """Describes one chunk of a large project to scan independently."""
    id: str                          # "batch_01", "batch_02", …
    name: str                        # Human-readable label shown in UI
    description: str                 # Longer description / strategy hint
    include_paths: list[str]         # Relative paths from project root to include
    java_file_count: int = 0
    strategy: str = "folder"         # maven | gradle | dir | package | slice

    def to_batch_scope_block(self, project_path: str, batch_index: int, total_batches: int) -> str:
        """Return prompt text injected into each agent telling it to stay in scope."""
        paths_formatted = "\n".join(f"  - {p}" for p in self.include_paths)
        return f"""
=== BATCH SCAN SCOPE ===
This is BATCH {batch_index} of {total_batches}: "{self.name}"
You MUST ONLY analyze files that live under the following directories/paths:

{paths_formatted}

IMPORTANT: Do NOT analyze Java files outside these paths. Skip any file whose
path does not start with one of the above prefixes. This constraint exists
because the project is split into {total_batches} batches to avoid overload.
Findings from all batches will be merged automatically by the orchestrator.
=== END BATCH SCOPE ===
"""


@dataclass
class BatchPlan:
    """Full batch plan for a large project."""
    project_path: str
    total_java_files: int
    batches: list[ScanBatch]
    strategy: str          # How batches were determined

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "total_java_files": self.total_java_files,
            "batch_count": self.batch_count,
            "strategy": self.strategy,
            "batches": [
                {
                    "id": b.id,
                    "name": b.name,
                    "description": b.description,
                    "include_paths": b.include_paths,
                    "java_file_count": b.java_file_count,
                    "strategy": b.strategy,
                }
                for b in self.batches
            ],
        }


# ── File counting ──────────────────────────────────────────────────────────────

def count_java_files(path: Path) -> int:
    """Count .java files recursively, skipping build/git dirs."""
    try:
        return sum(
            1 for f in path.rglob("*.java")
            if not any(skip in f.parts for skip in _SKIP_DIRS)
        )
    except Exception:
        return 0


def detect_large_project(
    project_path: Path,
    threshold: int = LARGE_PROJECT_THRESHOLD,
) -> tuple[bool, int]:
    """Return (is_large, java_file_count)."""
    n = count_java_files(project_path)
    return n >= threshold, n


# ── Strategy helpers ───────────────────────────────────────────────────────────

def _find_maven_modules(project_path: Path) -> list[Path]:
    """Return Maven submodule directories that contain src/ trees."""
    root_pom = project_path / "pom.xml"
    if not root_pom.exists():
        return []
    try:
        root_text = root_pom.read_text(errors="ignore")
        # Only consider projects that actually have <modules> in root pom
        if "<modules>" not in root_text:
            return []
    except Exception:
        return []

    modules: list[Path] = []
    for pom in sorted(project_path.rglob("pom.xml")):
        if pom.parent == project_path:
            continue
        if any(skip in pom.parts for skip in _SKIP_DIRS):
            continue
        # Must have a src/ dir to be a real module (not just a parent pom)
        if (pom.parent / "src").exists():
            modules.append(pom.parent)
    return modules


def _find_gradle_subprojects(project_path: Path) -> list[Path]:
    """Return Gradle subproject directories from settings.gradle."""
    for name in ("settings.gradle", "settings.gradle.kts"):
        settings = project_path / name
        if settings.exists():
            break
    else:
        return []

    try:
        text = settings.read_text(errors="ignore")
    except Exception:
        return []

    # match include(":sub") and include(":parent:child")
    found = re.findall(r"""include\s*\(\s*['"]([^'"]+)['"]\s*\)""", text)
    result: list[Path] = []
    for sp in found:
        rel = sp.lstrip(":").replace(":", "/")
        sp_path = project_path / rel
        if sp_path.exists() and (sp_path / "src").exists():
            result.append(sp_path)
    return result


def _top_source_dirs(project_path: Path) -> list[tuple[Path, int]]:
    """
    Return (dir, java_count) for top-level directories that contain Java source.
    Prioritises common layout names: services/, modules/, components/, apps/.
    """
    priority = {"services", "modules", "components", "apps", "plugins", "lib", "core"}
    candidates: list[tuple[Path, int]] = []

    for child in sorted(project_path.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _SKIP_DIRS:
            continue
        n = count_java_files(child)
        if n > 0:
            candidates.append((child, n))

    # Sort: priority dirs first, then by file count desc
    candidates.sort(key=lambda x: (0 if x[0].name in priority else 1, -x[1]))
    return candidates


def _split_by_package_groups(project_path: Path, target_size: int) -> list[ScanBatch]:
    """
    Group Java files by their second-level package (e.g. com.example.auth) and
    merge small groups until target_size is reached.
    """
    # Locate Java source roots
    java_roots: list[Path] = []
    for pattern in ("src/main/java", "src/test/java", "src"):
        for p in project_path.glob(f"**/{pattern}"):
            if p.is_dir() and any(p.rglob("*.java")):
                java_roots.append(p)
                break  # One per sub-tree

    if not java_roots:
        java_roots = [project_path]

    # Build package → file list map
    pkg_groups: dict[str, list[Path]] = {}
    for root in java_roots:
        for jf in root.rglob("*.java"):
            if any(skip in jf.parts for skip in _SKIP_DIRS):
                continue
            rel_parts = jf.relative_to(root).parts
            # Use up to 3-level package (com.example.service) as group key
            key = ".".join(rel_parts[:min(3, len(rel_parts) - 1)]) or rel_parts[0]
            pkg_groups.setdefault(key, []).append(jf)

    # Sort groups by size descending, then merge small ones into batches
    sorted_groups = sorted(pkg_groups.items(), key=lambda x: -len(x[1]))
    batches: list[ScanBatch] = []
    current_pkgs: list[str] = []
    current_count = 0
    batch_num = 1

    def _flush():
        nonlocal current_pkgs, current_count, batch_num
        if not current_pkgs:
            return
        label = ", ".join(current_pkgs[:2]) + ("…" if len(current_pkgs) > 2 else "")
        # Convert package notation to path prefixes
        include_paths = [p.replace(".", "/") for p in current_pkgs]
        batches.append(ScanBatch(
            id=f"batch_{batch_num:02d}",
            name=f"Packages: {label}",
            description=f"{len(current_pkgs)} package group(s), ~{current_count} Java files",
            include_paths=include_paths,
            java_file_count=current_count,
            strategy="package",
        ))
        batch_num += 1
        current_pkgs = []
        current_count = 0

    for pkg, files in sorted_groups:
        if current_count + len(files) > target_size and current_pkgs:
            _flush()
        current_pkgs.append(pkg)
        current_count += len(files)

    _flush()
    return batches


def _merge_dirs_into_batches(
    dirs: list[tuple[Path, int]],
    project_path: Path,
    target_size: int,
) -> list[ScanBatch]:
    """Pack directories greedily into target_size batches."""
    batches: list[ScanBatch] = []
    current_dirs: list[Path] = []
    current_count = 0
    batch_num = 1

    def _flush():
        nonlocal current_dirs, current_count, batch_num
        if not current_dirs:
            return
        rel_paths = [str(d.relative_to(project_path)) for d in current_dirs]
        label_dirs = ", ".join(d.name for d in current_dirs[:3])
        batches.append(ScanBatch(
            id=f"batch_{batch_num:02d}",
            name=f"Dirs: {label_dirs}{'…' if len(current_dirs) > 3 else ''}",
            description=f"{len(rel_paths)} director{'y' if len(rel_paths)==1 else 'ies'}, ~{current_count} Java files",
            include_paths=rel_paths,
            java_file_count=current_count,
            strategy="dir",
        ))
        batch_num += 1
        current_dirs = []
        current_count = 0

    for child, n in dirs:
        if current_count + n > target_size and current_dirs:
            _flush()
        current_dirs.append(child)
        current_count += n

    _flush()
    return batches


# ── Public API ─────────────────────────────────────────────────────────────────

def create_batch_plan(
    project_path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> BatchPlan:
    """
    Analyse *project_path* and return a BatchPlan whose batches are sized
    around *batch_size* Java files each.

    Strategy waterfall:
      maven  → gradle  → source-dir  → package-group  → file-count slice
    """
    total = count_java_files(project_path)

    # ── 1. Maven multi-module ───────────────────────────────────────────────
    maven_modules = _find_maven_modules(project_path)
    if len(maven_modules) >= 2:
        raw: list[ScanBatch] = []
        for i, mod_path in enumerate(maven_modules, 1):
            n = count_java_files(mod_path)
            if n == 0:
                continue
            rel = str(mod_path.relative_to(project_path))
            raw.append(ScanBatch(
                id=f"batch_{i:02d}",
                name=f"Module: {mod_path.name}",
                description=f"Maven module at {rel}  ({n} Java files)",
                include_paths=[rel],
                java_file_count=n,
                strategy="maven",
            ))
        if len(raw) >= 2:
            # Re-number sequentially after filtering empty modules
            for idx, b in enumerate(raw, 1):
                b.id = f"batch_{idx:02d}"
            return BatchPlan(str(project_path), total, raw, "maven")

    # ── 2. Gradle subprojects ───────────────────────────────────────────────
    gradle_projs = _find_gradle_subprojects(project_path)
    if len(gradle_projs) >= 2:
        raw = []
        for i, sp_path in enumerate(gradle_projs, 1):
            n = count_java_files(sp_path)
            if n == 0:
                continue
            rel = str(sp_path.relative_to(project_path))
            raw.append(ScanBatch(
                id=f"batch_{i:02d}",
                name=f"Subproject: {sp_path.name}",
                description=f"Gradle subproject at {rel}  ({n} Java files)",
                include_paths=[rel],
                java_file_count=n,
                strategy="gradle",
            ))
        if len(raw) >= 2:
            for idx, b in enumerate(raw, 1):
                b.id = f"batch_{idx:02d}"
            return BatchPlan(str(project_path), total, raw, "gradle")

    # ── 3. Top-level source directories ─────────────────────────────────────
    top_dirs = _top_source_dirs(project_path)
    if len(top_dirs) >= 2:
        batches = _merge_dirs_into_batches(top_dirs, project_path, batch_size)
        if len(batches) >= 2:
            return BatchPlan(str(project_path), total, batches, "dir")

    # ── 4. Package groups ───────────────────────────────────────────────────
    pkg_batches = _split_by_package_groups(project_path, batch_size)
    if len(pkg_batches) >= 2:
        return BatchPlan(str(project_path), total, pkg_batches, "package")

    # ── 5. File-count slices (last resort) ──────────────────────────────────
    all_java = sorted(
        f for f in project_path.rglob("*.java")
        if not any(s in f.parts for s in _SKIP_DIRS)
    )
    slice_batches: list[ScanBatch] = []
    for i, start in enumerate(range(0, len(all_java), batch_size), 1):
        chunk = all_java[start:start + batch_size]
        # Derive common parent directories for this chunk
        dirs = sorted({str(f.parent.relative_to(project_path)) for f in chunk})
        slice_batches.append(ScanBatch(
            id=f"batch_{i:02d}",
            name=f"Files {start + 1}–{start + len(chunk)}",
            description=f"{len(chunk)} Java files (alphabetical slice)",
            include_paths=dirs[:8],   # cap at 8 path entries in prompt
            java_file_count=len(chunk),
            strategy="slice",
        ))

    return BatchPlan(str(project_path), total, slice_batches, "slice")

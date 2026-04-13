"""
springinsight.rag.code_graph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQLite-backed code graph for Spring Boot codebases.

Tables (added to the existing springinsight.db):
  code_nodes   — every class / method / field / endpoint / config chunk
  code_edges   — relationships: calls, autowires, extends, implements,
                 publishes, listens, annotates

The graph is used after vector search to expand context:
  given a matching class, also pull in its methods, dependencies, and callers.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .parser import CodeChunk


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS code_nodes (
    id           TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    node_type    TEXT NOT NULL,
    fqn          TEXT NOT NULL,
    simple_name  TEXT,
    file_path    TEXT,
    line_start   INTEGER DEFAULT 0,
    line_end     INTEGER DEFAULT 0,
    annotations  TEXT DEFAULT '[]',
    metadata     TEXT DEFAULT '{}',
    text         TEXT,
    indexed_at   REAL
);

CREATE INDEX IF NOT EXISTS idx_nodes_project ON code_nodes (project_path);
CREATE INDEX IF NOT EXISTS idx_nodes_type    ON code_nodes (project_path, node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_fqn     ON code_nodes (fqn);

CREATE TABLE IF NOT EXISTS code_edges (
    id           TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    from_node    TEXT NOT NULL,
    to_node      TEXT NOT NULL,
    edge_type    TEXT NOT NULL,
    metadata     TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_edges_from    ON code_edges (from_node);
CREATE INDEX IF NOT EXISTS idx_edges_to      ON code_edges (to_node);
CREATE INDEX IF NOT EXISTS idx_edges_project ON code_edges (project_path);

CREATE TABLE IF NOT EXISTS rag_index_state (
    project_path TEXT PRIMARY KEY,
    last_indexed REAL,
    file_count   INTEGER DEFAULT 0,
    chunk_count  INTEGER DEFAULT 0,
    node_count   INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'idle'
);
"""


# ---------------------------------------------------------------------------
# CodeGraph
# ---------------------------------------------------------------------------

class CodeGraph:
    """Manages the SQLite code graph for one or more projects."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_tables()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_tables(self):
        with self._conn() as conn:
            conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def clear_project(self, project_path: str):
        """Remove all nodes/edges for a project before re-indexing."""
        with self._conn() as conn:
            conn.execute("DELETE FROM code_nodes WHERE project_path = ?", (project_path,))
            conn.execute("DELETE FROM code_edges WHERE project_path = ?", (project_path,))

    def insert_chunks(self, chunks: List[CodeChunk], batch_size: int = 500):
        """Bulk-insert CodeChunks into code_nodes."""
        rows = [
            (
                c.chunk_id,
                c.project_path,
                c.chunk_type,
                c.fqn,
                c.simple_name,
                c.file_path,
                c.line_start,
                c.line_end,
                json.dumps(c.annotations),
                json.dumps(c.metadata),
                c.text,
                time.time(),
            )
            for c in chunks
        ]
        with self._conn() as conn:
            for i in range(0, len(rows), batch_size):
                conn.executemany(
                    """INSERT OR REPLACE INTO code_nodes
                       (id, project_path, node_type, fqn, simple_name, file_path,
                        line_start, line_end, annotations, metadata, text, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows[i : i + batch_size],
                )

    def build_edges(self, project_path: str):
        """
        Post-process: derive edges from the stored nodes using annotation
        and naming patterns.  Called once after all chunks are inserted.
        """
        with self._conn() as conn:
            nodes = conn.execute(
                "SELECT id, fqn, node_type, simple_name, annotations, metadata "
                "FROM code_nodes WHERE project_path = ?",
                (project_path,),
            ).fetchall()

        edges: List[Tuple] = []
        # Build lookup maps
        class_by_simple: Dict[str, str] = {}  # simple_name → node_id
        node_by_fqn: Dict[str, str] = {}       # fqn → node_id

        for n in nodes:
            node_by_fqn[n["fqn"]] = n["id"]
            if n["node_type"] == "class":
                class_by_simple[n["simple_name"]] = n["id"]

        # Derive edges from metadata
        for n in nodes:
            meta: Dict[str, Any] = json.loads(n["metadata"] or "{}")
            fqn = n["fqn"]
            node_id = n["id"]

            # extends edge
            extends = meta.get("extends", "")
            if extends:
                for ext in extends.split(","):
                    ext = ext.strip().split("<")[0]
                    target = class_by_simple.get(ext)
                    if target:
                        edges.append(self._edge(project_path, node_id, target, "extends"))

            # implements edge
            impls = meta.get("implements", "")
            if impls:
                for impl in impls.split(","):
                    impl = impl.strip().split("<")[0]
                    target = class_by_simple.get(impl)
                    if target:
                        edges.append(self._edge(project_path, node_id, target, "implements"))

            # autowires edge: field with @Autowired OR injected type name matches a class
            if n["node_type"] == "field":
                field_type = meta.get("type", "").split("<")[0].strip()
                is_injected = meta.get("is_injected", False)
                class_fqn = meta.get("class_fqn", "")
                if (is_injected or not json.loads(n["annotations"] or "[]")) and field_type:
                    source_class = node_by_fqn.get(class_fqn) or class_by_simple.get(class_fqn.split(".")[-1])
                    target_class = class_by_simple.get(field_type)
                    if source_class and target_class and source_class != target_class:
                        edges.append(self._edge(project_path, source_class, target_class, "autowires",
                                                 {"field_type": field_type}))

        # Write edges
        with self._conn() as conn:
            conn.execute("DELETE FROM code_edges WHERE project_path = ?", (project_path,))
            if edges:
                conn.executemany(
                    "INSERT OR IGNORE INTO code_edges (id, project_path, from_node, to_node, edge_type, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    edges,
                )

    def _edge(self, project_path, from_id, to_id, edge_type, meta=None) -> Tuple:
        import hashlib
        eid = hashlib.sha256(f"{from_id}::{to_id}::{edge_type}".encode()).hexdigest()[:16]
        return (eid, project_path, from_id, to_id, edge_type, json.dumps(meta or {}))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM code_nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(row) if row else None

    def get_neighbours(self, node_id: str, depth: int = 1) -> List[Dict]:
        """Return directly connected nodes (in both directions)."""
        visited = {node_id}
        frontier = {node_id}
        result: List[Dict] = []

        with self._conn() as conn:
            for _ in range(depth):
                if not frontier:
                    break
                placeholders = ",".join("?" * len(frontier))
                rows = conn.execute(
                    f"SELECT to_node FROM code_edges WHERE from_node IN ({placeholders})",
                    list(frontier),
                ).fetchall()
                rows += conn.execute(
                    f"SELECT from_node AS to_node FROM code_edges WHERE to_node IN ({placeholders})",
                    list(frontier),
                ).fetchall()
                new_frontier = {r["to_node"] for r in rows} - visited
                if new_frontier:
                    nph = ",".join("?" * len(new_frontier))
                    node_rows = conn.execute(
                        f"SELECT * FROM code_nodes WHERE id IN ({nph})",
                        list(new_frontier),
                    ).fetchall()
                    result.extend(dict(r) for r in node_rows)
                visited |= new_frontier
                frontier = new_frontier

        return result

    def get_nodes_by_type(self, project_path: str, node_type: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM code_nodes WHERE project_path = ? AND node_type = ?",
                (project_path, node_type),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_class_tree(self, project_path: str, class_fqn: str) -> Dict:
        """Return a class + its methods + its autowired dependencies."""
        with self._conn() as conn:
            cls = conn.execute(
                "SELECT * FROM code_nodes WHERE fqn = ? AND project_path = ?",
                (class_fqn, project_path),
            ).fetchone()
            if not cls:
                return {}
            cls = dict(cls)

            methods = conn.execute(
                "SELECT * FROM code_nodes WHERE project_path = ? AND node_type = 'method' "
                "AND json_extract(metadata, '$.class_fqn') = ?",
                (project_path, class_fqn),
            ).fetchall()

            out_edges = conn.execute(
                "SELECT e.edge_type, n.fqn, n.simple_name, n.node_type "
                "FROM code_edges e JOIN code_nodes n ON e.to_node = n.id "
                "WHERE e.from_node = ?",
                (cls["id"],),
            ).fetchall()

        return {
            "class": cls,
            "methods": [dict(m) for m in methods],
            "dependencies": [dict(e) for e in out_edges],
        }

    def search_by_name(self, project_path: str, name: str) -> List[Dict]:
        """Simple name-based lookup."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM code_nodes WHERE project_path = ? AND "
                "(simple_name LIKE ? OR fqn LIKE ?) LIMIT 20",
                (project_path, f"%{name}%", f"%{name}%"),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Index state
    # ------------------------------------------------------------------

    def update_index_state(self, project_path: str, **kwargs):
        fields = {**kwargs, "last_indexed": time.time()}
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [project_path]
        with self._conn() as conn:
            conn.execute(
                f"INSERT OR IGNORE INTO rag_index_state (project_path) VALUES (?)",
                (project_path,),
            )
            conn.execute(
                f"UPDATE rag_index_state SET {cols} WHERE project_path = ?",
                vals,
            )

    def get_index_state(self, project_path: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM rag_index_state WHERE project_path = ?",
                (project_path,),
            ).fetchone()
        return dict(row) if row else None

    def get_stats(self, project_path: str) -> Dict:
        with self._conn() as conn:
            nc = conn.execute(
                "SELECT COUNT(*) as c FROM code_nodes WHERE project_path = ?",
                (project_path,),
            ).fetchone()["c"]
            ec = conn.execute(
                "SELECT COUNT(*) as c FROM code_edges WHERE project_path = ?",
                (project_path,),
            ).fetchone()["c"]
            by_type = conn.execute(
                "SELECT node_type, COUNT(*) as c FROM code_nodes WHERE project_path = ? GROUP BY node_type",
                (project_path,),
            ).fetchall()
        return {
            "nodes": nc,
            "edges": ec,
            "by_type": {r["node_type"]: r["c"] for r in by_type},
        }

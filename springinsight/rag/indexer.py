"""
springinsight.rag.indexer
~~~~~~~~~~~~~~~~~~~~~~~~~~
Orchestrates the full indexing pipeline:

  1. Scan project → CodeChunks  (parser.py)
  2. Insert chunks into SQLite code graph  (code_graph.py)
  3. Build graph edges from annotation analysis
  4. Embed each chunk's text with sentence-transformers all-MiniLM-L6-v2
  5. Upsert embeddings into ChromaDB

ChromaDB persists to  <work_dir>/chroma/
Embeddings model is downloaded once to ~/.cache/huggingface/ (~80 MB).

Usage:
    from springinsight.rag.indexer import Indexer
    indexer = Indexer(db_path="springinsight.db", chroma_dir="./chroma")
    async for progress in indexer.index(project_path="./my-spring-app"):
        print(progress)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from .parser import CodeChunk, scan_project
from .code_graph import CodeGraph

log = logging.getLogger(__name__)

# ChromaDB collection name pattern: <project_name>_code
def _collection_name(project_path: str) -> str:
    name = Path(project_path).name.lower()
    # ChromaDB collection names must be alphanumeric + hyphens/underscores, 3-63 chars
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    safe = safe[:50] or "project"
    return f"{safe}_code"


# ---------------------------------------------------------------------------
# Lazy singletons (avoid loading heavy models at import time)
# ---------------------------------------------------------------------------

_embedder = None
_chroma_client = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _get_chroma_client(persist_dir: str):
    global _chroma_client
    if _chroma_client is None:
        import chromadb  # type: ignore
        os.makedirs(persist_dir, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=persist_dir)
    return _chroma_client


# ---------------------------------------------------------------------------
# IndexProgress
# ---------------------------------------------------------------------------

class IndexProgress:
    __slots__ = ("phase", "total", "done", "message", "error")

    def __init__(self, phase: str, message: str, total: int = 0, done: int = 0, error: str = ""):
        self.phase = phase
        self.message = message
        self.total = total
        self.done = done
        self.error = error

    def to_dict(self) -> Dict:
        return {
            "phase": self.phase,
            "message": self.message,
            "total": self.total,
            "done": self.done,
            "pct": round(self.done / self.total * 100) if self.total else 0,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------

class Indexer:
    """Full indexing pipeline for a Spring Boot project."""

    BATCH_SIZE = 64   # chunks per embedding batch

    def __init__(self, db_path: str, chroma_dir: str):
        self.db_path = db_path
        self.chroma_dir = chroma_dir
        self.graph = CodeGraph(db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def index(self, project_path: str) -> AsyncIterator[IndexProgress]:
        """
        Full re-index pipeline.  Yields IndexProgress objects as each
        phase completes.  Safe to call multiple times (idempotent).
        """
        project_path = str(Path(project_path).resolve())

        # ── Phase 1: Scan ──────────────────────────────────────────────
        yield IndexProgress("scan", "Scanning Java source files…")
        await asyncio.sleep(0)  # yield to event loop

        chunks: List[CodeChunk] = []
        file_set: set = set()
        try:
            for chunk in scan_project(project_path):
                chunks.append(chunk)
                file_set.add(chunk.file_path)
        except Exception as e:
            yield IndexProgress("error", "Scan failed", error=str(e))
            return

        # Safety-net dedup: overloaded methods or regex edge-cases can still
        # produce duplicate chunk_ids.  Keep the first occurrence of each ID.
        seen_ids: set = set()
        deduped: List[CodeChunk] = []
        for c in chunks:
            if c.chunk_id not in seen_ids:
                seen_ids.add(c.chunk_id)
                deduped.append(c)
        chunks = deduped

        total_chunks = len(chunks)
        total_files = len(file_set)

        yield IndexProgress("scan", f"Found {total_files} files → {total_chunks} chunks", total=total_chunks, done=total_chunks)
        await asyncio.sleep(0)

        if not chunks:
            yield IndexProgress("done", "No Java files found in project", total=0, done=0)
            return

        # ── Phase 2: Graph ─────────────────────────────────────────────
        yield IndexProgress("graph", "Building code graph…", total=total_chunks)
        await asyncio.sleep(0)

        self.graph.clear_project(project_path)
        self.graph.insert_chunks(chunks)
        self.graph.build_edges(project_path)
        stats = self.graph.get_stats(project_path)

        yield IndexProgress("graph",
                            f"Graph: {stats['nodes']} nodes, {stats['edges']} edges",
                            total=stats['nodes'], done=stats['nodes'])
        await asyncio.sleep(0)

        # ── Phase 3: Embed ─────────────────────────────────────────────
        yield IndexProgress("embed", "Loading embedding model…", total=total_chunks)
        await asyncio.sleep(0)

        embedder = await asyncio.get_event_loop().run_in_executor(None, _get_embedder)
        client = _get_chroma_client(self.chroma_dir)
        coll_name = _collection_name(project_path)

        # Delete and recreate collection to ensure clean state
        try:
            client.delete_collection(coll_name)
        except Exception:
            pass
        collection = client.create_collection(
            name=coll_name,
            metadata={"hnsw:space": "cosine"},
        )

        embedded = 0
        for i in range(0, total_chunks, self.BATCH_SIZE):
            batch = chunks[i : i + self.BATCH_SIZE]
            texts = [c.text for c in batch]

            # Run embedding in executor to avoid blocking the event loop
            embeddings = await asyncio.get_event_loop().run_in_executor(
                None, lambda t=texts: embedder.encode(t).tolist()
            )

            ids = [c.chunk_id for c in batch]
            metadatas = [
                {
                    "file_path": c.file_path,
                    "node_type": c.chunk_type,
                    "fqn": c.fqn,
                    "simple_name": c.simple_name,
                    "line_start": c.line_start,
                    "annotations": json.dumps(c.annotations),
                    "project_path": project_path,
                }
                for c in batch
            ]

            collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )

            embedded += len(batch)
            yield IndexProgress("embed",
                                f"Embedding chunks… {embedded}/{total_chunks}",
                                total=total_chunks, done=embedded)
            await asyncio.sleep(0)

        # ── Phase 4: Finalise ──────────────────────────────────────────
        self.graph.update_index_state(
            project_path,
            file_count=total_files,
            chunk_count=total_chunks,
            node_count=stats["nodes"],
            status="ready",
        )

        yield IndexProgress(
            "done",
            f"Index complete — {total_files} files, {total_chunks} chunks, {stats['nodes']} graph nodes",
            total=total_chunks,
            done=total_chunks,
        )

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def get_status(self, project_path: str) -> Dict:
        project_path = str(Path(project_path).resolve())
        state = self.graph.get_index_state(project_path)
        if not state:
            return {"status": "not_indexed", "project_path": project_path}
        stats = self.graph.get_stats(project_path)
        return {**state, **stats, "project_path": project_path}

    def is_indexed(self, project_path: str) -> bool:
        project_path = str(Path(project_path).resolve())
        state = self.graph.get_index_state(project_path)
        return bool(state and state.get("status") == "ready")

    def get_collection(self, project_path: str):
        """Return the ChromaDB collection for a project (None if not indexed)."""
        client = _get_chroma_client(self.chroma_dir)
        coll_name = _collection_name(project_path)
        try:
            return client.get_collection(coll_name)
        except Exception:
            return None

"""
springinsight.rag.searcher
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Semantic search + Claude-powered answer synthesis for SpringInsight CodeSearch.

Pipeline per query:
  1. Embed the user's natural-language query (MiniLM-L6-v2)
  2. Vector similarity search in ChromaDB → top-k chunks
  3. Graph context expansion (pull in neighbouring nodes)
  4. Build a rich context window
  5. Claude claude-sonnet-4-6 synthesises a concise, cited answer

Streaming variant yields tokens as they arrive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from .code_graph import CodeGraph
from .indexer import Indexer, _get_embedder

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result data model
# ---------------------------------------------------------------------------

@dataclass
class Source:
    node_type: str          # class|method|endpoint|field|config
    fqn: str
    simple_name: str
    file_path: str
    line_start: int
    score: float            # cosine similarity 0–1
    snippet: str            # first 300 chars of chunk text


@dataclass
class SearchResult:
    query: str
    answer: str
    sources: List[Source] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Synthesiser prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are CodeSearch, an expert Spring Boot code intelligence assistant embedded
in SpringInsight.  You answer developer questions about a specific codebase
using the retrieved code context below.

Rules:
- Answer PRECISELY what was asked.  Be concise but complete.
- Always cite which class / method the information comes from.
- If the context does not contain enough information, say so clearly.
- Use Markdown for code blocks (```java).
- Focus on Spring Boot specifics: annotations, transactions, beans, REST.
- Do NOT invent code that is not in the context.
"""

_USER_TEMPLATE = """\
## Developer Question
{query}

## Retrieved Code Context
{context}

Answer the question above based ONLY on the context provided.
Cite the relevant class/method names in your answer.
"""


# ---------------------------------------------------------------------------
# Searcher
# ---------------------------------------------------------------------------

class Searcher:

    TOP_K = 10          # vector results
    GRAPH_DEPTH = 1     # neighbour expansion depth
    MAX_CONTEXT_CHARS = 12_000

    def __init__(self, db_path: str, chroma_dir: str):
        self.graph = CodeGraph(db_path)
        self.indexer = Indexer(db_path=db_path, chroma_dir=chroma_dir)

    # ------------------------------------------------------------------
    # Non-streaming search (returns complete SearchResult)
    # ------------------------------------------------------------------

    async def search(self, project_path: str, query: str, top_k: int = TOP_K) -> SearchResult:
        project_path = str(Path(project_path).resolve())

        collection = self.indexer.get_collection(project_path)
        if collection is None:
            return SearchResult(query=query, answer="", error="Project not indexed. Run index first.")

        # ── 1. Embed query ────────────────────────────────────────────
        embedder = await asyncio.get_event_loop().run_in_executor(None, _get_embedder)
        q_embedding = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embedder.encode(query).tolist()
        )

        # ── 2. Vector search ──────────────────────────────────────────
        results = collection.query(
            query_embeddings=[q_embedding],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        docs      = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0]  if results["metadatas"] else []
        distances = results["distances"][0]  if results["distances"] else []

        sources: List[Source] = []
        context_parts: List[str] = []

        for doc, meta, dist in zip(docs, metadatas, distances):
            score = max(0.0, 1.0 - float(dist))
            src = Source(
                node_type=meta.get("node_type", ""),
                fqn=meta.get("fqn", ""),
                simple_name=meta.get("simple_name", ""),
                file_path=meta.get("file_path", ""),
                line_start=int(meta.get("line_start", 0)),
                score=round(score, 3),
                snippet=doc[:300],
            )
            sources.append(src)

        # ── 3. Graph expansion ─────────────────────────────────────────
        node_ids_seen: set = set()
        for meta in metadatas:
            # Fetch neighbours from graph to enrich context
            fqn = meta.get("fqn", "")
            neighbours = self.graph.search_by_name(project_path, fqn.split(".")[-1])
            for n in neighbours[:3]:
                if n["id"] not in node_ids_seen and n.get("text"):
                    node_ids_seen.add(n["id"])
                    context_parts.append(f"[RELATED: {n['fqn']}]\n{n['text'][:400]}")

        # Build primary context from vector results
        primary = []
        total = 0
        for doc, meta in zip(docs, metadatas):
            block = f"[{meta.get('node_type','').upper()}: {meta.get('fqn','')}  {meta.get('file_path','')}:{meta.get('line_start','')}]\n{doc}"
            if total + len(block) > self.MAX_CONTEXT_CHARS:
                break
            primary.append(block)
            total += len(block)

        context = "\n\n---\n\n".join(primary + context_parts[:5])

        # ── 4. Synthesise answer ───────────────────────────────────────
        answer = await self._synthesise(query, context)

        return SearchResult(query=query, answer=answer, sources=sources)

    # ------------------------------------------------------------------
    # Streaming search (yields tokens for SSE)
    # ------------------------------------------------------------------

    async def stream_search(self, project_path: str, query: str) -> AsyncIterator[str]:
        """
        Yields:
          "sources:<json>"    — source list JSON as first event
          "<token>"           — answer tokens as they stream
          "DONE"              — terminal marker
          "ERROR:<msg>"       — on failure
        """
        project_path = str(Path(project_path).resolve())

        collection = self.indexer.get_collection(project_path)
        if collection is None:
            yield "ERROR:Project not indexed. Please index the project first."
            return

        try:
            embedder = await asyncio.get_event_loop().run_in_executor(None, _get_embedder)
            q_embedding = await asyncio.get_event_loop().run_in_executor(
                None, lambda: embedder.encode(query).tolist()
            )

            results = collection.query(
                query_embeddings=[q_embedding],
                n_results=min(self.TOP_K, collection.count()),
                include=["documents", "metadatas", "distances"],
            )

            docs      = results["documents"][0] if results["documents"] else []
            metadatas = results["metadatas"][0]  if results["metadatas"] else []
            distances = results["distances"][0]  if results["distances"] else []

            sources = []
            for doc, meta, dist in zip(docs, metadatas, distances):
                score = max(0.0, 1.0 - float(dist))
                sources.append({
                    "node_type":   meta.get("node_type", ""),
                    "fqn":         meta.get("fqn", ""),
                    "simple_name": meta.get("simple_name", ""),
                    "file_path":   meta.get("file_path", ""),
                    "line_start":  int(meta.get("line_start", 0)),
                    "score":       round(score, 3),
                    "snippet":     doc[:300],
                })

            # Emit sources first
            yield f"sources:{json.dumps(sources)}"

            # Build context
            context_parts = []
            total = 0
            for doc, meta in zip(docs, metadatas):
                block = f"[{meta.get('node_type','').upper()}: {meta.get('fqn','')}  {meta.get('file_path','')}:{meta.get('line_start','')}]\n{doc}"
                if total + len(block) > self.MAX_CONTEXT_CHARS:
                    break
                context_parts.append(block)
                total += len(block)
            context = "\n\n---\n\n".join(context_parts)

            # Stream answer from Claude
            async for token in self._stream_synthesise(query, context):
                yield token

        except Exception as e:
            log.exception("stream_search failed")
            yield f"ERROR:{e}"

    # ------------------------------------------------------------------
    # Claude synthesis helpers
    # ------------------------------------------------------------------

    async def _synthesise(self, query: str, context: str) -> str:
        """Non-streaming Claude call, returns complete answer."""
        prompt = _USER_TEMPLATE.format(query=query, context=context)
        full_prompt = f"<system>\n{_SYSTEM}\n</system>\n\n{prompt}"

        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "--model", "claude-sonnet-4-6",
            "--allowedTools", "",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=full_prompt.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"Claude error: {stderr.decode()[:500]}")
        return stdout.decode().strip()

    async def _stream_synthesise(self, query: str, context: str) -> AsyncIterator[str]:
        """Streaming Claude call — yields tokens."""
        prompt = _USER_TEMPLATE.format(query=query, context=context)
        full_prompt = f"<system>\n{_SYSTEM}\n</system>\n\n{prompt}"

        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "--model", "claude-sonnet-4-6",
            "--allowedTools", "",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Write prompt and close stdin
        proc.stdin.write(full_prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        # Stream stdout
        buffer = b""
        while True:
            chunk = await proc.stdout.read(64)
            if not chunk:
                break
            buffer += chunk
            # Decode and yield what we have
            try:
                text = buffer.decode("utf-8")
                yield text
                buffer = b""
            except UnicodeDecodeError:
                pass  # incomplete UTF-8 sequence, accumulate more

        if buffer:
            yield buffer.decode("utf-8", errors="replace")

        await proc.wait()
        yield "DONE"

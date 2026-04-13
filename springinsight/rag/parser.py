"""
springinsight.rag.parser
~~~~~~~~~~~~~~~~~~~~~~~~
Java source-file parser that produces structured chunks for embedding.

Parses every .java file into typed chunks:
  - CLASS      : class / interface / enum declaration
  - METHOD     : method with signature, annotations, body excerpt
  - FIELD      : field declarations with type and annotations
  - ENDPOINT   : synthesised endpoint node (HTTP method + path + handler)
  - CONFIG     : key-value pairs from application.properties / .yml

No JDK required — pure regex + lightweight AST via javalang (falls back to
regex if javalang fails for any file).
"""

from __future__ import annotations

import hashlib
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CodeChunk:
    """A single indexable unit from the codebase."""
    chunk_id: str                   # stable ID: project::fqn::chunk_type
    project_path: str               # absolute path to project root
    chunk_type: str                 # class|method|field|endpoint|config
    fqn: str                        # fully-qualified name (best-effort)
    simple_name: str
    file_path: str                  # relative to project_path
    line_start: int
    line_end: int
    annotations: List[str] = field(default_factory=list)
    text: str = ""                  # the embedding-ready text block
    raw_code: str = ""              # original source excerpt
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Spring annotation sets
# ---------------------------------------------------------------------------

SPRING_ANNOTATIONS = {
    "@RestController", "@Controller", "@Service", "@Repository",
    "@Component", "@Configuration", "@SpringBootApplication",
    "@Entity", "@Table", "@MappedSuperclass", "@Embeddable",
    "@RequestMapping", "@GetMapping", "@PostMapping", "@PutMapping",
    "@DeleteMapping", "@PatchMapping",
    "@Transactional", "@Async", "@Scheduled", "@EventListener",
    "@TransactionalEventListener", "@Cacheable", "@CacheEvict", "@CachePut",
    "@FeignClient", "@KafkaListener",
    "@Autowired", "@Value", "@Bean", "@Primary", "@Qualifier",
}

HTTP_MAPPINGS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    "RequestMapping": "ANY",
}

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_ANN_RE   = re.compile(r'@[\w.]+(?:\([^)]*\))?')
_CLASS_RE = re.compile(
    r'(?:public\s+|protected\s+|private\s+)?(?:abstract\s+|final\s+)?'
    r'(class|interface|enum|record)\s+(\w+)'
    r'(?:\s+extends\s+([\w.<>, ]+?))?'
    r'(?:\s+implements\s+([\w.<>, ]+?))?'
    r'\s*\{'
)
_METHOD_RE = re.compile(
    r'(?:public|protected|private)\s+'
    r'(?:static\s+|final\s+|synchronized\s+|async\s+)?'
    r'(?:[\w<>\[\].,? ]+)\s+'
    r'(\w+)\s*\(([^)]*)\)\s*'
    r'(?:throws\s+[\w, ]+)?\s*\{'
)
_FIELD_RE = re.compile(
    r'(?:private|protected|public)\s+(?:final\s+|static\s+|volatile\s+)*'
    r'([\w<>\[\].,? ]+)\s+(\w+)\s*(?:=.+?)?;'
)
_PATH_RE = re.compile(r'(?:value|path)\s*=\s*["\{]([^"}\)]+)["\}]|["\{]([^"}\)]+)["\}]')


def _extract_annotations(lines: List[str], idx: int) -> List[str]:
    """Walk backwards from idx collecting annotation lines."""
    anns: List[str] = []
    i = idx - 1
    while i >= 0:
        stripped = lines[i].strip()
        if stripped.startswith("@"):
            anns.append(stripped.split("(")[0])
        elif stripped == "" or stripped.startswith("//") or stripped.startswith("/*"):
            pass
        else:
            break
        i -= 1
    return list(reversed(anns))


def _stable_id(project_path: str, fqn: str, chunk_type: str, line: int = 0) -> str:
    """Stable chunk ID that is unique even for overloaded methods (same name, different line)."""
    raw = f"{project_path}::{fqn}::{chunk_type}::{line}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _path_from_annotation(ann_line: str) -> Optional[str]:
    m = _PATH_RE.search(ann_line)
    if m:
        return m.group(1) or m.group(2)
    return None


# ---------------------------------------------------------------------------
# Java file parser
# ---------------------------------------------------------------------------

class JavaFileParser:
    """Parses a single .java file into CodeChunks."""

    def __init__(self, file_path: Path, project_path: Path):
        self.file_path = file_path
        self.project_path = project_path
        self.rel_path = str(file_path.relative_to(project_path))
        self.source = file_path.read_text(encoding="utf-8", errors="ignore")
        self.lines = self.source.splitlines()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse(self) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        try:
            chunks.extend(self._parse_with_javalang())
        except Exception:
            chunks.extend(self._parse_with_regex())
        return chunks

    # ------------------------------------------------------------------
    # javalang-based parse (preferred)
    # ------------------------------------------------------------------

    def _parse_with_javalang(self) -> List[CodeChunk]:
        import javalang  # noqa: F401  (imported here to allow fallback)
        tree = javalang.parse.parse(self.source)

        package = tree.package.name if tree.package else ""
        chunks: List[CodeChunk] = []

        for path, node in tree:
            if isinstance(node, (javalang.tree.ClassDeclaration,
                                 javalang.tree.InterfaceDeclaration,
                                 javalang.tree.EnumDeclaration,
                                 javalang.tree.RecordDeclaration)):
                chunks.extend(self._jl_class(node, package))

        return chunks

    def _jl_class(self, node, package: str) -> List[CodeChunk]:
        """Extract class + its methods + fields from a javalang AST node."""
        import javalang
        chunks: List[CodeChunk] = []

        class_name = node.name
        fqn = f"{package}.{class_name}" if package else class_name
        annotations = [f"@{a.name}" for a in (node.annotations or [])]
        line = getattr(node.position, "line", 1) if node.position else 1

        extends_str = ""
        if hasattr(node, "extends") and node.extends:
            ext = node.extends
            if isinstance(ext, list):
                extends_str = ", ".join(e.name for e in ext if hasattr(e, "name"))
            else:
                extends_str = getattr(ext, "name", str(ext))

        impls_str = ""
        if hasattr(node, "implements") and node.implements:
            impls_str = ", ".join(i.name for i in node.implements if hasattr(i, "name"))

        # Build readable text for the class chunk
        raw_snippet = self._extract_lines(line - 1, min(line + 20, len(self.lines)))
        text = self._class_text(class_name, fqn, annotations, extends_str, impls_str, package, raw_snippet)

        chunks.append(CodeChunk(
            chunk_id=_stable_id(str(self.project_path), fqn, "class", line),
            project_path=str(self.project_path),
            chunk_type="class",
            fqn=fqn,
            simple_name=class_name,
            file_path=self.rel_path,
            line_start=line,
            line_end=line,
            annotations=annotations,
            text=text,
            raw_code=raw_snippet,
            metadata={
                "package": package,
                "extends": extends_str,
                "implements": impls_str,
                "is_controller": any(a in ("@RestController", "@Controller") for a in annotations),
                "is_service": "@Service" in annotations,
                "is_repository": "@Repository" in annotations,
                "is_entity": "@Entity" in annotations,
            }
        ))

        # Methods
        for method in getattr(node, "methods", []) or []:
            chunks.extend(self._jl_method(method, fqn, package, class_name, annotations))

        # Fields / dependencies
        for f in getattr(node, "fields", []) or []:
            chunks.extend(self._jl_field(f, fqn, class_name))

        return chunks

    def _jl_method(self, method, class_fqn: str, package: str, class_name: str, class_anns: List[str]) -> List[CodeChunk]:
        import javalang
        chunks: List[CodeChunk] = []
        m_anns = [f"@{a.name}" for a in (method.annotations or [])]
        line = getattr(method.position, "line", 1) if method.position else 1
        params = ", ".join(
            f"{p.type.name} {p.name}" for p in (method.parameters or [])
            if hasattr(p.type, "name")
        )
        method_fqn = f"{class_fqn}.{method.name}"
        raw_snippet = self._extract_lines(line - 1, min(line + 30, len(self.lines)))

        text = self._method_text(method.name, method_fqn, m_anns, class_name, params, raw_snippet)

        chunk = CodeChunk(
            chunk_id=_stable_id(str(self.project_path), method_fqn, "method", line),
            project_path=str(self.project_path),
            chunk_type="method",
            fqn=method_fqn,
            simple_name=method.name,
            file_path=self.rel_path,
            line_start=line,
            line_end=line + 30,
            annotations=m_anns,
            text=text,
            raw_code=raw_snippet,
            metadata={
                "class_fqn": class_fqn,
                "params": params,
                "is_transactional": "@Transactional" in m_anns,
                "is_async": "@Async" in m_anns,
                "is_scheduled": "@Scheduled" in m_anns,
                "is_event_listener": any(a in ("@EventListener", "@TransactionalEventListener") for a in m_anns),
            }
        )
        chunks.append(chunk)

        # Endpoint synthesis
        http_ann = next((a for a in m_anns if any(a == f"@{k}" for k in HTTP_MAPPINGS)), None)
        if http_ann:
            ann_name = http_ann.lstrip("@")
            http_method = HTTP_MAPPINGS.get(ann_name, "ANY")
            # Try to extract path from annotation line
            ann_line_raw = ""
            for raw_a in (method.annotations or []):
                if raw_a.name == ann_name:
                    break
            path = self._extract_path_from_source(line)
            class_path = self._extract_class_path_from_source(class_anns)
            full_path = (class_path or "") + (path or "")
            endpoint_fqn = f"{class_fqn}#{method.name}[{http_method} {full_path}]"
            ep_text = (
                f"ENDPOINT: {http_method} {full_path}\n"
                f"HANDLER: {class_name}.{method.name}({params})\n"
                f"ANNOTATIONS: {', '.join(m_anns)}\n"
                f"CLASS: {class_fqn}\n"
                f"CODE:\n{raw_snippet[:600]}"
            )
            chunks.append(CodeChunk(
                chunk_id=_stable_id(str(self.project_path), endpoint_fqn, "endpoint", line),
                project_path=str(self.project_path),
                chunk_type="endpoint",
                fqn=endpoint_fqn,
                simple_name=f"{http_method} {full_path}",
                file_path=self.rel_path,
                line_start=line,
                line_end=line + 30,
                annotations=m_anns,
                text=ep_text,
                raw_code=raw_snippet,
                metadata={
                    "http_method": http_method,
                    "path": full_path,
                    "handler": f"{class_name}.{method.name}",
                    "class_fqn": class_fqn,
                }
            ))

        return chunks

    def _jl_field(self, field_node, class_fqn: str, class_name: str) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        f_anns = [f"@{a.name}" for a in (field_node.annotations or [])]
        line = getattr(field_node.position, "line", 1) if field_node.position else 1
        type_name = getattr(field_node.type, "name", "?")
        for decl in field_node.declarators:
            field_fqn = f"{class_fqn}.{decl.name}"
            text = (
                f"FIELD: {decl.name}\n"
                f"TYPE: {type_name}\n"
                f"CLASS: {class_name} ({class_fqn})\n"
                f"ANNOTATIONS: {', '.join(f_anns) if f_anns else 'none'}\n"
            )
            if "@Autowired" in f_anns or not f_anns:
                text += f"DEPENDENCY: {class_name} depends on {type_name}\n"

            chunks.append(CodeChunk(
                chunk_id=_stable_id(str(self.project_path), field_fqn, "field", line),
                project_path=str(self.project_path),
                chunk_type="field",
                fqn=field_fqn,
                simple_name=decl.name,
                file_path=self.rel_path,
                line_start=line,
                line_end=line,
                annotations=f_anns,
                text=text,
                metadata={"type": type_name, "class_fqn": class_fqn, "is_injected": "@Autowired" in f_anns},
            ))
        return chunks

    # ------------------------------------------------------------------
    # Regex fallback
    # ------------------------------------------------------------------

    def _parse_with_regex(self) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        package = ""
        for line in self.lines[:10]:
            if line.startswith("package "):
                package = line.replace("package ", "").strip().rstrip(";")
                break

        current_class = None
        current_class_line = 0
        current_anns: List[str] = []

        for i, line in enumerate(self.lines):
            stripped = line.strip()

            # Class detection
            cm = _CLASS_RE.search(stripped)
            if cm:
                class_name = cm.group(2)
                fqn = f"{package}.{class_name}" if package else class_name
                ann_block = _extract_annotations(self.lines, i)
                current_class = fqn
                current_class_line = i
                current_anns = ann_block
                raw = self._extract_lines(i, min(i + 15, len(self.lines)))
                text = self._class_text(class_name, fqn, ann_block, cm.group(3) or "", cm.group(4) or "", package, raw)
                chunks.append(CodeChunk(
                    chunk_id=_stable_id(str(self.project_path), fqn, "class", i + 1),
                    project_path=str(self.project_path),
                    chunk_type="class",
                    fqn=fqn,
                    simple_name=class_name,
                    file_path=self.rel_path,
                    line_start=i + 1,
                    line_end=i + 1,
                    annotations=ann_block,
                    text=text,
                    raw_code=raw,
                    metadata={"package": package},
                ))
                continue

            # Method detection
            mm = _METHOD_RE.search(stripped)
            if mm and current_class:
                method_name = mm.group(1)
                params = mm.group(2)
                m_anns = _extract_annotations(self.lines, i)
                method_fqn = f"{current_class}.{method_name}"
                raw = self._extract_lines(i, min(i + 25, len(self.lines)))
                text = self._method_text(method_name, method_fqn, m_anns, current_class.split(".")[-1], params, raw)
                chunks.append(CodeChunk(
                    chunk_id=_stable_id(str(self.project_path), method_fqn, "method", i + 1),
                    project_path=str(self.project_path),
                    chunk_type="method",
                    fqn=method_fqn,
                    simple_name=method_name,
                    file_path=self.rel_path,
                    line_start=i + 1,
                    line_end=i + 25,
                    annotations=m_anns,
                    text=text,
                    raw_code=raw,
                    metadata={"class_fqn": current_class, "params": params},
                ))

        return chunks

    # ------------------------------------------------------------------
    # Text builders (for embedding)
    # ------------------------------------------------------------------

    def _class_text(self, name, fqn, anns, extends, impls, package, snippet) -> str:
        parts = [
            f"CLASS: {name}",
            f"PACKAGE: {package}",
            f"FQN: {fqn}",
        ]
        if anns:
            parts.append(f"ANNOTATIONS: {', '.join(anns)}")
        if extends:
            parts.append(f"EXTENDS: {extends}")
        if impls:
            parts.append(f"IMPLEMENTS: {impls}")

        # Spring-context description
        desc_parts = []
        if "@RestController" in anns or "@Controller" in anns:
            desc_parts.append("HTTP controller (exposes REST endpoints)")
        if "@Service" in anns:
            desc_parts.append("business logic service")
        if "@Repository" in anns:
            desc_parts.append("data access repository")
        if "@Entity" in anns:
            desc_parts.append("JPA entity (database table)")
        if "@Configuration" in anns:
            desc_parts.append("Spring configuration class")
        if "@FeignClient" in anns:
            desc_parts.append("Feign HTTP client (external service)")
        if desc_parts:
            parts.append(f"ROLE: {', '.join(desc_parts)}")

        parts.append(f"SOURCE:\n{snippet[:800]}")
        return "\n".join(parts)

    def _method_text(self, name, fqn, anns, class_name, params, snippet) -> str:
        parts = [
            f"METHOD: {name}",
            f"FQN: {fqn}",
            f"CLASS: {class_name}",
            f"SIGNATURE: {name}({params})",
        ]
        if anns:
            parts.append(f"ANNOTATIONS: {', '.join(anns)}")

        hints = []
        if "@Transactional" in anns:
            hints.append("runs within a database transaction")
        if "@Async" in anns:
            hints.append("executes asynchronously in thread pool")
        if "@Scheduled" in anns:
            hints.append("scheduled/cron method")
        if any(a in anns for a in ("@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping", "@PatchMapping")):
            hints.append("HTTP handler method")
        if "@EventListener" in anns or "@TransactionalEventListener" in anns:
            hints.append("Spring event listener")
        if "@Cacheable" in anns:
            hints.append("result is cached")
        if hints:
            parts.append(f"BEHAVIOUR: {', '.join(hints)}")

        parts.append(f"SOURCE:\n{snippet[:1000]}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_lines(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start:end])

    def _extract_path_from_source(self, line: int) -> Optional[str]:
        """Scan a few lines around the method to find a mapping path."""
        for i in range(max(0, line - 5), min(len(self.lines), line + 2)):
            l = self.lines[i]
            if any(m in l for m in HTTP_MAPPINGS):
                m = _PATH_RE.search(l)
                if m:
                    return m.group(1) or m.group(2)
        return None

    def _extract_class_path_from_source(self, class_anns: List[str]) -> Optional[str]:
        return None  # would need full annotation scanning; best-effort


# ---------------------------------------------------------------------------
# Config file parsers
# ---------------------------------------------------------------------------

def parse_properties_file(file_path: Path, project_path: Path) -> List[CodeChunk]:
    chunks: List[CodeChunk] = []
    rel = str(file_path.relative_to(project_path))
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries: List[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            entries.append(stripped)
    if not entries:
        return chunks

    # Group into a single CONFIG chunk per file
    text = (
        f"CONFIG FILE: {rel}\n"
        f"TYPE: application.properties\n"
        f"ENTRIES:\n" + "\n".join(entries[:200])
    )
    chunk_id = _stable_id(str(project_path), rel, "config")
    chunks.append(CodeChunk(
        chunk_id=chunk_id,
        project_path=str(project_path),
        chunk_type="config",
        fqn=rel,
        simple_name=file_path.name,
        file_path=rel,
        line_start=1,
        line_end=len(lines),
        text=text,
        metadata={"format": "properties"},
    ))
    return chunks


def parse_yaml_file(file_path: Path, project_path: Path) -> List[CodeChunk]:
    rel = str(file_path.relative_to(project_path))
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    text = (
        f"CONFIG FILE: {rel}\n"
        f"TYPE: application.yml\n"
        f"CONTENT:\n{content[:2000]}"
    )
    return [CodeChunk(
        chunk_id=_stable_id(str(project_path), rel, "config"),
        project_path=str(project_path),
        chunk_type="config",
        fqn=rel,
        simple_name=file_path.name,
        file_path=rel,
        line_start=1,
        line_end=content.count("\n"),
        text=text,
        metadata={"format": "yaml"},
    )]


# ---------------------------------------------------------------------------
# Project scanner
# ---------------------------------------------------------------------------

def scan_project(project_path: str) -> Iterator[CodeChunk]:
    """Yield all CodeChunks from a Spring Boot project directory."""
    root = Path(project_path)

    for java_file in root.rglob("*.java"):
        # Skip generated/build dirs
        parts = java_file.parts
        if any(p in parts for p in ("build", "target", ".gradle", "generated", "test-results")):
            continue
        try:
            parser = JavaFileParser(java_file, root)
            yield from parser.parse()
        except Exception as e:
            # Never fail the whole scan due to one bad file
            pass

    # Config files
    for props_file in root.rglob("application*.properties"):
        if any(p in props_file.parts for p in ("build", "target")):
            continue
        try:
            yield from parse_properties_file(props_file, root)
        except Exception:
            pass

    for yml_file in root.rglob("application*.yml"):
        if any(p in yml_file.parts for p in ("build", "target")):
            continue
        try:
            yield from parse_yaml_file(yml_file, root)
        except Exception:
            pass

"""SQLAlchemy ORM models for SpringInsight."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Run — top-level record for each springinsight run
# ---------------------------------------------------------------------------
class Run(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True, default=_uuid)
    project_name = Column(String, nullable=False)
    project_path = Column(String, nullable=False)
    started_at = Column(DateTime, default=_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")          # running | complete | failed | partial
    agents_requested = Column(JSON, default=list)       # ["A03", "A10", "A12"]
    agents_completed = Column(JSON, default=list)
    git_commit = Column(String, nullable=True)
    git_branch = Column(String, nullable=True)
    source_type = Column(String, default="local")       # local | github
    source_url = Column(String, nullable=True)          # GitHub URL if applicable
    context_snapshot = Column(JSON, nullable=True)      # snapshot of context.yaml

    # Token / cost tracking
    haiku_input_tokens = Column(Integer, default=0)
    haiku_output_tokens = Column(Integer, default=0)
    sonnet_input_tokens = Column(Integer, default=0)
    sonnet_output_tokens = Column(Integer, default=0)
    opus_input_tokens = Column(Integer, default=0)
    opus_output_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)

    # Aggregate scores (populated after all agents complete)
    score_overall = Column(Integer, nullable=True)
    score_security = Column(Integer, nullable=True)
    score_code_quality = Column(Integer, nullable=True)
    score_architecture = Column(Integer, nullable=True)
    score_api_design = Column(Integer, nullable=True)
    score_test_coverage = Column(Integer, nullable=True)
    score_production_readiness = Column(Integer, nullable=True)

    # Relationships
    findings = relationship("Finding", back_populates="run", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="run", cascade="all, delete-orphan")
    insights = relationship("Insight", back_populates="run", cascade="all, delete-orphan")
    score_history = relationship("ScoreHistory", back_populates="run", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="run", cascade="all, delete-orphan")

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def finding_counts(self) -> dict:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in self.findings:
            counts[f.severity.lower()] = counts.get(f.severity.lower(), 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Finding — individual issue found by an agent
# ---------------------------------------------------------------------------
class Finding(Base):
    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    agent_id = Column(String, nullable=False)           # A01, A03, A10, etc.

    severity = Column(String, nullable=False)           # CRITICAL | HIGH | MEDIUM | LOW | INFO
    category = Column(String, nullable=False)           # Security | Code Quality | CVE | License | Config
    subcategory = Column(String, nullable=True)

    # Location
    file_path = Column(String, nullable=True)           # relative to project root
    line_number = Column(Integer, nullable=True)
    class_name = Column(String, nullable=True)
    method_name = Column(String, nullable=True)

    # Content
    problem = Column(Text, nullable=False)
    code_snippet = Column(Text, nullable=True)
    impact = Column(Text, nullable=True)
    fix_description = Column(Text, nullable=True)
    fix_code = Column(Text, nullable=True)

    # Dependency-specific (A03)
    dependency_group_id = Column(String, nullable=True)
    dependency_artifact_id = Column(String, nullable=True)
    dependency_version = Column(String, nullable=True)
    cve_ids = Column(JSON, default=list)               # ["CVE-2024-XXXX"]
    cvss_score = Column(Float, nullable=True)
    license_type = Column(String, nullable=True)

    # Actionability
    actionable = Column(Boolean, default=True)
    effort_hours = Column(Float, nullable=True)         # estimated fix time

    # Lifecycle
    status = Column(String, default="open")             # open | acknowledged | fixed | wont-fix
    wont_fix_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    # Relationships
    run = relationship("Run", back_populates="findings")
    insight = relationship("Insight", back_populates="finding", uselist=False)


# ---------------------------------------------------------------------------
# AgentRun — execution record for a single agent within a run
# ---------------------------------------------------------------------------
class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    agent_id = Column(String, nullable=False)           # A03, A10, A12
    agent_name = Column(String, nullable=False)
    model = Column(String, nullable=False)              # haiku | sonnet | opus

    status = Column(String, default="pending")          # pending | running | complete | failed
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    files_processed = Column(Integer, default=0)
    findings_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    high_count = Column(Integer, default=0)

    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)

    error_message = Column(Text, nullable=True)
    output_md_path = Column(String, nullable=True)      # path to markdown report
    output_json_path = Column(String, nullable=True)    # path to JSON findings

    run = relationship("Run", back_populates="agent_runs")

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


# ---------------------------------------------------------------------------
# Insight — curated, prioritized actionable items (distilled from findings)
# ---------------------------------------------------------------------------
class Insight(Base):
    __tablename__ = "insights"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    finding_id = Column(String, ForeignKey("findings.id"), nullable=True)

    priority = Column(Integer, nullable=False)          # 1 (highest) to 100
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    effort_estimate = Column(String, nullable=True)     # "30 min" | "2 hours" | "1 day"
    category = Column(String, nullable=True)
    tags = Column(JSON, default=list)                   # ["security", "quick-win", "breaking"]

    status = Column(String, default="open")             # open | in-progress | done | dismissed
    assigned_to = Column(String, nullable=True)
    due_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)

    run = relationship("Run", back_populates="insights")
    finding = relationship("Finding", back_populates="insight")


# ---------------------------------------------------------------------------
# ScoreHistory — trend tracking across runs
# ---------------------------------------------------------------------------
class ScoreHistory(Base):
    __tablename__ = "score_history"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    git_commit = Column(String, nullable=True)
    measured_at = Column(DateTime, default=_now)

    overall = Column(Integer, nullable=True)
    security = Column(Integer, nullable=True)
    code_quality = Column(Integer, nullable=True)
    architecture = Column(Integer, nullable=True)
    api_design = Column(Integer, nullable=True)
    test_coverage = Column(Integer, nullable=True)
    production_readiness = Column(Integer, nullable=True)

    run = relationship("Run", back_populates="score_history")


# ---------------------------------------------------------------------------
# Artifact — generated files (tests, docs, LLDs)
# ---------------------------------------------------------------------------
class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    agent_id = Column(String, nullable=False)
    artifact_type = Column(String, nullable=False)      # test-class | doc | lld | api-doc
    target_file = Column(String, nullable=True)         # source file this artifact covers
    artifact_path = Column(String, nullable=True)
    content_preview = Column(Text, nullable=True)       # first 500 chars
    created_at = Column(DateTime, default=_now)

    run = relationship("Run", back_populates="artifacts")


# ---------------------------------------------------------------------------
# FileCache — incremental scan support (skip unchanged files)
# ---------------------------------------------------------------------------
class FileCache(Base):
    __tablename__ = "file_cache"

    id = Column(String, primary_key=True, default=_uuid)
    project_path = Column(String, nullable=False)
    file_path = Column(String, nullable=False)          # relative path
    file_hash = Column(String, nullable=False)          # SHA-256
    last_analyzed_at = Column(DateTime, default=_now)
    last_run_id = Column(String, ForeignKey("runs.id"), nullable=True)

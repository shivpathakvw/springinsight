# Changelog

All notable changes to SpringInsight are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · [Semantic Versioning](https://semver.org/)

---

## [0.2.0] — 2026-04-11

### Added
**Phase 2 agents — Sonnet deep analysis (all enabled)**
- **A01 Deep Code Review** — SOLID violations, God classes, exception handling, null safety,
  logging anti-patterns, Spring proxy pitfalls
- **A02 Security Scanner** — full OWASP Top 10 for Spring Boot: IDOR, mass assignment,
  SQL/JPQL/SpEL injection, weak crypto, JWT validation gaps, SSRF, deserialization
- **A04 Database & JPA Review** — N+1 detection, FetchType.EAGER on collections, Cartesian
  products, missing @Version, CascadeType.ALL risks, findAll() without pagination
- **A09 PR Review** — git diff blast radius, breaking API change detection, schema migration
  risk, rollback feasibility scoring
- **A11 Performance Analyzer** — caching gaps, thread pool misconfiguration, unbounded
  queries, @Async with SimpleAsyncTaskExecutor, memory hot-spots
- **A13 API Design Auditor** — REST compliance, HTTP status codes, missing validation,
  entities exposed as API responses, pagination gaps, OpenAPI coverage
- **A14 Concurrency & Transaction Audit** — race conditions, self-invocation bypass,
  @Transactional on private methods, ThreadLocal leaks, @Async exception handling
- **A15 Dependency Graph** — import + Spring bean wiring graph, circular dependency
  detection, hot-spot/God-class classification, Mermaid diagram output

**Infrastructure**
- PyPI publish workflow with OIDC trusted publishing (no API tokens)
- Dependency graph Mermaid diagrams in Markdown reports
- `~/.springinsight/skills/` user override directory for custom SKILL.md files
- `PUBLISHING.md` — step-by-step PyPI release guide
- Product website at `docs/` (GitHub Pages)

### Changed
- Version bumped to `0.2.0`
- `resolve_skill_path` now supports three lookup locations:
  user override → installed package → dev repo
- README roadmap updated to mark Phase 2 as complete

---

## [0.1.0] — 2026-04-01

### Added
**Phase 1 agents — Haiku fast scan**
- **A03 CVE & License Scanner** — pom.xml / build.gradle CVE detection, GPL license flags
- **A10 Dead Code Detector** — Spring-aware unused class/method/field detection
- **A12 Config & Infra Review** — hardcoded secrets, actuator exposure, DDL-auto=create,
  Docker root user, CI/CD secret leaks

**Core**
- `context.yaml` project descriptor (makes system generic across any Spring Boot project)
- Multi-model strategy: Haiku (Phase 1) → Sonnet (Phase 2) → Opus (Phase 3)
- SQLite via SQLAlchemy: runs, findings, scores, agent results, persistent history
- `asyncio` runner with `claude --print` and bounded parallelism
- GitHub URL support with shallow clone + auto-pull on re-scan
- Web UI with SSE live progress, score dashboard, filterable findings table
- CLI commands: `init`, `run`, `report`, `findings`, `history`, `agents`, `web`
- `.env` / `ANTHROPIC_API_KEY` auto-loading with multi-location search
- MIT License

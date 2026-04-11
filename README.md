# 🍃 SpringInsight

> **Autonomous multi-agent codebase intelligence for Java & Spring Boot.**  
> 15 AI agents. 60 seconds. Find what code reviews miss.

SpringInsight runs a fleet of AI agents over your Spring Boot project — simultaneously scanning for CVEs, dead code, security misconfigurations, N+1 queries, race conditions, API design violations, and more — then delivers actionable, prioritised findings with exact fix recommendations.

[![PyPI version](https://img.shields.io/pypi/v/springinsight?style=flat-square&color=22c55e)](https://pypi.org/project/springinsight/)
[![PyPI downloads](https://img.shields.io/pypi/dm/springinsight?style=flat-square&color=22c55e)](https://pypi.org/project/springinsight/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/shivpathakvw/springinsight?style=flat-square&color=f97316)](https://github.com/shivpathakvw/springinsight/stargazers)
[![CI](https://img.shields.io/github/actions/workflow/status/shivpathakvw/springinsight/ci.yml?style=flat-square&label=CI)](https://github.com/shivpathakvw/springinsight/actions)

**[🌐 Website](https://springinsight.vercel.app)** · **[📦 PyPI](https://pypi.org/project/springinsight/)** · **[⭐ Star on GitHub](https://github.com/shivpathakvw/springinsight)**

---

## Why SpringInsight?

Modern Spring Boot projects accumulate technical debt faster than manual reviews can keep up. SpringInsight brings **automated expert-level analysis** that runs in minutes:

- 🔐 **Security** — CVEs in dependencies, auth bypass risks, hardcoded secrets, actuator exposure
- 🏗️ **Architecture** — SOLID violations, circular dependencies, layering antipatterns
- 🗑️ **Dead Code** — Spring-aware unused class/method detection (never false-positives on `@Bean` or `@EventListener`)
- ⚙️ **Config Review** — DDL-auto dangers, debug mode in production, Docker/CI/CD misconfigs
- 📐 **Low-Level Design** — Auto-generate class diagrams and sequence diagrams (Mermaid/PlantUML)
- 🧪 **Test Generation** — AI-generated JUnit 5 + Mockito tests for uncovered critical paths
- 📄 **Documentation** — Feature specs, API docs, developer guides auto-generated from source

---

## Architecture

```
springinsight/
├── orchestrator (CLI / Web)
│   ├── context.yaml          ← project descriptor (makes system generic)
│   └── .springinsight/       ← DB, run history, cached findings
│
├── Phase 1 agents  (claude-haiku)     — fast pattern matching
│   ├── A03  CVE & License Scanner
│   ├── A10  Dead Code Detector
│   └── A12  Config & Infra Review
│
├── Phase 2 agents  (claude-sonnet)    — deep analysis
│   ├── A01  Deep Code Review
│   ├── A02  Security Scanner (OWASP Top 10)
│   ├── A04  Database & JPA Review
│   ├── A09  PR Review
│   ├── A11  Performance Analyzer
│   ├── A13  API Design Auditor
│   ├── A14  Concurrency & Transaction Audit
│   └── A15  Dependency Graph (import + bean wiring + Mermaid)
│
└── Phase 3/4 agents  (claude-opus)    — synthesis & generation
    ├── A05  Architecture Review
    ├── A06  Test Generator
    ├── A07  Feature Documentation
    └── A08  LLD Generator
```

Each agent is a **SKILL.md** — a structured natural-language contract that drives a `claude --print` subprocess. The orchestrator injects your `context.yaml` into every prompt, making the system work on **any** Spring Boot project without hardcoding.

---

## Quick Start

### Prerequisites

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)
- An [Anthropic API key](https://console.anthropic.com/)

### Install

```bash
# CLI only
pip install springinsight

# CLI + Web UI
pip install 'springinsight[web]'

# From source
git clone https://github.com/shivpathakvw/springinsight
cd springinsight
pip install -e '.[web]'
```

### Configure API Key

```bash
# Copy the example and add your key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

### Run via CLI

```bash
# 1. Initialise (scans project structure, creates context.yaml)
springinsight init --project /path/to/your/spring-boot-project

# 2. Run all Phase 1 agents
springinsight run

# 3. View the report
springinsight report

# Run a specific agent
springinsight run --agents A03

# Scan a GitHub repo directly
springinsight init --project https://github.com/owner/repo
springinsight run
```

### Run via Web UI

```bash
# Start the server (opens at http://localhost:8080)
springinsight web --open

# Custom port and data directory
springinsight web --port 9000 --data-dir /var/data/springinsight
```

Then open `http://localhost:8080`, paste a GitHub URL or local path, and click **Start Scan**. Progress updates live via Server-Sent Events.

---

## Configuration: `context.yaml`

`springinsight init` generates a `context.yaml` in your working directory. Edit it to help agents understand your project:

```yaml
project:
  name: "my-api-service"
  description: "Multi-tenant SaaS REST API built with Spring Boot 3"

tech_stack:
  java_version: 17
  spring_boot_version: "3.2.5"
  build_tool: maven
  database: postgresql
  orm: hibernate
  messaging: kafka
  cache: redis
  auth: keycloak
  api_type: rest

patterns:
  multi_tenancy: true
  tenant_filter_class: "com.example.TenantContextFilter"
  base_entity: "com.example.domain.BaseEntity"
  custom_rules:
    - "All @Transactional annotations must be on the service layer only"
    - "Never use LazyCollectionOption.EXTRA"
```

The context is injected into every agent's prompt — this is what makes SpringInsight work correctly on **your** project without any additional configuration.

---

## Agents Reference

| ID  | Agent | Model | Phase | Status | What it finds |
|-----|-------|-------|-------|--------|---------------|
| A03 | CVE & License Scanner | Haiku | 1 | ✅ Live | Log4Shell, Spring4Shell, Text4Shell, LGPL/GPL violations |
| A10 | Dead Code Detector | Haiku | 1 | ✅ Live | Unused classes, methods, fields (Spring-aware) |
| A12 | Config & Infra Review | Haiku | 1 | ✅ Live | Hardcoded secrets, actuator exposure, DDL-auto=create |
| A01 | Deep Code Review | Sonnet | 2 | ✅ Live | Code smells, SOLID violations, null safety, Spring anti-patterns |
| A02 | Security Scanner | Sonnet | 2 | ✅ Live | SQL/JPQL/SpEL injection, IDOR, JWT gaps, deserialization |
| A04 | Database & JPA Review | Sonnet | 2 | ✅ Live | N+1 queries, FetchType.EAGER, missing @Version, Flyway risks |
| A09 | PR Review | Sonnet | 2 | ✅ Live | Blast radius, breaking API changes, rollback feasibility |
| A11 | Performance Analyzer | Sonnet | 2 | ✅ Live | Caching gaps, thread pool sizing, findAll() without pagination |
| A13 | API Design Auditor | Sonnet | 2 | ✅ Live | REST compliance, @Valid missing, pagination, OpenAPI gaps |
| A14 | Concurrency Audit | Sonnet | 2 | ✅ Live | Race conditions, @Transactional correctness, ThreadLocal leaks |
| A15 | Dependency Graph | Sonnet | 2 | ✅ Live | Circular deps, hot-spots, God classes, Mermaid diagrams |
| A05 | Architecture Review | Opus | 3 | ✅ Live | SOLID at architecture level, layer violations, coupling matrix, ADRs |
| A08 | LLD Generator | Opus | 3 | ✅ Live | Class diagrams, ER diagrams, sequence diagrams, API table (Mermaid) |
| A06 | Test Generator | Sonnet | 4 | ✅ Live | JUnit 5 + Mockito tests, @WebMvcTest, @DataJpaTest, security tests |
| A07 | Feature Docs | Sonnet | 4 | ✅ Live | Feature specs, REST API reference, developer onboarding guide |

> **All 15 agents across Phases 1–4 are live.** Run `springinsight agents` to see the full list.

---

## CLI Reference

```
springinsight init     Initialise project context (auto-detects build tool, modules, Spring Boot version)
springinsight run      Run agents (--agents A03,A10 | --phase 1 | default: all enabled)
springinsight report   Display latest run report with score breakdown
springinsight findings List findings with severity filters
springinsight history  Show run history table
springinsight agents   List all 14 agents with phase and status
springinsight web      Start the Web UI server
```

Full options: `springinsight <command> --help`

---

## Web UI

The Web UI (`springinsight web`) provides:

- **Repository input** — GitHub URL or local path
- **Live progress** — real-time agent status via Server-Sent Events
- **Score dashboard** — overall + per-dimension scores with visual bars
- **Findings table** — filter by severity or agent, with inline fix suggestions
- **Run history** — persistent across sessions via SQLite

---

## Findings Format

Each agent writes structured JSON findings:

```json
{
  "severity": "CRITICAL",
  "category": "CVE",
  "subcategory": "Vulnerable Dependency",
  "file": "pom.xml",
  "group_id": "org.springframework",
  "artifact_id": "spring-core",
  "version": "5.3.10",
  "cve_ids": ["CVE-2022-22965"],
  "cvss_score": 9.8,
  "problem": "spring-core 5.3.10 is vulnerable to Spring4Shell (RCE via data binding)",
  "impact": "Remote code execution without authentication on any endpoint",
  "fix": "Upgrade spring-core to >= 5.3.18",
  "fix_code": "<version>5.3.27</version>",
  "actionable": true,
  "effort_hours": 1
}
```

Findings are stored in SQLite at `.springinsight/springinsight.db` for historical comparison and trend analysis.

---

## Token Optimisation

SpringInsight uses a multi-model strategy to minimise cost without sacrificing quality:

| Phase | Model | Use case | Typical cost / scan |
|-------|-------|----------|-------------------|
| 1 | `claude-haiku-4-5` | Pattern matching, dependency enumeration | ~$0.02 |
| 2 | `claude-sonnet-4-6` | Deep code analysis, security reasoning | ~$0.30 |
| 3 | `claude-opus-4-6` | Architectural synthesis, ADR generation | ~$1.20 |
| 4 | `claude-sonnet-4-6` | Code/doc generation | ~$0.50 |

A full Phase 1 scan of a mid-size project typically costs **less than $0.05**.

---

## Roadmap

- [x] Phase 1: CVE scanner, dead code detector, config review (A03, A10, A12)
- [x] Phase 2: Deep code review, OWASP security, DB/JPA, PR review, performance, API audit, concurrency, dependency graph (A01–A04, A09, A11, A13–A15)
- [x] Phase 3: Architecture review with ADR generation, full LLD generation with Mermaid (A05, A08)
- [x] Phase 4: JUnit 5 test generation, feature docs + developer guide generation (A06, A07)
- [x] Product website — [springinsight.vercel.app](https://springinsight.vercel.app)
- [x] PyPI publishing with OIDC trusted publishing (push a tag → auto-publishes)
- [ ] GitHub Actions integration (`springinsight-action` marketplace)
- [ ] VS Code extension (findings as CodeLens annotations)
- [ ] MCP server (Claude Code / Cursor / Cline integration)
- [ ] SaaS hosted version

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Adding a new agent

1. Create `skills/<agent-id>-<name>/SKILL.md` following the SKILL.md contract
2. Register the agent in `springinsight/agents/registry.py`
3. Add tests in `tests/agents/`
4. Open a PR with example findings

---

## License

MIT © [Shiv Chandra Pathak](https://github.com/shivpathakvw)

---

<p align="center">
  Built with ❤️ for the Spring Boot community
</p>

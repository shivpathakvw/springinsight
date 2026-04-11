# ⚡ SpringInsight

> **Autonomous multi-agent codebase intelligence for Java & Spring Boot.**

SpringInsight runs a fleet of AI agents over your Spring Boot project — simultaneously scanning for CVEs, dead code, security misconfigurations, architecture smells, and more — then delivers actionable, prioritised findings with exact fix recommendations.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Open Source](https://img.shields.io/badge/open%20source-❤-f97316?style=flat-square)](https://github.com/shivpathakvw/springinsight)

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
│   └── A14  Concurrency & Transaction Audit
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

| ID  | Agent | Model | Phase | What it finds |
|-----|-------|-------|-------|---------------|
| A03 | CVE & License Scanner | Haiku | 1 | Log4Shell, Spring4Shell, Text4Shell, LGPL/GPL violations |
| A10 | Dead Code Detector | Haiku | 1 | Unused classes, methods, fields (Spring-aware) |
| A12 | Config & Infra Review | Haiku | 1 | Hardcoded secrets, actuator exposure, DDL-auto=create |
| A01 | Deep Code Review | Sonnet | 2 | Code smells, SOLID violations, null safety |
| A02 | Security Scanner | Sonnet | 2 | SQL injection, IDOR, missing auth, crypto issues |
| A04 | Database & JPA Review | Sonnet | 2 | N+1 queries, missing indexes, fetch strategy issues |
| A09 | PR Review | Sonnet | 2 | Breaking changes, blast radius, regression risk |
| A11 | Performance Analyzer | Sonnet | 2 | Unbounded queries, cache misuse, thread pool sizing |
| A13 | API Design Auditor | Sonnet | 2 | REST compliance, OpenAPI gaps, pagination missing |
| A14 | Concurrency Audit | Sonnet | 2 | @Async safety, @Transactional correctness, locking |
| A05 | Architecture Review | Opus | 3 | Coupling, layering, microservices fitness |
| A08 | LLD Generator | Opus | 3 | Class/sequence/component diagrams in Mermaid |
| A06 | Test Generator | Sonnet | 4 | JUnit 5 + Mockito tests for uncovered paths |
| A07 | Feature Docs | Sonnet | 4 | Feature specs, API docs, sequence diagrams |

> **Phase 1 agents (A03, A10, A12) and Phase 2 agents (A01, A02, A04, A09, A11, A13, A14) are live.** Phase 3–4 (architecture diagrams, test generation) coming soon.

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
- [x] Phase 2: Deep code review, OWASP security scan, DB/JPA review, PR review, performance, API audit, concurrency (A01, A02, A04, A09, A11, A13, A14)
- [ ] Phase 3: Architecture review, LLD generator (A05, A08)
- [ ] Phase 4: Test generator, feature documentation (A06, A07)
- [ ] GitHub Actions integration (`springinsight-action`)
- [ ] VS Code extension
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

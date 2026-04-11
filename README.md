# 🍃 SpringInsight

> **Autonomous multi-agent codebase intelligence for Java & Spring Boot.**  
> 15 AI agents. 4 interfaces. Find what code reviews miss.

SpringInsight runs a fleet of AI agents over your Spring Boot project — simultaneously scanning for CVEs, dead code, security misconfigurations, N+1 queries, race conditions, API design violations, and more — then delivers actionable, prioritised findings with exact fix recommendations.

[![PyPI version](https://img.shields.io/pypi/v/springinsight?style=flat-square&color=22c55e)](https://pypi.org/project/springinsight/)
[![PyPI downloads](https://img.shields.io/pypi/dm/springinsight?style=flat-square&color=22c55e)](https://pypi.org/project/springinsight/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/shivpathakvw/springinsight?style=flat-square&color=f97316)](https://github.com/shivpathakvw/springinsight/stargazers)

**[🌐 Website](https://springinsight.vercel.app)** · **[📦 PyPI](https://pypi.org/project/springinsight/)** · **[⭐ Star on GitHub](https://github.com/shivpathakvw/springinsight)**

---

## Why SpringInsight?

Modern Spring Boot projects accumulate technical debt faster than manual reviews can keep up. SpringInsight brings **automated expert-level analysis** that runs in minutes:

- 🔐 **Security** — CVEs in dependencies, auth bypass risks, hardcoded secrets, actuator exposure
- 🏗️ **Architecture** — SOLID violations, circular dependencies, layering antipatterns
- 🗑️ **Dead Code** — Spring-aware unused class/method detection (never false-positives on `@Bean` or `@EventListener`)
- ⚙️ **Config Review** — DDL-auto dangers, debug mode in production, Docker/CI/CD misconfigs
- 📐 **Low-Level Design** — Auto-generate class diagrams and sequence diagrams (Mermaid)
- 🧪 **Test Generation** — AI-generated JUnit 5 + Mockito tests for uncovered critical paths
- 📄 **Documentation** — Feature specs, API docs, developer guides auto-generated from source

---

## Architecture

```
springinsight/
├── orchestrator (CLI / Web / MCP / VS Code)
│   ├── context.yaml          ← project descriptor (makes system generic)
│   └── ~/.springinsight/     ← global DB, run history, cached findings
│
├── Phase 1 agents  (claude-haiku)     — fast pattern matching (~$0.05)
│   ├── A03  CVE & License Scanner
│   ├── A10  Dead Code Detector
│   └── A12  Config & Infra Review
│
├── Phase 2 agents  (claude-sonnet)    — deep analysis (~$0.80)
│   ├── A01  Deep Code Review
│   ├── A02  Security Scanner (OWASP Top 10)
│   ├── A04  Database & JPA Review
│   ├── A09  PR Review
│   ├── A11  Performance Analyzer
│   ├── A13  API Design Auditor
│   ├── A14  Concurrency & Transaction Audit
│   └── A15  Dependency Graph (import + bean wiring + Mermaid)
│
└── Phase 3/4 agents  (claude-opus/sonnet) — synthesis & generation (~$2+)
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

# CLI + Web UI + MCP Server
pip install 'springinsight[web,mcp]'

# Everything
pip install 'springinsight[all]'

# From source (editable)
git clone https://github.com/shivpathakvw/springinsight
cd springinsight
pip install -e '.[web,mcp]'
```

### Configure API Key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or create a .env file in your working directory
```

---

## Usage

### CLI

```bash
# Scan a GitHub repo (clones automatically)
springinsight run https://github.com/spring-projects/spring-petclinic

# Scan a local project
springinsight run /path/to/your/spring-boot-project

# Quick scan — Phase 1 only (fast + cheap, ~$0.05)
springinsight run ./my-app --agents A03,A10,A12

# Run a specific phase
springinsight run ./my-app --phase 2

# View the report
springinsight report

# List findings with filters
springinsight findings --severity CRITICAL,HIGH

# Show run history
springinsight history

# List all agents and their enabled/disabled status
springinsight agents
```

### Web UI

```bash
# Start the server (opens at http://localhost:8080)
springinsight web --open

# Show agent progress and logs in the terminal too
springinsight web --verbose

# Custom port
springinsight web --port 9000
```

Then open `http://localhost:8080`, paste a GitHub URL or local path, and click **Start Scan**.

**Web UI features:**
- Live agent progress via Server-Sent Events
- Click any agent card to expand live logs
- **Settings → Agents** to enable/disable individual agents and control cost
- Shared SQLite database with CLI (runs appear in both)
- Score history across runs

### MCP Server (Claude Code / Cursor / Cline)

```bash
pip install 'springinsight[mcp]'
```

Add to your MCP config (`~/.config/claude/claude_desktop_config.json` or Cursor settings):

```json
{
  "mcpServers": {
    "springinsight": {
      "command": "springinsight",
      "args": ["mcp"]
    }
  }
}
```

Available MCP tools once connected:

| Tool | Description |
|------|-------------|
| `scan_project` | Scan a local path or GitHub URL |
| `get_scan_status` | Poll a running scan by run_id |
| `get_findings` | Get findings, optionally filtered by severity |
| `get_agent_report` | Get the full markdown report from any agent |
| `list_recent_scans` | List recent scans with scores |
| `enable_agents` | Enable/disable specific agents to control cost |

### VS Code Extension

The extension is in `vscode-extension/`. To build:

```bash
cd vscode-extension
npm install
npm run compile
# Then install the .vsix via: code --install-extension springinsight-*.vsix
```

Features: scan from command palette, findings in Problems panel, inline gutter icons, live agent progress in output channel.

---

## Cost Management

Running all 15 agents on a large project can cost $3–8. Use these strategies:

| Strategy | Command | Cost |
|----------|---------|------|
| Quick check (Phase 1 only) | `--agents A03,A10,A12` | ~$0.05 |
| Security focus | `--agents A02,A03,A12` | ~$0.30 |
| Full analysis | (default) | $1–8 |
| Disable Opus agents | Settings → Agents → disable A05, A08 | saves ~$2 |

In the Web UI: **Settings → Agents** lets you toggle individual agents and see estimated cost per agent before scanning.

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
  auth: keycloak

patterns:
  multi_tenancy: true
  custom_rules:
    - "All @Transactional annotations must be on the service layer only"
    - "Never use LazyCollectionOption.EXTRA"
```

---

## Agents Reference

| ID  | Agent | Model | Phase | What it finds |
|-----|-------|-------|-------|---------------|
| A03 | CVE & License Scanner | Haiku | 1 | Log4Shell, Spring4Shell, LGPL/GPL violations |
| A10 | Dead Code Detector | Haiku | 1 | Unused classes, methods, fields (Spring-aware) |
| A12 | Config & Infra Review | Haiku | 1 | Hardcoded secrets, actuator exposure, DDL-auto=create |
| A01 | Deep Code Review | Sonnet | 2 | Code smells, SOLID violations, Spring anti-patterns |
| A02 | Security Scanner | Sonnet | 2 | SQL/JPQL/SpEL injection, IDOR, JWT gaps, deserialization |
| A04 | Database & JPA Review | Sonnet | 2 | N+1 queries, FetchType.EAGER, missing @Version |
| A09 | PR Review | Sonnet | 2 | Blast radius, breaking API changes, rollback feasibility |
| A11 | Performance Analyzer | Sonnet | 2 | Caching gaps, thread pool sizing, findAll() without pagination |
| A13 | API Design Auditor | Sonnet | 2 | REST compliance, @Valid missing, pagination, OpenAPI gaps |
| A14 | Concurrency Audit | Sonnet | 2 | Race conditions, @Transactional correctness, ThreadLocal leaks |
| A15 | Dependency Graph | Sonnet | 2 | Circular deps, hot-spots, God classes, Mermaid diagrams |
| A05 | Architecture Review | Opus | 3 | SOLID violations at architecture level, coupling matrix, ADRs |
| A08 | LLD Generator | Opus | 3 | Class diagrams, ER diagrams, sequence diagrams (Mermaid) |
| A06 | Test Generator | Sonnet | 4 | JUnit 5 + Mockito, @WebMvcTest, @DataJpaTest, security tests |
| A07 | Feature Docs | Sonnet | 4 | Feature specs, REST API reference, developer onboarding guide |

Run `springinsight agents` to see status and enable/disable each agent.

---

## CLI Reference

```
springinsight run      Scan a project (positional arg or --project)
springinsight web      Start the Web UI (--verbose for terminal agent logs)
springinsight mcp      Start the MCP server (for Claude Code / Cursor / Cline)
springinsight report   Display latest run report with score breakdown
springinsight findings List findings with severity/agent filters
springinsight history  Show run history table with scores
springinsight agents   List all 15 agents with phase and status
springinsight init     Initialise project context (creates context.yaml)
```

Full options: `springinsight <command> --help`

---

## Scoring

Each run produces a 0–100 score per dimension, plus a weighted overall:

| Dimension | Weight | What counts |
|-----------|--------|-------------|
| Security | 30% | CVEs, injection, auth bypass |
| Code Quality | 20% | Smells, SOLID, null safety |
| Architecture | 15% | Coupling, layering, SOLID at system level |
| API Design | 15% | REST compliance, versioning, validation |
| Production Readiness | 12% | Config, actuator, secrets |
| Test Coverage | 8% | Missing tests for critical paths |

CRITICAL finding = −25 pts in its dimension, HIGH = −10, MEDIUM = −4, LOW = −1.

---

## Database

SpringInsight stores all run data in a single **global SQLite database** at `~/.springinsight/springinsight.db`. Both the CLI and Web UI share this database, so runs started from the terminal appear in the Web UI and vice versa.

---

## Roadmap

- [x] Phase 1: CVE scanner, dead code, config review (A03, A10, A12)
- [x] Phase 2: Full deep analysis — security, DB/JPA, PR review, performance, API, concurrency, dependency graph
- [x] Phase 3: Architecture review with ADR generation, full LLD with Mermaid diagrams
- [x] Phase 4: JUnit 5 test generation, feature docs + developer guide generation
- [x] Web UI with live SSE progress, agent enable/disable, verbose logs
- [x] MCP Server — Claude Code / Cursor / Cline integration
- [x] VS Code extension — scan + diagnostics + Problems panel
- [x] Shared global database between CLI and Web UI
- [x] PyPI publishing with OIDC trusted publishing
- [x] Product website — [springinsight.vercel.app](https://springinsight.vercel.app)
- [ ] GitHub Actions integration (`springinsight-action` marketplace)
- [ ] PR comments (auto-comment on PRs with findings summary)
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

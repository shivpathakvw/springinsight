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
- 📋 **Project Context** — inject custom rules into every agent ("no field injection", "all endpoints need @PreAuthorize")
- 🔍 **GitHub PR Scanning** — auto-scan PRs and post findings as comments
- 📄 **PDF Export** — full scan reports as professional PDFs

---

## Architecture

```
springinsight/
├── orchestrator (CLI / Web / MCP / VS Code)
│   ├── context.yaml               ← per-project descriptor
│   └── ~/.springinsight/
│       ├── springinsight.db       ← global SQLite (CLI + Web share)
│       ├── global-context.yaml    ← global custom rules
│       ├── agent_config.json      ← enabled/disabled agents
│       ├── github.json            ← GitHub token + watched repos
│       └── pr-scans.json          ← PR scan history
│
├── Phase 1  (claude-haiku)    — fast pattern matching (~$0.05)
│   ├── A03  CVE & License Scanner
│   ├── A10  Dead Code Detector
│   └── A12  Config & Infra Review
│
├── Phase 2  (claude-sonnet)   — deep analysis (~$0.80)
│   ├── A01  Deep Code Review
│   ├── A02  Security Scanner (OWASP Top 10)
│   ├── A04  Database & JPA Review
│   ├── A09  PR Review
│   ├── A11  Performance Analyzer
│   ├── A13  API Design Auditor
│   ├── A14  Concurrency & Transaction Audit
│   └── A15  Dependency Graph
│
└── Phase 3/4 (claude-opus/sonnet) — synthesis & generation (~$2+)
    ├── A05  Architecture Review
    ├── A06  Test Generator
    ├── A07  Feature Documentation
    └── A08  LLD Generator
```

---

## Installation

```bash
# CLI only
pip install springinsight

# CLI + Web UI
pip install 'springinsight[web]'

# CLI + Web UI + MCP Server + PDF + GitHub
pip install 'springinsight[all]'

# From source (editable)
git clone https://github.com/shivpathakvw/springinsight
cd springinsight
pip install -e '.[all]'
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

# View the report
springinsight report

# Export report as PDF (requires: pip install reportlab)
springinsight report --pdf ./my-report.pdf

# List findings with filters
springinsight findings --severity CRITICAL,HIGH

# Show run history
springinsight history

# List all agents and their enabled/disabled status
springinsight agents
```

### Project Context (Custom Rules)

Teach agents your team's standards — injected into every agent prompt as MUST-APPLY constraints:

```bash
# Add a custom rule
springinsight context add-rule "Never use field injection (@Autowired on fields)"
springinsight context add-rule "All public REST endpoints must have @PreAuthorize"
springinsight context add-rule "Use constructor injection only"

# List all rules
springinsight context list-rules

# Remove a rule by index
springinsight context remove-rule 0

# Set tech-stack hints
springinsight context set java-version 21
springinsight context set spring-boot 3.3.x
springinsight context set database postgresql

# Show full global context
springinsight context show

# Edit raw YAML
springinsight context edit

# Reset to defaults
springinsight context reset
```

Per-project rules: `springinsight init` creates a `context.yaml` in your project directory. Rules there take precedence over global context.

### Web UI

```bash
# Start the server (opens at http://localhost:8765)
springinsight web --open

# Show agent progress and logs in the terminal too
springinsight web --verbose

# Custom port
springinsight web --port 9000
```

Then open `http://localhost:8765`, paste a GitHub URL or local path, and click **Start Scan**.

**Web UI features:**
- Live agent progress via Server-Sent Events
- Click any agent card to expand live logs
- **Settings → Agents** — enable/disable individual agents, see cost estimates
- **Settings → Project Context** — edit custom rules and tech-stack hints from the browser
- **Settings → GitHub PR** — connect GitHub and watch repositories for PR scanning
- **Export PDF** button on every completed scan result page
- Shared SQLite database with CLI

### GitHub PR Integration

Auto-scan every pull request and post a formatted findings summary as a PR comment:

```bash
# Step 1: Connect your GitHub token (needs 'repo' scope)
springinsight github connect --token ghp_xxxx

# Step 2: Watch repositories
springinsight github watch myorg/my-spring-service
springinsight github watch myorg/payments-api

# Step 3: Poll manually or let springinsight web auto-poll
springinsight github poll

# Scan a specific PR immediately
springinsight github scan-pr https://github.com/myorg/service/pull/42

# List watched repos
springinsight github repos

# View PR scan history
springinsight github history

# Show connection status
springinsight github status

# Remove a repo from watchlist
springinsight github unwatch myorg/service

# Disconnect GitHub
springinsight github disconnect
```

When `springinsight web` is running with a GitHub token configured, the PR poller runs automatically every 5 minutes (configurable in **Settings → GitHub PR**).

**PR Comment format:**
```markdown
## ⚡ SpringInsight Analysis
_Automated scan of 23 changed Java files in `my-spring-service`_

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 1 |
| 🟠 HIGH | 3 |
| 🟡 MEDIUM | 7 |

**🔴 CRITICAL — SQL Injection Risk**
`UserRepository.java:142` — Concatenated query string with user input
> 💡 Use @Query with named parameters

[📊 View full report →](http://localhost:8765/scans/run-id)
```

### PDF Export

```bash
# CLI
springinsight report --pdf ./scan-report.pdf

# Web UI: click "Export PDF" button on any scan result page

# Via API (programmatic)
curl http://localhost:8765/api/runs/<run-id>/export/pdf -o report.pdf
```

Requires: `pip install reportlab` (or `pip install 'springinsight[pdf]'`).

### MCP Server (Claude Code / Cursor / Cline)

```bash
pip install 'springinsight[mcp]'
```

Add to your MCP config:

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

Available MCP tools:

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
# Install: code --install-extension springinsight-*.vsix
```

Features: scan from command palette, findings in Problems panel, inline gutter icons, live status bar progress.

---

## Cost Management

Running all 15 agents on a large project can cost $3–8. Use these strategies:

| Strategy | Command | Cost |
|----------|---------|------|
| Quick check (Phase 1 only) | `--agents A03,A10,A12` | ~$0.05 |
| Security focus | `--agents A02,A03,A12` | ~$0.30 |
| Full analysis | (default) | $1–8 |
| Disable Opus agents | Settings → Agents → disable A05, A08 | saves ~$2 |

In the Web UI: **Settings → Agents** shows estimated cost per agent before scanning.

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
    - "All REST endpoints must return ResponseEntity<T>"
```

Global rules (apply to all projects) are stored at `~/.springinsight/global-context.yaml` and managed via `springinsight context` commands.

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
springinsight run        Scan a project (positional arg or --project)
  --agents A03,A10,A12   Run only specific agents
  --phase 1              Run only a specific phase

springinsight web        Start the Web UI
  --verbose / -v         Stream agent logs to terminal
  --port 9000            Custom port (default 8765)
  --open                 Open browser automatically

springinsight report     Display latest run report
  --pdf ./report.pdf     Export as PDF (requires reportlab)
  --severity CRITICAL    Filter by severity
  --run-id <id>          Specific run
  --export ./report.md   Export markdown report

springinsight context    Manage global project context and custom rules
  show                   Show current global context
  add-rule "text"        Add a custom rule for all agents
  remove-rule <index>    Remove a rule by index
  list-rules             List all custom rules
  set <key> <value>      Set a tech-stack value (java-version, spring-boot, etc.)
  edit                   Open context file in $EDITOR
  reset                  Reset to factory defaults
  export --format json   Export context as JSON or YAML

springinsight github     GitHub PR integration
  connect --token ghp_x  Connect with a Personal Access Token
  watch owner/repo       Watch a repository for new PRs
  unwatch owner/repo     Stop watching a repository
  repos                  List watched repositories
  scan-pr <URL>          Manually scan a specific PR URL
  poll                   Manually trigger poll cycle
  history                Show PR scan history
  status                 Show connection status
  disconnect             Remove GitHub token

springinsight mcp        Start the MCP server (for Claude Code / Cursor / Cline)
springinsight findings   List findings with severity/agent filters
springinsight history    Show run history table with scores
springinsight agents     List all 15 agents with phase and status
springinsight init       Initialise project context (creates context.yaml)
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

Other config files at `~/.springinsight/`:

| File | Contents |
|------|----------|
| `springinsight.db` | All run history, findings, scores |
| `global-context.yaml` | Global custom rules and tech-stack defaults |
| `agent_config.json` | Which agents are enabled/disabled |
| `github.json` | GitHub token, watched repos, polling settings |
| `pr-scans.json` | History of PR scans (prevents duplicate scans) |

---

## Roadmap

- [x] Phase 1–4: All 15 agents
- [x] Web UI with live SSE progress, agent enable/disable, verbose logs
- [x] MCP Server — Claude Code / Cursor / Cline integration
- [x] VS Code extension — scan + diagnostics + Problems panel
- [x] Shared global database between CLI and Web UI
- [x] Project Context — custom rules injected into every agent
- [x] PDF export — professional scan reports
- [x] GitHub PR auto-scanning + auto-comment
- [x] PyPI publishing with OIDC trusted publishing
- [x] Product website — [springinsight.vercel.app](https://springinsight.vercel.app)
- [ ] GitHub Actions marketplace action (`springinsight-action`)
- [ ] Incremental scanning (skip unchanged files)
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

# 🍃 SpringInsight

> **Autonomous multi-agent codebase intelligence for Java & Spring Boot.**  
> 17 AI agents. 4 interfaces. Find what code reviews miss.

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
- 🚀 **NFR Optimizer** *(new)* — concurrency, caching, HikariCP tuning, virtual threads, GC, startup time
- ⬆️ **Upgrade Advisor** *(new)* — detects deprecated APIs for Spring Boot 3.5 / 4.0, step-by-step migration plan
- 📋 **Project Context** — inject custom rules into every agent ("no field injection", "all endpoints need @PreAuthorize")
- 🔍 **GitHub PR Scanning** — scans only changed files (focused, fast), auto-posts findings as PR comments
- 📦 **Large Project Support** — auto-detects >1k file projects, splits into intelligent batches (maven/gradle/package)
- 📄 **PDF Export** — full scan reports as professional PDFs from any page

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
│   ├── A15  Dependency Graph
│   ├── A16  Spring Boot Upgrade Advisor  ← NEW
│   └── A17  NFR Optimizer                ← NEW
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

## Cost Management & Token Optimization

SpringInsight includes a comprehensive cost control system so you never get a surprise bill.

### Pre-scan Cost Estimation

Preview the estimated cost before committing to a scan:

```bash
# Print cost table and exit — no scan is run
springinsight run /path/to/project --estimate

# Example output:
#   Agent                            Model       Est. Cost
#   ──────────────────────────────────────────────────────
#   A05 Architecture Review          Opus          $1.250
#   A08 LLD Generator                Opus          $1.100
#   A01 Deep Code Review             Sonnet        $0.380
#   A02 Security Scanner             Sonnet        $0.320
#   ...
#   ──────────────────────────────────────────────────────
#   TOTAL                                          $4.870
```

In the **Web UI**: enter a repo URL and tab out of the field — a cost estimate appears instantly above the Start Scan button.

### Budget Cap

Cap spend and let SpringInsight auto-select the most valuable agents that fit:

```bash
# Run only agents that fit within $1.00
springinsight run /path/to/project --budget 1.00

# Prioritise security agents first
springinsight run /path/to/project --budget 2.00 --budget-strategy security

# Phase 1 only (Haiku agents, cheapest)
springinsight run /path/to/project --budget 0.50 --budget-strategy phase1
```

**Budget strategies:**

| Strategy | Description | Best for |
|----------|-------------|----------|
| `value` (default) | Phase order — most signal per dollar | General use |
| `security` | A02/A03/A12 first | Security audits |
| `phase1` | Haiku-only Phase 1 agents | Quick CI checks |

### Agent-Specific File Scoping

Each agent only reads files it actually needs, reducing token usage by 30–70%:

| Agent | Optimization | Typical saving |
|-------|-------------|----------------|
| A03 CVE Scanner | Reads only `pom.xml` / `build.gradle` — skips all `.java` | ~60% |
| A12 Config Review | Reads only config/infra files — skips all `.java` | ~60% |
| A04 DB & JPA | Reads only `@Entity`, `@Repository` classes | ~70% |
| A13 API Auditor | Reads only `@RestController` classes | ~65% |
| A02 Security | Skips test classes | ~30% |
| A14 Concurrency | Reads only `@Service`, `@Async` classes | ~50% |

File scoping is **on by default**. Disable only if you need full-scope analysis:

```bash
springinsight run /path/to/project --no-scope
```

### Incremental Scanning

After the first scan, subsequent scans skip files whose SHA-256 hash hasn't changed. On CI/PR workflows where only a handful of files change per commit, this can reduce token usage by **80–90%**.

```bash
# Incremental is on by default — second scan is dramatically cheaper
springinsight run /path/to/project

# Force a full re-scan (ignore cache)
springinsight run /path/to/project --no-incremental

# Manually clear the cache for a project
springinsight run /path/to/project --clear-cache
```

### Cost Table by Project Size

| Project size | Phase 1 only | Full scan (all agents) |
|-------------|--------------|------------------------|
| Small (50 files) | ~$0.02 | ~$0.80 |
| Medium (200 files) | ~$0.08 | ~$3.00 |
| Large (500 files) | ~$0.18 | ~$6.50 |
| With incremental (2nd scan) | ~$0.005 | ~$0.30 |

In the Web UI: **Settings → Agents** shows estimated cost per agent. The scan form shows a live cost estimate and lets you set a budget cap before starting.

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

## Spring Boot Version Support

SpringInsight supports **Spring Boot 2.7 through 4.0** and auto-detects the version from your `pom.xml` or `build.gradle` — no manual configuration needed.

| Version | Status | Notes |
|---------|--------|-------|
| 2.7.x | EOL | Detects `javax.*` → `jakarta.*` migration needs |
| 3.0.x / 3.1.x | EOL | Flags `WebSecurityConfigurerAdapter` removal, property renames |
| 3.2.x | Maintenance | Virtual threads preview (`spring.threads.virtual.enabled`) |
| 3.3.x | Maintenance | CDS support, `@ConditionalOnThreading` |
| 3.4.x | Stable | RestClient GA, Micrometer 1.14 |
| **3.5.x** | ✅ **Latest 3.x** | Structured logging, `applicationTaskExecutor` rename, heapdump access=NONE |
| **4.0.x** | Next major | Jakarta EE 11, Spring Framework 7, `spring-boot-parent` removed |

Version-specific guidance is automatically injected into every agent's context so findings are always relevant to your actual version. The **A16 Spring Boot Upgrade Advisor** agent produces a full migration plan with effort estimates when you're ready to upgrade.

```bash
# Set version explicitly (or let SpringInsight auto-detect from pom.xml)
springinsight context set spring-boot 3.5.x
```

---

## Large Project Support (Batch Scanning)

For projects with **1,000+ Java files**, SpringInsight automatically detects the size and offers intelligent batch scanning to prevent timeouts and memory issues.

```
⚠ Large project detected — 2,847 Java files
  Recommended: Split into 12 batches using maven strategy
  
  Batch 1: payments-service       (143 files)
  Batch 2: user-service           (98 files)
  Batch 3: order-service          (201 files)
  ...
```

**Splitting strategies** (chosen automatically in priority order):

| Strategy | When used | How it splits |
|----------|-----------|---------------|
| `maven` | Multi-module Maven project | One batch per `<module>` |
| `gradle` | Multi-module Gradle project | One batch per subproject |
| `dir` | Single module, many packages | One batch per top-level source directory |
| `package` | Dense single package tree | Groups Java packages by file count |
| `slice` | Anything else | Fixed file-count windows (150 files each) |

Batches run **sequentially** (one at a time) to avoid memory overload. Each batch creates its own live scan page with SSE progress. Results are aggregated into a single overall score and findings list.

**Web UI**: the dashboard detects large projects on URL blur and shows the batch plan before you start. Click **Start Batch Scan (Recommended)** to begin.

**CLI**:
```bash
# Auto-batch if >1000 files; runs all batches sequentially
springinsight run /path/to/large-project --batch

# Override batch size
springinsight run /path/to/large-project --batch --batch-size 100
```

---

## GitHub PR Scanning — Focused Mode

PR scans now only analyse the **changed files** in the PR, not the entire codebase. This makes PR scans dramatically faster and prevents noise from unrelated code.

- **Changed files only** — agents receive a strict scope block listing only the files modified in the PR
- **Focused agent set** — only PR-relevant agents run (A01, A02, A03, A04, A09, A11, A12, A13, A14). Full-project agents (LLD, Architecture, Dead Code, Docs) are skipped.
- **Removed files** — files deleted in the PR are noted but not scanned
- **Live progress** — scanning redirects to the standard live scan page with SSE agent progress

```bash
# Scan a specific PR (only changed Java files)
springinsight github scan-pr https://github.com/myorg/service/pull/42

# From the Web UI: Dashboard → Scan PR tab → paste PR URL → Scan PR
```

---

## New Agents: A16 & A17

### A16 — Spring Boot Upgrade Advisor

Reads your `pom.xml`, scans all Java source files for deprecated/removed APIs, and produces a step-by-step migration guide.

**What it catches:**
- `WebSecurityConfigurerAdapter` usage (removed in 3.0)
- `javax.*` imports that need `jakarta.*` migration
- `spring.redis.*` → `spring.data.redis.*` property renames
- `RestTemplate` usage (recommend RestClient/WebClient for new code)
- `taskExecutor` bean name → `applicationTaskExecutor` (3.5 breaking change)
- `heapdump` actuator endpoint now requires explicit opt-in (3.5)
- `spring-boot-parent` POM removal (4.0)
- Spring Cloud / Spring Security compatibility matrix violations

**Output:** prioritised migration table (MUST-FIX / SHOULD-FIX / QUICK-WINS) with exact file locations, before/after code snippets, and effort estimates.

### A17 — NFR Optimizer

Covers seven non-functional requirement pillars with concrete, measurable fixes.

| Pillar | Key findings |
|--------|-------------|
| **Concurrency** | `@Async` self-invocation, unbounded thread pools, virtual thread pinning, `HashMap` in singleton beans |
| **Caching** | Missing `@Cacheable` on hot paths, Redis cache without TTL, `ConcurrentMapCacheManager` (no eviction) |
| **DB / Connections** | HikariCP not tuned, N+1 via `FetchType.EAGER`, no pagination on `findAll()`, long transactions with I/O |
| **Memory / GC** | `ThreadLocal` leaks, unbounded static collections, `open-in-view=true` (flagged HIGH always) |
| **Startup** | Over-broad `@ComponentScan`, heavy `CommandLineRunner`, missing `lazy-initialization` |
| **Observability** | Missing `@Timed`, no MDC correlation ID, `log.debug()` without guard |
| **Resilience** | No circuit breaker on external calls, unbounded async queues, missing retry backoff |

> 💡 `spring.jpa.open-in-view=true` (Spring Boot's default) is always flagged **HIGH** — it holds a Hibernate session open for the entire HTTP request lifetime and is the single most common cause of performance problems in Spring Boot apps.

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
| **A16** | **Spring Boot Upgrade Advisor** ⭐ | Sonnet | 2 | Deprecated APIs, migration plan 3.2→3.5→4.0, effort estimates |
| **A17** | **NFR Optimizer** ⭐ | Sonnet | 2 | Thread pools, caching TTL, HikariCP, virtual threads, GC tuning |
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
  --estimate             Print cost estimate table and exit (no scan)
  --budget 1.50          Cap spend — auto-selects cheapest agents that fit
  --budget-strategy      value | security | phase1  (default: value)
  --no-scope             Disable agent-specific file filtering
  --no-incremental       Disable incremental scanning (force full re-scan)
  --clear-cache          Clear file hash cache before scanning
  --max-files 100        Override per-agent file cap

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
springinsight agents     List all 17 agents with phase and status
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

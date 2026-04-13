# 🍃 SpringInsight

> **Autonomous multi-agent codebase intelligence for Java & Spring Boot.**  
> 18 AI agents. 3 pillars. 4 interfaces. Find what code reviews miss.

SpringInsight is a three-pillar intelligence suite for Spring Boot teams:

- **Pillar 1 — Code Review**: 18 AI agents scan your codebase in parallel for CVEs, dead code, security misconfigurations, N+1 queries, race conditions, API design violations, and more — delivering prioritised, actionable findings.
- **Pillar 2 — CodeSearch**: Semantic RAG search over your codebase. Ask natural-language questions, get cited answers grounded in your actual code.
- **Pillar 3 — SpringTeam**: Delegate features to an autonomous AI development team. Agents write code, generate tests, update docs, and submit tasks for your review.

[![PyPI version](https://img.shields.io/pypi/v/springinsight?style=flat-square&color=22c55e)](https://pypi.org/project/springinsight/)
[![PyPI downloads](https://img.shields.io/pypi/dm/springinsight?style=flat-square&color=22c55e)](https://pypi.org/project/springinsight/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/shivpathakvw/springinsight?style=flat-square&color=f97316)](https://github.com/shivpathakvw/springinsight/stargazers)

**[🌐 Website](https://springinsight.vercel.app)** · **[📦 PyPI](https://pypi.org/project/springinsight/)** · **[⭐ Star on GitHub](https://github.com/shivpathakvw/springinsight)**

---

## Three Pillars

| | Pillar 1 — Code Review | Pillar 2 — CodeSearch | Pillar 3 — SpringTeam |
|---|---|---|---|
| **What it does** | 18 agents scan your codebase in parallel | Natural-language RAG search over your code | Delegate features to an autonomous AI dev team |
| **Core command** | `springinsight run <project>` | `springinsight search ask "<question>"` | `springinsight team task "<description>"` |
| **Model** | Haiku + Sonnet + Opus | MiniLM-L6-v2 + Claude Sonnet | Claude Sonnet |
| **Storage** | SQLite findings DB | ChromaDB vector store + SQLite code graph | SQLite task queue |
| **Web UI** | `/` (scan dashboard) | `/search` | `/tasks` |

---

## Why SpringInsight?

Modern Spring Boot projects accumulate technical debt faster than manual reviews can keep up. SpringInsight brings **automated expert-level analysis** across three pillars:

**Pillar 1 — Code Review**
- 🔐 **Security** — CVEs in dependencies, auth bypass risks, hardcoded secrets, actuator exposure
- 🏗️ **Architecture** — SOLID violations, circular dependencies, layering antipatterns
- 🗑️ **Dead Code** — Spring-aware unused class/method detection (never false-positives on `@Bean` or `@EventListener`)
- ⚙️ **Config Review** — DDL-auto dangers, debug mode in production, Docker/CI/CD misconfigs
- 🚀 **NFR Optimizer** — concurrency, caching, HikariCP tuning, virtual threads, GC, startup time
- ⬆️ **Upgrade Advisor** — detects deprecated APIs for Spring Boot 3.5 / 4.0, step-by-step migration plan
- 🔄 **Reverse Engineering** *(new)* — reconstructs architecture and docs from any codebase, including closed-source

**Pillar 2 — CodeSearch**
- 🔍 **Semantic Search** — ask "which service handles retries?" and get a cited answer from your actual code
- 🕸️ **Code Graph** — AST-based graph of classes, methods, endpoints, fields with cross-reference edges
- 🔒 **100% Local** — all-MiniLM-L6-v2 model + ChromaDB run on your machine; code never leaves your environment
- ⚡ **Fast** — 12ms embed + 8ms vector search on a 300-chunk project

**Pillar 3 — SpringTeam**
- 🤖 **Delegated Development** — describe a feature in plain English; agents write code, tests, and docs
- 👁️ **Human-in-the-loop** — every task goes through a review step before you accept the changes
- 🔁 **Retry with feedback** — reject tasks with a note; the agent revises and re-submits

**Platform**
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
│       ├── chroma/                ← ChromaDB vector store (CodeSearch)
│       ├── repos/                 ← auto-cloned GitHub repos
│       ├── global-context.yaml    ← global custom rules
│       ├── agent_config.json      ← enabled/disabled agents
│       ├── github.json            ← GitHub token + watched repos
│       └── pr-scans.json          ← PR scan history
│
├── Pillar 1: Code Review (springinsight run)
│   ├── Phase 1  (claude-haiku)    — fast pattern matching (~$0.05)
│   │   ├── A03  CVE & License Scanner
│   │   ├── A10  Dead Code Detector
│   │   └── A12  Config & Infra Review
│   │
│   ├── Phase 2  (claude-sonnet)   — deep analysis (~$0.80)
│   │   ├── A01  Deep Code Review
│   │   ├── A02  Security Scanner (OWASP Top 10)
│   │   ├── A04  Database & JPA Review
│   │   ├── A09  PR Review
│   │   ├── A11  Performance Analyzer
│   │   ├── A13  API Design Auditor
│   │   ├── A14  Concurrency & Transaction Audit
│   │   ├── A15  Dependency Graph
│   │   ├── A16  Spring Boot Upgrade Advisor
│   │   └── A17  NFR Optimizer
│   │
│   └── Phase 3/4 (claude-opus/sonnet) — synthesis & generation (~$2+)
│       ├── A05  Architecture Review
│       ├── A06  Test Generator
│       ├── A07  Feature Documentation
│       ├── A08  LLD Generator
│       └── A18  Reverse Engineering  ← NEW
│
├── Pillar 2: CodeSearch (springinsight search)
│   ├── Parser      — Java AST → typed code chunks
│   ├── CodeGraph   — SQLite graph of nodes + edges
│   ├── Embedder    — sentence-transformers all-MiniLM-L6-v2 (384-dim)
│   ├── ChromaDB    — cosine-similarity vector store
│   └── Searcher    — query embed → vector search → graph expansion → Claude
│
└── Pillar 3: SpringTeam (springinsight team)
    ├── Task queue  — SQLite-backed task state machine
    ├── Agents      — Feature Writer, Test Writer, Doc Writer,
    │                 Refactor Agent, Security Fixer, Code Reviewer
    └── Approval    — human-in-the-loop approve/reject workflow
```

---

## Installation

SpringInsight requires **three things** before it will work: Python 3.10+, Node.js (for the Claude Code CLI), and an Anthropic API key. Follow every step below — skipping any one of them is the most common reason scans fail.

---

### Step 1 — Install Python 3.10 or higher

Check your Python version:

```bash
python3 --version
# Must print Python 3.10.x or higher
```

If you don't have Python 3.10+, download it from [python.org](https://www.python.org/downloads/) or use your system package manager:

```bash
# macOS (with Homebrew)
brew install python@3.12

# Ubuntu / Debian
sudo apt update && sudo apt install python3.12 python3.12-venv python3-pip
```

---

### Step 2 — Create a Python virtual environment (strongly recommended)

Using a virtual environment keeps SpringInsight's dependencies isolated from your system Python and avoids version conflicts.

```bash
# Create a venv named 'si-env' (you can name it anything)
python3 -m venv si-env

# Activate it — you must do this every time you open a new terminal
# macOS / Linux:
source si-env/bin/activate

# Windows (PowerShell):
si-env\Scripts\Activate.ps1
```

Your terminal prompt will change to show `(si-env)` when the venv is active.

---

### Step 3 — Install SpringInsight

With the venv active, install SpringInsight:

```bash
# Web UI + all features (recommended)
pip install 'springinsight[all]'

# CLI only (no web UI)
pip install springinsight

# CLI + Web UI (no PDF export or MCP server)
pip install 'springinsight[web]'
```

**Installing from source** (if you cloned the repo):

```bash
git clone https://github.com/shivpathakvw/springinsight
cd springinsight
pip install -e '.[all]'
```

Verify the installation:

```bash
springinsight --version
# Should print the version number, e.g.: SpringInsight 0.4.x
```

---

### Step 4 — Install Node.js and the Claude Code CLI

SpringInsight agents run via the **Claude Code CLI** (`claude`). This is a separate tool installed via Node.js/npm.

**Install Node.js first** (if you don't have it):

```bash
# Check if you already have Node.js
node --version    # Must be v18 or higher
npm --version
```

If not installed, download from [nodejs.org](https://nodejs.org/) (choose the LTS version). Or via package manager:

```bash
# macOS (Homebrew)
brew install node

# Ubuntu / Debian
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
```

**Install Claude Code CLI globally via npm:**

```bash
npm install -g @anthropic-ai/claude-code
```

Verify it installed correctly:

```bash
claude --version
# Should print something like: Claude Code 1.x.x
```

> **⚠️ Important — venv PATH issue**: When you activate a Python venv, it can sometimes hide the npm global bin directory from your PATH. If `claude --version` works in a plain terminal but agents all fail inside the venv, add npm's bin directory to your PATH explicitly:
>
> ```bash
> # Find where npm installs global packages:
> npm root -g
> # Example output: /Users/you/.nvm/versions/node/v20.x.x/lib/node_modules
>
> # Add the parent bin/ to PATH in your shell profile (~/.zshrc or ~/.bashrc):
> export PATH="$(npm bin -g):$PATH"
>
> # Then reload your shell:
> source ~/.zshrc
> ```
>
> SpringInsight automatically searches common npm/nvm install locations, so this is usually handled for you.

**Complete Claude Code setup** (first-time only):

```bash
# This opens a browser to authenticate with Anthropic
claude
```

Follow the prompts to log in. Once authenticated, press Ctrl+C to exit. The CLI is now ready.

---

### Step 5 — Get an Anthropic API Key

SpringInsight uses the Anthropic API directly (not just the Claude Code CLI). You need an API key.

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Sign in or create an account
3. Navigate to **API Keys** and create a new key
4. Copy the key — it starts with `sk-ant-`

Set the key as an environment variable **or** create a `.env` file:

**Option A — environment variable (current terminal session only):**

```bash
export ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
```

**Option B — `.env` file (persists across sessions, recommended):**

Create a file named `.env` in the directory where you will run `springinsight`:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
```

> The `.env` file is loaded automatically when SpringInsight starts. Never commit it to version control — add `.env` to your `.gitignore`.

---

### Step 6 — Verify everything works end-to-end

```bash
# Make sure your venv is still active:
source si-env/bin/activate

# Check Python package
springinsight --version

# Check Claude Code CLI is found
claude --version

# Check API key is set
echo $ANTHROPIC_API_KEY   # should print sk-ant-...

# Run a quick Phase 1 scan (Haiku, very cheap ~$0.03)
springinsight run https://github.com/spring-projects/spring-petclinic --agents A03,A10,A12
```

You should see agents starting and findings appearing. If all agents fail immediately, see the [Troubleshooting](#troubleshooting) section below.

---

### Quick-reference: install commands in one block

```bash
# 1. Create and activate venv
python3 -m venv si-env
source si-env/bin/activate          # macOS/Linux

# 2. Install SpringInsight
pip install 'springinsight[all]'

# 3. Install Claude Code CLI
npm install -g @anthropic-ai/claude-code
claude                               # authenticate (first time only)

# 4. Set API key
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env

# 5. Run your first scan
springinsight run /path/to/your/spring-project
```

---

### Troubleshooting

**All agents fail immediately with `java_files: 0`**  
→ The `claude` CLI is not on your PATH. Run `claude --version` in your terminal. If it works outside the venv but not inside, add the npm global bin to your PATH (see Step 4 above).

**`springinsight: command not found`**  
→ Your venv is not active. Run `source si-env/bin/activate` first.

**`ModuleNotFoundError` on startup**  
→ You installed into the wrong Python environment. Deactivate and reactivate the venv, then reinstall: `pip install 'springinsight[all]'`.

**`AuthenticationError` or `401 Unauthorized`**  
→ Your `ANTHROPIC_API_KEY` is wrong or not set. Check with `echo $ANTHROPIC_API_KEY`.

**Scan starts but no findings appear**  
→ Either all agents failed (check agent cards for error messages) or the project has no Java files in the scanned path.

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

---

## Pillar 2 — CodeSearch

Semantic natural-language search over your indexed Spring Boot codebase, powered by a local embedding model (all-MiniLM-L6-v2) + ChromaDB + Claude Sonnet. Everything runs on your machine — code never leaves your environment.

### How it works

1. **Index** — scans Java source files, builds a code graph (nodes + edges), embeds each chunk with MiniLM, stores in ChromaDB.
2. **Ask** — embeds your question, runs cosine-similarity search, expands results via the code graph, sends context to Claude for a cited answer.

### CodeSearch CLI

```bash
# Index a local project
springinsight search index ./my-spring-app

# Index a GitHub repo (clones automatically to ~/.springinsight/repos/)
springinsight search index https://github.com/spring-projects/spring-petclinic

# Force a full re-index (even if already indexed)
springinsight search index ./my-spring-app --force

# Verbose indexing — shows per-phase timing, chunk-type breakdown, batch sizes
springinsight search index ./my-spring-app --verbose

# Ask a natural-language question (uses current directory as project)
springinsight search ask "which classes handle payment retry?"
springinsight search ask "how is JWT validation implemented?"
springinsight search ask "list all @Scheduled jobs"

# Ask against a specific project
springinsight search ask "explain the auth flow" --project ./my-spring-app
springinsight search ask "find all @Transactional methods" -p https://github.com/org/repo

# Verbose ask — shows collection size, embed/vector timing, all results with scores,
# context window usage, per-source snippets, and wall-time breakdown
springinsight search ask "which service handles orders?" --verbose

# Retrieve more vector results (default: 10)
springinsight search ask "find all REST endpoints" --top-k 20

# Show index statistics for a project
springinsight search status
springinsight search status --project ./my-spring-app

# Full status with chunk-type breakdown, DB/Chroma paths
springinsight search status --project ./my-spring-app --verbose
```

### `--verbose` output (index)

```
  🔍 Scanning Java source files…
  🔍 Found 48 files → 312 chunks [312/312]
  🕸️  Graph: 312 nodes, 487 edges [312/312]
  🔮 Embedding chunks… 64/312  0.6s
  🔮 Embedding chunks… 128/312  1.1s
  ...
  ✅ Index complete — 48 files, 312 chunks, 312 graph nodes

  ⏱️  Phase timings:
     🔍 Scan         ▓░░░░░░░░░░░░░░░░░░░   0.12s  (2%)
     🕸️  Graph        ▓▓░░░░░░░░░░░░░░░░░░   0.31s  (5%)
     🔮 Embed        ████████████████░░░░   5.21s  (87%)
     ✅ Done         ░░░░░░░░░░░░░░░░░░░░   0.04s  (1%)
     Total                                  5.99s

  📊 Chunk breakdown by type:
     method        187  ████████████████░░░░  60%
     class          68  ██████░░░░░░░░░░░░░░  22%
     endpoint       41  ███░░░░░░░░░░░░░░░░░  13%
     field          16  █░░░░░░░░░░░░░░░░░░░   5%
     TOTAL         312
```

### `--verbose` output (ask)

```
  ────────────────────────────────────────────────────────────────────────
  DEBUG — CodeSearch pipeline
  ────────────────────────────────────────────────────────────────────────
  Collection size  : 312 chunks indexed
  Embed query      : 12 ms  (all-MiniLM-L6-v2)
  Vector search    : 8 ms  → 10 results returned
  Graph expansion  : 4 neighbour nodes added to context
  Context window   : 9,842 chars / 12,000 max  (12 blocks)

  Vector search results (ranked by cosine similarity):
     1. [████████░░] 0.821  METHOD    OrderService.retryPayment
     2. [███████░░░] 0.779  METHOD    PaymentProcessor.retry
  ...
  ────────────────────────────────────────────────────────────────────────
  Sending context to Claude Sonnet → streaming answer...
  ────────────────────────────────────────────────────────────────────────

  [answer appears here, streamed token by token]

  📋 Sources  (top results):
     1. [████████░░] METHOD: OrderService.retryPayment
          src/main/java/com/example/OrderService.java:142
     2. [███████░░░] METHOD: PaymentProcessor.retry
          ...

  ⏱️  Wall time: 2.41s  (embed: 0.012s  search: 0.008s  claude: 2.39s)
```

### CodeSearch Web UI

Start `springinsight web` and navigate to `http://localhost:8765/search`.

- Paste a GitHub URL or local path → click **Index** to build (or rebuild) the vector index
- Type a natural-language question and press Enter or click **Ask**
- Answers stream token-by-token; source citations appear with similarity scores
- Each conversation turn persists in the page for reference

---

## Pillar 3 — SpringTeam

Delegate development work to a team of AI agents. Each task goes through a write → review → approve/reject workflow — you stay in control.

### Agents in the team

| Agent | Role |
|-------|------|
| Feature Writer | Implements features from natural-language descriptions |
| Test Writer | Writes JUnit 5 + Mockito tests for new or existing code |
| Doc Writer | Generates Javadoc, README sections, OpenAPI annotations |
| Refactor Agent | Improves code quality, applies patterns, fixes smells |
| Security Fixer | Applies security patches identified by Code Review agents |
| Code Reviewer | Reviews other agents' output before it's surfaced to you |

### SpringTeam CLI

```bash
# Delegate a task (agent auto-selected based on description)
springinsight team task "Add pagination to the /orders endpoint"
springinsight team task "Write unit tests for OrderService"
springinsight team task "Fix the SQL injection in UserRepository.java:142"

# Specify an agent explicitly
springinsight team task "Refactor PaymentService to use strategy pattern" --skill refactor
springinsight team task "Document the auth flow" --skill docs

# Set priority (1 = highest, default: 3)
springinsight team task "Critical security patch for JWT validation" --priority 1

# List all tasks and their status
springinsight team list

# Show detail for a specific task
springinsight team status <task-id>

# Start processing pending tasks
springinsight team start

# Stop the team (graceful — finishes current task)
springinsight team stop

# Approve a completed task (accept the changes)
springinsight team approve <task-id>

# Reject a task (send it back with optional feedback)
springinsight team reject <task-id>
springinsight team reject <task-id> --reason "Use Optional<T> not null return"
```

### Task lifecycle

```
PENDING → IN_PROGRESS → REVIEW → APPROVED
                                ↘ REJECTED → PENDING (retry)
```

Tasks in `REVIEW` state appear in the Web UI (`/tasks`) with a diff view, accept/reject buttons, and the agent's reasoning.

### SpringTeam Web UI

Navigate to `http://localhost:8765/tasks` to see the team's Kanban board:

- **Pending** — tasks queued for the team
- **In Progress** — task currently being worked on by an agent
- **For Review** — completed tasks waiting for your approval (diff view)
- **Done** — approved tasks ready to apply to your codebase

---

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

## New Agents: A16, A17 & A18

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

### A18 — Reverse Engineering

Reconstructs the intent, architecture, and documentation of any Spring Boot codebase — including closed-source JARs, legacy code with no docs, or third-party services you need to understand quickly.

**What it produces:**
- Architecture overview: layers, modules, key services, data flow
- Annotated class/method inventory with inferred responsibilities
- Sequence diagrams for the most important flows (Mermaid)
- OpenAPI-style endpoint catalogue inferred from `@RestController` classes
- Onboarding guide for new developers
- Gap analysis: what's missing (tests, docs, error handling)

```bash
# Reverse-engineer a local project
springinsight run ./legacy-service --agents A18

# Or include it in a full scan
springinsight run ./legacy-service
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
| **A16** | **Spring Boot Upgrade Advisor** ⭐ | Sonnet | 2 | Deprecated APIs, migration plan 3.2→3.5→4.0, effort estimates |
| **A17** | **NFR Optimizer** ⭐ | Sonnet | 2 | Thread pools, caching TTL, HikariCP, virtual threads, GC tuning |
| A05 | Architecture Review | Opus | 3 | SOLID violations at architecture level, coupling matrix, ADRs |
| A08 | LLD Generator | Opus | 3 | Class diagrams, ER diagrams, sequence diagrams (Mermaid) |
| A06 | Test Generator | Sonnet | 4 | JUnit 5 + Mockito, @WebMvcTest, @DataJpaTest, security tests |
| A07 | Feature Docs | Sonnet | 4 | Feature specs, REST API reference, developer onboarding guide |
| **A18** | **Reverse Engineering** ⭐ | Opus | 3 | Reconstructs architecture, intent, and documentation from closed-source or legacy code |

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

springinsight web        Start the Web UI (all three pillars)
  --verbose / -v         Stream agent logs to terminal
  --port 9000            Custom port (default 8765)
  --open                 Open browser automatically
                         Routes: / (scan)  /search (CodeSearch)  /tasks (SpringTeam)

springinsight report     Display latest run report
  --pdf ./report.pdf     Export as PDF (requires reportlab)
  --severity CRITICAL    Filter by severity
  --run-id <id>          Specific run
  --export ./report.md   Export markdown report

# ── Pillar 2: CodeSearch ─────────────────────────────────────────────────────

springinsight search index <project>
  Build / rebuild the semantic vector index for a project.
  <project>              Local path or GitHub URL (cloned to ~/.springinsight/repos/)
  --force                Re-index even if already indexed
  --work-dir <dir>       Custom work directory (default: ~/.springinsight)
  --verbose / -v         Show per-phase timing, per-batch progress, chunk-type breakdown

springinsight search ask "<question>"
  Ask a natural-language question about an indexed codebase.
  --project / -p         Project path or GitHub URL (default: current dir)
  --top-k N              Number of vector results to retrieve (default: 10)
  --work-dir <dir>       Custom work directory
  --verbose / -v         Show collection size, embed/search timing (ms), all results
                         with cosine scores and snippets, context window chars,
                         wall-time split (embed / vector / claude)

springinsight search status
  Show index statistics for a project.
  --project / -p         Project path or GitHub URL (default: current dir)
  --work-dir <dir>       Custom work directory
  --verbose / -v         Show chunk-type breakdown, DB/Chroma paths

# ── Pillar 3: SpringTeam ──────────────────────────────────────────────────────

springinsight team task "<description>"
  Delegate a development task to the AI team.
  --skill SKILL          Force a specific agent: feature | tests | docs |
                         refactor | security | review
  --priority N           1 (highest) – 5 (lowest), default: 3

springinsight team list  List all tasks with IDs, status, and assigned agent
springinsight team status <task-id>
  Show full detail for a task: description, agent reasoning, diff preview

springinsight team start Start processing pending tasks
springinsight team stop  Gracefully stop after the current task finishes

springinsight team approve <task-id>
  Accept the agent's output and mark task APPROVED

springinsight team reject <task-id>
  Send a task back for revision.
  --reason "feedback"    Optional feedback to guide the retry

# ── A18: Reverse Engineering ──────────────────────────────────────────────────

springinsight reverse <project>
  Reconstruct architecture, intent, and documentation from any Spring Boot
  codebase — including closed-source JARs and legacy code with no docs.
  <project>              Local path or GitHub URL
  --output ./docs        Output directory for generated documents
  --format md|html|pdf   Output format (default: md)

# ── Other commands ────────────────────────────────────────────────────────────

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
springinsight agents     List all 18 agents with phase and status
springinsight init       Initialise project context (creates context.yaml)
```

Full options: `springinsight <command> --help`

### GitHub URL support

All commands that accept a `<project>` argument also accept a GitHub (or GitLab / Bitbucket) URL. The repo is cloned once and cached in `~/.springinsight/repos/`. Subsequent runs do a `git pull` to update.

```bash
# All of these accept a GitHub URL:
springinsight run       https://github.com/org/repo
springinsight search index  https://github.com/org/repo
springinsight search ask "..." -p https://github.com/org/repo
springinsight search status  -p https://github.com/org/repo
springinsight reverse   https://github.com/org/repo
```

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

**Pillar 1 — Code Review**
- [x] Phase 1–4: All 18 agents (A01–A18)
- [x] Web UI with live SSE progress, agent enable/disable, verbose logs
- [x] MCP Server — Claude Code / Cursor / Cline integration
- [x] VS Code extension — scan + diagnostics + Problems panel
- [x] Shared global database between CLI and Web UI
- [x] Project Context — custom rules injected into every agent
- [x] PDF export — professional scan reports
- [x] GitHub PR auto-scanning + auto-comment
- [x] A16 Spring Boot Upgrade Advisor
- [x] A17 NFR Optimizer
- [x] A18 Reverse Engineering
- [x] PyPI publishing with OIDC trusted publishing
- [x] Product website — [springinsight.vercel.app](https://springinsight.vercel.app)
- [ ] GitHub Actions marketplace action (`springinsight-action`)
- [ ] Incremental scanning (skip unchanged files)

**Pillar 2 — CodeSearch**
- [x] Java AST parser — classes, methods, endpoints, fields, config
- [x] SQLite code graph with cross-reference edges
- [x] sentence-transformers all-MiniLM-L6-v2 embeddings (local, private)
- [x] ChromaDB cosine-similarity vector store
- [x] Graph expansion for richer context
- [x] Claude Sonnet synthesis with source citation
- [x] CLI (`search index / ask / status`) with `--verbose` debug output
- [x] GitHub URL support — auto-clone and index remote repos
- [x] Web UI at `/search` with streaming SSE answer rendering
- [ ] Incremental re-indexing (only changed files)
- [ ] Multi-language support (Kotlin)

**Pillar 3 — SpringTeam**
- [x] Task queue with SQLite state machine
- [x] 6-agent team: Feature Writer, Test Writer, Doc Writer, Refactor, Security Fixer, Code Reviewer
- [x] CLI (`team task / list / status / start / stop / approve / reject`)
- [x] Web UI Kanban board at `/tasks` with approve/reject workflow
- [ ] Git integration — auto-commit approved tasks to a branch
- [ ] Slack/email notifications when tasks need review

**Platform**
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

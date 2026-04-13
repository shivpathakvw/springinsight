# SpringInsight v0.6.0 — ULTRAPLAN

> Three pillars: **Reverse Engineering Agent (A18)** · **CodeSearch (RAG)** · **SpringTeam (Multi-Agent Task Framework)**
> All contextual to Spring Boot. All run locally. All zero-infra.

---

## Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        SpringInsight v0.6.0                              │
├────────────────┬──────────────────────────┬─────────────────────────────┤
│   PILLAR 1     │        PILLAR 2           │         PILLAR 3            │
│                │                          │                             │
│  A18 Reverse   │   CodeSearch (RAG)       │  SpringTeam                 │
│  Engineering   │   Semantic codebase      │  Multi-agent task           │
│  Agent         │   Q&A + code graph       │  execution framework        │
│                │                          │                             │
│  "What does    │  "Which classes handle   │  "Add pagination to         │
│   this service │   payment retry logic?"  │   UserController" →         │
│   actually do" │   natural language       │   agents coordinate &       │
│   two modes    │   over your full repo    │   auto-complete it          │
└────────────────┴──────────────────────────┴─────────────────────────────┘
```

---

## PILLAR 1 — A18: Reverse Engineering Agent

### Purpose

Answers the question every new joiner and every architect asks: *"What does this codebase actually do, and how?"*

Rather than reading code file by file, A18 scans the entire Spring Boot project and produces a structured, human-readable document explaining **what features exist** and **how they are implemented** — tracing from REST endpoints down through services, repositories, events, and persistence.

### Two Modes

#### High-Level Mode (`--mode high-level`)
Target audience: tech leads, PMs, architects, new team members.
- Feature catalogue (inferred from controllers + service layer)
- Module breakdown by package with responsibility description
- External API surface (all `@RestController` + `@FeignClient` endpoints)
- Spring bean wiring summary (which services talk to which repos)
- Data model overview (JPA entities + relationships, no column details)
- Integration points (Kafka topics, Redis keys, external HTTP clients)
- One-page executive summary

Output: `ARCHITECTURE.md` (≈ 3–5 pages)

#### In-Depth Mode (`--mode in-depth [--target <class|package>]`)
Target audience: senior developers, reviewers, security auditors.
- Full call graph for each identified business flow
- `@RequestMapping` → `@Service` → `@Repository` → SQL/JPQL chain per endpoint
- `@Transactional` propagation and rollback rules traced per flow
- `@Async` / `@Scheduled` task documentation with thread pool config
- Event publishing (`ApplicationEventPublisher`) and listening (`@EventListener`) wiring
- Caching strategy per flow (`@Cacheable`, `@CacheEvict`, TTL)
- Error handling chain (global `@ControllerAdvice` → service exceptions)
- Sequence diagrams (Mermaid) for every major flow

Output: `TECHNICAL-REFERENCE.md` (≈ 15–40 pages depending on project size)

### CLI Usage

```bash
# High-level: understand the whole codebase
springinsight reverse --mode high-level ./my-spring-app

# In-depth: understand a specific service end-to-end
springinsight reverse --mode in-depth --target com.example.payments ./my-spring-app

# In-depth: trace a specific endpoint
springinsight reverse --mode in-depth --target "POST /api/orders" ./my-spring-app
```

### Technical Design

**Agent ID**: A18  
**Model**: `claude-opus-4-6` (needs the strongest reasoning for in-depth trace)  
**Phase**: 3 (after Phase 1+2 agents — uses their findings as enrichment)  
**SKILL.md**: `skills/a18-reverse-engineer/SKILL.md`

**High-Level pipeline**:
1. Enumerate all `@RestController` + `@Controller` classes → endpoint catalogue
2. For each endpoint, trace to service layer via `@Autowired` references
3. For each service, trace to repository layer
4. Enumerate `@Entity` / `@Table` classes → data model
5. Enumerate `@FeignClient`, `KafkaTemplate`, `RedisTemplate`, `RestClient` → integrations
6. Synthesize into structured Markdown

**In-Depth pipeline**:
1. Same as above but at method level
2. Build call graph: `Controller.method()` → `Service.method()` → `Repository.method()`
3. Trace `@Transactional` boundaries with propagation settings
4. Extract JPQL/SQL from `@Query` annotations and native queries
5. Detect cache interactions per method
6. Generate Mermaid sequence diagrams per flow
7. Synthesize into TECHNICAL-REFERENCE.md

**Output JSON (for web UI)**:
```json
{
  "mode": "high-level",
  "features": [
    {
      "name": "Order Management",
      "package": "com.example.orders",
      "endpoints": ["POST /api/orders", "GET /api/orders/{id}"],
      "services": ["OrderService", "PaymentService"],
      "entities": ["Order", "OrderItem"],
      "flows": [...]
    }
  ],
  "integrations": {
    "kafka_topics": ["order.created", "order.cancelled"],
    "external_clients": ["PaymentGatewayClient", "NotificationClient"]
  }
}
```

---

## PILLAR 2 — CodeSearch: RAG-Powered Semantic Code Intelligence

### Purpose

Give every developer a **natural language interface to the codebase**. Instead of `grep` or Ctrl+Shift+F in the IDE, you ask:

- *"Which classes handle payment retry logic and what's the retry strategy?"*
- *"Show me all @Transactional methods that call the inventory repository"*
- *"Where is the JWT token validated and what are the claims checked?"*
- *"What Spring beans are wired into the CheckoutService?"*
- *"Which endpoints don't have any test coverage?"*

The system answers using semantic vector search over a rich code index — not just text matching.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CodeSearch Architecture                       │
│                                                                 │
│  ┌──────────┐    ┌────────────────┐    ┌────────────────────┐   │
│  │  Java    │───▶│   Indexer      │───▶│   Vector Store     │   │
│  │  Source  │    │  Parser +      │    │   ChromaDB         │   │
│  │  Files   │    │  Chunker +     │    │   (sqlite-backed)  │   │
│  └──────────┘    │  Embedder      │    └────────────────────┘   │
│                  └────────────────┘             │               │
│                                                 │               │
│  ┌──────────────────────────────────────────────▼─────────────┐ │
│  │                    Code Graph (SQLite)                      │ │
│  │   Nodes: Class, Method, Field, Annotation, Endpoint        │ │
│  │   Edges: calls, extends, implements, autowires, annotates  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                  │
│  User Query                  ▼                                  │
│  ──────────▶  ┌──────────────────────────────┐                  │
│               │  Searcher                    │                  │
│               │  1. Embed query              │                  │
│               │  2. Vector similarity search │                  │
│               │  3. Graph context expansion  │                  │
│               │  4. Claude synthesizes answer│                  │
│               └──────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

### Tech Stack Decisions

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Vector DB | **ChromaDB** | Zero-infra, Python-native, SQLite-backed, no Docker needed |
| Embeddings | **sentence-transformers `all-MiniLM-L6-v2`** | Free, local, 80MB, 384-dim, excellent code+text similarity |
| Code Graph | **SQLite** (existing `springinsight.db`) | New tables — no new infra |
| Synthesis | **Claude claude-sonnet-4-6** | Reason over retrieved context, generate answers |
| Web UI | **FastAPI SSE + Alpine.js** | Consistent with existing stack |

### Indexing Pipeline

**Step 1 — Java File Parsing** (`springinsight/rag/parser.py`)

Parse every `.java` file into structured chunks. Each chunk represents a logical unit:
- Class declaration (name, annotations, extends/implements)
- Method (name, signature, annotations, body)
- Field (name, type, annotations)
- Config properties (from `application.properties`, `application.yml`)

**Step 2 — Code Graph Construction** (`springinsight/rag/code_graph.py`)

Build a graph stored in SQLite:
```sql
-- code_nodes: every class, method, field
CREATE TABLE code_nodes (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  node_type TEXT NOT NULL,  -- class|method|field|endpoint|config
  fqn TEXT NOT NULL,        -- fully-qualified name
  simple_name TEXT,
  file_path TEXT,
  line_start INTEGER,
  line_end INTEGER,
  annotations JSON,         -- ["@RestController", "@RequestMapping('/api')"]
  metadata JSON,            -- extra Spring-specific attributes
  summary TEXT,             -- AI-generated one-line description
  indexed_at TIMESTAMP
);

-- code_edges: relationships between nodes
CREATE TABLE code_edges (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  from_node TEXT,           -- FK to code_nodes.id
  to_node TEXT,             -- FK to code_nodes.id
  edge_type TEXT NOT NULL,  -- calls|extends|implements|autowires|annotates|publishes|listens
  metadata JSON
);
```

Spring-aware edge detection:
- `@Autowired` / constructor injection → `autowires` edge
- Method calls between classes → `calls` edge (static analysis)
- `extends` / `implements` in class declaration → `extends` / `implements` edge
- `ApplicationEventPublisher.publishEvent(X.class)` → `publishes` edge to event class
- `@EventListener` on method → `listens` edge from event class

**Step 3 — Embedding & Storage** (`springinsight/rag/indexer.py`)

For each chunk, create an embedding-ready text representation:
```
CLASS: OrderService
ANNOTATIONS: @Service, @Transactional
PACKAGE: com.example.orders
SUMMARY: Manages order lifecycle including creation, payment processing, and cancellation.
METHODS: createOrder(CreateOrderRequest), cancelOrder(String orderId), ...
DEPENDENCIES: OrderRepository, PaymentService, InventoryClient
```

Store in ChromaDB collection `{project_name}_code`:
- `id`: `{project_name}::{fqn}::{chunk_type}`
- `document`: text representation
- `embedding`: 384-dim float vector
- `metadata`: `{file_path, node_type, annotations, line_start, ...}`

**Step 4 — Search & Answer** (`springinsight/rag/searcher.py`)

```python
async def search(project_path: str, query: str, top_k: int = 10) -> SearchResult:
    # 1. Embed the query
    query_embedding = embedder.encode(query)

    # 2. Vector search → top-k most similar chunks
    results = chroma_collection.query(query_embeddings=[query_embedding], n_results=top_k)

    # 3. Graph expansion: for each result, fetch direct neighbours from code_graph
    enriched = expand_with_graph_context(results, project_path)

    # 4. Claude synthesizes a natural language answer from the context
    answer = await claude_synthesize(query, enriched)

    return SearchResult(answer=answer, sources=enriched)
```

### New Web Routes

```
GET  /search                     → search UI page
POST /api/search/index           → trigger indexing for a project
GET  /api/search/index/status    → indexing progress (SSE)
POST /api/search/ask             → submit query, returns SSE stream with answer
GET  /api/search/graph/{fqn}     → node + neighbours from code graph (for visualisation)
```

### Web UI — `/search` page

- **Indexing panel**: shows last indexed time, file count, chunk count. "Re-index" button.
- **Search bar**: large text input with example queries shown below
- **Chat interface**: query history with answers, source citations linking to file+line
- **Code graph panel** (optional, Phase 2): D3.js force-directed graph of Spring beans

### CLI

```bash
# Index a project (build RAG database)
springinsight search index ./my-spring-app

# Ask a question (CLI mode)
springinsight search ask "which classes handle payment retry?" --project ./my-spring-app

# Start web UI with search enabled (automatic if index exists)
springinsight web
```

### Incremental Re-indexing

Like existing `file_cache` logic — only re-index files that changed since last index (by SHA-256). Index metadata stored in a new `rag_index_state` table.

---

## PILLAR 3 — SpringTeam: Multi-Agent Task Execution Framework

### The Vision

A team of specialist AI agents that work like colleagues. You describe work in plain English — they pick it up, coordinate, execute, and report back. Inspired by Multica's model but **Spring Boot-native** and **fully embedded** in SpringInsight.

```
User: "Add cursor-based pagination to the UserController GET /users endpoint,
       write tests, and update the OpenAPI docs."

SpringTeam:
  [Planner]       → splits into 3 tasks:
    Task 1:  Implement cursor pagination in UserController (→ Coder)
    Task 2:  Write unit + integration tests for pagination (→ Tester) [depends: Task 1]
    Task 3:  Update OpenAPI spec for /users endpoint (→ Documenter) [depends: Task 1]

  [Coder]        → reads context, implements changes, creates Task 1 PR diff
  [Tester]       → reads Task 1 output, writes JUnit 5 tests
  [Documenter]   → reads Task 1 output, updates @Operation annotations + swagger docs

  User Dashboard: Live kanban board showing all three tasks progress in real-time
```

### Agent Pool — 6 Specialist Agents

| Agent | Skill | Spring Expertise |
|-------|-------|-----------------|
| **Planner** | Decomposes complex tasks into sub-tasks with dependencies | Spring architecture patterns |
| **Coder** | Implements features, fixes bugs, refactors | Spring Boot idioms, JPA, REST |
| **Tester** | Writes JUnit 5, Mockito, @WebMvcTest, @DataJpaTest | Spring test slices, MockMvc |
| **Reviewer** | Reviews code changes, flags Spring anti-patterns | SOLID, transaction safety |
| **DB Optimizer** | Fixes N+1, adds indexes, tunes JPA fetch strategies | JPA, Hibernate, Flyway |
| **Documenter** | JavaDoc, OpenAPI annotations, README updates | SpringDoc, Swagger |

### Task Model

```
Status flow:
  PENDING → CLAIMED → IN_PROGRESS → REVIEW → DONE
                                  ↘ BLOCKED (dependency not met)
                                  ↘ FAILED  (agent error)
```

```sql
-- Tasks table
CREATE TABLE springteam_tasks (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,         -- full natural language description
  required_skill TEXT,               -- coder|tester|reviewer|db_optimizer|documenter|planner
  status TEXT DEFAULT 'pending',     -- pending|claimed|in_progress|review|done|blocked|failed
  priority INTEGER DEFAULT 5,        -- 1 (urgent) to 10 (low)
  parent_task_id TEXT,               -- for sub-tasks
  depends_on JSON DEFAULT '[]',      -- task IDs that must complete first
  assigned_agent TEXT,               -- which agent slot picked this up
  created_at TIMESTAMP,
  claimed_at TIMESTAMP,
  completed_at TIMESTAMP,
  context JSON,                      -- extra context (files to focus on, etc.)
  output TEXT,                       -- agent's output (diff, doc, test code, etc.)
  output_type TEXT,                  -- code_diff|test_file|doc_update|review_comment
  error TEXT
);

-- Agent messages — inter-agent communication
CREATE TABLE springteam_messages (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  from_agent TEXT NOT NULL,          -- planner|coder|tester|reviewer|system|user
  to_agent TEXT,                     -- null = broadcast
  message_type TEXT NOT NULL,        -- status_update|question|blocker|handoff|completion
  content TEXT NOT NULL,
  created_at TIMESTAMP
);

-- Agent slots — running agent workers
CREATE TABLE springteam_agents (
  id TEXT PRIMARY KEY,
  agent_type TEXT NOT NULL,          -- coder|tester|reviewer|db_optimizer|documenter|planner
  status TEXT DEFAULT 'idle',        -- idle|working|paused
  current_task_id TEXT,
  last_heartbeat TIMESTAMP,
  capabilities JSON                  -- skills list for routing
);
```

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     SpringTeam Architecture                      │
│                                                                  │
│  User Input                                                      │
│     │                                                            │
│     ▼                                                            │
│  ┌─────────────────┐                                             │
│  │  Planner Agent  │  ← Claude Sonnet                           │
│  │  - Understands  │    Decomposes task, identifies skills,      │
│  │    the request  │    creates dependency graph of sub-tasks    │
│  └────────┬────────┘                                             │
│           │ creates tasks                                        │
│           ▼                                                      │
│  ┌──────────────────────────────────────────────┐               │
│  │              Task Queue (SQLite)             │               │
│  │  PENDING tasks sorted by priority + deps     │               │
│  └──────────────────────────────────────────────┘               │
│           │                                                      │
│     ┌─────┼──────────────────┐                                  │
│     ▼     ▼                  ▼                                   │
│  ┌──────┐ ┌──────┐       ┌──────┐   Agent Workers               │
│  │Coder │ │Tester│  ...  │DocBot│   (asyncio tasks, each polls  │
│  │Agent │ │Agent │       │Agent │    queue for matching skill)   │
│  └──┬───┘ └──┬───┘       └──┬───┘                               │
│     │        │              │                                    │
│     └────────┴──────────────┘                                    │
│                    │                                             │
│                    ▼                                             │
│  ┌─────────────────────────────────────────┐                    │
│  │    Message Bus (springteam_messages)    │                    │
│  │  Agents post progress, questions,       │                    │
│  │  handoffs, completions                  │                    │
│  └─────────────────────────────────────────┘                    │
│                    │                                             │
│                    ▼                                             │
│  ┌──────────────────────────────────────────┐                   │
│  │  Orchestrator  (background asyncio task) │                   │
│  │  - Watches task status changes           │                   │
│  │  - Unblocks dependent tasks when deps    │                   │
│  │    complete                              │                   │
│  │  - Handles agent failures / retry        │                   │
│  │  - Pushes SSE events to web UI           │                   │
│  └──────────────────────────────────────────┘                   │
└──────────────────────────────────────────────────────────────────┘
```

### Agent Communication Protocol

Each agent posts messages to the shared bus. The orchestrator routes relevant messages:

```python
# Agent handoff example
# Coder completes implementation, hands off to Tester
{
  "from_agent": "coder",
  "to_agent": "tester",
  "message_type": "handoff",
  "content": {
    "completed_task": "task-001",
    "output_files": ["src/main/java/.../UserController.java"],
    "context_for_next": "Added cursor-based pagination. PageToken is Base64-encoded. Test with GET /api/users?pageToken=xxx&size=20",
    "next_task": "task-002"
  }
}
```

### Agent Skill Routing

The router uses a two-step approach:

1. **Keyword matching** (fast): `test`, `junit`, `coverage` → Tester; `n+1`, `index`, `fetch` → DB Optimizer
2. **Claude classification** (accurate, for ambiguous tasks): Send task description to Haiku with a skill-matching prompt → returns required skill

```python
SKILL_KEYWORDS = {
    "coder":        ["implement", "add", "create feature", "fix bug", "refactor", "build"],
    "tester":       ["test", "junit", "coverage", "spec", "mockito", "@test"],
    "reviewer":     ["review", "audit", "check", "analyse", "critique"],
    "db_optimizer": ["n+1", "query", "index", "jpa", "fetch", "hibernate", "flyway", "slow"],
    "documenter":   ["document", "javadoc", "openapi", "readme", "swagger", "@operation"],
}
```

### Web UI — `/tasks` page (Kanban Board)

```
┌────────────────────────────────────────────────────────────────────┐
│  SpringTeam                              [+ New Task]  [▶ Run All] │
│                                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ PENDING  │  │IN PROGRESS│  │  REVIEW  │  │   DONE   │          │
│  │    3     │  │    2     │  │    1     │  │    5     │          │
│  ├──────────┤  ├──────────┤  ├──────────┤  ├──────────┤          │
│  │[Card]    │  │[Card]    │  │[Card]    │  │[Card ✓]  │          │
│  │Add paging│  │Write test│  │Review    │  │Fix N+1   │          │
│  │[Coder]   │  │[Tester]  │  │payment   │  │OrderRepo │          │
│  │priority:1│  │⏳ 2m 14s │  │[Reviewer]│  │          │          │
│  │━━━━━━━━━━│  │━━━━━━━━━━│  │━━━━━━━━━━│  │━━━━━━━━━━│          │
│  │[Card]    │  │[Card]    │  │          │  │[Card ✓]  │          │
│  │Update    │  │Implement │  │          │  │Add cache │          │
│  │OpenAPI   │  │JWT refresh│  │         │  │UserSvc   │          │
│  │[DocBot]  │  │[Coder]   │  │          │  │          │          │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘          │
│                                                                    │
│  Agent Activity Feed                                               │
│  ─────────────────────────────────────────────────────────────    │
│  [Tester] ✓ Generated 14 test cases for UserController pagination  │
│  [Coder]  ⟳ Implementing cursor-based pagination (UserController) │
│  [Planner] → Created 3 sub-tasks from "Add pagination" request    │
└────────────────────────────────────────────────────────────────────┘
```

**Task detail modal** (click a card):
- Full description
- Agent message thread (like a GitHub PR conversation)
- Output preview (diff, test code, doc update)
- Dependency graph mini-view
- Approve / Request Changes buttons (for Review state)

### CLI

```bash
# Create a task
springinsight team task "Add cursor-based pagination to UserController" --project ./my-app

# Create with explicit skill assignment
springinsight team task "Fix N+1 in OrderRepository" --skill db_optimizer --priority 1

# List tasks
springinsight team list

# Check task status
springinsight team status task-001

# Start agents (runs in background)
springinsight team start --agents coder,tester,documenter --project ./my-app

# Stop agents
springinsight team stop

# View agent logs
springinsight team logs
```

### Agent Coordination Workflows (Built-in)

The orchestrator ships with pre-defined coordination templates:

| Template | Trigger | Agents Involved | Flow |
|----------|---------|----------------|------|
| `implement-and-test` | Any `coder` task | Coder → Tester → Reviewer | Implement → Write tests → Review |
| `fix-and-validate` | Bug fix task | Coder → Tester | Fix → Verify fix with test |
| `db-optimize-and-test` | N+1 / query task | DB Optimizer → Tester | Fix query → Test performance |
| `document-from-code` | Doc task | Coder (reads) → Documenter | Read implementation → Document |
| `full-feature` | Complex feature | Planner → Coder → Tester → Reviewer → Documenter | Full lifecycle |

---

## New File Structure

```
springinsight/
├── rag/                              # NEW — Pillar 2: CodeSearch
│   ├── __init__.py
│   ├── parser.py                     # Java AST-style parser (regex + heuristic)
│   ├── code_graph.py                 # Build/query Spring bean + call graph
│   ├── indexer.py                    # Chunker + embedder + ChromaDB writer
│   ├── searcher.py                   # Query → search → Claude synthesis
│   └── embedder.py                   # sentence-transformers wrapper
│
├── tasks/                            # NEW — Pillar 3: SpringTeam
│   ├── __init__.py
│   ├── models.py                     # Task, AgentMessage, AgentSlot dataclasses
│   ├── queue.py                      # SQLite-backed task queue
│   ├── router.py                     # Skill-based task routing
│   ├── orchestrator.py               # Dependency engine + workflow runner
│   ├── pool.py                       # Agent worker lifecycle management
│   └── agents/
│       ├── __init__.py
│       ├── base.py                   # BaseSpringAgent (common Claude call logic)
│       ├── planner.py                # Planner (task decomposition)
│       ├── coder.py                  # Coder (implementation)
│       ├── tester.py                 # Tester (JUnit 5)
│       ├── reviewer.py               # Reviewer (code review)
│       ├── db_optimizer.py           # DB Optimizer (JPA/Hibernate)
│       └── documenter.py             # Documenter (JavaDoc + OpenAPI)
│
├── agents/
│   └── registry.py                   # UPDATED: add A18
│
└── web/
    ├── app.py                        # UPDATED: new /search and /tasks routes
    └── templates/
        ├── search.html               # NEW — CodeSearch UI
        ├── search_result.html        # NEW — Search answer + sources
        ├── tasks.html                # NEW — SpringTeam Kanban board
        └── task_detail.html          # NEW — Task detail modal/page

skills/
└── a18-reverse-engineer/
    └── SKILL.md                      # NEW — Reverse Engineering Agent

pyproject.toml                        # UPDATED: add chromadb, sentence-transformers deps
```

---

## DB Schema Additions

```sql
-- RAG index state
CREATE TABLE rag_index_state (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL UNIQUE,
  indexed_at TIMESTAMP NOT NULL,
  java_files_count INTEGER,
  chunk_count INTEGER,
  embedding_model TEXT,
  chroma_collection TEXT
);

-- Code graph: nodes
CREATE TABLE code_nodes (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  node_type TEXT NOT NULL,    -- class|method|field|endpoint|config
  fqn TEXT NOT NULL,          -- com.example.OrderService.createOrder
  simple_name TEXT,
  file_path TEXT,
  line_start INTEGER,
  line_end INTEGER,
  annotations JSON,
  metadata JSON,
  summary TEXT,               -- AI-generated one-liner
  indexed_at TIMESTAMP
);

-- Code graph: edges
CREATE TABLE code_edges (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  from_node TEXT,
  to_node TEXT,
  edge_type TEXT NOT NULL,    -- calls|extends|implements|autowires|publishes|listens
  metadata JSON
);

-- SpringTeam tasks
CREATE TABLE springteam_tasks (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  required_skill TEXT,
  status TEXT DEFAULT 'pending',
  priority INTEGER DEFAULT 5,
  parent_task_id TEXT,
  depends_on JSON DEFAULT '[]',
  assigned_agent TEXT,
  created_at TIMESTAMP,
  claimed_at TIMESTAMP,
  completed_at TIMESTAMP,
  context JSON,
  output TEXT,
  output_type TEXT,
  error TEXT
);

-- SpringTeam inter-agent messages
CREATE TABLE springteam_messages (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  from_agent TEXT NOT NULL,
  to_agent TEXT,
  message_type TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMP
);
```

---

## Implementation Phases

### Phase 1 — Foundation (Week 1)
**Goal**: A18 + RAG indexing pipeline working end-to-end

| # | Task | File(s) |
|---|------|---------|
| 1 | Add A18 to registry, write SKILL.md (both modes) | `registry.py`, `skills/a18-*` |
| 2 | Java parser: extract classes, methods, annotations | `rag/parser.py` |
| 3 | Code graph builder: Spring bean edges | `rag/code_graph.py` |
| 4 | Embedder wrapper (sentence-transformers MiniLM) | `rag/embedder.py` |
| 5 | Indexer: chunk → embed → ChromaDB | `rag/indexer.py` |
| 6 | DB schema migrations for new tables | `db/models.py` |
| 7 | CLI: `springinsight reverse` + `springinsight search index` | `commands/` |

### Phase 2 — Search UI + A18 Web (Week 2)
**Goal**: Working `/search` web page, A18 visible in scan reports

| # | Task | File(s) |
|---|------|---------|
| 1 | Searcher: query → embed → vector search → Claude synthesis | `rag/searcher.py` |
| 2 | FastAPI routes: `/search`, `/api/search/ask`, `/api/search/index` | `web/app.py` |
| 3 | Search UI: chat-style, SSE streaming, source citations | `templates/search.html` |
| 4 | A18 output rendering in web report | `templates/report.html` |
| 5 | Add nav link "Search" to base.html | `templates/base.html` |

### Phase 3 — SpringTeam Core (Week 3)
**Goal**: Working task queue, agent workers, Planner + Coder agents

| # | Task | File(s) |
|---|------|---------|
| 1 | Task queue + models (SQLite-backed) | `tasks/queue.py`, `tasks/models.py` |
| 2 | Skill router (keyword + Claude fallback) | `tasks/router.py` |
| 3 | BaseSpringAgent (common Claude + context loading) | `tasks/agents/base.py` |
| 4 | Planner agent (task decomposition) | `tasks/agents/planner.py` |
| 5 | Coder agent (implementation, produces diff) | `tasks/agents/coder.py` |
| 6 | Orchestrator (dependency engine, SSE events) | `tasks/orchestrator.py` |
| 7 | CLI: `springinsight team task`, `springinsight team start` | `commands/` |

### Phase 4 — Full Agent Pool + Kanban UI (Week 4)
**Goal**: All 5 specialist agents, full Kanban board, coordination workflows

| # | Task | File(s) |
|---|------|---------|
| 1 | Tester, Reviewer, DB Optimizer, Documenter agents | `tasks/agents/*.py` |
| 2 | Agent pool lifecycle management | `tasks/pool.py` |
| 3 | Built-in coordination workflow templates | `tasks/orchestrator.py` |
| 4 | Kanban board UI with SSE live updates | `templates/tasks.html` |
| 5 | Task detail page (message thread, diff preview) | `templates/task_detail.html` |
| 6 | FastAPI routes: `/tasks`, `/api/tasks/*` | `web/app.py` |
| 7 | Tests, documentation, README update | - |

---

## Dependency Additions (`pyproject.toml`)

```toml
[project.dependencies]
# Existing ...
chromadb = ">=0.4.22"                   # Vector store (zero-infra, SQLite-backed)
sentence-transformers = ">=2.7.0"       # Local embeddings (no API cost)
torch = ">=2.0.0"                       # Required by sentence-transformers (CPU only)
javalang = ">=0.13.0"                   # Java AST parser (optional, regex fallback)
```

> **Note on torch**: sentence-transformers requires torch but CPU-only is ~200MB. Alternative: use `fastembed` (~50MB) with ONNX runtime for a leaner install.

---

## Key Design Principles

1. **Zero new infrastructure** — ChromaDB uses SQLite on disk (`.springinsight/rag/chroma/`). No Docker, no Postgres, no Redis.

2. **Free to run** — All embeddings are local (sentence-transformers). Only Claude API calls cost money (synthesis only, not indexing).

3. **Spring Boot-aware everywhere** — Every agent, every parser, every graph edge is designed around Spring annotations and idioms.

4. **Progressive enhancement** — Each pillar is independently useful. CodeSearch works without SpringTeam. A18 works without CodeSearch.

5. **Existing patterns** — All new features follow existing conventions: SQLAlchemy models, FastAPI SSE, Alpine.js UI, SKILL.md behavioral contracts.

6. **Incremental indexing** — RAG index only re-processes changed files (SHA-256 cache). First index: slow. Subsequent: fast.

---

## Questions to Resolve Before Implementation

1. **Embedding model size**: `all-MiniLM-L6-v2` is 80MB. Is that acceptable, or should we use `fastembed` with ONNX (~50MB) for a leaner install?

2. **Code graph depth**: Method-level call graph is expensive to build precisely in Java (requires full type resolution). Start with class-level only + annotation-level, and use heuristics for method-to-method calls?

3. **SpringTeam output format**: Does the Coder agent produce a raw diff, or write files directly to a working copy? Writing to a temp branch is safer — should the agent create a git branch?

4. **SpringTeam authentication**: Should the Reviewer's approval gate require a user click before the next agent proceeds, or is it fully autonomous?

5. **A18 target scoping**: For in-depth mode on a 500k-line codebase, full tracing is expensive. Should we require `--target` for in-depth (recommended), or auto-select top 10 flows by complexity?

---

*Ready to begin implementation — start with Phase 1: A18 SKILL.md + RAG parser.*

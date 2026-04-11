#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SpringInsight — One-time Git setup & push script
# Run this from the springinsight directory on your machine:
#
#   cd /path/to/springinsight
#   bash setup-git.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

REMOTE="https://github.com/shivpathakvw/springinsight.git"
AUTHOR_NAME="Shiv Chandra Pathak"
AUTHOR_EMAIL="shivchandrapathak@gmail.com"

echo "🍃 SpringInsight — Git setup"
echo ""

# Remove any partial .git from the sandbox (if present)
if [ -d ".git" ]; then
  echo "→ Removing existing .git directory..."
  rm -rf .git
fi

# Init fresh repo
echo "→ Initialising git repository..."
git init
git checkout -b main

# Author config (local only — does not affect global git config)
git config user.name  "$AUTHOR_NAME"
git config user.email "$AUTHOR_EMAIL"

# Stage everything (respects .gitignore)
echo "→ Staging files..."
git add \
  README.md LICENSE .gitignore CONTRIBUTING.md CHANGELOG.md PUBLISHING.md GROWTH.md \
  .env.example pyproject.toml MANIFEST.in \
  springinsight/ skills/ tests/ docs/ \
  .github/

# Commit
echo "→ Creating initial commit..."
git commit -m "$(cat <<'EOF'
feat: SpringInsight v0.2.0 — Phase 1 + Phase 2 live, website, PyPI

Autonomous multi-agent codebase intelligence for Java and Spring Boot.

Phase 1 agents (Haiku — fast pattern matching):
- A03 CVE & License Scanner
- A10 Dead Code Detector (Spring-aware)
- A12 Config & Infra Review

Phase 2 agents (Sonnet — deep analysis) — all live:
- A01 Deep Code Review (SOLID, null safety, Spring anti-patterns)
- A02 Security Scanner (OWASP Top 10, injection, JWT, deserialization)
- A04 Database & JPA Review (N+1, fetch strategies, schema risks)
- A09 PR Review (blast radius, breaking changes, rollback plan)
- A11 Performance Analyzer (caching, thread pools, unbounded queries)
- A13 API Design Auditor (REST compliance, pagination, OpenAPI)
- A14 Concurrency & Transaction Audit (race conditions, @Async safety)
- A15 Dependency Graph (import + bean wiring, circular deps, Mermaid)

Infrastructure:
- context.yaml: project descriptor injected into every agent prompt
- Multi-model strategy: Haiku → Sonnet → Opus for cost-optimised scanning
- SQLite via SQLAlchemy: runs, findings, scores, agent results
- Async runner: asyncio + claude --print with bounded parallelism
- GitHub URL support: shallow clone with auto-pull on re-scan
- SKILL.md lookup order: user override → installed package → dev repo

CLI: init, run, report, findings, history, agents, web

Web UI (springinsight web):
- Dark-themed dashboard with live SSE progress (SSE pub/sub)
- Score dashboard and filterable findings table
- Persistent run history via SQLite

Product website: docs/index.html (GitHub Pages)
- Full landing page: agents, intelligence layers, comparison table, pricing

PyPI publishing:
- pyproject.toml with full metadata, classifiers, project URLs
- .github/workflows/publish.yml with OIDC trusted publishing (no tokens)
- CHANGELOG.md, PUBLISHING.md, GROWTH.md

Author: Shiv Chandra Pathak <shivchandrapathak@gmail.com>
EOF
)"

# Enable GitHub Pages (if you haven't already, go to repo Settings → Pages →
# Source: Deploy from a branch → Branch: main, /docs)
echo ""
echo "→ Next steps for GitHub Pages:"
echo "   1. Go to https://github.com/shivpathakvw/springinsight/settings/pages"
echo "   2. Source: Deploy from a branch"
echo "   3. Branch: main, Folder: /docs"
echo "   4. Site will be at: https://shivpathakvw.github.io/springinsight"
echo ""

# Set remote
echo "→ Setting remote origin..."
git remote add origin "$REMOTE"

# Push
echo "→ Pushing to GitHub..."
echo "   (You may be prompted for your GitHub credentials)"
echo "   (If the repo already has commits, run: git push --force -u origin main)"
git push -u origin main

echo ""
echo "✅ Done! SpringInsight is live:"
echo "   📦 GitHub:  https://github.com/shivpathakvw/springinsight"
echo "   🌐 Website: https://shivpathakvw.github.io/springinsight  (after Pages setup)"
echo "   🚀 PyPI:    Push tag v0.2.0 to publish → git tag v0.2.0 && git push origin v0.2.0"

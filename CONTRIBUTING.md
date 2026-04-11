# Contributing to SpringInsight

Thank you for your interest in contributing! SpringInsight is an open-source project and welcomes contributions of all kinds — new agents, bug fixes, documentation improvements, and feature ideas.

## Getting Started

### Prerequisites

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (for running agents locally)
- An [Anthropic API key](https://console.anthropic.com/)

### Development Setup

```bash
# Fork and clone
git clone https://github.com/<your-fork>/springinsight
cd springinsight

# Install in editable mode with all extras
pip install -e '.[web,dev]'

# Copy .env.example
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

# Run tests
pytest

# Lint
ruff check . && ruff format --check .
```

## Ways to Contribute

### 1. Add a New Agent (most impactful)

Each agent lives in `skills/<agent-id>-<name>/SKILL.md`. The SKILL.md is the full behavioral contract for the agent — it tells `claude --print` exactly what to analyse and how to format its findings.

**Steps:**

1. Look at an existing SKILL.md (e.g., `skills/a03-cve-license/SKILL.md`) for the expected structure.
2. Create `skills/<new-agent-id>-<name>/SKILL.md`.
3. Register the agent in `springinsight/agents/registry.py`.
4. Add tests in `tests/agents/test_<agent_id>.py`.
5. Open a PR with:
   - The SKILL.md
   - Registry entry
   - At least one example finding (as a JSON fixture in `tests/fixtures/`)
   - A short description in the PR body of what the agent finds and why it matters

**SKILL.md writing guidelines:**

- Be explicit about the file discovery steps (Glob patterns)
- Use concrete examples of what to look for
- Define the exact JSON finding schema expected
- End with the `SPRINGINSIGHT_DONE: <N> findings written to <path>` completion line
- Prefer false negatives over false positives (never flag something you're unsure about)

### 2. Report a Bug

Open a [GitHub issue](https://github.com/shivpathakvw/springinsight/issues/new) with:

- SpringInsight version (`springinsight --version`)
- Python version
- Steps to reproduce
- Expected vs. actual behaviour
- Any relevant log output

### 3. Suggest a Feature

Open a [GitHub Discussion](https://github.com/shivpathakvw/springinsight/discussions) describing:

- The problem it solves
- Your proposed solution
- Any alternatives you considered

### 4. Improve Documentation

- Fix typos, clarify confusing sections, add examples
- Improve SKILL.md files with better instructions
- Add more CVEs, license patterns, or misconfiguration rules to Phase 1 agents

## Pull Request Process

1. Branch from `main`: `git checkout -b feature/your-feature`
2. Make your changes, add/update tests
3. Run `ruff check . && ruff format .`
4. Run `pytest` — all tests must pass
5. Open a PR against `main` with a clear description
6. Address review feedback

## Code Style

- Python: [Ruff](https://docs.astral.sh/ruff/) for linting and formatting (100-char lines)
- Type hints on all public functions
- Docstrings on all public classes and functions
- No bare `except` — always catch specific exceptions

## Project Structure

```
springinsight/
├── springinsight/          Python package
│   ├── agents/             Agent registry + async runner
│   ├── commands/           CLI subcommands (init, run, report, web)
│   ├── context/            context.yaml loader + renderer
│   ├── db/                 SQLAlchemy models + database init
│   ├── utils/              GitHub cloning, scoring, env loader
│   └── web/                FastAPI app + SSE scanner + templates
├── skills/                 SKILL.md files (one per agent)
│   ├── a03-cve-license/
│   ├── a10-dead-code/
│   └── a12-config-review/
└── tests/                  pytest tests
```

## License

By contributing to SpringInsight, you agree that your contributions will be licensed under the [MIT License](LICENSE).

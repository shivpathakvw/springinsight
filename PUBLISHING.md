# Publishing SpringInsight to PyPI

SpringInsight uses **OIDC Trusted Publishing** — no long-lived API tokens required.

---

## One-time Setup (do this once)

### 1. Register on PyPI / TestPyPI

1. Create an account at https://pypi.org (and optionally https://test.pypi.org)
2. Go to **Account settings → Publishing** (or https://pypi.org/manage/account/publishing/)
3. Add a new **Trusted Publisher**:
   - **PyPI project name**: `springinsight`
   - **Owner**: `shivpathakvw`
   - **Repository**: `springinsight`
   - **Workflow filename**: `publish.yml`
   - **Environment name**: `pypi`
4. Repeat for TestPyPI with environment name `testpypi`

### 2. Create GitHub Environments

In your GitHub repo → **Settings → Environments**:
- Create environment named `pypi`
- Create environment named `testpypi`
- (Optional) Add required reviewers for production `pypi` environment

---

## Publishing a Release

### Automated (recommended)

Push a version tag — CI handles everything:

```bash
# Bump version in pyproject.toml and __init__.py first, then:
git add pyproject.toml springinsight/__init__.py
git commit -m "chore: bump version to v0.3.0"
git tag v0.3.0
git push origin main --tags
```

This will:
1. Run tests on Python 3.10 / 3.11 / 3.12
2. Build wheel + sdist
3. Publish to PyPI via OIDC (no token!)
4. Create a GitHub Release with the dist files attached

### Manual (TestPyPI first)

```bash
# Trigger manually from Actions tab → "Publish to PyPI" → Run workflow
# Select target: testpypi

# Test the install from TestPyPI:
pip install --index-url https://test.pypi.org/simple/ springinsight
```

---

## Version Numbering

Follows [Semantic Versioning](https://semver.org/):

| Version bump | When |
|---|---|
| `PATCH` (0.2.**1**) | Bug fixes, dependency updates |
| `MINOR` (0.**3**.0) | New agents, new CLI commands, non-breaking changes |
| `MAJOR` (**1**.0.0) | Breaking changes to CLI API, config format, or findings schema |

---

## Files to update when bumping version

1. `pyproject.toml` — `version = "X.Y.Z"`
2. `springinsight/__init__.py` — `__version__ = "X.Y.Z"`
3. `CHANGELOG.md` — add release notes section

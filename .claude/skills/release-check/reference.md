# Release Runbook

Step-by-step procedure for cutting releases. See ADR-0004
(`docs/adr/0004-release-workflow-and-breaking-change-policy.md`) for the
philosophy behind this workflow.

Protean uses **direct minor releases** (no release candidates). Minor versions
are cut straight from `main` when the changelog has substantive entries. Bugs
discovered after a release are shipped as **patch releases** from the release
branch.

## Version bump commands

```bash
# Install bump-my-version (in dev dependencies)
uv sync --group dev

# Minor release (e.g., 0.15.0 → 0.16.0)
bump-my-version bump minor

# Patch release (e.g., 0.15.0 → 0.15.1)
bump-my-version bump patch
```

Version is updated automatically in: `pyproject.toml`, `src/protean/__init__.py`,
`src/protean/template/domain_template/pyproject.toml.jinja`,
`docs/guides/getting-started/installation.md`, `.bumpversion.toml`.

`bump-my-version` auto-creates a commit and tag (e.g., `v0.16.0`). Push the tag
to trigger the publish workflow.

The GitHub Actions workflow (`.github/workflows/publish.yml`) handles:
- Building with uv
- Publishing to PyPI (trusted publishing)
- Creating a GitHub Release

## Minor release workflow (from main)

```
main:  ──A──B──C──[tag v0.16.0]──D──E──...
                      │
release/0.16.x:       └── (created on demand for patches)
```

**Cutting a minor release:**

```bash
git checkout main
git pull --ff-only

# 1. Finalize CHANGELOG: rename [Unreleased] → [0.X.0] - YYYY-MM-DD, leave a fresh empty [Unreleased] above it
$EDITOR CHANGELOG.md
git add CHANGELOG.md
git commit -m "Mark 0.X.0 release in CHANGELOG"

# 2. Bump version, create commit + tag
bump-my-version bump minor                    # 0.15.0 → 0.16.0
git push origin main --tags

# 3. Create release branch from the new tag (for future patches)
git branch release/0.16.x v0.16.0
git push origin release/0.16.x
```

## Patch release workflow (from release branch)

Bugfixes land on `main` first, then are cherry-picked to the release branch:

```bash
# Fix the bug on main, merge PR, then:
git checkout release/0.16.x
git pull --ff-only
git cherry-pick <commit-hash>

# Update CHANGELOG on the release branch under [0.16.1]
$EDITOR CHANGELOG.md
git add CHANGELOG.md
git commit -m "Mark 0.16.1 release in CHANGELOG"

bump-my-version bump patch                    # 0.16.0 → 0.16.1
git push origin release/0.16.x --tags
```

## Post-release checklist

1. Verify the `[Unreleased]` section in `CHANGELOG.md` on `main` is empty and ready for the next cycle
2. Verify the package on PyPI
3. For minor releases, confirm `release/0.X.x` branch is pushed for future patches

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

# 2. Bump version, then commit + tag MANUALLY.
#    bump-my-version's own commit is aborted by the `uv-lock` pre-commit hook:
#    bumping the version in pyproject makes uv.lock stale, the hook regenerates
#    it, and pre-commit's stash/rollback reverts the commit (seen cutting 0.16.0).
#    `--no-verify` is blocked by policy, so refresh the lockfile first, then let
#    the hooks pass on a normal commit.
bump-my-version bump minor --no-commit --no-tag    # 0.15.0 → 0.16.0, files only
uv lock                                             # bring uv.lock to the new version
git add -A
git commit -m "Bump version: 0.15.0 → 0.16.0"       # uv-lock hook now passes
git tag -a v0.16.0 -m "Bump version: 0.15.0 → 0.16.0"
git push origin main
git push origin v0.16.0                              # tag push triggers publish.yml

# 3. Create release branch from the new tag (for future patches)
git branch release/0.16.x v0.16.0
git push origin release/0.16.x
```

## Patch release workflow (from release branch)

The `release/0.X.x` branch is created when the minor ships (step 3 above) and
stays around for the life of that line, so a patch never waits on branch
creation. Bugfixes land on `main` first, then are cherry-picked to the release
branch:

```bash
# Fix the bug on main, merge PR, then:
git checkout release/0.16.x
git pull --ff-only
git cherry-pick <commit-hash>                 # CI runs on the release branch push

# Update CHANGELOG on the release branch under [0.16.1]
$EDITOR CHANGELOG.md
git add CHANGELOG.md
git commit -m "Mark 0.16.1 release in CHANGELOG"

# Bump version, then commit + tag MANUALLY — same uv-lock gotcha as the minor
# flow: bump-my-version's own commit is aborted by the `uv-lock` pre-commit
# hook (the stale uv.lock is regenerated and pre-commit rolls the commit back).
bump-my-version bump patch --no-commit --no-tag   # 0.16.0 → 0.16.1, files only
uv lock                                            # bring uv.lock to the new version
git add -A
git commit -m "Bump version: 0.16.0 → 0.16.1"      # uv-lock hook now passes
git tag -a v0.16.1 -m "Bump version: 0.16.0 → 0.16.1"
git push origin release/0.16.x
git push origin v0.16.1                             # tag push triggers publish.yml
```

## Backporting fixes to the release branch

Two ways to get a `main` fix onto `release/0.X.x`:

- **Automated (preferred):** add the `backport release/0.X.x` label to the PR
  before merging. The `Backport` workflow (`.github/workflows/backport.yml`)
  opens a cherry-pick PR against the release branch on merge. Review and merge
  that PR, then cut the patch.
- **Manual:** cherry-pick the merge commit as shown in the patch workflow above.
  Use this when the automated cherry-pick conflicts.

Only the latest minor line is patched (see `SECURITY.md`); don't backport to
older `release/*` branches.

## Post-release checklist

1. Verify the `[Unreleased]` section in `CHANGELOG.md` on `main` is empty and ready for the next cycle
2. Verify the package on PyPI
3. For minor releases, confirm `release/0.X.x` branch is pushed for future patches

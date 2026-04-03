---
name: release-check
description: Run pre-release validation checks — version consistency, changelog entries, GitHub issue status, CI state, and release branch health. Use when the user says "release check", "ready to release", "pre-release validation", "can we cut a release", or is about to run bump-my-version. Also trigger when the user mentions version numbers or release candidates in the context of shipping.
argument-hint: "[minor|patch|rc]"
---

# Pre-Release Validation

Run every check needed before cutting a release. The version is bumped automatically by `bump-my-version`, so the job here is to verify that the codebase is in a clean, consistent state *before* the bump happens.

## Check 1: Changelog has entries

```bash
head -40 CHANGELOG.md
```

Verify there's content under `## [Unreleased]` — at least one entry. An empty unreleased section means either the changelog wasn't maintained or there's genuinely nothing to release. If empty, flag it as a blocker.

## Check 2: Version consistency

The version string lives in 4 files and must match across all of them:

```bash
grep '^version' pyproject.toml | head -1
grep '__version__' src/protean/__init__.py
grep 'protean>=' src/protean/template/domain_template/pyproject.toml.jinja
grep -E 'pip install protean|protean==' docs/guides/getting-started/installation.md
```

Report any mismatches. Note: the template and docs files may use a base version (e.g., `0.15.0`) while pyproject.toml has an RC suffix (e.g., `0.15.0rc1`). This is expected during RC cycles — flag it only if the base versions differ.

## Check 3: Epic sub-issues

Find the active epic(s) from GitHub:

```bash
gh issue list -R proteanhq/protean --label "epic" --state open --limit 10
```

Query the relevant epic for sub-issue status:

```bash
gh issue view <epic-number> -R proteanhq/protean --json title,subIssues
```

Report open sub-issues. They may need to be closed, deferred, or descoped before release. This is informational, not always a hard blocker — the user decides.

## Check 4: Branch state

```bash
git branch --show-current
git fetch origin --quiet
```

If on a release branch (`release/X.Y.x`):
- Check for unmerged cherry-picks from main: `git log origin/main..HEAD --oneline`
- Check for main commits not yet cherry-picked: `git log HEAD..origin/main --oneline`

If on `main`:
- Check whether a release branch exists and whether one needs to be created

## Check 5: CI status

```bash
gh run list -R proteanhq/protean --branch "$(git branch --show-current)" --limit 5
```

Flag any failing or in-progress checks. A release should not be tagged with red CI.

## Check 6: Dry-run the version bump

Show what `bump-my-version` would do without applying it:

```bash
uv run bump-my-version bump --dry-run --verbose minor 2>&1 | head -30
```

If `$ARGUMENTS` specifies a bump type (e.g., `minor`, `patch`, `rc`), use that instead of `minor`. The dry-run shows which files change and what the new version string would be.

## Report

Produce a pass/fail checklist:

```
## Release Readiness

- [x] CHANGELOG: 5 entries under [Unreleased]
- [x] Version consistency: 0.15.0rc2 across all 4 files
- [ ] Epic sub-issues: 2 of 8 still open (#756, #757)
- [x] Branch: release/0.15.x, up to date
- [x] CI: all checks passing
- [x] Dry-run: 0.15.0rc2 → 0.15.0 (4 files updated)

Blockers: 2 open sub-issues need resolution before final release.
```

If everything passes, confirm explicitly: "All checks pass — safe to run `bump-my-version bump <type>`."

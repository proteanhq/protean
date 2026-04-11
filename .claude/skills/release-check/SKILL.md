---
name: release-check
description: Run pre-release validation checks — version consistency, changelog entries, GitHub issue status, CI state, and release branch health. Use when the user says "release check", "ready to release", "pre-release validation", "can we cut a release", or is about to run bump-my-version.
argument-hint: "[minor|patch]"
---

# Pre-Release Validation

Run every check needed before cutting a release. The version is bumped automatically by `bump-my-version`, so the job here is to verify that the codebase is in a clean, consistent state *before* the bump happens.

Protean uses **direct minor releases** cut from `main`, and **patch releases** cut from `release/0.X.x` branches. There is no release candidate step.

## Check 1: Changelog has entries

```bash
head -40 CHANGELOG.md
```

Verify there's content under `## [Unreleased]` — at least one entry. An empty unreleased section means either the changelog wasn't maintained or there's genuinely nothing to release. If empty, flag it as a blocker.

The release step will rename `[Unreleased]` to `[0.X.Y] - YYYY-MM-DD` — verify the section is coherent and ready to become a release header.

## Check 2: Version consistency

The version string lives in 5 files and must match across all of them:

```bash
grep '^version' pyproject.toml | head -1
grep '__version__' src/protean/__init__.py
grep 'protean>=' src/protean/template/domain_template/pyproject.toml.jinja
grep -E 'pip install protean|protean==' docs/guides/getting-started/installation.md
grep '^current_version' .bumpversion.toml
```

Report any mismatches — all five must agree on a clean `MAJOR.MINOR.PATCH` string (no `rc` suffixes).

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

**For a minor release** — must be on `main`:
- Check `main` is up to date: `git log HEAD..origin/main --oneline` should be empty
- Check a `release/0.X.x` branch does not already exist for the target version

**For a patch release** — must be on `release/0.X.x`:
- Check the branch is up to date: `git log HEAD..origin/release/0.X.x --oneline`
- Confirm the intended cherry-picks have landed: `git log origin/main..HEAD --oneline`
- Check nothing on main that should have been cherry-picked: `git log HEAD..origin/main --oneline`

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

If `$ARGUMENTS` specifies a bump type (`minor` or `patch`), use that. The dry-run shows which files change and what the new version string would be.

## Report

Produce a pass/fail checklist:

```
## Release Readiness

- [x] CHANGELOG: 12 entries under [Unreleased]
- [x] Version consistency: 0.15.0 across all 5 files
- [ ] Epic sub-issues: 2 of 8 still open (#756, #757)
- [x] Branch: main, up to date with origin
- [x] CI: all checks passing
- [x] Dry-run: 0.15.0 → 0.16.0 (5 files updated)

Blockers: 2 open sub-issues need resolution before release.
```

If everything passes, confirm explicitly: "All checks pass — safe to run `bump-my-version bump <type>`."

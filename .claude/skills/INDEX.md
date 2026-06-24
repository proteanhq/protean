# Skills Index

The catalogue of Claude Code skills for this repo. One entry per skill.

**Keep current:** update this file in the same change that adds or removes a
skill. Each skill's own trigger phrasing lives in its `SKILL.md` frontmatter
(and is injected into context automatically) — the value *here* is the
**boundaries** (when *not* to reach for each) and the **composition graph**,
which aren't surfaced anywhere else.

## Catalogue

| Skill | Purpose | Don't use when |
|-------|---------|----------------|
| `/adr` | Record an Architecture Decision Record in `docs/adr/` | The decision is trivial or already covered by an existing ADR |
| `/breaking-change` | Diff the branch for public-API breaks, classify Tier 1/2/3, generate deprecation shims | The change is internal-only with no `protean.*` surface user code depends on |
| `/changelog` | Assemble `changes/*.md` fragments into `CHANGELOG.md` per-epic, then delete them | Mid-feature — fragments stay until the epic closes; never edit `CHANGELOG.md` directly in a feature PR |
| `/check` | Run the full quality pipeline: `protean check`, `ruff check`, `ruff format`, `mypy` | You only need the affected-test subset → `/test-impact` |
| `/epic-plan` | Deep-dive an epic and break it into PR-sized GitHub sub-issues with project fields set | The work is a one-off fix with no epic |
| `/epic-status` | Dashboard of epic progress, blockers, and ready-to-work items | You need the next physical step on one issue → `/implement` |
| `/implement` | End-to-end issue delivery: research → implement → simplify → review → test → commit → PR | The change is exploratory or not yet a scoped issue |
| `/pr` | Create a well-formed PR (fragment check, breaking-change scan, description, issue link) | No changelog fragment exists, or unmitigated breaks remain |
| `/pr-respond` | Poll PR review comments, fix, reply, resolve threads | No review feedback exists yet |
| `/release-check` | Pre-release validation: version across bump files, changelog, issues, CI, dry-run bump | Mid-development |
| `/test` | Run the suite **and fix** failures | You want diagnosis only, no edits → the `test-runner` agent |
| `/test-impact` | Run only the tests affected by current changes (src→tests mapping) | You need full-suite confidence before a release → `/test` or `/check` |

## Agents (`.claude/agents/`)

Read-only gates — they diagnose and review, they **never edit**:

| Agent | Role |
|-------|------|
| `pr-reviewer` | Reviews the working-tree diff against Protean conventions; reports blockers/suggestions |
| `test-runner` | Runs tests and diagnoses failures without touching code |

## Composition

- **`/implement` is the orchestrator.** In its Phase 2 it invokes `/simplify`
  and launches the `pr-reviewer` agent inline (self-review is explicitly *not*
  a substitute), then runs the suite, commits, and opens a PR via `/pr`.
- **`/pr` gates on release hygiene** — it runs the breaking-change scan and
  ensures a `changes/<issue>.<category>.md` fragment exists before creating the PR.
- **`/pr-respond` picks up after `/pr`** — it handles review feedback once a PR is open.
- **`/release-check` → release runbook.** When its checks pass, the actual
  cut-the-release steps live in `.claude/skills/release-check/reference.md`.
- **`/epic-plan` → project automation.** GraphQL mutations and field/option IDs
  live in `.claude/skills/epic-plan/reference.md`.

## Maintenance

This index is itself a drift surface. The `protean-pulse` SessionStart hook
(`.claude/hooks/protean-pulse.py`) flags any `.claude/skills/*/` directory that
has no row in the Catalogue table above, so a newly added skill can't silently
go uncatalogued.

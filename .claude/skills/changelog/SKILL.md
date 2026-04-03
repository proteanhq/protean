---
name: changelog
description: Generate and insert a CHANGELOG.md entry for the current branch's changes. Use when the user says "add changelog", "update changelog", "changelog entry", or when wrapping up a feature/fix and needing to document it. Also trigger when the /pr skill needs a changelog entry — this skill is designed to be composable. Trigger even when the user just says "document this change" or "what changed".
argument-hint: "[Added|Changed|Deprecated|Removed|Fixed|Security]"
---

# Smart Changelog Entry

Analyze the current branch's changes, draft a changelog entry, and insert it into the correct section of CHANGELOG.md. The changelog is the project's communication channel with its users — every entry should help someone decide whether to upgrade and what to expect.

## Understand what changed

```bash
git diff main...HEAD --stat
git log main..HEAD --oneline
```

Read the diffs carefully. Focus on what changed from a *user's* perspective — the capability that was added, the bug that was fixed, the behavior that shifted. File paths and line numbers are implementation details; the changelog reader cares about what they can now do (or can't, or must change).

## Categorize

Determine which subsection the entry belongs under:

| Category | When to use | Signal in the diff |
|----------|------------|-------------------|
| **Added** | Entirely new capabilities | New classes, CLI commands, public methods, config options |
| **Changed** | Existing behavior modified | Changed signatures, different defaults, altered semantics |
| **Deprecated** | Marked for future removal | `DeprecationWarning`, `deprecated=` option added |
| **Removed** | Previously deprecated, now gone | Deleted public APIs, removed config options |
| **Fixed** | Bug corrections | Conditional fixes, edge case handling, error message fixes |
| **Security** | Vulnerability patches | Auth fixes, input sanitization, dependency CVEs |

If `$ARGUMENTS` specifies a category, use it directly. A single branch may warrant entries in multiple categories — for instance, a refactor that adds a new API and deprecates the old one needs both an **Added** and a **Deprecated** entry.

## Draft the entry

The audience is a developer scanning the changelog before upgrading. They want to know:
- What changed (in terms they recognize from using the framework)
- Why it matters to them (especially for fixes and behavioral changes)

**Writing style to follow** (based on this project's actual changelog):

```
- Add `protean schema generate` CLI command for JSON Schema output
```
```
- Fix aggregate identity not being set when using `from_dict()` class method
```
```
- `value_object_from_entity()` utility function that auto-generates a `BaseValueObject`
  subclass mirroring an entity's fields, eliminating manual field duplication for
  command/event payloads
```

Notice the patterns:
- Start with the feature/fix name or the affected API in backticks
- Describe the user-visible outcome, not the files touched
- For complex entries, one opening sentence followed by elaboration is fine
- Bug fixes start with "Fix" and name the symptom the user would have seen

**Avoid these:**
- "Update cli/schema.py to add generate subcommand" (file-centric, not user-centric)
- "Fix bug in aggregate.py line 234" (meaningless to a user)
- "Refactor internal handling of X" (if it's purely internal, it doesn't belong in the changelog)

## Check for duplicates

Read the `[Unreleased]` section of `CHANGELOG.md`. If an existing entry already covers the same change, report it and suggest updating or extending that entry instead of adding a duplicate. This matters because multiple commits on a branch often touch the same feature — they should be one changelog entry, not three.

## Insert the entry

Edit `CHANGELOG.md` to add the entry under the correct subsection within `[Unreleased]`. If the subsection doesn't exist yet, create it. The project uses this ordering: Added, Changed, Deprecated, Removed, Fixed, Security.

Place new entries at the end of their subsection (before the next `###` heading or the next `## [` version heading).

When invoked standalone, edit the file but don't commit — the user or the `/pr` skill handles that.

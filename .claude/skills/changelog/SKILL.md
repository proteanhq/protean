---
name: changelog
description: Assemble changelog fragments into a CHANGELOG.md entry for a completed epic. Use when the user says "add changelog", "update changelog", "changelog entry", or when an epic is marked Done. Fragments live in `changes/` and are created per-PR by the /implement skill. This skill assembles them, groups by epic, and cleans up the fragments.
argument-hint: "#epic-number [--title 'Epic Title']"
---

# Assemble Changelog from Fragments

Collect all fragment files in `changes/`, group them by epic, and insert a consolidated entry into `CHANGELOG.md` under `[Unreleased]`. Then delete the assembled fragments.

## Step 1: Identify the epic

Parse `$ARGUMENTS` for an epic number (`#N` or bare number) and optional title (`--title`).

If an epic number is provided, fetch its title and sub-issues:
```bash
gh issue view <NUMBER> -R proteanhq/protean --json title,body
```

List the sub-issue numbers so you know which fragments belong to this epic. If no epic is provided, assemble ALL fragments in `changes/`.

## Step 2: Read all fragments

```bash
ls changes/*.md 2>/dev/null | grep -v README.md
```

Each fragment is named `<issue-number>.<category>.md`. Parse the issue number and category from the filename. Read each file's content.

If assembling for a specific epic, only include fragments whose issue number is a sub-issue of that epic. If assembling all, include everything.

## Step 3: Group and format

Group fragments by category in this order: Added, Changed, Deprecated, Removed, Fixed, Security. Skip empty categories.

Format as a per-epic section:

```markdown
### <Epic Title> (#<epic-number>)

#### Added
- Fragment content from 752.added.md
- Fragment content from 753.added.md

#### Fixed
- Fragment content from 754.fixed.md
```

If no epic context (assembling all fragments), use a flat structure without the epic heading — just the category subsections directly under `[Unreleased]`.

## Step 4: Writing style check

Before inserting, review each entry against the project's style:

- Start with the feature/fix name or the affected API in backticks
- Describe the user-visible outcome, not the files touched
- Bug fixes start with "Fix" and name the symptom the user would have seen
- No file paths, no line numbers, no "Refactor internal handling of X"

Rewrite entries that don't meet the bar. The fragments are drafts — the assembled changelog should read well as a whole.

## Step 5: Insert into CHANGELOG.md

Read `CHANGELOG.md`. Find the `## [Unreleased]` section. Insert the new epic section after any existing content under `[Unreleased]` but before the next `## [` version heading.

If there are already entries under `[Unreleased]` that aren't in epic sections (legacy flat entries), leave them as-is above the new epic section.

## Step 6: Clean up fragments

Delete the assembled fragment files:
```bash
rm changes/<issue-number>.<category>.md
```

Keep `changes/README.md` and `changes/.gitkeep`.

## Step 7: Report

Output a summary:
```
Assembled N fragments for epic #M — "Epic Title"
Categories: Added (X), Fixed (Y), ...
Fragments removed: list of files
```

Do not commit — the user or calling skill handles that.

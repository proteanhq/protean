---
name: adr
description: Create an Architecture Decision Record in docs/adr/. Use when the user says "create an ADR", "document this decision", "record this architecture decision", or when a design discussion leads to a conclusion that should be preserved. Also trigger when the user describes a significant technical trade-off or says "why did we choose X over Y" in a way that implies the decision should be documented.
argument-hint: "<decision-title> [--issue N]"
---

# Architecture Decision Record Creator

Create an ADR following the project's established template at `docs/adr/TEMPLATE.md`. ADRs are the permanent record of *why* things are the way they are — they prevent re-litigating settled questions and help future contributors understand the framework's design.

## Determine the next number

```bash
ls docs/adr/ | grep -E '^[0-9]{4}-' | sort -r | head -1
```

Extract the highest number, increment by 1, zero-pad to 4 digits. ADR-0000 is reserved for guiding principles.

## Gather the content

From `$ARGUMENTS` and the conversation context, extract the building blocks of the ADR. The template (from `docs/adr/TEMPLATE.md`) has these sections:

**Title**: Short noun-phrase. Good: "Use networkx for dependency graphs". Bad: "We decided to add networkx".

**Status**: Almost always `Accepted` when creating a new ADR — if the decision is already made, it's accepted. Use `Proposed` only if the ADR is being written *before* the decision is final.

**Date**: Current month and year (e.g., "April 2026").

**Context**: The forces at play, the problem that needed solving, the constraints. Write as you would explain to a new team member with domain context. If the conversation has a design discussion, synthesize the key tensions here.

**Decision**: What was chosen, in active voice. "We will use X" / "We chose Y because Z." Specific enough that someone could implement or verify it.

**Consequences**: What becomes easier *and* harder. Every decision has trade-offs — state them plainly. This is the most valuable section for future readers.

**Alternatives Considered** (optional): Other approaches evaluated and why they were not chosen. Include this when multiple viable options were discussed.

If the user provides only a brief summary, expand it into the full structure. If the conversation contains a detailed design discussion, distill it — don't copy-paste the whole thread.

## Create the file

Write to `docs/adr/NNNN-<kebab-case-title>.md`.

The filename should be descriptive but concise:
- Good: `0010-use-networkx-for-dependency-graphs.md`
- Bad: `0010-decision-about-which-graph-library-to-use.md`

## Link to related issue

If `$ARGUMENTS` contains `--issue N` or the conversation references a GitHub issue or epic, add a reference in the Context section:

```markdown
Related: [#123](https://github.com/proteanhq/protean/issues/123)
```

Also reference other ADRs when the decision builds on or constrains earlier ones — e.g., "Building on the IR-first approach established in ADR-0005."

## Stage and report

```bash
git add docs/adr/NNNN-*.md
```

Show the user the file path and a brief summary so they can review before committing. ADRs are best reviewed before merge — they're hard to correct retroactively because they represent a point-in-time decision.

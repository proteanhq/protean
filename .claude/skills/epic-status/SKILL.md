---
name: epic-status
description: Show the current status of a Protean epic — progress, sub-issues, blockers, and what's ready to work on next. Use this skill whenever the user asks "where are we on the epic", "epic status", "what's left", "what's next", "show progress", or wants a dashboard-style view of an epic's sub-issues. Also trigger when the user starts a new session and wants to pick up where they left off on an active epic.
argument-hint: "[epic-number-or-name]"
---

# Epic Status Report

Generate a clear, at-a-glance status report for an epic and its sub-issues. This is read-only — no mutations, no edits, just information.

## Find the epic

If `$ARGUMENTS` is provided, use it to identify the epic — it could be:
- An issue number (e.g., `751`)
- A sequence number from the roadmap (e.g., `1.10`)
- A name fragment (e.g., `IR Materialization`)

If no argument is given, query GitHub for active epics:

```bash
gh issue list -R proteanhq/protean --label "epic" --state open --limit 10
```

This shows all open epics. If `todo/0-ROADMAP.md` exists locally, it may have additional context on which epics are actively being worked — but GitHub is the source of truth.

## Gather data

Query the epic issue and its sub-issues:

```bash
gh issue view <epic-number> -R proteanhq/protean --json title,body,state,labels,number

# Get sub-issues
gh issue view <epic-number> -R proteanhq/protean --json subIssues
```

For each sub-issue, get its status and any linked PRs:

```bash
gh issue view <sub-issue-number> -R proteanhq/protean --json title,state,number,linkedPullRequests
```

Check for blocking relationships:

```bash
gh api graphql -f query='{ repository(owner: "proteanhq", name: "protean") {
  issue(number: <N>) {
    blockedBy(first: 10) { nodes { number title state } }
    blocking(first: 10) { nodes { number title state } }
  }
} }'
```

## Check the plan file

Look for a matching plan file in `.claude/plans/`. Your local Claude project memory (under `~/.claude/projects/<project>/memory/MEMORY.md`) may record the plan file path for active epics. If a plan exists, scan it for any discrepancies with the current GitHub state — sub-issues that were added or removed, scope changes, etc.

## Report format

Present the status like this:

```
## Epic: <title> (#<number>)
Status: <Active/In Progress>  |  Progress: X/Y closed

### Sub-issues
  #123 [x] First sub-issue title               PR #456 (merged)
  #124 [x] Second sub-issue title               PR #457 (merged)
  #125 [ ] Third sub-issue title                (no PR)
  #126 [ ] Fourth sub-issue title               PR #458 (open)
       └─ blocked by #125

### Ready to work on
- #125: Third sub-issue title (unblocked, no PR yet)

### Blockers
- #126 is blocked by #125 (still open)
```

Keep it scannable. The user should be able to glance at this and know exactly where things stand and what to pick up next.

If multiple epics are active, report on each one separately.

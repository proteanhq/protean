---
name: epic-plan
description: Plan and break down an epic from the Protean roadmap into self-contained GitHub Issues with proper project board fields and dependencies. Use this skill whenever the user mentions planning an epic, breaking down an epic, starting a new epic, or refers to a specific epic by number or name from the roadmap (e.g., "let's plan 1.10", "break down the IR materialization epic", "start the next epic"). Also trigger when the user says "what's next on the roadmap" and the answer involves planning work.
argument-hint: "<epic-number-or-name>"
---

# Plan an Epic

Take an epic from the Protean roadmap and turn it into a concrete, actionable set of GitHub Issues ready for execution. This is a multi-phase process that produces durable tracking artifacts — the issues, PRs, and commit messages are the permanent trail, not the project board.

## Phase 1: Understand the epic

Start by building a deep understanding of what the epic requires.

### Find the epic

Find the epic matching `$ARGUMENTS` — it might be referenced by issue number (e.g., "#751"), name (e.g., "IR Materialization"), or sequence number (e.g., "1.10").

Query the GitHub Project to find it:

```bash
gh issue list -R proteanhq/protean --label "epic" --state all --limit 30
```

If `todo/0-ROADMAP.md` exists locally, read it for additional context — but don't depend on it, as it's gitignored and may not be present on all machines.

### Review the epic on GitHub

Query the GitHub Project to see the epic's current state — its status, release, sequence, and any existing sub-issues:

```bash
gh issue view <number> -R proteanhq/protean
gh issue view <number> -R proteanhq/protean --json title,body,labels,state
```

If the epic is still a draft item on the project board (not yet a real issue), you'll need to convert it in Phase 2.

### Deep-dive the codebase

This is the most important step. Read the relevant source code and tests to understand:

- What already exists that the epic builds on
- What patterns the codebase uses that the new code should follow
- What the boundaries of change are — which files, which modules
- What tests exist and what test patterns to follow

Don't rush this. A shallow understanding here leads to sub-issues that are either too vague or incorrectly scoped. Read actual source files, not just directory listings.

**Capture findings as you go.** You will need file paths, line numbers, and design rationale when writing the epic body and sub-issues in Phase 2. Write down:
- Every existing file/function that the epic builds on (with line numbers)
- Design choices you're making and why — at the level of: "Health check HTTP server: **aiohttp** — lightweight, pure asyncio, no ASGI overhead; not ASGI because Engine has no web framework"
- Patterns in the codebase that new code should follow (e.g., "DLQ maintenance should follow the OutboxProcessor async task pattern")

### Break into sub-issues

Each sub-issue should be:

- **One PR's worth of work** — coherent, reviewable, independently mergeable
- **Tests ship with code** — never a separate "add tests" issue
- **Sequenced logically** — later issues can depend on earlier ones
- **Specific** — the issue title and body should make it clear exactly what to build

Aim for 3-8 sub-issues per epic. If you need more, the epic might be too large.

## Phase 2: Create tracking artifacts

### Convert draft to real issue (if needed)

If the epic exists as a draft item on the project board, convert it using the GraphQL API:

```bash
gh api graphql -f query='mutation {
  convertProjectV2DraftIssueItemToIssue(input: {
    projectId: "PVT_kwDOAmXm_s4BRFMC"
    itemId: "<draft-item-id>"
    repositoryId: "<repo-node-id>"
  }) { item { id } }
}'
```

To find the repo node ID:
```bash
gh api graphql -f query='{ repository(owner: "proteanhq", name: "protean") { id } }'
```

### Set up the epic issue

Add the `epic` label and flesh out the body. The epic issue is the **single source of truth** — everything the implementer needs to understand cross-cutting context must be here, not in a local file.

```bash
gh issue edit <number> -R proteanhq/protean --add-label "epic" --body "$(cat <<'EOF'
## Outcome
What this epic delivers when complete.

## Why
Why this matters — the motivation, constraint, or stakeholder need.

## Success criteria
- [ ] Criterion 1
- [ ] Criterion 2

## What already exists
Code, patterns, and infrastructure this epic builds on. Include file paths and line numbers.
This section prevents `/implement` from duplicating existing work or re-solving solved problems.

- `src/protean/path/to/file.py` (lines N-M) — description of what it does
- ...

## Design decisions
Key choices made during planning — library selections, API shape, config format — and *why*.
These are constraints on implementation, not suggestions.

- **Decision:** rationale — include what was considered and why it was rejected
- e.g., "Health check HTTP server: **aiohttp** — lightweight, pure asyncio, no ASGI overhead. Not Flask/FastAPI because Engine has no web framework and adding one is disproportionate."
- ...

## Dependency order
Brief rationale for why sub-issues are sequenced the way they are.

```
#N1 Title (foundation — other issues build on this)
  ├── #N2 Title (needs N1 for X)
  ├── #N3 Title (independent of N2, but needs N1)
  └── #N4 Title (needs N2 + N3)
```

## Sub-issues
Created as native sub-issues below.
EOF
)"
```

Set project fields — Item Type to Epic, Status to Active:

```bash
# Get the item ID on the project board first
gh api graphql -f query='{ repository(owner: "proteanhq", name: "protean") {
  issue(number: <N>) { projectItems(first: 5) { nodes { id project { title } } } }
} }'

# Set Item Type = Epic
gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: {
  projectId: "PVT_kwDOAmXm_s4BRFMC"
  itemId: "<item-id>"
  fieldId: "PVTSSF_lADOAmXm_s4BRFMCzg_KRSg"
  value: { singleSelectOptionId: "1acf4758" }
}) { projectV2Item { id } } }'

# Set Status = Active
gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: {
  projectId: "PVT_kwDOAmXm_s4BRFMC"
  itemId: "<item-id>"
  fieldId: "PVTSSF_lADOAmXm_s4BRFMCzg_A5gY"
  value: { singleSelectOptionId: "5a1d9210" }
}) { projectV2Item { id } } }'
```

### Create sub-issues

Each sub-issue must be **self-contained** — an implementer should be able to read just the issue body and the epic's "Design Decisions" / "What Already Exists" sections to know exactly what to build. Use this structure:

```bash
gh issue create -R proteanhq/protean \
  --title "Sub-issue title" \
  --body "$(cat <<'EOF'
## Sub-issue of #<EPIC> (<epic name>)

### Gap
What's missing or wrong — be specific. Include file paths and line numbers where relevant.

### Deliverables
Concrete list of what to build. Each item should be verifiable.

### Key files
- `src/protean/path/to/file.py` (what to modify and why)
- New: `src/protean/path/to/new_file.py` (if creating)

### Tests
- What to verify, what assertions to make
- Edge cases to cover
EOF
)"
```

Then add it as a sub-issue of the epic using the GitHub UI or API. Set each sub-issue's project fields:
- Item Type = Task (`ae8e6519`)
- Release = same as parent epic
- Status = Backlog (`f75ad846`)

### Set dependencies

If sub-issues have ordering dependencies, add blocked-by relationships:

```bash
gh api graphql -f query='mutation { addBlockedBy(input: {
  issueId: "<blocked-issue-node-id>"
  blockingIssueId: "<blocking-issue-node-id>"
}) { issue { number } blockingIssue { number } } }'
```

This returns a "already taken" error if the relationship exists — treat as a no-op.

## Phase 3: Update the roadmap

Update the GitHub Project board:

1. Set the epic's Status to **Active** or **In Progress**
2. If a previous epic is now complete, set its Status to **Done**

If `todo/0-ROADMAP.md` exists locally, update it too — but the GitHub Project is the source of truth.

## Phase 4: Verify completeness

Review the epic and all sub-issues you created. Check that:

1. **The epic body** has substantive "What already exists" and "Design decisions" sections — not placeholders
2. **Each sub-issue** has Gap, Deliverables, Key Files, and Tests sections with enough detail that an implementer reading only the issue + epic can start coding without additional research
3. **Dependencies** are set between sub-issues where ordering matters
4. **No cross-cutting context is missing** — if a design decision affects multiple sub-issues, it must be in the epic body, not just one sub-issue

The GitHub issues are the durable artifacts. Everything needed for implementation must be there.

## Output

When complete, report:
- Epic issue URL
- List of sub-issue URLs with titles
- Dependencies between sub-issues
- Any design questions or decisions that need the user's input before execution begins

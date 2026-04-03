---
name: epic-plan
description: Plan and break down an epic from the Protean roadmap into GitHub Issues with proper project board fields, dependencies, and a plan file. Use this skill whenever the user mentions planning an epic, breaking down an epic, starting a new epic, or refers to a specific epic by number or name from the roadmap (e.g., "let's plan 1.10", "break down the IR materialization epic", "start the next epic"). Also trigger when the user says "what's next on the roadmap" and the answer involves planning work.
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

This is the most important step. Read the relevant source code, tests, and any prior plan files to understand:

- What already exists that the epic builds on
- What patterns the codebase uses that the new code should follow
- What the boundaries of change are — which files, which modules
- What tests exist and what test patterns to follow

Don't rush this. A shallow understanding here leads to sub-issues that are either too vague or incorrectly scoped. Read actual source files, not just directory listings.

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

Add the `epic` label and flesh out the body:

```bash
gh issue edit <number> -R proteanhq/protean --add-label "epic" --body "$(cat <<'EOF'
## Outcome
What this epic delivers when complete.

## Why
Why this matters — the motivation, constraint, or stakeholder need.

## Success criteria
- [ ] Criterion 1
- [ ] Criterion 2

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

For each sub-issue, create a GitHub Issue and link it as a sub-issue of the epic:

```bash
gh issue create -R proteanhq/protean \
  --title "Sub-issue title" \
  --body "Description of what to implement, including test expectations"
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

## Phase 4: Write a plan file

Create a plan file at `.claude/plans/<descriptive-name>.md` that serves as the implementation reference. Include:

- Epic context and motivation
- Sub-issue list with brief descriptions
- Key design decisions made during the deep-dive
- Architecture notes — what patterns to follow, what to watch out for
- Dependency order for implementation

This plan file is what you'll reference during execution. Make it genuinely useful, not just a copy of the issue descriptions.

## Output

When complete, report:
- Epic issue URL
- List of sub-issue URLs with titles
- Dependencies between sub-issues
- Plan file path
- Any design questions or decisions that need the user's input before execution begins

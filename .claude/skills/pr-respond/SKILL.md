---
name: pr-respond
description: Wait for review comments on a PR, address them, push fixes, reply to each comment, and resolve threads. Use after creating a PR when you want to handle Copilot or human review feedback automatically. Trigger when the user says "wait for reviews", "address review comments", "handle PR feedback", "respond to copilot", or "review comments on the PR". Also trigger when the user says "listen for comments" or "watch the PR".
argument-hint: "[PR-number]"
---

# Respond to PR Review Comments

Poll a PR for review comments, address the valid ones, push fixes, reply to each comment explaining what was done, and resolve the threads. Uses `gh api` for all GitHub interactions — no MCP, no attribution.

## Identify the PR

If `$ARGUMENTS` contains a PR number, use it. Otherwise, find the current branch's PR:

```bash
gh pr view --json number,url -R proteanhq/protean
```

## Poll for review comments

Check for comments, waiting up to 10 minutes. Copilot reviews typically arrive within 2-5 minutes.

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments --jq 'length'
```

If zero comments, wait 60 seconds and check again. Repeat up to 10 times (10 minutes total). If no comments arrive after 10 minutes, report that and stop.

Once comments arrive, fetch them all:

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments --jq '.[] | {id, path, body, line, side, in_reply_to_id}'
```

## Triage each comment

For each top-level comment (where `in_reply_to_id` is null), decide:

- **Agree and fix** — the comment identifies a real issue. Fix the code.
- **Disagree** — the comment is wrong, based on a misunderstanding, or suggests something that conflicts with project conventions. Prepare a reply explaining why.
- **Not applicable** — the comment points to something outside the PR's scope or already addressed.

Read the file and line referenced by each comment to understand the full context before deciding. Don't blindly accept suggestions — Copilot often misses project-specific conventions (like `todo/` being gitignored but present locally, or `settings.local.json` providing wider permissions).

## Fix the code

For comments you agree with, make the code changes. Batch all fixes into a single commit:

```bash
git add <fixed files>
git commit -m "Address review feedback on PR #<NUMBER>"
git push
```

## Reply to each comment

For every comment, post a reply using the REST API. This posts as the authenticated `gh` user (you), with no AI attribution:

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments \
  -f body="Fixed — adjusted the regex to allow --force-with-lease while still blocking plain --force." \
  -F in_reply_to=<COMMENT_ID>
```

Reply guidelines:
- **For fixes**: briefly state what was changed. "Fixed — [one sentence]."
- **For disagreements**: explain the reasoning concisely. Don't be defensive — just state the facts.
- **For not-applicable**: acknowledge and explain why it's out of scope or already handled.

Keep replies short. One to two sentences is ideal.

## Resolve threads

After replying, resolve each thread using the GraphQL API. First, get the thread IDs:

```bash
gh api graphql -f query='{ repository(owner: "proteanhq", name: "protean") {
  pullRequest(number: <PR_NUMBER>) {
    reviewThreads(first: 50) {
      nodes { id isResolved comments(first: 1) { nodes { id databaseId } } }
    }
  }
} }'
```

Match each thread to its comment by `databaseId`, then resolve:

```bash
gh api graphql -f query='mutation { resolveReviewThread(input: { threadId: "<THREAD_ID>" }) { thread { isResolved } } }'
```

## Report

When done, summarize:

```
PR #867 — 10 review comments processed

Fixed (7):
  - block-dangerous-git.sh: allow --force-with-lease
  - stop-changelog-reminder.sh: redirect to stderr
  - settings.json: guard osascript for non-macOS
  - test-impact/SKILL.md: collect tests/ changes
  - test-impact/SKILL.md: fix field/ and port/ dir names
  - epic-status/SKILL.md: genericize memory path
  - release-check/SKILL.md: use $ARGUMENTS not $1

Dismissed (3):
  - settings.json permissions: intentionally narrow (settings.local.json has wider set)
  - todo/ doesn't exist: it does, just gitignored
  - release-check todo/: same as above

All threads replied to and resolved.
```

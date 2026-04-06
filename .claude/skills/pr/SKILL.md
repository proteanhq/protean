---
name: pr
description: Create a pull request for the current branch following Protean's conventions — changelog fragment, breaking change check, proper PR description, and issue linkage. Use this skill whenever the user says "create a PR", "open a pull request", "submit this for review", "push and create PR", or is wrapping up a piece of work and needs to get it reviewed. Also trigger when the user says "we're done with this issue" or "ship it" — those are PR signals even without the word "pull request".
argument-hint: "[#issue-number]"
---

# Create a Pull Request

Package up the current branch's work into a well-formed PR that follows the project's conventions. The goal is a PR that's ready for review — no missing changelog fragment, no unaddressed breaking changes, no vague descriptions.

## Step 1: Understand what changed

Run these to build a complete picture:

```bash
git status
git diff main...HEAD
git log main..HEAD --oneline
```

Read the diffs carefully. You need to understand the changes well enough to write a meaningful summary and detect breaking changes.

## Step 2: Verify changelog fragment

Check that a `changes/<issue-number>.<category>.md` fragment exists for this PR's issue. If missing, create one — a 1-2 line user-facing description of the change. Category is one of: `added`, `changed`, `deprecated`, `removed`, `fixed`, `security`. Do NOT edit `CHANGELOG.md` directly.

## Step 3: Check for breaking changes

Scan the diff for anything that could break existing usage. The project uses a three-tier classification:

**Tier 1 (surface):** Renamed class, moved import path, changed function signature. Mitigation: keep the old API as a deprecated wrapper that delegates to the new one.

**Tier 2 (behavioral):** Same signature but different behavior. Mitigation: put the new behavior behind a config flag, defaulting to old behavior.

**Tier 3 (structural):** Changed persistence format, event schema, serialization. Mitigation: version the schema, provide migration steps.

If you find a breaking change that isn't mitigated, flag it to the user before creating the PR. Don't silently proceed — unmitigated breaks are the most common reason PRs get sent back.

## Step 4: Push and create the PR

Push the branch if it hasn't been pushed yet:

```bash
git push -u origin HEAD
```

If `$ARGUMENTS` contains an issue number (like `#123` or just `123`), use it for the "Closes" reference. Otherwise, check the branch name — it often contains an issue number.

Create the PR:

```bash
gh pr create -R proteanhq/protean --title "the title" --body "$(cat <<'EOF'
## Summary
- First key change
- Second key change

## Test plan
- [ ] Core tests pass (`protean test`)
- [ ] Relevant adapter tests pass (if applicable)

Closes #N

EOF
)"
```

**Title guidelines:**
- Under 70 characters
- Start with a verb: "Add", "Fix", "Update", "Remove", "Refactor"
- Describe the what, not the how

**Body guidelines:**
- Summary should be 1-3 bullet points a reviewer can scan in 10 seconds
- Test plan should be specific to what changed — don't just copy a generic checklist
- Include "Closes #N" if there's a related issue

## Step 5: Report the result

Print the PR URL so the user can click through to review it. That's it — never merge, approve, or modify the PR after creation. The user handles review and merge.

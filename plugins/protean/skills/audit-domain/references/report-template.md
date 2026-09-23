# Audit Report Template

Use this template when presenting audit findings to the user.

## Template

```markdown
# Domain Audit Report

**Scanned**: [date]
**Files**: [N] domain files, [N] test files
**Aggregates**: [list]
**Handlers**: [list]

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | N |
| HIGH     | N |
| MEDIUM   | N |
| LOW      | N |
| **Total** | **N** |

## Findings

### CRITICAL

#### C1. [Category name] — `path/to/file.py:line`

**What**: [One-sentence description of what was found]

**Why it matters**: [One-sentence explanation of the risk]

**Fix**: [One-sentence suggestion] — see [skill link]

```python
# Current code (problematic)
...

# Suggested fix
...
```

---

### HIGH

#### H1. [Category name] — `path/to/file.py:line`

...

### MEDIUM

...

### LOW

...

---

## Recommended Refactoring Order

Based on impact and dependency between fixes:

1. **[Fix C1 first]** — [why this is most urgent]
2. **[Fix H1 next]** — [why this follows]
3. **[Fix M1]** — [can be done independently]
4. ...

## Health Score

| Area | Score | Notes |
|------|-------|-------|
| Aggregate design | X/10 | [brief note] |
| Handler hygiene | X/10 | [brief note] |
| Event-driven architecture | X/10 | [brief note] |
| Validation placement | X/10 | [brief note] |
| Test quality | X/10 | [brief note] |
| **Overall** | **X/10** | |
```

## Scoring Guide

| Score | Meaning |
|-------|---------|
| 9-10 | Exemplary — follows Protean patterns closely |
| 7-8 | Good — minor issues, easy to fix |
| 5-6 | Fair — several anti-patterns, refactoring recommended |
| 3-4 | Poor — fundamental patterns violated, significant refactoring needed |
| 1-2 | Critical — major redesign likely needed |

## Tips for Presenting Findings

1. **Lead with the most impactful finding** — don't bury critical issues
2. **Show code, not just descriptions** — a 3-line code snippet communicates faster than a paragraph
3. **Group related findings** — if a handler has 3 issues, present them together
4. **Be specific about locations** — always include file path and line number
5. **Suggest the refactoring order** — don't just list problems, show the path forward

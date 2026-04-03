---
name: check
description: Run all code quality checks on the Protean codebase — domain validation, linting, formatting, and type checking. Use this skill whenever the user says "check the code", "run checks", "lint", "validate", "run quality checks", or wants to verify code health before a PR or commit. Also trigger when the user asks about code quality, formatting issues, type errors, or domain validation problems — even if they phrase it as "is the code clean?" or "anything wrong with the codebase?".
argument-hint: "[--fix]"
---

# Run All Quality Checks

Run the full quality pipeline across the Protean codebase. Each check catches a different class of problem, so run them all in sequence — a file that passes linting might still have type errors, and code that type-checks fine might violate domain design rules.

## Step 1: Domain validation

```bash
uv run protean check
```

This is Protean's own domain linter. It checks for DDD-level design issues — things like missing command handlers, circular cluster dependencies, orphaned elements, and invariant violations. These are problems that ruff and mypy can't catch because they require understanding the domain model's structure.

If this fails, read the diagnostics carefully. They point to specific domain elements and explain what's wrong.

## Step 2: Lint with ruff

```bash
uv run ruff check src/ tests/
```

If there are violations, many are auto-fixable:

```bash
uv run ruff check --fix src/ tests/
```

Then re-run the check to see if anything remains that needs manual attention.

## Step 3: Format with ruff

```bash
uv run ruff format --check src/ tests/
```

If files need formatting:

```bash
uv run ruff format src/ tests/
```

This is a no-judgment step — formatting is mechanical. Just apply it.

## Step 4: Type check with mypy

```bash
uv run mypy src/protean
```

Type errors usually require reading the source to understand the intended types. Common fixes include adding type annotations, adjusting return types, or fixing actual logic bugs where the wrong type flows through.

## Handling failures

When any step fails, fix the code to satisfy the checker — not the other way around. Weakening lint rules, adding type ignores, or disabling checks is the wrong response. The rules exist because the project chose them deliberately. If a rule seems wrong for a specific case, flag it to the user rather than suppressing it.

For `$ARGUMENTS`:
- If the user passes `--fix`, apply auto-fixes aggressively (ruff check --fix, ruff format) without asking.
- Without `--fix`, report what's wrong and propose fixes, but let the user decide.

## Reporting

After all four steps complete, summarize concisely:

```
Domain validation: passed
Ruff lint: passed (3 auto-fixed)
Ruff format: passed
Mypy: 2 errors in src/protean/core/aggregate.py
```

Only expand on steps that had issues.

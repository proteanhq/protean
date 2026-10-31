---
applyTo: "**/*.py"
---

# Python source review rules

## Imports

Imports belong at module top. Flag a function-local import unless it is one of:
an optional adapter dependency (so `import protean` works without the extra); a
monkeypatch seam that must re-read the symbol at call time; lazy CLI startup for a
heavy subsystem; a PEP-562 lazy export; a real circular-import breaker; or a
dynamically loaded domain module.

## Comments and docstrings

- Flag a comment or docstring that asserts an invariant ("X is always None here")
  the code does not enforce.
- Flag a hardcoded count ("seven options..."). It goes stale. State the rule and
  where the data comes from.
- Flag a docstring that walks through how the code works. A docstring states the
  contract a caller relies on: what the code does, returns, raises or changes.
- Flag added source line-number references, version history, commented-out code,
  and "this fixes the bug" phrasing.
- Flag an issue or PR number token, except in `TODO(#NNN): reason` or in a
  regression test's docstring that states the behaviour in words first. An issue
  in another repo uses the full name (`owner/repo#NNN`).

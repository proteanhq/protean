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
- Flag added source line-number references, issue or PR number tokens, and "this
  fixes the bug" phrasing.

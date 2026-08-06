# Copilot review instructions for Protean

Protean is an opinionated, domain-driven Python framework (DDD, CQRS, event
sourcing), Python 3.11+, type-hinted throughout. Review for correctness, silent
failures, test integrity, and fit with the framework's established patterns.
Prefer a few high-signal comments over many minor ones, and match the surrounding
code's style.

## Correctness and silent failures

- Flag a guard that checks truthiness before type. `if not config: return` ahead of
  an `isinstance` check lets `False`, `0`, and `""` through silently while rejecting
  a valid `True`. The order should be: absence (`"key" not in config`), then type,
  then emptiness.
- Flag `except` blocks that swallow an error, fall back to a default that hides a
  failure, or turn a hard error into a quiet wrong value. An error that cannot be
  handled should surface, not be masked.
- When two layers both handle an "unset" value, flag a lower layer that resolves
  "unset" to a config-time default the caller's own value should have won. Decide
  what "unset" means at each layer, and test the empty shapes (`None`, `""`, missing
  key) against a non-default configured value.
- Flag list-typed parameters that back security or correctness (redaction lists,
  allowlists, deny-lists) when they replace their defaults instead of unioning with
  them. An operator must not be able to disable a core protection by passing a list.

## Pipelines and ordering

- When a stage is inserted into an existing chain (structlog processors, middleware,
  filters), flag wrong ordering. Sanitization and redaction run last, so a
  caller-supplied stage cannot push sensitive data past them. Walk the chain and
  confirm the new stage's position relative to its neighbours.

## Tests

- Flag a new log or metric emission (security, access, perf) that ships without both
  a positive test (it fires when expected) and a negative test (it does not fire
  outside its stated scope). Intent like "boundary-only" or "Nth-failure-only"
  drifts silently without the negative test.
- Flag a timing test that sleeps just under a deadline and asserts on the outcome; it
  will flake under load. Read the recorded schedule instead of racing it.
- On a shared `MagicMock` helper, flag overriding one method with `return_value` when
  the helper set `side_effect`. The override no-ops and the line it was written for
  stays uncovered. Set `side_effect = None` first.
- A test that builds its own `Domain(name=...)` instead of the autouse fixture must
  carry `@pytest.mark.no_test_domain`.
- Any test needing an external service (PostgreSQL, Redis, Elasticsearch, MessageDB)
  must carry the matching pytest marker. Test selection is marker-based, not
  path-based.

## Scaffolds, config, and examples

- Flag a config snippet, `domain.toml`, or generated scaffold that no test executes.
  A config example is correct only if it runs; a "spelled right, nobody reads it"
  key survives releases. Verify by loading it, not by matching its text.
- Flag a new `domain.toml` key wired into only one bootstrap path. A key must be
  exercised through every entry point (programmatic init, server worker, shell,
  middleware).
- When an example fails, flag a change that edits the example to match the broken
  behavior instead of fixing the code. The tell is a stranded orphan: an env var
  nothing reads, a config key nothing consumes, a flag nothing checks.

## Imports

- Imports belong at module top. Flag a function-local import unless it has one of
  these verified reasons: an optional adapter dependency kept local so base import
  works without the extra installed; a monkeypatch test seam that must re-read the
  symbol at call time; deliberate lazy CLI startup for a heavy subsystem; a PEP-562
  lazy export; a genuine circular-import breaker; or a dynamically loaded domain
  module.

## Breaking changes

- Flag any rename, move, removal, or behavior change to public `protean.*` API that
  ships without a deprecation path. A surface break introduces the new API alongside
  the old with a `DeprecationWarning` (via `protean._deprecation`, which validates
  the removal version). A behavioral break goes behind a config flag defaulting to
  old behavior. A removal is never in the same release as its deprecation.
- Flag a changelog fragment marked breaking, or any `.changed` / `.removed` fragment,
  that has no matching entry in the migration guide. A behavior change is not shipped
  until the guide tells the upgrader what to do.

## Comments and docstrings

- Flag a comment or docstring that asserts an invariant ("X is always None here")
  the code does not enforce. Verify it against the model, migration, or validator, or
  drop it.
- Flag a hardcoded count in a comment or docstring ("seven options..."). It goes
  stale. State the rule and where the data comes from, not how many there were.
- Flag added source line-number references, issue or PR number tokens, and
  "this fixes the bug" phrasing in comments and docstrings.

## Editing existing files

- Flag a scripted single replacement (`replace(old, new, 1)`) where the snippet
  occurs more than once; it can edit the wrong occurrence. Anchor on something unique.
- For an edit to a long document, flag a splice whose anchor is slightly off. It can
  delete everything up to the next match while the result still reads fine. Compare
  the headings before and after.

## What not to flag

- Do not suggest new third-party dependencies or new abstractions. Protean favors
  fewer, coherent components over feature breadth.
- Do not flag the framework's deliberate DDD choices as defects: a single surrogate
  identity per aggregate (no composite keys), validation in the domain layer rather
  than the database, and hard deletion as an infrastructure escape hatch.
- Do not restate what a diff does. Comment only where there is a concrete risk or a
  clear improvement.

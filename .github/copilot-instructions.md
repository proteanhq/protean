# Copilot review instructions for Protean

Protean is an opinionated, domain-driven Python framework (DDD, CQRS, event
sourcing), Python 3.11+, type-hinted throughout. Review for correctness, silent
failures, test integrity, and fit with the framework's patterns. Prefer a few
high-signal comments over many minor ones. Rules for tests, Python source, and
config or examples live in `.github/instructions/`.

## Correctness and silent failures

- Flag a guard that checks truthiness before type. `if not config: return` ahead
  of an `isinstance` check lets `False`, `0` and `""` through while rejecting
  `True`. Check absence (`"key" not in config`), then type, then emptiness.
- Flag an `except` that swallows an error, falls back to a default that hides a
  failure, or turns a hard error into a quiet wrong value.
- Flag an `except` or `contextlib.suppress` whose comment names a cause the call
  does not raise for. Redis `XRANGE`, `XLEN` and `LLEN` return `[]` or `0` for a
  missing key, so a `ResponseError` handler commented "the stream does not exist"
  only catches real failures such as `WRONGTYPE` or `NOPERM`.
- Flag a log message that formats a whole config table, such as the `repr()` of
  `[server]`. Other keys can hold credentials, and the redaction filter only reads
  structured log fields. Log the key and the value's type, and the value only when
  it cannot hold a credential.
- When two layers both handle "unset", flag a lower layer that resolves it to a
  config-time default the caller's own value should have won.
- Flag a list parameter that backs security or correctness (redaction lists,
  allowlists, deny-lists) and replaces its defaults instead of unioning with them.
- When a stage is inserted into a chain (structlog processors, middleware,
  filters), check its position. Sanitization and redaction run last.

## Breaking changes

- Flag a rename, move, removal, or behavior change to public `protean.*` API with
  no deprecation path. A surface break keeps the old API with a
  `DeprecationWarning` from `protean._deprecation`. A behavioral break goes behind
  a config flag that defaults to the old behavior. A removal never ships in the
  same release as its deprecation.
- Flag a `.changed` or `.removed` changelog fragment, or one marked breaking, with
  no matching entry in the migration guide.

## What not to flag

- Do not suggest new third-party dependencies or new abstractions.
- Do not flag deliberate DDD choices: one surrogate identity per aggregate (no
  composite keys), validation in the domain layer, and hard deletion as an
  infrastructure escape hatch.
- Do not restate what a diff does. Comment only on a concrete risk or a clear
  improvement.

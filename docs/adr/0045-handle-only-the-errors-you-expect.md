# ADR-0045: Handle only the errors you expect

**Status:** Accepted

**Date:** October 2026

## Context

Several paths in `src/protean` caught every exception and dropped it with `pass`
or `continue`. Each one was written for a single known case, but the bare
`except Exception` also caught every other error. A real fault then looked the
same as the known case, and nobody saw it. Three examples:

- `Domain.check()` dropped any failure from `self.to_ir()`. A broken IR builder
  produced a check result with no IR diagnostics and no sign that anything had
  failed.
- The IR diff caught `Exception` around a version comparison. The one failure
  it expected was a `TypeError` from comparing a number segment with a text
  segment. It also hid an `AttributeError` when the removal version was
  written as a number, such as `removal: 0.18`, and classed the removal as
  premature.
- The CloudEvents `source` on a `Message` caught every error. The catch was
  there for one case: falling back when no domain context was active. `source`
  also caught the error from a domain config whose `get()` raised, and fell
  back in the same way.

The ruff 0.16 upgrade turned on three rules that find these sites: `BLE001`
(`except Exception` or a bare `except`), `S110` (an `except` whose only
statement is `pass`) and `S112` (the same with `continue`). The maintainers
listed the files that failed these rules under `per-file-ignores` in
`pyproject.toml`. In two follow-up issues, they fix those files and remove the
entries.

Related issues: narrow the blind `except` blocks in `src`
([#1715](https://github.com/proteanhq/protean/issues/1715)), and fix the
swallowed errors in `src`
([#1716](https://github.com/proteanhq/protean/issues/1716))

## Decision

Every `except` in `src/protean` handles an error in one of three ways.

1. **The error is expected and harmless.** Catch the specific exception class.
   Keep the `try` block, or the `contextlib.suppress` block, to the one call
   that raises it. For example, closing a health-check connection ignores
   `OSError` from a peer that already disconnected.
2. **The error means a step was skipped, and the caller can continue.** Catch
   the specific exception. Log it. When the user has nothing to do about the
   error, log it at debug level. A stream that disappeared during an
   observatory scrape is one such case. When the user would want to know about
   the error, log it at warning level, as for a failed stale-consumer cleanup
   at subscription startup.
3. **The site is a catch-all point.** One failing handler, endpoint or status
   probe must not stop the others. Keep `except Exception`. Give a short reason
   on the same line or the line above. Log the error, or pass it on as a
   finding, a stored result or a returned message. A catch-all point must not
   drop the error. Ruff's `BLE001` does not flag a block that logs the
   traceback or re-raises. In such a block, write the reason as a plain
   comment. Any other catch-all needs `# noqa: BLE001 - <reason>`. A `noqa` on
   a block that ruff does not flag fails `RUF100`.

Two cases do not need an `except` at all:

- When a condition can be checked before the call, check it. To read the domain
  config, code calls `has_domain_context()` first. It does not catch the
  failure of reading the config without a domain context.
- When an empty result is a normal outcome, ask for a default. Use
  `next(iterator, None)` and test the result with `is not None`. Ruff's
  `SIM105` suggests `contextlib.suppress(StopIteration)` for a `try`/`except
  StopIteration: pass` block. That form still treats "no match" as an error. It
  also hides a `StopIteration` raised by any later line in the block. For a
  dictionary key that may be missing, use `dict.get()`.

`BLE001`, `S110` and `S112` stay on for `src/`. No new `per-file-ignores` entry
or project-wide `ignore` entry is added for them. `tests/` and `docs_src/` keep
their exemptions: a test catches `Exception` to record a failure for an
assertion, and an example on a page catches it to stay short.

## Consequences

Each path was written for one case. An error outside that case now reaches the
caller or the log. When user configuration or framework code has a bug, the
error appears at the point of the bug.

Narrowing these catch-alls is a behavior change. Before, when some other error
hit one of these paths, the calling code got the fallback value in silence. Now
the calling code gets the exception. Under the breaking change policy
(ADR-0004), a behavioral break normally goes behind a flag. These changes ship
without a flag, because the old behavior was the bug. A flag set to the old
default would keep hiding the errors that the changes exist to show. The 0.18
migration guide lists each path, the case it still handles, and what happens in
that case.

Ruff flags a new blind or silent `except`. Ruff cannot tell whether a `# noqa:
BLE001` site is a genuine catch-all point. The reviewer makes that judgment by
checking the reason on the `noqa` line.

Each logging site needs a test that checks the log record. Each narrowed
`except` needs a test. The test raises the exception that the `except` now
catches. That adds test code for paths that had none.

## Alternatives Considered

**Keep the catch-alls and log everything at debug level.** Every error would
leave a trace, but only for someone running with debug logging. The caller
would still get the fallback value for a real fault.

**Narrow the sites behind a configuration flag.** This is the usual path for a
behavioral break under the breaking change policy (ADR-0004). It was not chosen
because each fallback was written for one known case. Keeping the old default
would keep the bug.

**Leave the files under `per-file-ignores`.** Ruff would check new files. The
existing sites would stay as they were. Two of the examples above are real
faults that would stay hidden: the IR build and the version comparison.

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
- The CloudEvents `source` on a `Message` caught every error so it could fall
  back when no domain context was active. A domain config whose `get()` raised
  was handled the same way.

The ruff 0.16 upgrade turned on three rules that find these sites: `BLE001`
(`except Exception` or a bare `except`), `S110` (an `except` whose only
statement is `pass`) and `S112` (the same with `continue`). The files that
failed them were listed under `per-file-ignores` in `pyproject.toml`, and two
follow-up issues fix them and remove the entries.

Related: [#1715](https://github.com/proteanhq/protean/issues/1715),
[#1716](https://github.com/proteanhq/protean/issues/1716)

## Decision

Every `except` in `src/protean` handles an error in one of three ways.

1. **The error is expected and harmless.** Catch the specific exception class.
   Keep the `try` block, or the `contextlib.suppress` block, to the one call
   that raises it. For example, closing a health-check connection ignores
   `OSError` from a peer that already disconnected.
2. **The error means a step was skipped, and the caller can carry on.** Catch
   the specific exception and log it. Log at debug level when the user has
   nothing to do about it, such as a stream that disappeared during an
   observatory scrape. Log at warning level when the user would want to know,
   such as a failed stale-consumer cleanup at subscription startup.
3. **The site is a catch-all point.** One failing handler, endpoint or status
   probe must not stop the others. Keep `except Exception` and give a short
   reason on the same line or the line above. Log the error, or pass it on as
   a finding, a stored result or a returned message. A catch-all point must not
   drop the error. Ruff's `BLE001` does not flag a block that logs the
   traceback or re-raises, so the reason there is a plain comment. Any other
   catch-all needs `# noqa: BLE001 - <reason>`. A `noqa` on a block that ruff
   does not flag fails `RUF100`.

Two cases do not need an `except` at all:

- When a condition can be checked before the call, check it. Code that reads
  the domain config calls `has_domain_context()` first and does not catch the
  failure of reading without one.
- When an empty result is a normal outcome, ask for a default. Use
  `next(iterator, None)` and test the result with `is not None`. Ruff's `SIM105`
  suggests `contextlib.suppress(StopIteration)` for a `try`/`except
  StopIteration: pass` block, but that form still treats "no match" as an
  error, and it also hides a `StopIteration` raised by any later line in the
  block. For a dictionary key that may be missing, use `dict.get()`.

`BLE001`, `S110` and `S112` stay on for `src/`. No new `per-file-ignores` entry
or project-wide `ignore` entry is added for them. `tests/` and `docs_src/` keep
their exemptions: a test catches `Exception` to record a failure for an
assertion, and an example on a page catches it to stay short.

## Consequences

An error outside the case a path was written for now reaches the caller or the
log. A bug in user configuration or in framework code shows up where it
happens.

This is a behavior change. Code that hit one of these paths with some other
error used to get the fallback value in silence, and now gets the exception.
Under ADR-0004 a behavioral break normally goes behind a flag. These changes
ship without one, because the old behavior was the bug: a flag set to the old
default would keep hiding the errors the change exists to show. The 0.18
migration guide lists each path, the case it still handles, and what happens
in that case.

Ruff flags a new blind or silent `except`. It cannot tell whether a
`# noqa: BLE001` site is a genuine catch-all point, so that judgment stays with
the reviewer, and the reason on the `noqa` line is what the reviewer checks.

Each site that logs needs a test that checks the log record, and each narrowed
`except` needs a test that raises the exception it now catches. That adds test
code for paths that had none.

## Alternatives Considered

**Keep the catch-alls and log everything at debug level.** Every error would
leave a trace, but only for someone running with debug logging. The caller
would still get the fallback value for a real fault.

**Narrow the sites behind a configuration flag.** This is the usual path for a
behavioral break under ADR-0004. It was not chosen because each fallback was
written for one known case. Keeping the old default would keep the bug.

**Leave the files under `per-file-ignores`.** New files would be checked, and
the existing sites would stay as they were. The two examples above, the IR
build and the version comparison, are real faults that would stay hidden.

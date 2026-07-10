<!--
Protean is developed under a single-maintainer model. Please read CONTRIBUTING.md
before opening a pull request:
https://github.com/proteanhq/protean/blob/main/CONTRIBUTING.md
-->

## Before you open this PR

Protean is single-maintainer, and its coherence depends on changes fitting a
single design view. **Unsolicited non-trivial PRs without a linked, agreed-upon
issue may be closed unread** — this is not about code quality; see
[CONTRIBUTING.md](https://github.com/proteanhq/protean/blob/main/CONTRIBUTING.md).

Confirm one of the following (delete the other):

- [ ] This is a **small, obvious fix** — a typo, a docstring, a clearly correct one-line bug fix.
- [ ] This implements an issue a **maintainer has already agreed to**: closes #\_\_\_

## Summary

<!-- What does this change do, and why? If AI tooling helped, you are still the
author: you must understand the change and be able to explain every part of it. -->

## Checklist

- [ ] Tests added or updated, and the suite passes (`protean test`; `protean test -c FULL` for changes touching adapters)
- [ ] `ruff check` and `ruff format --check` are clean
- [ ] Changelog fragment added under `changes/` as `<issue>.<category>.md`
- [ ] Docs updated for any user-facing change (or N/A)
- [ ] Breaking changes carry a deprecation path (see CONTRIBUTING.md and ADR-0004)

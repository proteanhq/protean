# Contributing to Protean

Thank you for your interest in Protean. This document explains how the project
is developed and the ways you can help.

## How Protean is developed

Protean is designed and maintained by a single maintainer, with development
driven from a single, coherent view of the whole framework. This is a
deliberate choice, in the tradition of small, focused, long-lived
infrastructure projects: it keeps the design consistent and the correctness bar
high.

Practically, this means most of the code is written by the maintainer, and the
roadmap is set by the maintainer. It does **not** mean the project is closed to
you. The contributions below are genuinely valuable and actively wanted.

## The most valuable ways to contribute

1. **Report bugs.** A clear, reproducible bug report is the single most useful
   thing you can send. Real-world failure cases are how a framework earns its
   correctness, and bug reports are answered as a matter of priority.
2. **Share use cases and design feedback.** Tell us where Protean fits your
   domain awkwardly, where an abstraction leaks, or where the docs mislead you.
   Open a [Discussion](https://github.com/proteanhq/protean/discussions) or an
   [issue](https://github.com/proteanhq/protean/issues).
3. **Build adapters.** Databases, brokers, event stores, and caches plug in
   through a public port contract and are verified by a conformance suite.
   Adapters live in their own packages, owned by their authors, rather than in
   the core. See
   [Building Adapters](https://docs.proteanhq.com/community/contributing/adapters/).
4. **Improve documentation.** Corrections and clarifications are welcome, and
   small doc fixes can go straight to a pull request.

## Code contributions

- **Small, obvious fixes** (typos, docstrings, a clearly correct one-line bug
  fix) are welcome directly as pull requests.
- **Anything non-trivial**, such as a new feature, a behavioral change, or a
  refactor, should start with an issue so we can agree on the approach before
  you invest time. Unsolicited large pull requests may not be merged, however
  good the code; the cost of a change is in its design fit and long-term
  maintenance, not the diff.
- **AI-assisted contributions** are held to the same bar, and the bar is
  understanding, not output. A PR must be tied to an agreed issue, and you must
  be able to explain every part of the change and why it fits Protean's design.
  Pull requests that read as unreviewed AI output — no linked issue, generated
  boilerplate, or changes the author cannot speak to — will be closed. Judgment
  about design fit is the actual work here, and it cannot be delegated to a tool.

This is not a reflection on your work. It is how the project keeps a single,
coherent design under one maintainer. If that trade-off does not suit you, the
Apache license guarantees you can always fork.

## Licensing

Protean is licensed under the [Apache License 2.0](LICENSE). By submitting a
contribution, you agree that it is licensed under the same terms (Apache-2.0,
inbound equals outbound), as described in section 5 of the license.

**Licensing commitment.** The Protean framework core is, and will remain,
available under the Apache License 2.0. This is a permanent commitment: the
core will not be relicensed to a proprietary or source-available license.

## Setting up locally

If you are fixing a bug, adding a discussed change, or building an adapter, the
[local setup guide](https://docs.proteanhq.com/community/contributing/setup/)
walks through getting Protean running for development.

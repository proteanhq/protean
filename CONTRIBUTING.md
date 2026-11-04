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
   [Building Adapters](https://docs.proteanhq.com/reference/adapters/building-adapters/).
4. **Improve documentation.** Corrections and clarifications are welcome. Open
   an [issue](https://github.com/proteanhq/protean/issues) that names the page
   and the fix.

## Code contributions

Only collaborators can open pull requests on this repository. Anyone can read
the code, open issues and Discussions, and comment on pull requests.

To propose a code or documentation change, open an issue. Describe the problem,
the change you have in mind, and why it fits Protean's design. The maintainer
then makes the change. A contributor who has worked through several issues with
the maintainer may be invited to become a collaborator.

AI tools can now write a pull request in minutes, but reviewing one still takes
the maintainer hours. The review decides whether a change fits the design, and
that judgement needs someone who understands the framework. Starting from an
issue keeps review time for contributors who have that understanding.

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

If you are a collaborator, are building an adapter, or want to run Protean from
source, the [local setup guide](https://docs.proteanhq.com/community/contributing/setup/)
walks through getting Protean running for development.

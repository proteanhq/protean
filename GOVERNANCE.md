# Governance

Protean is a single-maintainer project. This document describes how decisions are
made. For how to contribute, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Decision-making

Design and direction rest with the maintainer,
[Subhash Bhushan](https://github.com/subhashb). This is deliberate. Protean is an
opinionated framework, and its value comes from a single, coherent design view held
to a high correctness bar. In practice:

- The roadmap, the public API, and what gets accepted are the maintainer's call.
- Bug reports, reproductions, use-case feedback, adapters, and documentation fixes
  are the most valuable contributions and are actively wanted.
- Non-trivial code changes start from an issue and an agreed approach before any
  code. A good diff with no design fit is still a maintenance cost, and may be
  declined on that basis alone.

There is no committee and no voting. Disagreement is welcome as discussion; the
maintainer decides.

## Releases

Releases are cut by the maintainer from `main`. Versioning and the breaking-change
policy follow [ADR-0004](docs/adr/0004-release-workflow-and-breaking-change-policy.md).
There is no fixed calendar; a release ships when the work is ready.

## Licensing

Protean's core is licensed under the Apache License 2.0, inbound equals outbound.
The core will remain Apache-2.0 and will not be relicensed to a proprietary or
source-available license. This is a permanent commitment, stated in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Continuity

A single-maintainer project is a single point of failure, and the license is the
answer to that: anyone can fork at any time, for any reason. That right is the
guarantee behind the model.

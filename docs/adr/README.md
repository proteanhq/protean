# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the Protean framework.

## What are ADRs?

An Architecture Decision Record captures a single architectural decision along with its context
and consequences. ADRs are short documents (readable in 2-3 minutes) that record why we made
a particular choice at a particular time, so that future contributors can understand not just
what the system does, but why it does it that way.

The practice was introduced by Michael Nygard in his blog post
[Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

## Why Protean uses ADRs

Protean is an opinionated DDD framework with a growing IR-based "domain compiler" architecture.
Many of our decisions involve trade-offs between DDD purity, developer ergonomics, and tooling
extensibility. Recording these decisions prevents re-litigating settled questions and helps new
contributors understand the reasoning behind the framework's design.

## Naming convention

ADRs are numbered sequentially with four-digit zero-padded prefixes and kebab-case titles:

```
NNNN-short-kebab-title.md
```

Examples:
- `0001-monotonic-integer-event-versioning.md`
- `0003-one-ir-document-per-bounded-context.md`

ADR-0000 is reserved for the guiding principles document. It is not a decision record itself
but a meta-document that captures the principles governing all Protean architectural decisions.

## Status lifecycle

Each ADR has one of the following statuses:

- **Proposed** — Under discussion, not yet committed to.
- **Accepted** — The decision has been made and is in effect.
- **Deprecated** — The decision is no longer relevant (technology changed, feature removed).
- **Superseded by ADR-XXXX** — Replaced by a newer decision.

Status changes are recorded by editing the ADR's Status field. The original ADR is never deleted;
it remains as historical context.

## Referencing ADRs

In code comments:

```python
# See ADR-0001 for why we use monotonic integers, not semver
```

In commit messages:

```
Implement event upcaster chain (ADR-0001)
```

In other ADRs, reference by number: "as established in ADR-0003."

## Template

See [TEMPLATE.md](TEMPLATE.md) for the ADR template.

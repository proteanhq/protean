# Versioning policy

This page states what a Protean version number promises you, so you can decide
how much attention an upgrade needs.

Read it before you assume strict semantic versioning. Protean does not use it,
and the difference matters when you plan upgrades.

---

## The contract

**Code that runs warning-free on 1.N runs unmodified on 1.N+1.**

That is the whole promise, and it is stated in terms of warnings rather than
version numbers on purpose. Protean tells you about every upcoming removal
ahead of time, through a `DeprecationWarning` and a `protean check` rule. If
you are not seeing any of those, the next minor version will not break you.

The corollary matters just as much: if you *are* seeing deprecation warnings and
you ignore them, a future minor will break you. The warnings are the mechanism,
not a courtesy.

## Enforce it in CI

Do not read release notes hoping to spot what applies to you. Make the contract
a test failure:

```toml
# pyproject.toml
[tool.pytest.ini_options]
filterwarnings = [
    "error::protean.exceptions.ProteanDeprecationWarning",
]
```

Now "will this upgrade break us?" is answered by running your test suite. A
green suite on 1.N means 1.N+1 is a version-number change and nothing else.

To find deprecated usage without running tests, use the CLI:

```shell
protean check
```

It reports every active deprecation in your domain, including ones your tests
do not happen to exercise.

---

## What each version position means

| Position | Example | What it may contain |
|----------|---------|---------------------|
| **Patch** | 1.2.0 → 1.2.1 | Bug fixes only. Never an API change. |
| **Minor** | 1.2 → 1.3 | New features. New deprecations. Behavior flags flipped after their warning period. Persistence and schema changes that ship with migrations. Never a removal that was not already deprecated for two minors. |
| **Major** | 1.x → 2.0 | A shift in what Protean claims to do. See below. |

### Removals

A removal happens only in a **pre-announced cleanup release** or at a major.
Before anything is removed it must have carried a `DeprecationWarning` and a
`protean check` rule for **at least two minor versions**. Deprecated in 1.3
means the earliest possible removal is 1.5.

### Majors are eras, not accumulated breakage

A major version does not mean "we saved up breaking changes." It means the
boundary of what the framework does has moved: a change in the security posture
(what Protean holds and protects for you), or a change in the concurrency and
deployment model. Those are shifts you need to think about rather than
mechanically patch.

A renamed parameter will never cost you a major upgrade. Nor will it be left
permanently wrong to avoid one.

---

## Why not strict semantic versioning

Strict SemVer says breaking changes only in majors. For a framework, that
produces one of two outcomes, and neither is good for you.

Either majors get burned on trivia, so the version number stops carrying
information: 4.0 might be a rearchitecture or a renamed keyword argument, and
you cannot tell which without reading the notes. Or, far more commonly, majors
become so expensive that nothing is ever corrected, and early mistakes calcify
into permanent API.

The deprecation-managed model splits the two questions SemVer runs together:

- **"Is this safe to upgrade?"** is answered continuously, by your own warning
  log, per release.
- **"Has this project changed shape?"** is answered by the major version.

You get a mechanical, checkable answer to the first question, and a meaningful
signal from the second.

The full reasoning is in
[ADR-0004](https://github.com/proteanhq/protean/blob/main/docs/adr/0004-release-workflow-and-breaking-change-policy.md).

---

## What the contract covers

The promise applies to the **Stable** tier of Protean's public surface: the
top-level `protean` exports, the element decorators and their options,
`protean.fields`, `protean.exceptions`, the public testing DSL, documented
`domain.toml` keys, and documented CLI commands and exit codes.

Alongside it sit a **Provisional** tier (usable and documented, may change in a
minor with a changelog notice) and an **Internal** tier (underscore-prefixed
names, `protean.core.*` internals, adapter implementation modules) which carries
no promise at all.

Two things worth knowing:

- **Documented guarantees are part of the API.** Weakening a guarantee in
  [Consistency & delivery guarantees](guarantees.md) is a breaking change even
  when no signature changes. A method that quietly stops being idempotent has
  broken the contract as surely as one that was renamed.
- **Internal names are not covered.** Reaching into `protean.core.*` internals
  or underscore-prefixed attributes may break in any release, including a patch.

---

## How breaking changes are handled

When a break is unavoidable, it is classified and mitigated by type:

| Type | What it looks like | How you find out |
|------|--------------------|------------------|
| **Surface** | A renamed class, a moved import, a changed signature | An immediate `ImportError` or `TypeError`, preceded by two minors of `DeprecationWarning` |
| **Behavioral** | Same signature, different behavior | A config flag, defaulting to the old behavior, then a warning minor, then the flip |
| **Structural** | Persistence format, event schema, serialization | A versioned schema and a shipped migration, plus upgrade notes |

Behavioral changes get the most ceremony because they are the most dangerous:
your code keeps running and produces different results. You always get a
release where the new behavior is opt-in, and a release where not having chosen
warns you, before any default moves.

There are two deliberate exceptions, both documented in ADR-0004: operational
defaults (timeouts, pool sizes, retry counts) may change in a minor with a
changelog note, and a silent correctness bug is fixed rather than preserved
behind a flag.

---

## Related reading

- [Consistency & delivery guarantees](guarantees.md): the behavioral contract per port and adapter.
- [Migration guides](migration/index.md): version-specific upgrade steps.
- [`protean check`](cli/check.md): find deprecated usage in your domain.

# Versioning policy

A Protean version number tells you how much attention an upgrade needs.

Read it before you assume strict semantic versioning. Protean does not use
strict semantic versioning. The difference matters when you plan upgrades.

---

## The contract

**Code that runs warning-free on 1.N runs unmodified on 1.N+1.**

That is the whole promise, and it is stated in terms of warnings rather than
version numbers on purpose. Protean tells you about every upcoming removal
ahead of time, through a `DeprecationWarning` and a `protean check` rule. If
you are not seeing any of those, the next minor version will not break you.

The reverse also holds. If you *are* seeing deprecation warnings and you ignore
them, a future minor version will break your code. The warnings are the
mechanism, not a courtesy.

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
| **Minor** | 1.2 → 1.3 | Where change lands: new features, new deprecations, behavior flags flipped after their warning release, schema changes with shipped migrations, and the removal of anything already deprecated. May break code that ignored its warnings. May not break code that had none. |
| **Major** | 1.x → 2.0 | A shift in what Protean claims to do. See below. |

### Removals

There is no fixed number of releases a deprecated API survives for. Instead,
**every deprecation names the version it will be removed in**, and says so in
the warning:

```
ProteanDeprecationWarning: old_method() is deprecated. Use new_method()
instead. Will be removed in v1.5.0.
```

One rule is fixed, and the contract depends on it:

> A removal is never in the same release as its deprecation.

So at least one released version always comes before a removal. That version
warns you and tells you which release to be ready for. We decide for each
deprecation how many more releases you get beyond that one. The number depends
on how widely the API is used, and no fixed number applies to all deprecations.

!!! warning "If you skip releases, run `protean check`"

    A version emits its warnings only when you actually run it. Going straight
    from 1.3 to 1.5 can miss the 1.4 release that warned you. `protean check`
    reads the declared removal versions and does not replay warnings. It can
    tell you what a later version will remove even if you never ran the release
    with the warning.

### How this compares to SQLAlchemy

SQLAlchemy also uses a "modified semantic versioning scheme". It follows the
same warning-driven upgrade path: an application that runs clean under the
deprecation warnings is ready for the next series. Protean uses per-version
warning classes for the same reason they do.

Both projects follow the same pattern. Patches change no API, breaking changes
arrive in minor versions, majors are kept for a categorical shift, and neither
project fixes a deprecation window.

Protean differs from SQLAlchemy in one way. SQLAlchemy allows "some risk of
non-backwards compatibility" in a minor even outside previously-deprecated
APIs. Protean does not: a minor may remove a deprecated API, but it may not
break code that was running warning-free. That is the whole point of the
contract at the top of this page.

### Majors are eras, not accumulated breakage

A major version does not mean "we saved up breaking changes." It means Protean
has changed what the framework does. Either the security posture (what Protean
holds and protects for you) changed, or the concurrency and deployment model
changed. Those are shifts you need to think about rather than mechanically
patch.

A renamed parameter will never cost you a major upgrade. Nor will it be left
permanently wrong to avoid one.

---

## Why not strict semantic versioning

Strict SemVer says breaking changes only in majors. For a framework, that
produces one of two outcomes, and neither is good for you.

Either the project spends majors on trivial changes, and the version number
stops carrying information. A 4.0 release might be a rearchitecture or a
renamed keyword argument, and you cannot tell which without reading the notes.
Or, far more commonly, majors become so expensive that nobody corrects
anything. Early mistakes then stay in the API permanently.

The deprecation-managed model separates two questions that SemVer answers with
one number:

- **"Is this safe to upgrade?"** is answered continuously, by your own warning
  log, per release.
- **"Has this project changed what it does?"** is answered by the major
  version.

You get a mechanical, checkable answer to the first question, and a major
version number that tells you something real for the second.

The full reasoning is in the decision record on the release workflow and
breaking-change policy
([ADR-0004](https://github.com/proteanhq/protean/blob/main/docs/adr/0004-release-workflow-and-breaking-change-policy.md)).

---

## What the contract covers

The promise applies to the **Stable** tier of Protean's public surface. [Stable
surface](stable-surface.md) lists exactly which imports, decorators, options,
config keys, and CLI commands are covered. It also lists which are
**Provisional** (usable and documented, may change in a minor with a changelog
notice), and which are **Internal** and carry no promise at all.

The promise also follows two rules:

- **Documented guarantees are part of the API**: Weakening a guarantee in
  [Consistency & delivery guarantees](guarantees.md) is a breaking change even
  when no signature changes. A method that quietly stops being idempotent
  breaks the contract. A renamed method breaks it in the same way.
- **Internal names are not covered**: Code that uses `protean.core.*` internals
  or underscore-prefixed attributes may break in any release, including a
  patch.

---

## How breaking changes are handled

When a break is unavoidable, it is classified and mitigated by type:

| Type | What it looks like | How you find out |
|------|--------------------|------------------|
| **Surface** | A renamed class, a moved import, a changed signature | An immediate `ImportError` or `TypeError`, preceded by a `DeprecationWarning` naming the removal version |
| **Behavioral** | Same signature, different behavior | A config flag, defaulting to the old behavior, then a warning minor, then the flip |
| **Structural** | Persistence format, event schema, serialization | A versioned schema and a shipped migration, plus upgrade notes |

Behavioral changes get the most warning steps because they are the most
dangerous: your code keeps running and produces different results. Before any
default changes, you always get a release where the new behavior is opt-in. You
then get a release that warns you if you have not chosen a behavior.

There are two deliberate exceptions, both documented in ADR-0004: operational
defaults (timeouts, pool sizes, retry counts) may change in a minor with a
changelog note, and a silent correctness bug is fixed rather than preserved
behind a flag.

---

## Related reading

- [Stable surface](stable-surface.md): What is covered by the contract, tier by tier.
- [Consistency & delivery guarantees](guarantees.md): The behavioral contract per port and adapter.
- [Migration guides](migration/index.md): Version-specific upgrade steps.
- [`protean check`](cli/check.md): Find deprecated usage in your domain.

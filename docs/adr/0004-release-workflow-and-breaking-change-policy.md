# ADR: Release Workflow and Breaking Change Policy

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-11 |
| **Last updated** | 2026-08-03 (post-1.0 policy: deprecation-managed 1.x, majors as eras) |
| **Author** | Subhash Bhushan |
| **Applies to** | Protean Framework |
| **Supersedes** | None |

---

## Context

Protean now has enough features and enough complexity that it is close to ready
for production use. Development velocity has increased significantly with
LLM-assisted workflows, compressing what used to be weeks of work into days.
However, the release process has not changed to match that speed. The
maintainers batch releases into large events that wait for an epic to finish.
Open-ended validation by early adopters often delays those releases further.

This decision came from one case: the first release (R1) had every planned
feature but stayed unshipped while the maintainers waited for developers to
validate it against their existing codebases. Meanwhile, work on the second
release (R2) was implicitly blocked until the first release (R1) shipped. This
tied development activities to release activities for no good reason.

Additionally, Protean has no systematic process for introducing breaking
changes. The maintainers hesitated to release partly because Protean had no
mechanism to tell users about API incompatibilities and to phase them in. Human
validation took the place of that missing system.

## Decision

We adopt a **continuous release model** with a **tiered breaking change policy** and **theme-based roadmap planning**, as described below.

---

## 1. Release Philosophy

### Core Principles

Releases are cheap, frequent, and decoupled from epic completion. The guiding question for cutting a release is not "have we completed the epic?" but **"is this release better than what's currently on PyPI?"** If yes, ship it.

Version numbers are coordination signals, not milestones. Minor version bumps
(0.15 → 0.16) can happen as often as meaningful work merges, weekly or even
more often during periods of high velocity.

Development and stabilization run in parallel. Completing an epic and shipping a release are independent activities. Work on the next set of features begins immediately, without waiting for the current release to go through validation.

### Release Cadence

There is no fixed schedule. Releases are cut when there is something worth
telling users about: a meaningful feature, a significant fix, or an important
behavioral improvement. The changelog is the release trigger: when the
unreleased section has substantive entries, it's time to ship.

### No Release Candidates

Protean does **not** use release candidates. Minor versions are cut directly
from `main` when the changelog has substantive entries. Patch releases on a
`release/0.X.x` branch fix any bugs discovered after a minor ships.

**Why drop them:** Release candidates (RCs) added extra steps and gave no
meaningful safety. In practice, the RC window delayed shipping. It also did not
produce the early-adopter feedback it was meant to generate. With frequent
minor releases, patch releases, and the three-tier breaking change policy
(deprecations, flags, versioned schemas), users already have several
protections and need no explicit pre-release phase.

When a future change seems large or risky enough to need pre-release
validation, split it across more incremental releases. Do not hold back the
regular releases to wait for feedback.

---

## 2. Breaking Change Taxonomy

Not all breaking changes carry the same risk or require the same mitigation. We classify them into three tiers, each with a distinct handling strategy.

### Tier 1: Surface-Level Breaks

**What they are:** Renamed classes, moved imports, changed method signatures, removed configuration keys. These produce immediate and obvious errors (`ImportError`, `TypeError`) on startup.

**Detection:** Loud. Users discover surface-level breaks instantly.

**Mitigate surface-level breaks with deprecation warnings.**

Introduce the new API alongside the old. The old API emits a `DeprecationWarning` with a specific removal version. The deprecated path delegates to the new implementation.

Do not hand-roll `warnings.warn(...)`. Use the reusable mechanism in
`protean._deprecation`, so every deprecation cites a removal version in the
same format. The mechanism also emits a per-version warning class
(`RemovedInProtean018Warning`, etc.), and downstream projects can filter on
that class precisely.

```python
from protean._deprecation import deprecated, warn_deprecated

# A whole callable that is going away — warns on every call, then delegates:
@deprecated(removal="0.17.0", alternative="Use new_method() instead.")
def old_method(self):
    return self.new_method()

# A single deprecated branch inside a still-supported function:
def run(self, debug=False):
    if debug:
        warn_deprecated("debug=True", removal="0.17.0", alternative="Use log_level.")
```

Each removal version maps internally to a `RemovedInProteanXXWarning` subclass
of the public `protean.exceptions.ProteanDeprecationWarning` (itself a
`DeprecationWarning`). The `@deprecated` decorator validates the version
eagerly, so a typo fails at import. The inline `warn_deprecated` helper never
raises on the live deprecated path. For an unregistered version, it falls back
to the base `ProteanDeprecationWarning` so a consumer's program keeps running.
When you promote the `ProteanDeprecationWarning` category to an error in CI
(see the guidance below), every Protean deprecation fails the run. Filter by
that category and never by module, because a decorated helper attributes its
warning to the *caller's* module.

**How long does a deprecation survive?** There is no fixed count. Each
deprecation declares its removal version in the `removal=` argument. The same
argument selects its warning class. That declared version is the commitment.
The invariant is fixed: **a removal is never in the same release as its
deprecation**. So at least one released version warns about every removal
before it happens, and that warning names the release that removes it.

Pick a removal version with judgement rather than arithmetic. A rarely-touched
internal helper can go in the next minor. A decorator option in every user's
domain file should get several minors. `protean check` reads the declared
targets. A user can run it to learn what a future version will remove, even
without having seen the warning.

### Tier 2: Behavioral Breaks

**What they are:** A method still exists with the same signature but does
something different. Three examples: a repository method that previously
returned `None` for missing entities now raises an exception; event handlers
run in a different order; validation rules are enforced at a different
lifecycle point.

**Detection:** Silent. The user's code runs without errors but produces
incorrect results. This is the most dangerous category.

**Mitigate behavioral breaks with an explicit opt-in flag, then flip the
default.**

Introduce the new behavior behind a configuration flag. The old behavior remains the default.

```python
class MyAggregate(BaseAggregate):
    class Meta:
        strict_validation = True  # New behavior, opt-in in v0.15
```

**Transition sequence:**

1. **Opt in**: New behavior is available behind the flag. The default preserves
   the old behavior.
2. **Warn**: When the flag is unset, emit a warning naming the release of the
   new default: "The default for `strict_validation` will change to `True` in
   v0.N+2. Set it explicitly to suppress this warning."
3. **Flip**: Change the default. Users who set the flag explicitly are unaffected.

Each step is a separate release. A user who sets the flag after the warning is
never surprised. The maintainer picks the number of releases between the steps
by judging how widely users rely on the behavior. No fixed number applies.

### Tier 3: Structural Breaks

**What are they?** Changes to persistence formats, event schemas, serialization
conventions, or configuration structures that stored data or deployed
infrastructure depend on. For a framework with an event store, this is the
highest-consequence category.

**How do you detect them?** It varies: some raise errors (deserialization
errors) and some raise none (data read incorrectly under a new schema).

**Mitigate structural breaks with versioned schemas and documented migration
paths.**

For any change to how data is persisted or read:

1. Version the internal schema or format explicitly.
2. Document the exact migration steps in the release's upgrade notes.
3. Where feasible, provide a migration script or CLI command.

In the short term (pre-1.0), a clear "Upgrade Notes" section in each release is sufficient. Post-1.0, invest in automated migration tooling analogous to Django's `manage.py migrate` or Alembic.

### Summary Table

| Tier | Example | Detection | Mitigation | Before removal |
|------|---------|-----------|------------|----------------|
| Surface | Renamed class, moved import | Immediate error | `DeprecationWarning` naming the removal version | At least one warned release |
| Behavioral | Changed return value, reordered execution | Silent incorrect behavior | Opt-in flag → warning → default flip | At least one warned release per step |
| Structural | Event schema change, config format change | Varies | Versioned schema + migration docs | Case-by-case |

### Exception: Operational Defaults

The Tier-2 transition path has a narrow exception for **operational defaults**.
These are values that tune infrastructure behaviour (connection pool sizes,
bound ports, timeout thresholds, retention windows) without changing any public
API signature or method semantics. These may be flipped in a single release
when **all** of the following hold:

1. The default's previous value remains available via a config key in
   `domain.toml`. Operators can restore old behaviour declaratively without
   touching code.
2. The flip is documented as a Tier-2 change in the release notes with an explicit opt-out recipe.
3. Failures caused by the new value are observable and non-silent, typically a
   domain validator warning (e.g. `LOW_POOL_SIZE`) or a logged runtime warning
   on first use.

This exception exists because operational defaults carry a different kind of
risk from API breaks. A wrong operational default causes a visible failure
(connection exhaustion, port collision) and does not silently produce incorrect
results. Operators who tuned these values already set the keys explicitly. The
3-version transition would add work for users and give them little extra
safety.

Epic 5.1 applied this exception to two shipped changes: the SQLAlchemy pool
defaults for `pool_size`/`max_overflow` went `2/5 → 5/10` (#794), and the
Engine health server binds port 8080 by default (#795). Both carry opt-out
paths in `domain.toml` and non-silent failure modes (pool warning,
port-collision log entry).

### Exception: Silent Correctness Bug

The Tier-2 transition path has a second narrow exception: the "old behaviour"
being changed was never an intentional contract and was in fact a **silent
correctness bug**. Such code ran without error yet produced incorrect or unsafe
results (reads executed inside a UnitOfWork, events double-processed, a
validation that never fired). When **all** of the following hold, a maintainer
may reject such behaviour outright in a single release (no opt-in flag, no
warning window):

1. The prior behaviour violated a documented or clearly-implied contract; no correct program should have depended on it.
2. The failure is **loud and immediate**, typically an `IncorrectUsageError`
   at `domain.init()` or on startup, carrying a message that names the fix, rather than a
   silent change of results.
3. The migration is mechanical and unambiguous (usually a one-line edit), so the loud failure is self-resolving.
4. A transition window would not help. If Protean kept the old code path, it
   would either *perpetuate the incorrect result* or *silently change
   semantics*. A silent change of semantics is itself a Tier-2 silent break,
   the most dangerous category.

Protean offers an opt-out only when a legitimate use of the old behaviour may
exist. With no legitimate use, the mechanical migration is the only option.

This exception has the same reason as the one for operational defaults: the
failure is visible and costs little to fix. A failure that is immediate, raises
an error and has a mechanical fix carries none of the danger the 3-version
transition exists to prevent. A transition window here would *prolong*
incorrect behaviour and protect no one. It is deliberately narrow. The
exception covers bugs and never disliked-but-intentional API. The author of the
change must show that the old behaviour was never a contract.

Protean applied this exception to two changes. The first is multi-worker
event-store double-processing (#1089): the server now refuses to start, with an
`--allow-event-store-multiworker` opt-out for the rare legitimate case. The
second is `@handle` on a Query Handler method (#1104): it now raises
`IncorrectUsageError` at `domain.init()` naming `@read`. It has no opt-out,
since a stateless read must never run in a UnitOfWork.

---

## 3. Compatibility Checking

### `protean check` CLI Command

Build a lightweight CLI command that scans a user's domain definitions and reports:

- Usage of deprecated APIs with their removal version
- Configuration keys that have changed or been renamed
- Aggregate or entity declarations using old-style patterns
- Behavioral flags that will have their defaults changed in an upcoming version

`protean check` is a Protean-specific equivalent of `python -W all` that is
easier to find and to use. `protean check` replaces the manual exercise of
"validate my app against this version" with a 30-second command.

### CI Integration Guidance

Recommend that users add the following to their test configuration:

```ini
# pytest.ini or pyproject.toml
[tool:pytest]
filterwarnings =
    error::protean.exceptions.ProteanDeprecationWarning
```

This turns Protean deprecation warnings into test failures, ensuring users
catch deprecated usage during development rather than after a breaking release.
Scope the filter to the `ProteanDeprecationWarning` **category**, not to a
`:protean.*` **module**: a `@deprecated`-decorated helper attributes its
warning to the caller's module, so a module filter would silently miss exactly
those sites. (If you want to fail on every library's deprecations, and not only
Protean's, use the broader `error::DeprecationWarning` instead.)

Use pytest's `filterwarnings` (or a programmatic `warnings.filterwarnings(...,
category=ProteanDeprecationWarning)`) for this, and avoid the interpreter's
`-W`/`PYTHONWARNINGS`. The command-line form resolves a warning category at
startup, before third-party packages are importable. So it accepts only
built-in categories like `DeprecationWarning` and rejects
`protean.exceptions.ProteanDeprecationWarning` with "invalid module name".

---

## 4. Release Lifecycle

### Standard Release

1. Work merges into `main` through the normal PR workflow.
2. The author of every PR that touches a public API answers: **does this break
   existing usage?**
   - No, merge and continue.
   - Yes. Classify the change into one of the three tiers in Section 2. In the
     same PR, apply the mitigation that tier names.
3. Each PR adds an entry to the unreleased section of `CHANGELOG.md`.
4. When the changelog has substantive entries, cut a release: bump version, tag, build, publish to PyPI.

**Target: releasing should take less than 10 minutes of manual effort.** Invest in CI automation to achieve this.

### Releases That Remove

A removal ships in an ordinary minor. Protean has no separate release type for
removals. The goal is that no user is surprised.

1. Pre-announce: "v0.X.0 will remove the APIs deprecated in v0.Y.x. Run `protean check`, or test with the `ProteanDeprecationWarning` category promoted to an error, to identify affected code."
2. Make the removals, and only of things whose declared removal version has arrived.
3. Document every removal in the changelog with a migration path.

Keep putting removals together in one release, and avoid spreading them across
several. Users then plan for one upgrade instead of many.

Only a release that removes something intentionally breaks user code. It breaks
only code that ignored its warnings. Label each removal release clearly when
you announce it.

### Hotfix Release

For critical bugs discovered after a release:

1. Fix on `main` through normal PR workflow.
2. Cherry-pick the fix to the corresponding `release/0.X.x` branch. The
   `Backport` workflow opens the cherry-pick PR when the fix merges. It does so
   only while the patch milestone (such as `0.15.1`) is open and the
   `release/0.X.x` branch exists. The fix PR, or the issue it closes, must
   carry that milestone. If you set the milestone on the issue after the merge,
   the `Backport` workflow opens the cherry-pick PR at that point. For a fix
   with no milestone, add a `backport release/0.X.x` label to the PR, and the
   `Backport` workflow opens the cherry-pick PR the same way. The author of a
   fix for a patch writes its migration note under the patch version in that
   minor's guide. Both branches have that file, so the note does not conflict.
   If the cherry-pick conflicts elsewhere, the `Backport` workflow opens the PR
   as a draft, and the maintainer resolves the conflict.
3. Tag a patch version (e.g., `v0.15.1`) on the release branch.
4. Publish immediately.

Patch releases need no extra steps. The changelog entry on the release branch
is the documentation. Users who stay on a minor version upgrade along its
release branch, which stays stable while `main` keeps changing.

---

## 5. Communication

### CHANGELOG.md

The changelog is the primary release artifact. Contributors update the
changelog continuously (and not at release time) and organize it by release
version, with the following sections:

- **Added**: New features and capabilities
- **Changed**: Behavioral changes (when a change uses a flag or an opt-in,
  always note it)
- **Deprecated**: Items marked for future removal, with the target removal version
- **Removed**: Items deleted in this release, each with its migration path
- **Fixed**: Bug fixes
- **Upgrade Notes**: Explicit steps users need to take, especially for Tier 2 and Tier 3 changes

### Migration Guides

For releases with Tier 2 or Tier 3 breaking changes, publish a standalone migration guide in the documentation. The guide should:

- Explain what changed and why
- Provide before/after code examples
- Reference `protean check` for automated detection
- Estimate the effort required to migrate

---

## 6. Pre-1.0 vs. Post-1.0

The policies in this ADR apply to the current pre-1.0 phase. Pre-1.0, we have
more latitude: the API is explicitly unstable, and early adopters accept that.
However, the goal is to build the habits and tooling now so that the process is
mature by 1.0.

### The post-1.0 model: deprecation-managed, not strict SemVer

At 1.0 Protean adopts a **deprecation-managed** model for the 1.x series, in the style of Django, Rails, and SQLAlchemy rather than strict semantic versioning.

**What does the contract promise?** Code that runs warning-free on 1.N runs
unmodified on 1.N+1.

Users can plan their upgrades on that promise. The promise is deliberately
stated in terms of warnings and makes no claim about version numbers. Before every removal, at least one released version warns about it. That warning names the release that removes it. Users enforce the contract mechanically
in CI with the category filter from Section 3:

```toml
# pyproject.toml
[tool.pytest.ini_options]
filterwarnings = ["error::protean.exceptions.ProteanDeprecationWarning"]
```

A user who does that has turned "will my upgrade break?" into a test run. (Filter on the **category**, not on a `:protean.*` module pattern: a `@deprecated`-decorated helper attributes its warning to the caller's module, so a module filter misses exactly those sites. Section 3 covers this.)

**What each version position means:**

- **Patch** (1.2.0 → 1.2.1) never changes API. Bug fixes only.
- **Minor** (1.2 → 1.3) carries the changes: new features, new deprecations,
  Tier 2 flag flips, Tier 3 schema changes with shipped migrations, and **the
  removal of anything already deprecated**. A minor may break code that ignored
  its warnings. It may not break code that had none.
- **A major version marks a shift in Protean's declared scope** and never
  collects accumulated breakage.

**There is no fixed deprecation window.** Every deprecation already declares
its own removal version and gets a dedicated warning class
(`@deprecated(removal="0.18.0")` → `RemovedInProtean018Warning`). `protean
check` reads those declarations. Users gain nothing from a blanket "survives
two minors" rule, because each deprecation already has an explicit,
machine-readable target that is already shipping. Such a rule only adds false
precision. Section 1 makes releases cheap and frequent, so "two minors" can be
two weeks. Two weeks is less protection than the number implies.

One invariant takes the place of a fixed window, and the contract depends on
it:

> **A removal is never in the same release as its deprecation.**

Before every removal, at least one released version warns about it. That warning names the release that removes it. This invariant makes "warning-free
on 1.N runs on 1.N+1" mechanically true. It is the only timing rule worth
stating.

**What does this cost?** Without a fixed window, a user who skips releases can
miss the version that warned them. For example, an API is deprecated in 1.4 and
removed in 1.5, and someone going 1.3 → 1.5 never saw the warning. A counted
window would have covered that case and this does not. Two facts make this cost
acceptable. Upgrading minor by minor is the documented path. That path is cheap
precisely because minors are frequent. `protean check` also covers this case.
It reads the declared removal targets and does not replay the warnings you
missed. So it tells a user on 1.3 what 1.5 will remove, which no fixed
deprecation window could.

### Why not strict SemVer

Strict SemVer says breaking changes only in majors. For a framework, that rule
produces one of two bad outcomes. Which one you get depends only on the
maintainers' temperament:

**Burn majors on trivia.** The first time a badly-named parameter needs
correcting, you either ship 2.0 for it or you do not fix it. Version numbers
stop carrying information: 4.0 might mean a rearchitecture or a renamed keyword
argument, and users cannot tell without reading the notes. The major version no
longer tells users how much changed.

**Or never fix anything.** More commonly, a major becomes so costly that nobody
ever corrects a mistake. Mistakes stay in the API permanently. This failure is
the more likely one for Protean, because the framework is opinionated. Protean
is *supposed* to guide users toward correct patterns. To do that, the
maintainers must be able to change a pattern that turned out wrong.

Under the deprecation-managed model, users get separate answers to the two
questions that SemVer merges into one version number. Users answer "Is this
safe to upgrade?" from the warning-free contract, continuously, per release.
Users answer "Has the nature of the project changed?" from the major version. A
user with a clean warning log upgrades minors without reading anything. A major
means the boundary of what Protean claims to do has moved.

**What a major is reserved for.** A major marks a change in Protean's declared
scope and is never a collection of small breaks. Concretely, a major is for a
change in the security posture (what Protean will hold and protect on the
user's behalf). It is also for a change in the concurrency model, such as
cluster-safe multi-worker operation, which changes the deployment contract and
leaves every signature as it was. These are shifts a user must think about, not
mechanically patch.

### Precedent: this is the SQLAlchemy model, and we already ship half of it

The closest precedent is **SQLAlchemy**, and Django is a weaker match.
SQLAlchemy describes its scheme as a "modified semantic versioning scheme". It
states plainly that point releases are fully compatible, and that minor
releases are "typically backwards compatible within the range of
not-previously-deprecated APIs, with some risk of non-backwards compatibility."

Its upgrade mechanism is the one adopted here, almost exactly:

- **Emit one deprecation warning class per version**: SQLAlchemy emits
  `RemovedIn20Warning`. Protean already emits `RemovedInProtean018Warning` and
  the other per-version classes from `protean._deprecation`. The maintainers
  built these classes before writing down the policy. So this policy records
  existing code and proposes no new work.
- **Warning-free means upgrade-safe**: In SQLAlchemy's stated strategy, an
  application that runs on 1.4 with the deprecation flags on and emits no 2.0
  warnings is cross-compatible with 2.0. That is our contract sentence. We
  wrote it independently, and SQLAlchemy, a project with far more users
  depending on it than ours, has confirmed it in practice.
- **Let users see warnings early**: SQLAlchemy shows next-major warnings only
  when `SQLALCHEMY_WARN_20=1` is set. Users opt in to see those warnings before
  they are due. `protean check` does the same job for Protean, and it does not
  need the code path to actually execute.
- **Offer opt-in flags for behavioral change**: SQLAlchemy's `future=True` let
  1.4 users run 2.0 semantics early. That is exactly our Tier 2 flag sequence.

We follow SQLAlchemy's version scheme. **Breaking changes ship in minors**,
patches change no API, and majors are reserved for a categorical shift. We also
follow them in not fixing a deprecation window.

We promise **more** than SQLAlchemy only in the contract itself. SQLAlchemy
accepts "some risk of non-backwards compatibility" in a minor even outside
previously-deprecated APIs. We do not: a minor may remove a deprecated API, but
it may not break code that was running warning-free. We can afford the stricter
promise for two reasons. Our public API is smaller and younger than
SQLAlchemy's. The per-deprecation removal targets also make the promise
checkable, so it is more than an aspiration.

An earlier draft of this section took the opposite approach. It reserved
removals for "cleanup releases" and fixed a two-minor survival window. Both
were dropped. The cleanup release was only a name for a minor that had been
announced, so it added no real distinction. Writing it down also produced a
contradiction between this ADR and the reference page within a day. The fixed
window was redundant with the removal version each deprecation already
declares. Neither rule gave users anything that the contract sentence and the
invariant above do not give more simply.

### What hardens at 1.0

The taxonomy and both exceptions (operational defaults, silent correctness
bugs) carry over unchanged. The invariant that a removal is never in the same
release as its deprecation also carries over. Four things become stricter:

- **Tier 3 migration tooling becomes mandatory** where it was optional before.
  A persistence or event-schema change ships with a migration or it does not
  ship.
- **A deprecation may not ship without a `protean check` rule that detects
  it**: The warning and the detector ship in the same release, so the
  mechanical upgrade path exists from the moment the deprecation does.
- **The guarantees specification becomes part of the API**: Weakening a documented guarantee is a breaking change even when every signature is untouched. See `docs/reference/guarantees.md`.
- **The public surface is enumerated in three tiers** (Stable / Provisional / Internal) so the contract above has a defined subject. See `docs/reference/stable-surface.md`.

**What stays the same at 1.0:**

- The tiered breaking change taxonomy.
- The changelog-driven release trigger.
- The theme-based roadmap organization.
- The principle that releases are cheap and frequent.

### Related open question

Issue #841 tracks a separate question: how a developer *acknowledges* an
intentional breaking change in their own domain. This is the inverse problem,
where user code declares "yes, I meant to change this". That question belongs
to the same policy and concerns a different actor. Nothing in this section
depends on its outcome.

---

## Consequences

### Positive

- Development no longer waits for release validation.
- Early adopters have clear, systematic steps for upgrading.
- The deprecation system creates a paper trail that builds trust.
- Frequent releases mean smaller changes between versions. Smaller changes are
  easier to debug when a release breaks something.
- The roadmap reflects strategic intent rather than release scheduling, reducing pressure to batch features.

### Negative

- More releases means more changelog discipline. Every PR must include a
  changelog entry.
- The tiered deprecation system adds overhead to PRs that touch public APIs.
- `protean check` is an additional tool that the maintainers must build and
  maintain.
- Frequent releases may tire users who prefer stability ("update fatigue"). If
  this happens after 1.0, mitigate it with LTS versions.

### Risks

- Without strong CI, frequent releases could ship regressions. **How to reduce
  it:** Invest in test coverage and automated publishing before increasing
  release cadence.
- Deprecation warnings may go unnoticed if users don't run tests with
  appropriate warning filters. **How to reduce it:** Ship the `protean check`
  CLI and clear documentation on CI configuration.

---

## References

- [Keep a Changelog](https://keepachangelog.com/)
- [Semantic Versioning](https://semver.org/)
- [Python Deprecation Warning Documentation](https://docs.python.org/3/library/warnings.html)
- [Django Deprecation
  Timeline](https://docs.djangoproject.com/en/stable/internals/deprecation/):
  An example of the opt-in flag pattern
- [Rust Release Process](https://forge.rust-lang.org/release/process.html): An
  example of the release train model
- [VS Code Iteration
  Plans](https://github.com/microsoft/vscode/wiki/Iteration-Plans): An example
  of theme-based planning with continuous delivery

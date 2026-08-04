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

Protean has reached a level of complexity and feature richness where it is approaching production readiness. Development velocity has increased significantly with LLM-assisted workflows, compressing what used to be weeks of work into days. However, the release process has not kept pace — releases are treated as heavyweight, batched events tied to epic completion, and are frequently blocked by open-ended validation from early adopters.

The specific friction that prompted this decision: Release R1 was feature-complete but remained unshipped while waiting for developers to validate against their existing codebases. Meanwhile, R2 development was implicitly blocked on shipping R1, creating unnecessary coupling between development and release activities.

Additionally, there is no systematic approach to handling breaking changes. The hesitation to release stems partly from the absence of a mechanism to communicate and manage API incompatibilities, leaving human validation as a substitute for a missing system.

## Decision

We adopt a **continuous release model** with a **tiered breaking change policy** and **theme-based roadmap planning**, as described below.

---

## 1. Release Philosophy

### Core Principles

Releases are cheap, frequent, and decoupled from epic completion. The guiding question for cutting a release is not "have we completed the epic?" but **"is this release better than what's currently on PyPI?"** If yes, ship it.

Version numbers are coordination signals, not milestones. Minor version bumps (0.15 → 0.16) can happen as frequently as meaningful work lands — weekly or even more often during periods of high velocity.

Development and stabilization run in parallel. Completing an epic and shipping a release are independent activities. Work on the next set of features begins immediately, without waiting for the current release to go through validation.

### Release Cadence

There is no fixed schedule. Releases are cut when there is something worth telling users about — a meaningful feature, a significant fix, or an important behavioral improvement. The changelog is the release trigger: when the unreleased section has substantive entries, it's time to ship.

### No Release Candidates

Protean does **not** use release candidates. Minor versions are cut directly from `main` when the changelog has substantive entries. Patch releases on a `release/0.X.x` branch handle any bugs discovered after a minor ships.

**Rationale:** RCs added ceremony without buying meaningful safety. In practice, the RC window became a bottleneck that delayed shipping without producing the early-adopter feedback it was meant to generate. With frequent minor releases, patch releases, and the three-tier breaking change policy (deprecations, flags, versioned schemas), users already have multiple layers of protection without needing an explicit pre-release phase.

If a future release contains a change so large or risky that pre-release validation is warranted, that is a signal to split the change across more incremental releases — not to gate the release train behind a feedback window.

---

## 2. Breaking Change Taxonomy

Not all breaking changes carry the same risk or require the same mitigation. We classify them into three tiers, each with a distinct handling strategy.

### Tier 1: Surface-Level Breaks

**What they are:** Renamed classes, moved imports, changed method signatures, removed configuration keys. These produce immediate and obvious errors (`ImportError`, `TypeError`) on startup.

**Detection:** Loud — users discover them instantly.

**Mitigation: Deprecation warnings.**

Introduce the new API alongside the old. The old API emits a `DeprecationWarning` with a specific removal version. The deprecated path delegates to the new implementation.

Do not hand-roll `warnings.warn(...)`: use the reusable mechanism in `protean._deprecation`, so every deprecation cites a removal version in the same format and emits a per-version warning class (`RemovedInProtean018Warning`, etc.) that downstream projects can filter precisely.

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

Each removal version maps internally to a `RemovedInProteanXXWarning` subclass of the public `protean.exceptions.ProteanDeprecationWarning` (itself a `DeprecationWarning`). The `@deprecated` decorator validates the version eagerly (a typo fails at import); the inline `warn_deprecated` helper never raises on the live deprecated path, degrading to the base `ProteanDeprecationWarning` for an unregistered version so a consumer's program keeps running. Promoting the `ProteanDeprecationWarning` category to an error in CI (see the guidance below) surfaces every Protean deprecation — filter by that category, not by module, since a decorated helper attributes its warning to the *caller's* module.

**Survival window:** There is no fixed count. Each deprecation declares the version it will be removed in, via the `removal=` argument that also selects its warning class, and that declaration is the commitment. What is fixed is the invariant: **a removal is never in the same release as its deprecation**, so every removal is preceded by at least one released version that warned about it and named the release it was going away in.

Pick a removal version with judgement rather than arithmetic. A rarely-touched internal helper can go in the next minor; a decorator option in every user's domain file should be given several. `protean check` reads the declared targets, so a user can ask what a future version will remove without having to have seen the warning.

### Tier 2: Behavioral Breaks

**What they are:** A method still exists with the same signature but does something different. Examples include a repository method that previously returned `None` for missing entities now raising an exception, event handlers executing in a different order, or validation rules being enforced at a different lifecycle point.

**Detection:** Silent — the user's code runs without errors but produces incorrect results. This is the most dangerous category.

**Mitigation: Explicit opt-in flags with eventual default flip.**

Introduce the new behavior behind a configuration flag. The old behavior remains the default.

```python
class MyAggregate(BaseAggregate):
    class Meta:
        strict_validation = True  # New behavior, opt-in in v0.15
```

**Transition sequence:**

1. **Opt-in.** New behavior is available behind the flag. The default preserves the old behavior.
2. **Warn.** If the flag is not set explicitly, emit a warning naming the version the default changes in: "The default for `strict_validation` will change to `True` in v0.N+2. Set it explicitly to suppress this warning."
3. **Flip.** Change the default. Users who set the flag explicitly are unaffected.

Each step is a separate release, so a user who sets the flag when warned is never surprised. How many releases sit between the steps is a judgement call about how widely the behavior is relied on, not a fixed number.

### Tier 3: Structural Breaks

**What they are:** Changes to persistence formats, event schemas, serialization conventions, or configuration structures that affect stored data or deployed infrastructure. For a framework with an event store, this is the highest-consequence category.

**Detection:** Varies — may be loud (deserialization errors) or silent (data read incorrectly under a new schema).

**Mitigation: Versioned schemas and documented migration paths.**

For any change that affects how data is persisted or read:

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

A narrow exception to the Tier-2 transition path applies to **operational defaults** — values that tune infrastructure behaviour (connection pool sizes, bound ports, timeout thresholds, retention windows) without changing any public API signature or method semantics. These may be flipped in a single release when **all** of the following hold:

1. The previous value remains available via a config key in `domain.toml` — operators can restore old behaviour declaratively without touching code.
2. The flip is documented as a Tier-2 change in the release notes with an explicit opt-out recipe.
3. Failures caused by the new value are observable and non-silent — typically a domain validator warning (e.g. `LOW_POOL_SIZE`) or a logged runtime warning on first use.

This exception exists because operational defaults have different risk economics than API breaks: they fail loudly when wrong (connection exhaustion, port collision) rather than silently producing incorrect results, and operators who have invested in tuning already set these keys explicitly. Forcing the 3-version transition imposes friction without commensurate safety gain.

Epic 5.1 applied this exception to two shipped changes — SQLAlchemy pool defaults `2/5 → 5/10` (#794) and the Engine health server binding port 8080 by default (#795). Both carry opt-out paths in `domain.toml` and non-silent failure modes (pool warning, port-collision log entry).

### Exception: Silent Correctness Bug

A second narrow exception to the Tier-2 transition path applies when the "old behaviour" being changed was never an intentional contract but a **silent correctness bug** — code that ran without error yet produced incorrect or unsafe results (reads executed inside a UnitOfWork, events double-processed, a validation that never fired). Such behaviour may be rejected outright in a single release — no opt-in flag, no warning window — when **all** of the following hold:

1. The prior behaviour violated a documented or clearly-implied contract; no correct program should have depended on it.
2. The failure is **loud and immediate** — typically an `IncorrectUsageError` at `domain.init()` or on startup — carrying a message that names the fix, rather than a silent change of results.
3. The migration is mechanical and unambiguous (usually a one-line edit), so the loud failure is self-resolving.
4. A transition window would not help: keeping the old path alive would either *perpetuate the incorrect result* or *silently change semantics* — itself a Tier-2 silent break, the most dangerous category.

An opt-out is offered only when a legitimate use of the old behaviour may exist; where none does, the mechanical migration is the only path forward.

This exception exists for the same risk-economics reason as operational defaults: a loud, immediate, mechanically-fixable failure carries none of the danger the 3-version transition is designed to absorb, and a transition window here would *prolong* incorrect behaviour rather than protect against it. It is deliberately narrow — it covers bugs, not disliked-but-intentional API; the burden is on the change to show the old behaviour was never a contract.

Applied to #1089 (multi-worker event-store double-processing — the server now refuses to start, with an `--allow-event-store-multiworker` opt-out for the rare legitimate case) and #1104 (`@handle` on a Query Handler method — now raises `IncorrectUsageError` at `domain.init()` naming `@read`, with no opt-out, since a stateless read must never run in a UnitOfWork).

---

## 3. Compatibility Checking

### `protean check` CLI Command

Build a lightweight CLI command that scans a user's domain definitions and reports:

- Usage of deprecated APIs with their removal version
- Configuration keys that have changed or been renamed
- Aggregate or entity declarations using old-style patterns
- Behavioral flags that will have their defaults changed in an upcoming version

This serves as a targeted, Protean-specific equivalent of `python -W all`, but more discoverable and user-friendly. It transforms "validate my app against this version" from a manual exercise into a 30-second command.

### CI Integration Guidance

Recommend that users add the following to their test configuration:

```ini
# pytest.ini or pyproject.toml
[tool:pytest]
filterwarnings =
    error::protean.exceptions.ProteanDeprecationWarning
```

This turns Protean deprecation warnings into test failures, ensuring users catch deprecated usage during development rather than after a breaking release. Scope the filter to the `ProteanDeprecationWarning` **category**, not to a `:protean.*` **module**: a `@deprecated`-decorated helper attributes its warning to the caller's module, so a module filter would silently miss exactly those sites. (Use the broader `error::DeprecationWarning` instead if you want to fail on every library's deprecations, not just Protean's.)

Use pytest's `filterwarnings` (or a programmatic `warnings.filterwarnings(..., category=ProteanDeprecationWarning)`) for this, not the interpreter's `-W`/`PYTHONWARNINGS`: the command-line form resolves a warning category at startup, before third-party packages are importable, so it accepts only built-in categories like `DeprecationWarning` and rejects `protean.exceptions.ProteanDeprecationWarning` with "invalid module name".

---

## 4. Release Lifecycle

### Standard Release

1. Work lands on `main` through normal PR workflow.
2. Every PR that touches a public API answers: **does this break existing usage?**
   - No — merge and continue.
   - Yes — classify the tier and apply the appropriate mitigation in the same PR.
3. Each PR adds an entry to the unreleased section of `CHANGELOG.md`.
4. When the changelog has substantive entries, cut a release: bump version, tag, build, publish to PyPI.

**Target: releasing should take less than 10 minutes of manual effort.** Invest in CI automation to achieve this.

### Cleanup Release

Periodically (roughly every 4–6 releases, or when deprecated items have aged past their survival window), cut a cleanup release that removes deprecated code.

1. Pre-announce: "v0.X.0 will remove all deprecations from v0.Y.x and earlier. Run `protean check` or test with `-W error::DeprecationWarning` to identify affected code."
2. Make the removals.
3. Document every removal in the changelog with a migration path.

Cleanup releases are the only releases that intentionally break user code. They should be clearly labeled and communicated.

### Hotfix Release

For critical bugs discovered after a release:

1. Fix on `main` through normal PR workflow.
2. Cherry-pick the fix to the corresponding `release/0.X.x` branch.
3. Tag a patch version (e.g., `v0.15.1`) on the release branch.
4. Publish immediately.

No ceremony needed for patch releases. The changelog entry on the release branch is the documentation. The release branch pattern keeps minor-version consumers on a stable line even while `main` continues to move.

---

## 5. Communication

### CHANGELOG.md

The changelog is the primary release artifact. It is maintained continuously (not written at release time) and organized by release version with the following sections:

- **Added** — new features and capabilities
- **Changed** — behavioral changes (always note if a flag or opt-in is involved)
- **Deprecated** — items marked for future removal, with the target removal version
- **Removed** — items deleted in this release (cleanup releases only)
- **Fixed** — bug fixes
- **Upgrade Notes** — explicit steps users need to take, especially for Tier 2 and Tier 3 changes

### Migration Guides

For releases with Tier 2 or Tier 3 breaking changes, publish a standalone migration guide in the documentation. The guide should:

- Explain what changed and why
- Provide before/after code examples
- Reference `protean check` for automated detection
- Estimate the effort required to migrate

---

## 6. Pre-1.0 vs. Post-1.0

The policies in this ADR apply to the current pre-1.0 phase. Pre-1.0, we have more latitude: the API is explicitly unstable, and early adopters accept that. However, the goal is to build the muscle and tooling now so that by 1.0, the process is mature.

### The post-1.0 model: deprecation-managed, not strict SemVer

At 1.0 Protean adopts a **deprecation-managed** model for the 1.x series, in the style of Django, Rails, and SQLAlchemy rather than strict semantic versioning.

**The contract, in one sentence:** Code that runs warning-free on 1.N runs unmodified on 1.N+1.

That is the promise users can plan against, and it is deliberately stated in terms of warnings rather than version numbers. Every removal is preceded by at least one released version that warned about it and named the release it was going away in. Users enforce the contract mechanically in CI with the category filter from Section 3:

```toml
# pyproject.toml
[tool.pytest.ini_options]
filterwarnings = ["error::protean.exceptions.ProteanDeprecationWarning"]
```

A user who does that has turned "will my upgrade break?" into a test run. (Filter on the **category**, not on a `:protean.*` module pattern: a `@deprecated`-decorated helper attributes its warning to the caller's module, so a module filter misses exactly those sites. Section 3 covers this.)

**What each version position means:**

- **Patch** (1.2.0 → 1.2.1) never changes API. Bug fixes only.
- **Minor** (1.2 → 1.3) is where change lands: new features, new deprecations, Tier 2 flag flips, Tier 3 schema changes with shipped migrations, and **the removal of anything already deprecated**. A minor may break code that ignored its warnings. It may not break code that had none.
- **Majors are eras**, not accumulated breakage.

**There is no fixed deprecation window.** Every deprecation already declares its own removal version and gets a dedicated warning class (`@deprecated(removal="0.18.0")` → `RemovedInProtean018Warning`), and `protean check` reads those declarations. A blanket "survives two minors" rule adds nothing to a per-deprecation target that is explicit, machine-readable, and already shipping. It only adds false precision: with releases as cheap and frequent as Section 1 makes them, "two minors" can be two weeks, which is not the protection the number implies.

What replaces it is one invariant, which is the thing the contract actually rests on:

> **A removal is never in the same release as its deprecation.**

Every removal is preceded by at least one released version that warned about it and named the release it was going away in. That is what makes "warning-free on 1.N runs on 1.N+1" mechanically true, and it is the only timing rule worth stating.

**The cost, stated plainly.** Without a fixed window, a user who skips releases can miss the version that warned them: deprecated in 1.4, removed in 1.5, and someone going 1.3 → 1.5 never saw it. A counted window would have covered that case and this does not. Two things make it acceptable. Upgrading minor by minor is the documented path, and it is cheap precisely because minors are frequent. And `protean check` resolves it properly anyway: it reads the declared removal targets rather than replaying the warnings you missed, so it tells a user on 1.3 what 1.5 will remove, which no survival window could.

### Why not strict SemVer

Strict SemVer says breaking changes only in majors. Applied to a framework, that produces one of two bad outcomes, and which one you get depends only on temperament:

**Burn majors on trivia.** The first time a badly-named parameter needs correcting, you either ship 2.0 for it or you do not fix it. Version numbers stop carrying information: 4.0 might mean a rearchitecture or a renamed keyword argument, and users cannot tell without reading the notes. The signal the major version was supposed to carry is gone.

**Or petrify.** More commonly, the cost of a major becomes so high that nothing is ever corrected. Mistakes calcify into permanent API. This is the more likely failure for Protean specifically, because the framework is opinionated: it is *supposed* to guide users toward correct patterns, and that requires the ability to move a pattern that turned out wrong.

The deprecation-managed model separates the two questions SemVer conflates. "Is this safe to upgrade?" is answered by the warning-free contract, continuously, per release. "Has the nature of the project changed?" is answered by the major version. A user with a clean warning log upgrades minors without reading anything. A major means the boundary of what Protean claims to do has moved.

**What a major is reserved for.** A major marks a shift in the declared scope boundary, not a pile of small breaks. Concretely: a change in the security posture (what Protean will hold and protect on the user's behalf), or a change in the concurrency model (for example, cluster-safe multi-worker operation, which changes the deployment contract rather than a signature). These are shifts a user must think about, not mechanically patch.

### Precedent: this is the SQLAlchemy model, and we already ship half of it

The closest precedent is not Django but **SQLAlchemy**, which describes its scheme as a "modified semantic versioning scheme" and states plainly that point releases are fully compatible while minor releases are "typically backwards compatible within the range of not-previously-deprecated APIs, with some risk of non-backwards compatibility."

Its upgrade mechanism is the one adopted here, almost exactly:

- **A per-version deprecation warning class.** SQLAlchemy emits `RemovedIn20Warning`; Protean already emits `RemovedInProtean018Warning` and friends from `protean._deprecation`. This was built before the policy was written down, so the policy is ratifying existing machinery rather than proposing new work.
- **Warning-free means upgrade-safe.** SQLAlchemy's stated strategy is that once an application runs on 1.4 with the deprecation flags on and emits no 2.0 warnings, it is cross-compatible with 2.0. That is our contract sentence, arrived at independently and validated by a project with a far larger blast radius than ours.
- **An early-warning switch.** SQLAlchemy gates next-major warnings behind `SQLALCHEMY_WARN_20=1` so users opt into seeing them before they are due. `protean check` plays that role for us, with the advantage of not requiring the code path to actually execute.
- **Opt-in flags for behavioral change.** SQLAlchemy's `future=True` let 1.4 users run 2.0 semantics early. That is exactly our Tier 2 flag sequence.

We follow their shape: **the minor position is where breaking change lands**, patches are inert, and majors are reserved for a categorical shift. We also follow them in not fixing a deprecation window.

The one place we promise **more** is the contract itself. SQLAlchemy accepts "some risk of non-backwards compatibility" in a minor even outside previously-deprecated APIs. We do not: a minor may remove a deprecated API, but it may not break code that was running warning-free. We can afford the stricter line because our surface is smaller and younger, and because the per-deprecation removal targets make it checkable rather than aspirational.

An earlier draft of this section went the other way, reserving removals for "cleanup releases" and fixing a two-minor survival window. Both were dropped. The cleanup release was a distinction without a difference (it was a minor that had been announced), and writing it down produced a contradiction between this ADR and the reference page within a day. The fixed window was redundant with the removal version each deprecation already declares. Neither was buying anything the contract sentence and the invariant above do not buy more simply.

### What hardens at 1.0

The taxonomy, survival windows, and both exceptions (operational defaults, silent correctness bugs) carry over unchanged. Four things become stricter:

- **Tier 3 migration tooling becomes mandatory**, not a nice-to-have. A persistence or event-schema change ships with a migration or it does not ship.
- **A deprecation may not ship without a `protean check` rule that detects it.** The warning and the detector land together, so the mechanical upgrade path exists from the moment the deprecation does.
- **The guarantees specification becomes part of the API.** Weakening a documented guarantee is a breaking change even when every signature is untouched. See `docs/reference/guarantees.md`.
- **The public surface is enumerated in three tiers** (Stable / Provisional / Internal) so the contract above has a defined subject. See `docs/reference/stable-surface.md`.

**What stays the same at 1.0:**

- The tiered breaking change taxonomy.
- The changelog-driven release trigger.
- The theme-based roadmap organization.
- The principle that releases are cheap and frequent.

### Related open question

How a developer *acknowledges* an intentional breaking change in their own domain (the inverse problem: user code declaring "yes, I meant to change this") is tracked separately in issue #841. It is the same policy territory but a different actor, and nothing in this section depends on its outcome.

---

## Consequences

### Positive

- Development velocity is no longer gated on release validation.
- Early adopters have a clear, systematic path for handling upgrades.
- The deprecation system creates a paper trail that builds trust.
- Frequent releases mean smaller deltas, which are easier to debug when something goes wrong.
- The roadmap reflects strategic intent rather than release scheduling, reducing pressure to batch features.

### Negative

- More releases means more changelog discipline — every PR must include a changelog entry.
- The tiered deprecation system adds overhead to PRs that touch public APIs.
- `protean check` is an additional tool to build and maintain.
- Frequent releases may cause "update fatigue" for users who prefer stability — mitigate this post-1.0 with LTS versions if needed.

### Risks

- Without strong CI, frequent releases could ship regressions. **Mitigation:** Invest in test coverage and automated publishing before increasing release cadence.
- Deprecation warnings may go unnoticed if users don't run tests with appropriate warning filters. **Mitigation:** `protean check` CLI and clear documentation on CI configuration.

---

## References

- [Keep a Changelog](https://keepachangelog.com/)
- [Semantic Versioning](https://semver.org/)
- [Python Deprecation Warning Documentation](https://docs.python.org/3/library/warnings.html)
- [Django Deprecation Timeline](https://docs.djangoproject.com/en/stable/internals/deprecation/) — exemplar of the opt-in flag pattern
- [Rust Release Process](https://forge.rust-lang.org/release/process.html) — exemplar of the release train model
- [VS Code Iteration Plans](https://github.com/microsoft/vscode/wiki/Iteration-Plans) — exemplar of theme-based planning with continuous delivery

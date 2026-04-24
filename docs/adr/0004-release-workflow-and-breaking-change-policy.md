# ADR: Release Workflow and Breaking Change Policy

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-11 |
| **Last updated** | 2026-04-10 (removed release candidate workflow) |
| **Author** | Subhash Bhushan |
| **Applies to** | Protean Framework (pre-1.0) |
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

```python
import warnings

def old_method(self):
    warnings.warn(
        "old_method() is deprecated. Use new_method() instead. "
        "Will be removed in v0.17.0.",
        DeprecationWarning,
        stacklevel=2
    )
    return self.new_method()
```

**Survival window:** Deprecated items survive for a minimum of two minor versions. If deprecated in 0.15, the earliest removal is 0.17.

**Removal:** Deprecated items are removed in announced "cleanup releases" (see Section 4).

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

1. **v0.N** — New behavior is available but opt-in. Default preserves old behavior.
2. **v0.N+1** — If the flag is not explicitly set, emit a warning: "The default for `strict_validation` will change to `True` in v0.N+2. Set it explicitly to suppress this warning."
3. **v0.N+2** — Flip the default. Users who explicitly set the flag are unaffected.

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

| Tier | Example | Detection | Mitigation | Minimum Survival |
|------|---------|-----------|------------|-----------------|
| Surface | Renamed class, moved import | Immediate error | `DeprecationWarning` | 2 minor versions |
| Behavioral | Changed return value, reordered execution | Silent incorrect behavior | Opt-in flag → warning → default flip | 3 minor versions |
| Structural | Event schema change, config format change | Varies | Versioned schema + migration docs | Case-by-case |

### Exception: Operational Defaults

A narrow exception to the Tier-2 transition path applies to **operational defaults** — values that tune infrastructure behaviour (connection pool sizes, bound ports, timeout thresholds, retention windows) without changing any public API signature or method semantics. These may be flipped in a single release when **all** of the following hold:

1. The previous value remains available via a config key in `domain.toml` — operators can restore old behaviour declaratively without touching code.
2. The flip is documented as a Tier-2 change in the release notes with an explicit opt-out recipe.
3. Failures caused by the new value are observable and non-silent — typically a domain validator warning (e.g. `LOW_POOL_SIZE`) or a logged runtime warning on first use.

This exception exists because operational defaults have different risk economics than API breaks: they fail loudly when wrong (connection exhaustion, port collision) rather than silently producing incorrect results, and operators who have invested in tuning already set these keys explicitly. Forcing the 3-version transition imposes friction without commensurate safety gain.

Epic 5.1 applied this exception to two shipped changes — SQLAlchemy pool defaults `2/5 → 5/10` (#794) and the Engine health server binding port 8080 by default (#795). Both carry opt-out paths in `domain.toml` and non-silent failure modes (pool warning, port-collision log entry).

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
    error::DeprecationWarning:protean.*
```

This turns Protean deprecation warnings into test failures, ensuring users catch deprecated usage during development rather than after a breaking release.

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

**What changes at 1.0:**

- Semantic versioning becomes strict: breaking changes only in major versions.
- The deprecation survival window extends (minimum one major version cycle).
- Automated migration tooling becomes a requirement, not a nice-to-have.
- The `protean check` command becomes a first-class upgrade tool with comprehensive coverage.

**What stays the same at 1.0:**

- The tiered breaking change taxonomy.
- The changelog-driven release trigger.
- The theme-based roadmap organization.
- The principle that releases are cheap and frequent.

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

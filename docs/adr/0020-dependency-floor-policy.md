# ADR-0020: Dependency version floors are proven minimums, not moving targets

**Status:** Accepted

**Date:** July 2026

## Context

Protean is a library. Applications that depend on it also depend, directly, on
many of the same packages Protean does: `fastapi`, `pydantic`, `sqlalchemy`,
`typer`, `jinja2`, and so on. When Protean declares a lower bound such as
`fastapi>=X`, that bound is imposed on every downstream application: pip must
resolve a `fastapi` at least `X`, and an application pinned below `X` can no
longer install Protean. A library's floors therefore define the *width of its
compatibility window*, the set of dependency versions an application is free to
keep while still adopting Protean.

Dependabot was configured with `versioning-strategy: auto`, which raises a `>=`
floor to the newest release every time one is published. Over many weekly runs,
Dependabot kept raising the floors to the newest release: an audit found the
locked (latest) version of nearly every runtime dependency was *identical* to
its declared floor (`fastapi` floor and lock both `0.139.0`, `pydantic` both
`2.13.4`, `sqlalchemy` both `2.0.51`, and so on). The compatibility window had
shrunk to almost nothing. An application not already on the newest release of
each shared dependency would conflict with Protean, even though Protean's code
required none of those specific newest versions. A routine Dependabot floor
bump (PR #1216) prompted the maintainers to fix the underlying policy instead
of merging one more floor increase.

Two structural facts shape what "lowest supported" can mean:

1. **Protean tests on the newest supported Python (3.14)**: A declared floor
   must therefore have a distribution installable on 3.14. For pure-Python
   packages this is no constraint. For C-extension packages (`pydantic-core`,
   `cffi`, `greenlet`, `psycopg2-binary`, `pyodbc`), the real floor can be no
   lower than the first version shipping a 3.14 (`cp314`) wheel. In mid 2026,
   that version is close to current. C-extension floors cannot be widened as
   far as pure-Python ones, and that is inherent to supporting the
   newest Python.
2. **A floor is only real if the suite passes at it**: Resolution succeeding is
   necessary but not sufficient, because a floor can resolve yet break at
   runtime. For example, `typer 0.15` resolves fine but calls click's pre-8.2
   `make_metavar()` signature, and `elasticsearch < 8.18` lacks the bundled
   `.dsl` module Protean imports.

## Decision

**A runtime dependency's floor is the lowest version proven to work, not the
newest version available.** Concretely:

- Each `>=` floor on a *published* dependency (`[project.dependencies]` and
  `[project.optional-dependencies]`) is set to the lowest version that (a) has a
  distribution installable on every supported Python including the newest, and
  (b) passes the full test suite under `uv --resolution lowest-direct`. We do
  not raise a floor without a concrete reason (a required feature, a required
  bug fix, or a security fix).
- **The floor-proving CI leg is the enforcement mechanism**: The `test` job
  runs one extra leg on the newest Python with
  `uv sync --resolution lowest-direct`. That command installs Protean's own
  dependencies at their declared floors and keeps transitive dependencies at
  latest. The worst case a downstream application can present. The
  floor-proving leg runs the full suite. When a floor stops resolving, loses
  its newest-Python wheel, or is no longer API-compatible with Protean's code,
  the floor-proving leg fails CI, so the broken floor does not go unnoticed.
  (The normal legs resolve to latest via `uv.lock` and never exercise the
  floors, so the floors could drift without any test failing.)
- **Dependabot uses `versioning-strategy: increase-if-necessary`,** which
  leaves a floor alone while the newest release still satisfies the existing
  `>=X,<major` range. It proposes a change only when a new major release falls
  outside the cap, and that case is handled deliberately, per the existing
  `ignore` rules. Dependabot no longer raises floors on each new release.

  *Amended (October 2026): Dependabot's `pip` ecosystem edits `pyproject.toml`
  and never `uv.lock`, so the lint job and a weekly workflow now cover the
  lock. The lint job runs `uv lock --check`, which fails a change that edits
  `pyproject.toml` without the lock. A weekly `lock-refresh` workflow runs
  `uv lock --upgrade` and opens one PR, so CI tests the newest release each
  range allows. Without that workflow, a widened cap leaves the old version
  locked. Dependabot's `uv` ecosystem would update the lock itself. Protean did
  not adopt Dependabot's `uv` ecosystem because its handling of
  `versioning-strategy` is unsettled. Dependabot's maintainers say it supports
  the same strategies as `pip` (dependabot-core #12162), while users still
  report it raising floors to the newest release.
  Moving to it needs a trial run that shows `increase-if-necessary` leaves the
  floors alone. A hold on a dependency is a cap in `pyproject.toml` (`mypy<3`,
  `elasticsearch<9`), because `uv lock --upgrade` does not read Dependabot's
  `ignore` rules.*
- **Security floors are exempt from widening**: A floor that encodes a security
  fix (e.g. `jinja2>=3.1.6` for CVE-2025-27516) stays at the fixed version even
  when older versions would pass the functional suite.
- **Development dependencies (`[dependency-groups]`) are out of scope**: They are
  never installed by `pip install protean`, so their floors have no effect on
  downstream applications and are set for contributor convenience.

## Consequences

- Applications gain a materially wider compatibility window for the
  pure-Python dependencies they are most likely to share and pin (`fastapi`
  ecosystem: `typer`, `uvicorn`, `starlette`; plus `jinja2`,
  `structlog`, `marshmallow`, `flask`, and others). They can adopt or hold a
  Protean upgrade without being forced onto the newest release of each.
- The floors now state tested minimums, and the floor-proving leg verifies them
  on every CI run. When a future change starts using a newer API of a
  dependency, the change must raise that floor (a visible, reviewed edit), or
  the floor-proving leg fails.
- CI cost grows by one test leg per run (full services, newest Python). This
  extra leg is what it costs to prove the floors.
- C-extension floors stay close to the current release and will rise roughly as
  Protean adds support for each new Python version. This is expected and is not
  a regression. For those packages, the first versions with newest-Python
  wheels limit the compatibility window we can honestly offer.
- The floor audit is not a one-time event: floors can be re-lowered later if a
  dependency backfills wheels or Protean drops a newer-API usage, but only with
  the CI leg as proof.

## Alternatives Considered

- **Keep `versioning-strategy: auto` and merge the bumps**: Rejected: it is the
  root cause. It optimizes a library's floors as if they were an application's
  pins, which is exactly backwards: an application wants its lockfile current,
  but a library wants its floors low.
- **Lower the floors once, without the CI leg**: Rejected: Dependabot, or a new
  API usage that no test catches, would raise unverified floors again. The
  floor-proving CI leg is what keeps the policy in force.
- **Run the floor-proving leg on the oldest Python (3.11) instead of the
  newest.** Rejected: 3.11 has the widest wheel availability, so it would fail to
  catch a floor that lacks a newest-Python wheel. The most common way a floor
  is too low. The newest Python is the binding constraint.
- **Per-Python floors via environment markers** (e.g. a lower `pydantic` on 3.11
  than on 3.14). Rejected as premature complexity: it multiplies the number of
  version constraints to maintain for a modest widening on C-extension packages
  only. Revisit if the gap between oldest- and newest-Python floors becomes
  large enough to matter.

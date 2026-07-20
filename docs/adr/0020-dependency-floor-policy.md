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
compatibility window* — the set of dependency versions an application is free to
keep while still adopting Protean.

Dependabot was configured with `versioning-strategy: auto`, which raises a `>=`
floor to the newest release every time one lands. Over many weekly runs this
ratcheted every floor up to "newest as of last Tuesday": an audit found the
locked (latest) version of nearly every runtime dependency was *identical* to
its declared floor (`fastapi` floor and lock both `0.139.0`, `pydantic` both
`2.13.4`, `sqlalchemy` both `2.0.51`, and so on). The compatibility window had
collapsed to near-zero width — an application not already on the newest release
of each shared dependency would conflict with Protean — even though Protean's
code required none of those specific newest versions. PR #1216 (a routine
Dependabot floor bump) was the prompt to fix the underlying policy rather than
merge one more ratchet.

Two structural facts shape what "lowest supported" can mean:

1. **Protean tests on the newest supported Python (3.14).** A declared floor
   must therefore have a distribution installable on 3.14. For pure-Python
   packages this is no constraint. For C-extension packages (`pydantic-core`,
   `cffi`, `greenlet`, `psycopg2-binary`, `pyodbc`) the real floor is bounded
   below by the first version shipping a 3.14 (`cp314`) wheel — which, in mid
   2026, is close to current. C-extension floors cannot be widened as far as
   pure-Python ones, and that is inherent to supporting the newest Python.
2. **A floor is only real if the suite passes at it.** Resolution succeeding is
   necessary but not sufficient: a floor can resolve yet break at runtime (e.g.
   `typer 0.15` resolves fine but calls click's pre-8.2 `make_metavar()`
   signature, and `elasticsearch < 8.18` lacks the bundled `.dsl` module
   Protean imports).

## Decision

**A runtime dependency's floor is the lowest version proven to work, not the
newest version available.** Concretely:

- Each `>=` floor on a *published* dependency (`[project.dependencies]` and
  `[project.optional-dependencies]`) is set to the lowest version that (a) has a
  distribution installable on every supported Python including the newest, and
  (b) passes the full test suite under `uv --resolution lowest-direct`. We do
  not raise a floor without a concrete reason (a required feature, a required
  bug fix, or a security fix).
- **The floor-proving CI leg is the enforcement mechanism.** The `test` job runs
  one extra leg on the newest Python with `uv sync --resolution lowest-direct`,
  which installs Protean's own dependencies at their declared floors while
  keeping transitive dependencies at latest — the worst case a downstream
  application can present. It runs the full suite. A floor that stops resolving,
  loses its newest-Python wheel, or drifts out of API compatibility fails CI
  instead of rotting silently. (The normal legs resolve to latest via `uv.lock`
  and never exercise the floors — which is why the floors were free to drift.)
- **Dependabot uses `versioning-strategy: increase-if-necessary`,** which leaves
  a floor alone while the newest release still satisfies the existing
  `>=X,<major` range and only proposes a change when a new major escapes the cap
  (handled deliberately, per the existing `ignore` rules). Dependabot no longer
  ratchets floors.
- **Security floors are exempt from widening.** A floor that encodes a security
  fix (e.g. `jinja2>=3.1.6` for CVE-2025-27516) stays at the fixed version even
  when older versions would pass the functional suite.
- **Development dependencies (`[dependency-groups]`) are out of scope.** They are
  never installed by `pip install protean`, so their floors have no effect on
  downstream applications and are set for contributor convenience.

## Consequences

- Applications gain a materially wider compatibility window for the
  pure-Python dependencies they are most likely to share and pin (`fastapi`
  ecosystem: `typer`, `uvicorn`, `starlette`; plus `jinja2`, `werkzeug`,
  `structlog`, `marshmallow`, `flask`, and others). They can adopt or hold a
  Protean upgrade without being forced onto the newest release of each.
- The floors now mean something and are continuously verified. A future change
  that starts using a newer API of a dependency must either raise that floor (a
  visible, reviewed edit) or the floor-proving leg fails.
- CI cost grows by one test leg per run (full services, newest Python). This is
  the price of the floors being real rather than aspirational.
- C-extension floors remain close to current and will move forward roughly in
  step with new Python support. This is expected, not a regression; the window
  we can honestly offer for those packages is bounded by newest-Python wheels.
- The floor audit is not a one-time event: floors can be re-lowered later if a
  dependency backfills wheels or Protean drops a newer-API usage, but only with
  the CI leg as proof.

## Alternatives Considered

- **Keep `versioning-strategy: auto` and merge the bumps.** Rejected: it is the
  root cause. It optimizes a library's floors as if they were an application's
  pins, which is exactly backwards — an application wants its lockfile current, a
  library wants its floors low.
- **Lower the floors once, without the CI leg.** Rejected: unverified floors
  drift straight back up (Dependabot, or a new API usage landing unnoticed). The
  enforcement leg is what makes the policy durable.
- **Run the floor-proving leg on the oldest Python (3.11) instead of the
  newest.** Rejected: 3.11 has the widest wheel availability, so it would fail to
  catch a floor that lacks a newest-Python wheel — the most common way a floor
  is too low. The newest Python is the binding constraint.
- **Per-Python floors via environment markers** (e.g. a lower `pydantic` on 3.11
  than on 3.14). Rejected as premature complexity: it multiplies the constraint
  surface for a modest widening on C-extension packages only. Revisit if the
  gap between oldest- and newest-Python floors becomes large enough to matter.

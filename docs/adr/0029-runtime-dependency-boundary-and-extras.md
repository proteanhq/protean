# Decide which runtime dependencies stay in core and which move to feature extras (ADR-0029)

**Status:** Accepted

**Date:** August 2026

> **Changed in 0.18.0:** The String/Text `sanitize` default flipped from `True`
to `False` (issue #1455). Since then `bleach` runs only where a field opts in,
and no longer runs for nearly every domain by default. `bleach` still ships in
core (it > is not behind an extra), because a field that sets `sanitize=True`
or a domain > that sets `[field_defaults] sanitize = true` must not hit a
missing-package > error at runtime. The present-tense "sanitize by default"
claims below are > historical.

## Context

A plain `pip install protean` used to pull a web server, an ASGI stack, a Jinja
template engine, an interactive REPL, and a project scaffolder. It pulled them
whether or not the consumer ever ran a server, opened a shell, or generated a
project. The adapter ecosystem already kept its packages out of core:
`postgresql`, `redis`, `elasticsearch`, `flask`, and `sendgrid` are extras,
installed only when the consumer connects to that infrastructure. But several
install-time-optional concerns were hard runtime dependencies in
`[project].dependencies`:

- `fastapi`, `uvicorn`, `jinja2`: the HTTP/ASGI/observatory stack, used only by
  `protean observatory` and `protean.integrations.fastapi`.
- `ipython`: The interactive shell, used only by `protean shell`.
- `copier`: Project scaffolding, used only by `protean new`.

None of these are imported by `import protean`. The imports were already lazy,
gated behind a CLI subcommand or an opt-in integration module. So import
coupling cost nothing here. The cost was **install footprint**: the packages
every install downloads, and the version conflicts with those packages that
every consumer inherited. FastAPI uses the same fix: it moves `uvicorn` into
`fastapi[standard]`. Requests keeps its core at a handful of dependencies.

Two more packages were candidates but stayed in core after the original review.
`bleach` (HTML sanitization) looked optional, because only String/Text field
sanitization uses it. But `String()` and `Text()` default to `sanitize=True`.
Nearly every domain has a string field, so bleach runs for nearly every domain.
Moving bleach behind an extra would make that extra a de-facto requirement, and
anyone who missed the extra would silently lose sanitizing. `werkzeug` was a
genuine import-time need (it backed `current_domain`/ `current_uow`). `bleach`
and `werkzeug` both stayed in core at the time. (Each of `werkzeug`, `cffi`,
and `greenlet` was later reviewed and moved out; see the amendments in
Consequences.)

Moving a package out of `[project].dependencies` is a Tier-1 breaking change
under [ADR-0004](0004-release-workflow-and-breaking-change-policy.md): code
that worked on a fat install can fail on a lean one. The maintainers had to
decide which packages stay in core and which move to extras, and what a user
sees on using a feature without its extra. They also had to release the break
in a way that every upgrader can recover from.

## Decision

**Keep only the domain-modeling and message-processing essentials in core, and
move the five install-time-optional packages behind feature extras.**

Core (`pip install protean`) kept only what every consumer needed to define a
domain, persist through the memory adapter, and run the async engine:
`inflection`, `marshmallow`, `python-dateutil`, `typer` (the CLI framework
itself), `structlog`, `werkzeug`, `bleach`, `pydantic`, `greenlet`, and `cffi`
(at the time of the original decision; see the amendments in Consequences for
the current state).

Protean adds three feature extras:

| Extra | Packages | Gates |
|-------|----------|-------|
| `server` | `fastapi`, `uvicorn`, `jinja2` | `protean observatory`, `protean.integrations.fastapi` |
| `shell` | `ipython` | `protean shell` |
| `scaffold` | `copier` | `protean new` |

And two convenience bundles:

| Extra | Expands to | Purpose |
|-------|------------|---------|
| `cli` | `shell` + `scaffold` | the full interactive `protean new` / `protean shell` experience |
| `all` | `server` + `cli` | everything that shipped in the pre-0.18 core; the one-line upgrade |

**When a feature is used without its extra, fail with an actionable message
that names the extra to install, never a bare `ModuleNotFoundError`.**
`protean.utils.dependencies.missing_dependency_message` builds the message, and
`FEATURE_EXTRA_MODULES` in the same module maps each extra to the packages it
provides, so one module holds both facts. The CLI commands (`new`, `shell`,
`observatory`) import their optional stack lazily inside the command body; on
`ImportError` they call `abort_for_missing_dependency`, which prints `Error: …
requires the '<pkg>' package. Install it with 'pip install
"protean[<extra>]"'.` and exits non-zero.

To decide whether a package is actually missing, the guard uses
`importlib.util.find_spec` over the extra's packages, not the `ImportError`'s
name. An `ImportError` from an installed but broken package (an incompatible
version, a renamed symbol) names that same package, so a name-based check would
tell the user to install a package they already have. A name-based check would
also miss a `jinja2` error that a third party re-raises with no `name` at all.
If `find_spec` finds every package of the extra, the `ImportError` is a real
bug inside the feature, and the guard re-raises it unchanged. The FastAPI
integration applies the same `find_spec` guard at import, raising a clear
`ImportError` rather than a `typer.Abort` (a library import must not abort the
process).

**Ship the breaking change in 0.18.0 with no deprecation release first.**
Because the imports were already lazy, `import protean` never loaded these
deps, so no `import protean` code path could emit a pre-removal
`DeprecationWarning`. A staged "warn then move" plan would keep the fat install
for one more release and only warn about the change. The fix for that change is
a single word, so the extra release would add cycle time and protect no one.
Instead, 0.18.0 moves the packages to extras and ships the `all` extra as the
one-line restore of the previous behavior. The release also provides the
actionable errors and documents the change in the 0.18 migration guide. The
actionable error plus the `all` extra **is** the Tier-1 mitigation.

## Consequences

- A plain `pip install protean` is markedly smaller and installs fewer packages
  that can conflict with your own dependency versions. Consumers opt into the
  web stack, the shell, and the scaffolder only when they use them.
- Consumers who ran `protean observatory`, `protean shell`, or `protean new`, or
  imported `protean.integrations.fastapi`, must install the matching extra. The
  error message names the exact extra each of them needs. A project that wants
  the old behavior wholesale adds `protean[all]`.
- CI and dev environments that already run `uv sync --all-extras` are unaffected;
  the new extras are picked up automatically.
- Protean defines one extra per feature in place of one big `cli` extra, so
  there are more extra names to document. In return each install stays minimal:
  a REPL user does not install the scaffolder.
- `bleach` stays in core because String/Text fields sanitize by default (see
  Context). `werkzeug`, `cffi`, and `greenlet` stayed in core at the time of the
  original decision, but each was later reviewed and moved out; see the
  amendments below.

  *Amended (August 2026, #1376): `cffi` and `greenlet` left core. Nothing in
  `src/protean` imports either package on any runtime path (the SQLAlchemy
  adapter uses the synchronous engine), so both left core. Their version floors
  moved to the extras whose dependency trees pull them in. `greenlet` went to
  `postgresql`/`sqlite`/`mssql` (SQLAlchemy requires it on common platforms but
  pins no floor), and `cffi` went to `sendgrid` (its only consumer is
  `cryptography`, also floorless). The newest-Python-wheel floor from the
  dependency floor policy (ADR-0020) still holds where each package is actually
  installed.*

  *Amended (September 2026, #1580): the `mysql` extra carries both floors. The
  `mysql` extra is a SQLAlchemy extra, so it pulls `greenlet` like the other
  three. Its `pymysql[rsa]` dependency pulls `cryptography`, so the `mysql`
  extra also pulls `cffi` the way `sendgrid` does. The rule is unchanged: a
  floor sits on every extra whose tree reaches the package.*

  *Amended (October 2026, #1689): `postgresql` now installs psycopg 3. A new
  `postgresql-psycopg2` extra installs psycopg2. Both are SQLAlchemy extras, so
  both carry the `greenlet` floor. SQLAlchemy 2.1 no longer requires
  `greenlet`, but the extras still accept the 2.0 floor, which does.*

  *Amended (August 2026, #1375): `werkzeug` left core. `current_domain`,
  `current_uow`, and `g` are now backed by a small stdlib `contextvars`
  implementation that preserves the push/pop nesting semantics of the old
  `LocalStack`/`LocalProxy`. The public API of the three proxies is unchanged.*

## Alternatives Considered

- **Offer one coarse `cli` extra covering shell + scaffold.** It means fewer
  names to document. But it couples unrelated concerns: a user who only wants a
  REPL would install the scaffolder. Rejected in favor of precise extras plus
  the `cli`/`all` bundles.
- **Move `bleach` behind a `[sanitize]` extra and fail fast when a `sanitize=True`
  field is defined without it.** Rejected: `String()` and `Text()` default to
  `sanitize=True`, so bleach runs for nearly every domain. The extra would
  become a de-facto requirement, and the "fail fast" would fire on the
  *default* field declaration, not an opt-in one. Moving it out of core would
  also mean flipping the `sanitize` default to `False`. That flip is a separate
  and security-relevant behavioral break (string fields silently stop
  HTML-escaping) that does not belong in a packaging change. bleach stays in
  core, and if that default ever flips, the maintainers revisit this choice.
  (The default did flip to `False` in 0.18.0 via issue #1455, decided on its
  own merits, not as a packaging change. bleach still stays in core: a field or
  domain that opts back in must not hit a missing-package error at runtime, so
  the packaging conclusion here is unchanged.)
- **Detect the missing package from `ImportError.name` instead of
  `find_spec`.** This is simpler, but wrong for the case that matters most. An
  installed but broken package raises an `ImportError` naming itself, so a name
  check would tell the user to reinstall a package they already have. A name
  check would also miss entirely a `jinja2` miss re-raised without a `name`.
  `find_spec` distinguishes absent from present-but-broken directly.
- **Replace `werkzeug` with `contextvars` in this change to shrink core
  further.** Protean would have to reimplement the nested push/pop semantics of
  the domain-context and Unit-of-Work stacks, a real refactor with behavioral
  risk. If this packaging PR included that refactor, the same PR would carry an
  unrelated correctness risk. Deferred to its own issue.
- **Stage a Tier-1 deprecation (warn in 0.18, move in 0.19).** Rejected: with
  the imports already lazy, no natural code path exists where a warning could
  fire. The fix is also a one-word extra. The staged deprecation would add a
  release cycle without protecting anyone.

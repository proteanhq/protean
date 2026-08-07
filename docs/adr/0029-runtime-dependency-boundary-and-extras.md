# ADR-0029: Runtime Dependency Boundary and Feature Extras

**Status:** Accepted

**Date:** August 2026

## Context

A plain `pip install protean` used to pull a web server, an ASGI stack, a Jinja
template engine, an interactive REPL, a project scaffolder, and an HTML
sanitizer, whether or not the consumer ever ran a server, opened a shell, or
generated a project. The adapter ecosystem was already right: `postgresql`,
`redis`, `elasticsearch`, `flask`, and `sendgrid` are extras, installed only
when the consumer talks to that infrastructure. But several install-time-optional
concerns were hard runtime dependencies in `[project].dependencies`:

- `fastapi`, `uvicorn`, `jinja2` — the HTTP/ASGI/observatory stack, used only by
  `protean observatory` and `protean.integrations.fastapi`.
- `ipython` — the interactive shell, used only by `protean shell`.
- `copier` — project scaffolding, used only by `protean new`.

None of these are imported by `import protean` — the imports were already lazy,
gated behind a CLI subcommand or an opt-in integration module. So the cost was
not import coupling; it was **install footprint** and the dependency-conflict
surface every consumer inherited. FastAPI itself models the fix (it pushes
`uvicorn` into `fastapi[standard]`); Requests keeps its core at a handful of
dependencies.

Two more packages were candidates but stay in core after review. `bleach` (HTML
sanitization) looked optional — used only for String/Text field sanitization —
until you notice that `String()` and `Text()` default to `sanitize=True`. Nearly
every domain has a string field, so bleach runs for nearly every domain; moving
it behind an extra would make that extra a de-facto requirement and would
silently stop sanitizing for anyone who missed it. `werkzeug` is a genuine
import-time need (it backs `current_domain`/`current_uow`). Both stay in core.

Moving a package out of `[project].dependencies` is a Tier-1 breaking change
under [ADR-0004](0004-release-workflow-and-breaking-change-policy.md): code that
worked on a fat install can fail on a lean one. The question was how to draw the
core/extras boundary, what happens when a feature is used without its extra, and
how to land the break without stranding upgraders.

## Decision

**Draw the core at the domain-modeling and message-processing essentials, and
move the five install-time-optional packages behind feature extras.**

Core (`pip install protean`) keeps only what every consumer needs to define a
domain, persist through the memory adapter, and run the async engine:
`inflection`, `marshmallow`, `python-dateutil`, `typer` (the CLI framework
itself), `structlog`, `werkzeug`, `bleach`, `pydantic`, `greenlet`, and `cffi`.

The feature extras:

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

**When a feature is used without its extra, fail with an actionable message that
names the extra to install, never a bare `ModuleNotFoundError`.** The single
message builder lives in `protean.utils.dependencies.missing_dependency_message`,
so the wording is identical everywhere. The CLI commands (`new`, `shell`,
`observatory`) import their optional stack lazily inside the command body and, on
`ImportError`, print `Error: … requires the '<pkg>' package. Install it with
'pip install "protean[<extra>]"'.` and exit non-zero. The check only translates
the *expected* missing package; any other `ImportError` is re-raised so a genuine
bug inside the imported module is not masked as a missing extra. The FastAPI
integration package applies the same guard at import.

**Land the break cleanly in 0.18.0.** Because the imports were already lazy,
there is no `import protean` code path on which to emit a pre-removal
`DeprecationWarning` — the deps simply were not loaded at import. A staged
"warn then move" runway would keep the fat install for a release while warning
about a change whose fix is a single word, adding cycle time for no real
protection. Instead: move to extras in 0.18.0, ship the `all` extra as the
one-line restore of the previous behavior, provide the actionable errors, and
document the change in the 0.18 migration guide. The actionable error plus the
`all` extra **is** the Tier-1 mitigation.

## Consequences

- A plain `pip install protean` is markedly smaller and carries a smaller
  dependency-conflict surface. Consumers opt into the web stack, the shell, and
  the scaffolder only when they use them.
- Consumers who ran `protean observatory`, `protean shell`, or `protean new`, or
  imported `protean.integrations.fastapi`, must install the matching extra. They
  get a message that tells them exactly which one; a project that wants the old
  behavior wholesale adds `protean[all]`.
- CI and dev environments that already run `uv sync --all-extras` are unaffected;
  the new extras are picked up automatically.
- Deriving the boundary per feature (rather than one big `cli` bucket) means more
  extra names to document, but each install stays minimal — a REPL user does not
  drag in the scaffolder.
- `bleach`, `werkzeug`, `cffi`, and `greenlet` stay in core. `bleach` because
  String/Text fields sanitize by default (see Context); `werkzeug` because it
  backs `current_domain`/`current_uow` via `LocalProxy`/`LocalStack`. `cffi` and
  `greenlet` are not imported directly by `src/protean` and appear to be
  transitive-only. Whether `werkzeug` can be replaced by `contextvars`, and
  whether `cffi`/`greenlet` can leave core, is deferred to a separate review so
  this change stays a packaging change and does not touch the context system's
  semantics.

## Alternatives Considered

- **One coarse `cli` extra covering shell + scaffold.** Fewer names to document,
  but it couples unrelated concerns: a user who only wants a REPL would install
  the scaffolder. Rejected in favor of precise extras plus the `cli`/`all`
  bundles.
- **Move `bleach` behind a `[sanitize]` extra and fail fast when a `sanitize=True`
  field is defined without it.** Rejected: `String()` and `Text()` default to
  `sanitize=True`, so bleach runs for nearly every domain. The extra would become
  a de-facto requirement, and the "fail fast" would fire on the *default* field
  declaration, not an opt-in one. Moving it out of core would also mean flipping
  the `sanitize` default to `False` — a separate, security-relevant behavioral
  break (string fields silently stop HTML-escaping) that does not belong in a
  packaging change. bleach stays in core; revisit if that default ever flips.
- **Replace `werkzeug` with `contextvars` in this change to shrink core further.**
  Reimplementing the nested push/pop semantics of the domain-context and
  Unit-of-Work stacks is a real refactor with behavioral risk; folding it into a
  packaging change would put an unrelated correctness risk in the same PR.
  Deferred to its own issue.
- **A staged Tier-1 deprecation (warn in 0.18, move in 0.19).** Rejected: with the
  imports already lazy there is no natural code path to warn on, and the fix is a
  one-word extra. The runway would add a release cycle without protecting anyone.

# ADR-0039: Ship the developer-experience pack as package data

**Status:** Accepted

**Date:** September 2026

## Context

A coding agent is only correct about Protean if it reasons about the version of
the framework that is installed. The teaching skills and the agent instruction
surface (AGENTS.md) describe an API that changes release to release. When that
knowledge lives apart from the framework, the two drift: an agent reads guidance
for one version while the code runs another, and the model reasons about an API
that is no longer there.

The developer-experience epic ships a body of agent-facing knowledge: an
AGENTS.md source and a set of skills. It needs a home that couples it to the
framework version by construction, a runtime read path that works whether the
package is installed unpacked or zipped, and a guard that the data actually
reaches the built wheel.

Two existing data trees set the precedent. The `template/` copier tree and the
IR JSON schemas under `ir/schema/` already ship as package data inside
`protean` and are read at runtime. Hatchling includes them with no build
configuration: its wheel target picks up every file under `src/protean/`,
whatever its git status.

## Decision

We ship the pack as package data inside the `protean` wheel, under
`src/protean/dx/pack/`. The pack travels in the same distribution as the code,
so its version is the framework version and the two cannot drift.

We read the pack through `importlib.resources`. The accessor lives in
`protean.dx.pack` and is re-exported from `protean.dx`, so
`protean.dx.load_agents_source()` and `protean.dx.pack_files()` reach the data.
`importlib.resources` is the standard read path for package data and keeps
working when `protean` is installed zipped. The accessor mirrors the shape of
`protean.ir`: module-level constants (`PACK_VERSION`, `AGENTS_SOURCE`,
`SKILLS_DIR`) and `load_*` helpers.

We add no build configuration. Hatchling already ships every file under
`src/protean/` through its `packages` target, proven by `template/` and
`ir/schema/`. A CI job builds the wheel, installs it into a clean virtualenv
that cannot see the source tree, and asserts the pack is importable and readable
from the installed package. That job is the guard against silent loss of the
data from the build.

The pack's version is the framework version. `PACK_VERSION` resolves to
`protean.__version__`, the framework's single version source. A consumer reads
it to tell which framework version's guidance the pack carries, and
`bump-my-version` moves it, so it stays in step with the content it labels. A hand-typed version
constant would drift the day someone edits a skill and forgets to bump it.

## Consequences

The pack and the framework release together, so an agent reading the pack always
sees guidance for the installed code. There is no second distribution to publish
and no version pin between them.

Reading through `importlib.resources` hands consumers a `Traversable`, which is
the abstract resource interface rather than a filesystem `Path`. Code that needs
a real path on disk has to materialize one. The file-projection engine that
renders these files into a user's project (ADR-0037) reads text, so a
`Traversable` is enough.

The data files have to be committed so a clean checkout carries them. CI builds
the wheel from a fresh checkout, which holds only committed content, so an
uncommitted file drops out of that wheel with no error at build time. The
clean-venv CI check catches that, and a deleted or moved file too, because it
reads the pack from the installed wheel rather than the source tree.

The wheel grows with the pack. The skills corpus is text, so the cost is small,
and the coupling it buys is the point of the epic.

## Alternatives Considered

**A separate `protean-skills` distribution.** Publishing the pack as its own
package on PyPI reintroduces the split it was meant to close: a user can install
a skills version that does not match their framework version, and the drift is
back. Shipping inside `protean` couples them by construction.

**Reading with `Path(__file__).parent`.** The repo reads `ir/schema/` this way
today, and it works for an unpacked install. It breaks when the package is
installed zipped, because there is no file on disk to point `Path` at.
`importlib.resources` covers both cases, so the DX layer adopts it and leaves the
older read path where it is.

**A `force-include` or `artifacts` entry in the build config.** Hatchling's
default file selection already ships the pack, so an explicit build-config entry
would add configuration that restates the default. The clean-venv check verifies
the outcome without it.

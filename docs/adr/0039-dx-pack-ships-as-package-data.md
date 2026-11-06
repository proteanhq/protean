# ADR-0039: Ship the developer-experience pack as package data

**Status:** Accepted

**Date:** September 2026

## Context

A coding agent is only correct about Protean if it reasons about the installed
version of the framework. The teaching skills and the agent instruction surface
(AGENTS.md) describe an API that changes release to release. When that
knowledge lives apart from the framework, the two drift: an agent reads
guidance for one version while the code runs another, and the model reasons
about an API that is no longer there.

In the developer-experience epic, Protean ships a body of agent-facing
knowledge: an AGENTS.md source and a set of skills. This knowledge needs a
location in the package that ties it to the framework version by construction.
It also needs a runtime read path for both unpacked and zipped installs, and a
check that the built wheel contains the data.

Two existing data trees set the precedent. The `template/` copier tree and the
IR JSON schemas under `ir/schema/` already ship as package data inside
`protean` and are read at runtime. Hatchling includes them with no build
configuration: its wheel target picks up every file under `src/protean/`,
whatever its git status.

## Decision

We ship the pack as package data inside the `protean` wheel, under
`src/protean/dx/pack/`. The pack ships in the same distribution as the code, so
the pack version is always the framework version.

We read the pack through `importlib.resources`. The accessor is defined in
`protean.dx.pack` and re-exported from `protean.dx`, so you read the data
through `protean.dx.load_agents_source()` and `protean.dx.pack_files()`.
`importlib.resources` is the standard read path for package data. It also works
when `protean` is installed zipped. The accessor mirrors the shape of
`protean.ir`: module-level constants (`PACK_VERSION`, `AGENTS_SOURCE`,
`SKILLS_DIR`) and `load_*` helpers.

We add no build configuration. Hatchling already ships every file under
`src/protean/` through its `packages` target, proven by `template/` and
`ir/schema/`. A CI job builds the wheel and installs it into a clean virtualenv
with no access to the source tree. The job then asserts that the pack is
importable and readable from the installed package. That CI job catches the
case where the build silently leaves the data out of the wheel.

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
the abstract resource interface rather than a filesystem `Path`. If your code
needs a real path on disk, it has to materialize one from the `Traversable`.
The managed-file writer (ADR-0037) generates the pack files into a user's
project. The writer reads text, so a `Traversable` is enough for it.

The data files have to be committed so a clean checkout carries them. CI builds
the wheel from a fresh checkout, and a fresh checkout holds only committed
content. An uncommitted file is therefore missing from that wheel, and the
build reports no error. The clean-venv CI check catches that, and a deleted or
moved file too, because it reads the pack from the installed wheel rather than
the source tree.

The wheel grows with the pack. The skills corpus is text, so the added wheel
size is small. Tying the pack to the framework version is the goal of the
developer-experience epic.

## Alternatives Considered

**A separate `protean-skills` distribution.** Publishing the pack as its own
package on PyPI separates the pack from the framework again. A user can then
install a skills version that does not match their framework version. Shipping
inside `protean` couples them by construction.

**Reading with `Path(__file__).parent`.** The repo reads `ir/schema/` this way
today. That read path works for an unpacked install. Reading with
`Path(__file__).parent` fails for a zipped install, because a zipped install
has no file on disk for `Path` to point at. `importlib.resources` works for
both unpacked and zipped installs. The DX layer uses `importlib.resources`, and
`ir/schema/` keeps the older read path.

**A `force-include` or `artifacts` entry in the build config.** Hatchling's
default file selection already ships the pack, so an explicit build-config entry
would add configuration that restates the default. The clean-venv check verifies
the outcome without it.

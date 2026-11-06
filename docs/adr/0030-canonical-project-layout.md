# ADR-0030: Canonical Generated Project Layout

**Status:** Accepted

**Date:** August 2026

## Context

`protean new` stamps a project from `src/protean/template/`. That project's
shape is not arbitrary: element discovery and, downstream of it, the IR both
assume a specific directory layout. Until now the template files and the
discovery code encoded that assumption, and no document stated it. Without a
written layout, every later piece of this work (the additive `add` engine, the
renderer, a project manifest) would guess the layout again. Each piece would
have to guess where the domain root is, where element modules live, where tests
go, and which subtrees discovery must skip.

The layout is a contract because of how discovery works. `Domain.init(traverse=True)`
calls `_traverse()` (`src/protean/domain/__init__.py`), which:

- Treats the directory that holds the domain file (the module that constructs
  `Domain(...)`) as the **root**. `_guess_caller_path()` sets the root to the
  directory of the file that called the `Domain` constructor. It does this when
  the caller does not pass `root_path` explicitly and `DOMAIN_ROOT_PATH` is
  unset.
- Scans one level deep, without recursion: it imports every `.py` file directly
  in the root and every `.py` file directly in each immediate subdirectory,
  except the domain file itself. Each imported module executes, and its
  decorators register elements. A module nested two levels below the root (for
  example `example/handlers/foo.py`) is never imported.
- **Skips any immediate subdirectory that carries its own config file** (`domain.toml`,
  `.domain.toml`, or `pyproject.toml`). That file marks a separate boundary.
  This matches the one-domain-per-bounded-context decision (ADR-0003): one
  `Domain` is one bounded context is one IR document.

Config resolution follows the same root. `Config2.load_from_path(root_path)` looks for
`.domain.toml` / `domain.toml` / `pyproject.toml` in the root and up to two parent
directories.

Two failure modes in the 0.17 releases came directly from a layout that the
discovery path did not expect. A generated `example/__init__.py` re-exported
from its own submodules. During traversal those re-exports created partially
initialized module cycles, so a real `init(traverse=True)` crashed (#1316). And
a `logging.toml` sat in the scaffold that no adapter read (#1315). Both are
fixed, but they are the reason to fix the layout in writing rather than leave
it implied.

The IR is the other half of the contract. `Domain.to_ir()` builds the IR's
structural view (clusters, contracts, flows, projections, the elements index,
and config-derived domain metadata) from the initialized in-memory domain, not
from files on disk. `Domain.to_ir()` then runs an advisory `diagnostics` pass
that re-parses source files. That pass only adds annotations and derives no
structure. The canonical layout exists to make traversal deterministic. When
you init the canonical layout, the domain holds exactly the elements the
developer wrote and nothing spurious (no test doubles, no re-export
duplicates). The structural IR is a projection of that domain.

## Decision

We record the canonical layout below. `protean new` generates it, and discovery
and the IR expect it. A default project (package `myproj`) is shown below. The
`include_example` copier flag (default on) controls whether the `example` slice
and its test are generated. Everything else is generated either way.

```
myproj/                     # project root
├── pyproject.toml          # packaging; domain config lives in domain.toml, not here
├── Makefile, Dockerfile*, docker-compose*.yml, nginx.conf, scripts/, .github/  # deploy scaffolding
├── src/
│   └── myproj/             # importable package == domain root
│       ├── __init__.py     # empty
│       ├── domain.py       # composition root: constructs Domain(name="myproj")
│       ├── domain.toml     # domain config, co-located with domain.py
│       ├── example/        # one feature slice; generated only when include_example is on
│       │   ├── __init__.py # side-effect free (docstring only)
│       │   ├── aggregate.py
│       │   ├── commands.py
│       │   ├── events.py
│       │   ├── command_handlers.py
│       │   ├── projection.py
│       │   └── projectors.py
│       └── shared/         # cross-slice value objects, exceptions, logging helpers
│           ├── __init__.py # empty
│           ├── exceptions.py
│           ├── value_objects.py
│           └── logging.py
└── tests/
    └── myproj/             # test tree, a sibling of src/, never traversed as domain code
        ├── conftest.py     # session fixture boots the domain
        ├── test_smoke.py   # always generated, so a fresh project never collects zero tests
        ├── domain/
        │   └── __init__.py         # placeholder package; the __init__ keeps the empty dir in git
        ├── application/
        │   ├── __init__.py
        │   └── test_example.py     # generated only when include_example is on
        └── integration/
            └── __init__.py         # placeholder package; the __init__ keeps the empty dir in git
```

The rules that make this a contract, not a suggestion:

1. **Each domain has one composition root**: `src/<package>/domain.py`
   constructs the single `Domain` instance. Its directory is the discovery
   root. One `Domain` is one bounded context is one IR document (ADR-0003).

2. **Config goes in the domain root**: `domain.toml` is in `src/<package>/`
   next to `domain.py`, where `load_from_path` finds it first.

3. **Put each element module at most one directory below the domain root, with
   one concept per module.** Traversal imports any module directly in
   `src/<package>/` or directly in an immediate subpackage of it (here
   `example/` and `shared/`). Each imported module then registers its elements
   via decorators. Discovery scans one level deep only, so a module nested
   deeper (for example `example/handlers/foo.py`) is silently not discovered.
   Modules import the domain with `from <package>.domain import <domain>` and
   siblings with relative imports.

4. **Package `__init__.py` files are side-effect free**: They carry a docstring at most.
   They do not re-export from submodules. Re-exports run during traversal and
   create partially initialized module cycles. Those cycles broke
   `init(traverse=True)` in the traversal crash (#1316). Discovery finds
   elements by importing each module directly. So the re-exports add nothing
   that discovery needs, and they can break traversal.

5. **Tests live outside the domain root**: `tests/` is a sibling of `src/`, so no test
   module is ever imported as domain code during traversal. Tests boot the domain
   themselves through a session-scoped fixture in `conftest.py`.

6. **A nested config file marks a boundary discovery skips**: When a
   subdirectory of the domain root carries its own `domain.toml` /
   `.domain.toml` / `pyproject.toml`, discovery treats it as a separate
   boundary and does not traverse into it. You can add such a config file to
   keep a subtree from registering into this domain.

## Consequences

Developers of later features build against a written layout instead of
re-reading the template. The `add` engine places a new element module directly
in `src/<package>/` or in an immediate slice subpackage (one level deep, so
discovery finds it). The `add` engine does not change `__init__.py`. A project
manifest can record the domain root as the directory of the domain file. It can
also mark `tests/` as out of scope for discovery. The IR-derivation boundary is
explicit: the IR reflects the registered domain, so scaffold correctness is a
discovery question, not an IR question.

The generated project has a fixed structure. `protean new` fixes four choices:
a `src/`-layout package, a single composition root, config beside the domain
file, and tests as a sibling tree. If you want a flat layout or tests mixed in
with source, you leave the scaffold's layout and must keep discovery working
yourself. For example, you can pass `root_path` explicitly or add a config file
to exclude a subtree from discovery. That is the intended trade: the default is
correct by construction, and deviation is possible but manual.

The `__init__.py`-must-stay-empty rule is easy to violate by habit, since
re-exporting from a package initializer is idiomatic Python elsewhere. Two
groups have to know the rule: anyone who hand-edits a generated project, and
anyone who writes a code generator that changes these files. The rule is
written down in this ADR. The scaffold's `example/__init__.py` docstring also
states it inline.

## Alternatives Considered

**Prune "redundant" template files as originally scoped.** The issue first
paired this ADR with deleting template files the IR can derive. On inspection
there are none: the structural IR is computed from the registered domain model,
not from files, so no shipped file duplicates it. The Python element modules
are the domain model that the IR is built from. The other files are deployment
scaffolding, and the IR never represents them. (The one stranded file,
`logging.toml`, was an orphan that no adapter read, not an IR duplicate, and
was removed under #1315.) So the pruning half was dropped. By dropping the
pruning, we do not delete a file the project needs. The pruning rule does not
apply to any shipped file.

**Use a flat layout (no `src/`, modules beside `domain.py` at the project
root).** Discovery works with this layout. But the layout does not separate the
importable package from project files, so `tests/` or tooling files can easily
be placed inside the discovery root and be imported as domain code. With the
`src/`-layout, the importable package, and therefore the discovery root, stays
separate from project-level files.

**Put tests under the domain root (`src/<package>/tests/`).** Traversal would
then import test modules during discovery, executing test-time code and
registering test doubles into the real domain. When `tests/` is a sibling of
`src/`, traversal never imports test modules.

**Re-export from package `__init__.py` for more convenient imports.** Callers
find this convenient, but it directly caused the traversal crash (#1316):
re-exports execute during traversal and create partially initialized module
cycles. Discovery does not need them, so the cost has no matching benefit.

**Keep config only in `pyproject.toml`.** `load_from_path` supports this
option. A dedicated `domain.toml` beside `domain.py` keeps domain config next
to the composition root and out of the packaging file. `load_from_path` also
reads `domain.toml` first in the lookup order. A generated project uses the
dedicated `domain.toml` file. If you prefer `pyproject.toml` config, you can
still use it.

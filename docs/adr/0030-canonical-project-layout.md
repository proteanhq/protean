# ADR-0030: Canonical Generated Project Layout

**Status:** Accepted

**Date:** August 2026

## Context

`protean new` stamps a project from `src/protean/template/`. That project's shape is
not arbitrary: element discovery and, downstream of it, the IR both assume a specific
directory layout. Until now that assumption lived only in the template files and in the
discovery code, never written down. Every later piece of this work (the additive `add`
engine, the renderer, a project manifest) would otherwise re-guess where the domain root
is, where element modules live, where tests go, and which subtrees discovery must skip.

The layout is a contract because of how discovery works. `Domain.init(traverse=True)`
calls `_traverse()` (`src/protean/domain/__init__.py`), which:

- Treats the directory that holds the domain file (the module that constructs
  `Domain(...)`) as the **root**. When `root_path` is not passed explicitly and
  `DOMAIN_ROOT_PATH` is unset, `_guess_caller_path()` resolves it to the directory of
  the file that called the `Domain` constructor.
- Scans one level deep, not recursively: it imports every `.py` file directly in the root
  and every `.py` file directly in each immediate subdirectory (except the domain file
  itself), so each module executes and its decorators register elements. A module nested
  two levels below the root (for example `example/handlers/foo.py`) is never imported.
- **Skips any immediate subdirectory that carries its own config file** (`domain.toml`,
  `.domain.toml`, or `pyproject.toml`). That file marks a separate boundary, which lines up
  with ADR-0003: one `Domain` is one bounded context is one IR document.

Config resolution follows the same root. `Config2.load_from_path(root_path)` looks for
`.domain.toml` / `domain.toml` / `pyproject.toml` in the root and up to two parent
directories.

Two failure modes in the 0.17 line traced directly to a layout that the discovery path did
not expect. A generated `example/__init__.py` that re-exported from its own submodules created
partially initialized module cycles during traversal, so a real `init(traverse=True)`
crashed (#1316). And a `logging.toml` sat in the scaffold that no adapter read (#1315).
Both are fixed, but they are the reason to fix the layout in writing rather than leave it
implied.

The IR is the other half of the contract. `Domain.to_ir()` builds the IR's structural view
(clusters, contracts, flows, projections, the elements index, and config-derived domain
metadata) from the initialized in-memory domain, not from files on disk. It then runs an
advisory `diagnostics` pass that does re-parse source files, but that layer only annotates;
it derives no structure. So the layout's whole job is to make traversal deterministic: init
the canonical layout and the domain holds exactly the elements the developer wrote, and
nothing spurious (no test doubles, no re-export duplicates). The structural IR is a
projection of that domain.

## Decision

We record the following as the canonical layout that `protean new` generates and that
discovery and the IR expect. A default project (package `myproj`) is shown below. The
`example` slice and its test are gated on the `include_example` copier flag (default on);
everything else is generated either way.

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

1. **One composition root per domain.** `src/<package>/domain.py` constructs the single
   `Domain` instance. Its directory is the discovery root. One `Domain` is one bounded
   context is one IR document (ADR-0003).

2. **Config sits at the domain root.** `domain.toml` lives next to `domain.py` in
   `src/<package>/`, where `load_from_path` finds it first.

3. **Element modules live at most one directory below the domain root, one concept per
   module.** A module directly in `src/<package>/`, or directly in an immediate subpackage
   of it (here `example/` and `shared/`), is imported during traversal and registers via
   decorators. Discovery scans one level deep only, so a module nested deeper (for example
   `example/handlers/foo.py`) is silently not discovered. Modules import the domain with
   `from <package>.domain import <domain>` and siblings with relative imports.

4. **Package `__init__.py` files are side-effect free.** They carry a docstring at most.
   They do not re-export from submodules. Re-exports run during traversal and create
   partially initialized module cycles, which is exactly what broke `init(traverse=True)`
   in #1316. Discovery finds elements by importing each module directly, so the re-exports
   buy nothing and cost correctness.

5. **Tests live outside the domain root.** `tests/` is a sibling of `src/`, so no test
   module is ever imported as domain code during traversal. Tests boot the domain
   themselves through a session-scoped fixture in `conftest.py`.

6. **A nested config file marks a boundary discovery skips.** A subdirectory of the domain
   root that carries its own `domain.toml` / `.domain.toml` / `pyproject.toml` is treated
   as a separate boundary and is not traversed into. This is the escape hatch for a
   subtree that should not register into this domain.

## Consequences

Later work builds against a written layout instead of re-reading the template. The `add`
engine knows to drop a new element module directly in `src/<package>/` or in an immediate
slice subpackage (one level deep, so discovery finds it) and to leave `__init__.py` alone. A manifest knows the domain root is the directory of the
domain file and that `tests/` is out of scope for discovery. The IR-derivation boundary is
explicit: the IR reflects the registered domain, so scaffold correctness is a discovery
question, not an IR question.

The generated project is opinionated about structure. A `src/`-layout package, a single
composition root, config beside the domain file, and tests as a sibling tree are all
fixed. A user who wants a flat layout or tests interleaved with source has to move away
from the scaffold and take responsibility for keeping discovery working (for example by
passing `root_path` explicitly or dropping a config file to fence off a subtree). That is
the intended trade: the default is correct by construction, and deviation is possible but
manual.

The `__init__.py`-must-stay-empty rule is easy to violate by habit, since re-exporting
from a package initializer is idiomatic Python elsewhere. Anyone hand-editing a generated
project, or writing a code generator that touches these files, has to know the rule. This
ADR is where it is written down, and the scaffold's `example/__init__.py` docstring states
it inline.

## Alternatives Considered

**Prune "redundant" template files as originally scoped.** The issue first paired this ADR
with deleting template files the IR can derive. On inspection there are none: the structural
IR is computed from the registered domain model, not from files, so no shipped file
duplicates it. The Python element modules are the domain model the IR is built from, and the
rest is deployment scaffolding the IR never represents. (The one stranded file,
`logging.toml`, was an orphan that no adapter read, not an IR duplicate, and was removed
under #1315.) So the pruning half was dropped. Keeping the scope honest avoids deleting a
load-bearing file to satisfy a rule that does not apply.

**A flat layout (no `src/`, modules beside `domain.py` at the project root).** This works
for discovery but blurs the packaging boundary and makes it easy for `tests/` or tooling
files to land inside the discovery root and be imported as domain code. The `src/`-layout
keeps the importable package, and therefore the discovery root, cleanly separated from
project-level files.

**Tests under the domain root (`src/<package>/tests/`).** Traversal would then import test
modules during discovery, executing test-time code and registering test doubles into the
real domain. Keeping tests a sibling of `src/` removes that hazard entirely.

**Re-exporting from package `__init__.py` for ergonomic imports.** Convenient for callers,
but it is the direct cause of #1316: re-exports execute during traversal and create
partially initialized module cycles. Discovery does not need them, so the cost has no
matching benefit.

**Config only in `pyproject.toml`.** `load_from_path` supports it, but a dedicated
`domain.toml` beside `domain.py` keeps domain config next to the composition root and out
of the packaging file, and reads first in the lookup order. A generated project uses the
dedicated file; `pyproject.toml` config stays available for users who prefer it.

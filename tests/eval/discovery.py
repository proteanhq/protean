"""Shared subprocess setup for running a ``protean`` CLI over a produced project.

Two callers shell a ``protean`` command into a project the harness produced:
``run_verify`` (in :mod:`tests.eval.tools`) runs ``protean verify``, and
``build_ir`` (in :mod:`tests.eval.ir_probe`) runs ``protean ir show``. Both must
strip the same environment variables and discover the domain the same way, or
the result would depend on the outer shell instead of the project. This module
is the one copy of both, so a change to one applies to both callers.

The same domain discovery also answers what import package a project's modules
sit under, which :mod:`tests.eval.scoring` strips before reading an aggregate's
bounded-context segment.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

__all__ = [
    "STRIPPED_ENV_VARS",
    "discover_domain_arg",
    "discover_import_package",
    "stripped_env",
]

# Env vars dropped before a protean subprocess, mirroring the scaffold-test
# harness: VIRTUAL_ENV so a leaked value cannot point the child at a different
# source tree than sys.executable, and PROTEAN_ENV/PROTEAN_DEBUG so a value
# exported in the parent shell does not leak into the run. PROTEAN_DOMAIN and
# DOMAIN_ROOT_PATH too: the CLI honours the former over the `-d` argument and
# the latter as a Domain root, so either leaked value would point the run at a
# different domain than the produced project and make the result depend on the
# outer environment.
STRIPPED_ENV_VARS = (
    "VIRTUAL_ENV",
    "PROTEAN_ENV",
    "PROTEAN_DEBUG",
    "PROTEAN_DOMAIN",
    "DOMAIN_ROOT_PATH",
)


def stripped_env() -> dict[str, str]:
    """The parent environment minus :data:`STRIPPED_ENV_VARS`.

    The removed vars would otherwise point a protean subprocess at a different
    source tree or domain than the produced project, so a run's result would
    depend on the outer shell rather than the project's files.
    """
    return {
        key: value for key, value in os.environ.items() if key not in STRIPPED_ENV_VARS
    }


def discover_domain_arg(root: Path) -> str | None:
    """Return the ``-d`` value a protean command needs for the project at *root*,
    or ``None`` when a root ``domain.py`` makes the default discovery enough.

    A root ``domain.py`` is what the default discovery already finds, so it needs
    no ``-d``. Otherwise a single ``src/<pkg>/domain.py`` is addressed by its
    path; the CLI resolves the domain the module defines (or reports the file's
    own error if it will not import). A layout that matches neither returns
    ``None`` and lets the command report the missing domain itself.
    """
    if (root / "domain.py").is_file():
        return None
    candidates = (
        sorted((root / "src").glob("*/domain.py")) if (root / "src").is_dir() else []
    )
    if len(candidates) != 1:
        return None
    package = candidates[0].parent.name
    return f"src/{package}/domain.py"


def discover_import_package(root: Path) -> str:
    """Return the import package the project at *root* puts its modules under,
    or ``""`` when its modules sit under no package.

    The scorer needs this to read an aggregate's bounded context off its module
    name: the context is the first segment after the package, and the module
    name alone cannot say where the package ends. ``order.aggregate`` is either
    package ``order`` holding module ``aggregate``, or context ``order`` holding
    ``aggregate.py`` with no package at all, and the two read the same.

    The project on disk settles it, because the same two layouts
    :func:`discover_domain_arg` reads are the only ones the harness can run a
    protean command over: a ``src/<pkg>/domain.py`` project imports as ``<pkg>``,
    and a root ``domain.py`` project has the root itself on the import path, so
    its top-level directories are modules rather than a package.
    """
    domain_arg = discover_domain_arg(root)
    if domain_arg is None:
        return ""
    return PurePosixPath(domain_arg).parent.name

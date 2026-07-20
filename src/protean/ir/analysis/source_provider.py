"""Parsed-source access for IR diagnostic rules.

:class:`SourceProvider` is the single place where ``protean check`` turns a
module into an ``ast.Module``. It resolves a module name to a file with
``importlib.util.find_spec``, reads it as UTF-8, parses it once, and caches the
result — including the ``None`` that means "no source available".

Two contracts every caller depends on:

- **Fail open.** No lookup ever raises. A module that cannot be located, read,
  or parsed yields ``None``, and the rule that asked for it skips the module
  rather than aborting the diagnostics pass.
- **Read-only trees.** Every caller for a given module receives the *same*
  ``ast.Module`` object. Rules must treat it as immutable; mutating a tree
  would corrupt every later rule's view of that module.

Analysis is of source **as written**, which may diverge from what runs (a
module can be patched, generated, or shadowed at import time). That is the
intended trade: it is reproducible, which a runtime inspection is not.

A provider caches for its own lifetime only — one instance per
:class:`~protean.ir.builder.IRBuilder` — so a module edited between two builds
in the same process is re-read by the next build.
"""

from __future__ import annotations

import ast
import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protean.domain import Domain

# A subdirectory carrying one of these is a domain of its own, so it is not
# part of this domain's source. Mirrors ``Domain._traverse``.
_DOMAIN_MARKER_FILES = ("domain.toml", ".domain.toml", "pyproject.toml")


class SourceProvider:
    """Locate, parse, and cache the source of a domain's modules."""

    def __init__(self, domain: Domain) -> None:
        self._domain = domain
        # Module name -> parsed tree, or None when source is unavailable.
        # Negative results are cached too, so an unresolvable module is
        # attempted exactly once per provider.
        self._trees: dict[str, ast.Module | None] = {}
        self._modules: tuple[str, ...] | None = None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def tree(self, module_name: str) -> ast.Module | None:
        """Return the parsed source of ``module_name``, or ``None``.

        ``None`` covers every reason source is unavailable: the module does not
        resolve, resolving it raised, it has no file origin (built-in, frozen,
        namespace package), the file cannot be read, or it does not parse. The
        answer is cached either way, so a module is located and parsed at most
        once per provider.
        """
        if module_name in self._trees:
            return self._trees[module_name]

        tree = self._parse(module_name)
        self._trees[module_name] = tree
        return tree

    @staticmethod
    def _parse(module_name: str) -> ast.Module | None:
        try:
            spec = importlib.util.find_spec(module_name)
        # Broad by design: ``find_spec`` may import a not-yet-loaded parent
        # package and re-execute its ``__init__``, which can raise anything.
        # Fail open (skip the module) rather than abort the diagnostics pass.
        except Exception:
            return None

        origin = getattr(spec, "origin", None) if spec else None
        if not origin or origin in ("built-in", "frozen"):
            return None

        try:
            with open(origin, encoding="utf-8") as fh:
                return ast.parse(fh.read())
        # OSError: unreadable file. SyntaxError: invalid source. ValueError:
        # source the parser or the UTF-8 decoder rejects outright (a NUL byte,
        # undecodable bytes — ``UnicodeDecodeError`` is a ``ValueError``).
        except (OSError, SyntaxError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------

    def modules(self) -> tuple[str, ...]:
        """Module names in the domain's package, sorted, computed once.

        Enumeration mirrors the directory rules of ``Domain._traverse``: the
        directory holding the domain file plus its immediate subdirectories,
        minus ``__pycache__`` and minus any subdirectory carrying its own
        ``domain.toml`` / ``.domain.toml`` / ``pyproject.toml`` (that is a
        separate domain). Module names are built from the path relative to the
        root directory's parent, the same convention ``_traverse`` imports
        them under.

        Nothing is read or parsed here — enumeration is cheap, and the trees
        are only produced on demand via :meth:`tree` or :meth:`iter_trees`.

        This is *not* the resolution path for a specific element: registered
        elements frequently live outside ``root_path``. Use :meth:`tree` with
        the element's ``__module__`` for that.
        """
        if self._modules is None:
            self._modules = self._discover_modules()
        return self._modules

    def iter_trees(self) -> Iterator[tuple[str, ast.Module]]:
        """Yield ``(module_name, tree)`` for :meth:`modules`, in that order.

        Modules whose source is unavailable are skipped rather than yielded
        with a ``None`` tree — a rule iterating the domain's source should not
        have to restate the fail-open contract.
        """
        for module_name in self.modules():
            tree = self.tree(module_name)
            if tree is not None:
                yield module_name, tree

    def _discover_modules(self) -> tuple[str, ...]:
        root_path = Path(self._domain.root_path)
        # ``root_path`` is commonly given as ``__file__``; the package is the
        # directory that file sits in. Resolved to an absolute path so that a
        # relative ``root_path`` (``"."``) still has a parent to name the
        # package against.
        root_dir = (root_path.parent if root_path.is_file() else root_path).resolve()
        # Module names are relative to the parent of the root directory, so
        # the root directory itself is the top-level package name.
        system_folder_path = root_dir.parent

        directories = [root_dir]
        try:
            entries = sorted(os.listdir(root_dir))
        except OSError:
            return ()
        for name in entries:
            subdirectory = root_dir / name
            if name == "__pycache__" or not subdirectory.is_dir():
                continue
            if any((subdirectory / f).is_file() for f in _DOMAIN_MARKER_FILES):
                continue
            directories.append(subdirectory)

        module_names: set[str] = set()
        for directory in directories:
            package_name = str(directory)[len(str(system_folder_path)) + 1 :].replace(
                os.sep, "."
            )
            try:
                filenames = os.listdir(directory)
            except OSError:  # pragma: no cover - directory vanished mid-walk
                continue
            for filename in filenames:
                if not filename.endswith(".py") or not (directory / filename).is_file():
                    continue
                if filename == "__init__.py":
                    module_names.add(package_name)
                else:
                    module_names.add(f"{package_name}.{filename[: -len('.py')]}")

        return tuple(sorted(module_names))

"""Parsed-source access for IR diagnostic rules.

:class:`SourceProvider` is the single place where ``protean check`` turns a
module into an ``ast.Module``. It caches every answer, including the ``None``
that means "no source available".

There are two ways in, and they resolve source differently on purpose:

- :meth:`tree` takes a **module name** and resolves it the way Python would,
  through ``importlib.util.find_spec``. That is what a rule needs for a
  registered element, whose ``__module__`` is often outside the domain's
  package. It inherits Python's resolution: a module that is not importable
  has no tree, and a same-named module earlier on ``sys.path`` wins.
- :meth:`modules` and :meth:`iter_trees` walk the domain's package on **disk**
  and parse the files they find. No import machinery is involved, so a package
  that is not on ``sys.path``, or is shadowed by an installed one, is still
  read from the domain's own directory.

Two contracts every caller depends on:

- **Fail open.** No lookup raises. A module that cannot be located, read, or
  parsed yields ``None``, and the rule that asked for it skips the module
  rather than aborting the diagnostics pass.
- **Read-only trees.** Within one provider, every caller for a given module
  receives the *same* ``ast.Module`` object. Rules must treat it as immutable;
  mutating a tree would corrupt every later rule's view of that module.

Analysis is of source **as written**, which may diverge from what runs (a
module can be patched, generated, or shadowed at import time). That is the
intended trade: it is reproducible, which a runtime inspection is not. One
caveat on reproducibility: ``find_spec`` behind :meth:`tree` can import a
parent package and so run its ``__init__``.

A provider caches for its own lifetime only, and the convention is one
instance per :class:`~protean.ir.builder.IRBuilder`, so a module edited between
two builds in the same process is re-read by the next build. A provider is not
thread-safe; give each thread its own.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protean.domain import Domain

# A subdirectory carrying one of these is a domain of its own, so it is not
# part of this domain's source. Same list ``Domain._traverse`` uses.
_DOMAIN_MARKER_FILES = ("domain.toml", ".domain.toml", "pyproject.toml")


class SourceProvider:
    """Locate, parse, and cache the source of a domain's modules."""

    def __init__(self, domain: Domain) -> None:
        self._domain = domain
        # Module name -> parsed tree, or None when source is unavailable.
        # Negative results are cached too, so an unresolvable module is
        # attempted exactly once per provider.
        self._trees: dict[str, ast.Module | None] = {}
        # Module name -> the file the cached tree came from, or None when no
        # file was found. Also tells us whether a cached entry came from the
        # package walk or from name resolution.
        self._origins: dict[str, str | None] = {}
        self._package: tuple[tuple[str, Path], ...] | None = None
        self._module_names: tuple[str, ...] | None = None

    # ------------------------------------------------------------------
    # Name-based access
    # ------------------------------------------------------------------

    def tree(self, module_name: str) -> ast.Module | None:
        """Return the parsed source of ``module_name``, or ``None``.

        The module is resolved through ``importlib.util.find_spec``, so this is
        the right entry point for a registered element's ``__module__``, which
        need not live under the domain's ``root_path``.

        ``None`` covers every reason source is unavailable: the module does not
        resolve, resolving it raised, it has no file origin (built-in, frozen,
        namespace package), the file cannot be read, or it does not parse. The
        answer is cached either way, so a module is located and parsed at most
        once per provider.
        """
        if module_name in self._trees:
            return self._trees[module_name]

        origin = self._resolve(module_name)
        tree = self._parse(origin) if origin is not None else None
        self._origins[module_name] = origin
        self._trees[module_name] = tree
        return tree

    def origin(self, module_name: str) -> str | None:
        """Return the file :meth:`tree` read ``module_name`` from, or ``None``.

        A rule that turns a node's line number into a located diagnostic needs
        the path the tree came from; this is it, without a second resolution.
        The path is reported even when the file failed to parse.
        """
        self.tree(module_name)
        return self._origins[module_name]

    @staticmethod
    def _resolve(module_name: str) -> str | None:
        """Return the file a module name resolves to, or ``None``."""
        try:
            spec = find_spec(module_name)
        # Broad by design: ``find_spec`` may import a not-yet-loaded parent
        # package and re-execute its ``__init__``, which can raise anything.
        # Fail open (skip the module) rather than abort the diagnostics pass.
        except Exception:
            return None

        origin = getattr(spec, "origin", None) if spec else None
        if not isinstance(origin, str) or not origin:
            return None
        # Not paths: a built-in or frozen module has no file to read.
        if origin in ("built-in", "frozen"):
            return None
        return origin

    @staticmethod
    def _parse(path: str | Path) -> ast.Module | None:
        """Parse a file into a tree, or ``None`` if it cannot be parsed."""
        try:
            # Bytes rather than text: handed bytes, ``ast.parse`` honours a
            # UTF-8 BOM and a PEP 263 coding declaration. Reading as UTF-8
            # text would fail on both.
            return ast.parse(Path(path).read_bytes(), filename=str(path))
        # Broad by design, because the fail-open contract admits no exception:
        # an unreadable file (OSError), invalid source (SyntaxError,
        # ValueError) and parser exhaustion on pathological input
        # (RecursionError, MemoryError) all mean the same thing, "no tree".
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Package walk
    # ------------------------------------------------------------------

    def modules(self) -> tuple[str, ...]:
        """Module names found in the domain's package, sorted, computed once.

        The walk follows the directory rules ``Domain._traverse`` uses to
        import a domain: the directory holding the domain file plus its
        immediate subdirectories, minus ``__pycache__`` and minus any
        subdirectory carrying its own ``domain.toml`` / ``.domain.toml`` /
        ``pyproject.toml`` (that is a separate domain). Module names are built
        from the path relative to the root directory's parent.

        It is not a copy of ``_traverse``. Unlike ``_traverse`` this walk keeps
        the module that defines the domain (it is source worth analysing), and
        it names modules off an absolute path so a relative ``root_path`` still
        produces usable names.

        No file is read or parsed here, though the walk does list the root
        directory and each retained subdirectory. Trees are produced on demand
        by :meth:`iter_trees`.

        This is *not* the resolution path for a specific element: registered
        elements frequently live outside ``root_path``. Use :meth:`tree` with
        the element's ``__module__`` for that.
        """
        if self._module_names is None:
            self._module_names = tuple(name for name, _ in self._walk())
        return self._module_names

    def iter_trees(self) -> Iterator[tuple[str, ast.Module]]:
        """Yield ``(module_name, tree)`` for :meth:`modules`, in that order.

        Each tree is parsed from the file the walk found, not from whatever the
        name resolves to on ``sys.path``, so the domain's own source is what
        gets analysed even when the package is not importable.

        Modules whose source cannot be parsed are skipped rather than yielded
        with a ``None`` tree — a rule iterating the domain's source should not
        have to restate the fail-open contract.
        """
        for module_name, path in self._walk():
            tree = self._tree_at(module_name, path)
            if tree is not None:
                yield module_name, tree

    def _tree_at(self, module_name: str, path: Path) -> ast.Module | None:
        """Parse ``path`` as ``module_name``, caching under the module name.

        The path wins over anything :meth:`tree` may have cached for the same
        name: inside the package walk, the file on disk is the answer.
        """
        origin = str(path)
        if self._origins.get(module_name) == origin:
            return self._trees[module_name]

        tree = self._parse(path)
        self._origins[module_name] = origin
        self._trees[module_name] = tree
        return tree

    def _walk(self) -> tuple[tuple[str, Path], ...]:
        if self._package is None:
            self._package = self._discover_modules()
        return self._package

    def _discover_modules(self) -> tuple[tuple[str, Path], ...]:
        raw_root = str(self._domain.root_path or "")
        if not raw_root.strip():
            # An empty ``root_path`` would resolve to the current directory and
            # enumerate whatever happens to be there.
            return ()

        root_path = Path(raw_root)
        # ``root_path`` is commonly given as ``__file__``; the package is the
        # directory that file sits in. Made absolute (without resolving
        # symlinks, which would rename the package) so that a relative
        # ``root_path`` still has a parent to name the package against.
        root_dir = Path(
            os.path.abspath(root_path.parent if root_path.is_file() else root_path)
        )
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

        found: dict[str, Path] = {}
        for directory in directories:
            package_name = ".".join(directory.relative_to(system_folder_path).parts)
            if not package_name:
                # Only reachable when the root directory is the filesystem
                # root, where there is no package to name.
                continue
            try:
                filenames = os.listdir(directory)
            except OSError:  # pragma: no cover - directory vanished mid-walk
                continue
            for filename in filenames:
                path = directory / filename
                if os.path.splitext(filename)[1] != ".py" or not path.is_file():
                    continue
                if filename == "__init__.py":
                    found[package_name] = path
                else:
                    stem = os.path.splitext(filename)[0]
                    found[f"{package_name}.{stem}"] = path

        return tuple((name, found[name]) for name in sorted(found))

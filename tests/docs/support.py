"""Shared helpers for the tests that check the ``docs_src`` examples."""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_SRC = REPO_ROOT / "docs_src"
DOCS = REPO_ROOT / "docs"


def module_name_for(path: str) -> str:
    """Return the ``sys.modules`` name for an example path relative to ``docs_src``.

    ``guides/getting-started/hello.py`` becomes
    ``docs_src_guides_getting_started_hello``. Every character that is not a
    letter, digit or underscore becomes an underscore, so hyphenated folders
    and numbered file names give a valid, unique module name.
    """
    stem = path.removesuffix(".py")
    return "docs_src_" + re.sub(r"[^0-9A-Za-z_]", "_", stem)


def load_example(path: str, root: Path = DOCS_SRC) -> types.ModuleType:
    """Load the example at ``path`` (relative to ``root``) and return its module.

    The module is executed fresh on every call and registered in
    ``sys.modules`` under :func:`module_name_for`, so code that looks a class
    up by its module (pickling, ``fully_qualified_name``) finds it. Its
    ``__name__`` is never ``"__main__"``, so the example's
    ``if __name__ == "__main__"`` demo block does not run.

    ``test_docs_src_is_tested.py`` reads the string literal passed as ``path``
    to find out which examples a test loads, so pass a literal.
    """
    filepath = root / path
    if not filepath.is_file():
        raise FileNotFoundError(f"no docs_src example at {path}")

    name = module_name_for(path)
    spec = importlib.util.spec_from_file_location(name, filepath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # Do not leave a half-run module behind for the next import to find.
        sys.modules.pop(name, None)
        raise
    return module


def package_dirs(root: Path) -> dict[str, Path]:
    """Map each package's folder name under ``root`` to its folder.

    A package is a folder with an ``__init__.py``. Code imports a ``docs_src``
    package by its folder name alone, so two packages with the same folder name
    would shadow each other. That raises ``ValueError``.
    """
    packages: dict[str, Path] = {}
    for init in sorted(root.rglob("__init__.py")):
        folder = init.parent
        if folder.name in packages:
            raise ValueError(
                f"two docs_src packages share the folder name {folder.name!r}: "
                f"{packages[folder.name].relative_to(root).as_posix()} and "
                f"{folder.relative_to(root).as_posix()}"
            )
        packages[folder.name] = folder
    return packages


def imported_package_files(
    tree: ast.AST, root: Path, packages: dict[str, Path]
) -> set[str]:
    """Return the package files under ``root`` that the imports in ``tree`` load.

    ``import shop`` loads only ``shop/__init__.py``. ``import shop.models``,
    ``from shop.models import Thing`` and ``from shop import models`` also load
    ``shop/models.py``. Paths are relative to ``root``.
    """
    dotted: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dotted.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            dotted.append(node.module)
            # ``from shop import models`` may name a module, not an attribute.
            dotted.extend(f"{node.module}.{alias.name}" for alias in node.names)

    loaded: set[str] = set()
    for name in dotted:
        package, _, rest = name.partition(".")
        folder = packages.get(package)
        if folder is None:
            continue
        loaded.add((folder / "__init__.py").relative_to(root).as_posix())
        module = folder / f"{rest.split('.')[0]}.py"
        if rest and module.is_file():
            loaded.add(module.relative_to(root).as_posix())
    return loaded

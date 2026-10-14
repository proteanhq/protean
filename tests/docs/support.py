"""Shared helpers for the tests that check the ``docs_src`` examples."""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import types
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_SRC = REPO_ROOT / "docs_src"
DOCS = REPO_ROOT / "docs"

# Seconds one child pytest run of an example may take before it is stopped.
EXAMPLE_TESTS_TIMEOUT = 120


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


def run_example_tests(
    path: str,
    *,
    env: dict[str, str] | None = None,
    args: Sequence[str] = (),
    root: Path = DOCS_SRC,
) -> subprocess.CompletedProcess[str]:
    """Run the pytest tests in the example at ``path`` in a child process.

    ``path`` is relative to ``root``, as in :func:`load_example`. The child runs
    ``python -m pytest <file>`` from a fresh temporary folder, so files the
    tests write (a SQLite database, say) land there and not in the repo.
    ``root`` and the parent folder of every package under it go on
    ``PYTHONPATH``, as in ``test_docs_src_runs.py``, so an example imports a
    ``docs_src`` package such as ``myapp`` by its folder name. The parent's
    ``PYTHONPATH`` follows them. ``env`` adds environment variables, and
    ``args`` adds pytest options after the file.

    The child gets an empty config file from the temporary folder with ``-c``,
    so the repo's ``[tool.pytest.ini_options]`` (``--doctest-modules``,
    ``testpaths``, the warning filters) does not apply: a reader's project would
    not have it. pytest still loads every ``conftest.py`` in the example's
    folder and the folders above it. Protean's pytest plugin loads through its
    ``pytest11`` entry point. The cache plugin is off, so no ``.pytest_cache``
    folder is written next to the example, and ``PYTHONDONTWRITEBYTECODE`` is
    set, so no ``__pycache__`` folder is written either. The ``PYTEST_*``
    variables and ``PROTEAN_ENV`` in the parent's environment do not reach the
    child unless ``env`` passes them, so a developer's shell settings do not
    change the result.

    A run that takes longer than ``EXAMPLE_TESTS_TIMEOUT`` seconds raises
    ``TimeoutError`` with the output the child wrote so far in its message.

    Returns the finished process with its output. The caller checks
    ``returncode``; pytest exits with 5 when it collects no tests.
    ``test_docs_src_is_tested.py`` reads the string literal passed as ``path``,
    so pass a literal.
    """
    filepath = root / path
    if not filepath.is_file():
        raise FileNotFoundError(f"no docs_src example at {path}")

    package_parents = sorted(
        {str(folder.parent) for folder in package_dirs(root).values()}
    )
    pythonpath = [str(root), *package_parents]
    if os.environ.get("PYTHONPATH"):
        pythonpath.append(os.environ["PYTHONPATH"])
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("PYTEST_") and name != "PROTEAN_ENV"
    }
    child_env = {
        **inherited,
        "PYTHONPATH": os.pathsep.join(pythonpath),
        "PYTHONDONTWRITEBYTECODE": "1",
        **(env or {}),
    }
    with tempfile.TemporaryDirectory() as workdir:
        config = Path(workdir) / "pytest.ini"
        config.write_text("[pytest]\n", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(config),
            "-p",
            "no:cacheprovider",
            str(filepath),
            *args,
        ]
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                cwd=workdir,
                env=child_env,
                timeout=EXAMPLE_TESTS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            # pytest shows the exception message and not its attributes, so
            # the output the child wrote so far goes into the message.
            output = _text(exc.stdout) + _text(exc.stderr)
            raise TimeoutError(
                f"{path} ran longer than {EXAMPLE_TESTS_TIMEOUT}s. "
                f"Output so far:\n{output}"
            ) from exc


def _text(stream: str | bytes | None) -> str:
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream or ""


# The counts on pytest's last summary line: "3 passed, 1 skipped in 0.12s".
_SUMMARY_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)\b")


def outcome_counts(result: subprocess.CompletedProcess[str]) -> dict[str, int]:
    """Return the outcome counts from the summary line of a child pytest run.

    ``{"passed": 3, "skipped": 1}`` for a run that ended with
    ``3 passed, 1 skipped in 0.12s``. The count for ``error`` and ``errors``
    is reported as ``"errors"``. A run with no summary line gives ``{}``.
    """
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return {}
    counts: dict[str, int] = {}
    for number, outcome in _SUMMARY_COUNT.findall(lines[-1]):
        key = "errors" if outcome.startswith("error") else outcome
        counts[key] = int(number)
    return counts


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

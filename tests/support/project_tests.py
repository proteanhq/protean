"""Run real pytest files inside another project, in a child interpreter.

Some checks must run in a fresh interpreter: code that ``protean new`` or
``protean add`` generates, or an example domain that has to stay out of the
test process. Those checks live in ordinary test files in this repo, in a folder
whose ``conftest.py`` keeps the main suite from collecting them. A test copies
the files into the project with :func:`run_tests_in` and asserts the result
with :func:`passed_count`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def project_env(project: Path) -> dict[str, str]:
    """Return the environment for running *project* uninstalled.

    The project's ``src/`` goes on ``PYTHONPATH``. ``VIRTUAL_ENV`` is dropped so
    it cannot point the child at a different interpreter or source tree than
    ``sys.executable``. ``PROTEAN_ENV`` and ``PROTEAN_DEBUG`` are dropped too:
    Protean's pytest plugin only sets ``PROTEAN_ENV`` with ``setdefault``, so a
    value exported in the parent shell would leak into the child run.
    ``DATABASE_URL`` would point the project's ``domain.toml`` at another
    database, and ``PYTEST_ADDOPTS`` could reorder or filter the child's tests.
    """
    src = str(project / "src")
    existing = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": src + os.pathsep + existing if existing else src,
    }
    for name in (
        "VIRTUAL_ENV",
        "PROTEAN_ENV",
        "PROTEAN_DEBUG",
        "DATABASE_URL",
        "PYTEST_ADDOPTS",
    ):
        env.pop(name, None)
    return env


def run_tests_in(
    project: Path, sources: Sequence[Path], into: str = "tests"
) -> subprocess.CompletedProcess[str]:
    """Copy *sources* into ``project/into`` and run pytest on the copies.

    pytest runs from *project*, so it uses the project's own configuration and
    ``conftest.py`` files. Returns the finished process; it never raises on a
    test failure.
    """
    target = project / into
    target.mkdir(parents=True, exist_ok=True)
    copies = []
    for source in sources:
        copy = target / source.name
        shutil.copyfile(source, copy)
        copies.append(str(copy.relative_to(project)))

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-q",
            *copies,
        ],
        cwd=project,
        env=project_env(project),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )


def passed_count(result: subprocess.CompletedProcess[str]) -> int:
    """Return the number of passed tests in a pytest summary, or 0 when the
    summary names none."""
    match = re.search(r"\b(\d+) passed\b", result.stdout)
    return int(match.group(1)) if match else 0

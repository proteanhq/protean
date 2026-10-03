"""Run every ``docs_src`` example and require each domain it defines to initialize.

Every ``docs_src/**/*.py`` file is code a documentation page shows. This test
runs each one and, for every ``Domain`` the file defines, calls
``domain.init(traverse=False)``. A file that raises, or whose domain fails to
initialize, fails the test with the file's path.

The examples run in child interpreters, as in ``tests/dx/test_examples.py``:

- Each file runs under its own ``run_name``, which is never ``"__main__"``, so
  its ``if __name__ == "__main__"`` demo block is skipped and its registrations
  stay out of this test process.
- Each file runs with its working directory set to a fresh temporary folder,
  so a file that writes ``test.db`` or ``myapp.db`` leaves nothing in the repo.
- Each file has a time limit, so a file that blocks names itself.

A package under ``docs_src`` (a folder with an ``__init__.py``) runs as one
example: the runner imports the package and each of its modules, then
initializes the package's domains.

A file that needs a running service is listed in ``MARKERS`` with the pytest
marker for that service. Each marker group runs in its own child, under a test
that carries the marker, so the FULL leg runs it and the core lane skips it.
A file that shows an error on purpose is listed in ``EXPECTED_EXCEPTIONS``, and
passes only if it raises that exception.

The include guard at the end requires every ``docs_src`` file to be included
by a documentation page with ``--8<--``, so files no page shows do not pile up.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.docs.support import DOCS, DOCS_SRC
from tests.shared import POSTGRES_URI

pytestmark = pytest.mark.no_test_domain

# Example path (relative to docs_src) -> the pytest marker of the service it needs.
MARKERS: dict[str, str] = {
    "adapters/database/postgresql/001.py": "postgresql",
    "guides/getting-started/tutorial/ch10.py": "fastapi",
}

# Marker -> environment variables its examples read to reach the service. The
# examples default to the service's standard port; the test suite's Docker
# services listen on other ports (see tests/shared.py).
SERVICE_ENV: dict[str, dict[str, str]] = {
    "postgresql": {"DATABASE_URL": POSTGRES_URI},
}

# Example path (relative to docs_src) -> the exception it raises on purpose.
EXPECTED_EXCEPTIONS: dict[str, str] = {
    # Points at a database that does not exist to show the error.
    "adapters/001.py": "ConfigurationError",
}

# Seconds one example may run before the runner stops it and reports it.
EXAMPLE_TIMEOUT = 60


def package_dirs(root: Path) -> list[Path]:
    """Return every package folder under ``root``: a folder with an ``__init__.py``."""
    return sorted(init.parent for init in root.rglob("__init__.py"))


def discover_examples(root: Path) -> list[str]:
    """Return every example under ``root`` as a path relative to ``root``.

    A plain ``.py`` file is one example. A package is one example, named by its
    folder, and the files inside it are not listed on their own.
    """
    packages = package_dirs(root)
    files = [
        path
        for path in root.rglob("*.py")
        if not any(path.is_relative_to(package) for package in packages)
    ]
    return sorted(path.relative_to(root).as_posix() for path in files + packages)


def _independent_example_count(root: Path) -> int:
    """Count the examples under ``root`` with ``os.walk``.

    This walks the tree directly and does not reuse :func:`discover_examples`,
    so a broken glob in the discovery shows up as a count mismatch.
    """
    total = 0
    for _folder, subfolders, filenames in os.walk(root):
        if "__init__.py" in filenames:
            # The package counts once, and nothing below it counts again.
            total += 1
            subfolders.clear()
            continue
        total += sum(1 for name in filenames if name.endswith(".py"))
    return total


# The child-interpreter runner. It reads a JSON spec (the root, the examples to
# run, the expected exceptions, the time limit and the report path), runs each
# example in its own temporary working folder, initializes every domain the
# example defines, and writes a JSON report with the count it ran and a line per
# failure. It runs all examples before reporting, so one run names every broken
# file. It writes the report to a file, not a stream, so the framework's own
# logging cannot corrupt it.
_RUNNER = """
import importlib
import json
import os
import pathlib
import runpy
import signal
import sys
import tempfile

spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
root = pathlib.Path(spec["root"])
timeout = spec["timeout"]
# Examples import each other by their path under docs_src, as the test suite's
# conftest allows, so the child puts the root on sys.path the same way. A file
# that imports a docs_src package (ch10 imports bookshelf) finds it by its
# folder name, so each package's parent folder goes on sys.path too.
sys.path.insert(0, str(root))
for init in sorted(root.rglob("__init__.py")):
    sys.path.insert(0, str(init.parent.parent))

from protean.domain import Domain


class ExampleTimeout(BaseException):
    pass


def on_alarm(signum, frame):
    raise ExampleTimeout("did not finish within %d seconds" % timeout)


signal.signal(signal.SIGALRM, on_alarm)


def run_package(folder):
    namespaces = [vars(importlib.import_module(folder.name))]
    for module_file in sorted(folder.glob("*.py")):
        if module_file.name != "__init__.py":
            module = importlib.import_module(folder.name + "." + module_file.stem)
            namespaces.append(vars(module))
    return namespaces


def run_example(example, index):
    path = root / example
    if path.is_dir():
        namespaces = run_package(path)
    else:
        namespaces = [runpy.run_path(str(path), run_name="_docs_src_example_%d_" % index)]
    domains = {}
    for namespace in namespaces:
        for value in namespace.values():
            if isinstance(value, Domain):
                domains[id(value)] = value
    for domain in domains.values():
        domain.init(traverse=False)


def class_names(exc):
    return [cls.__name__ for cls in type(exc).__mro__]


workspace = pathlib.Path(tempfile.mkdtemp(prefix="docs_src_examples_"))
failures = []
for index, example in enumerate(spec["examples"]):
    workdir = workspace / str(index)
    workdir.mkdir()
    os.chdir(workdir)
    raised = None
    signal.alarm(timeout)
    try:
        run_example(example, index)
    except BaseException as exc:  # report the failure, then keep going
        raised = exc
    finally:
        signal.alarm(0)

    expected = spec["expected"].get(example)
    if expected is None:
        if raised is not None:
            failures.append(
                "%s: %s: %s" % (example, type(raised).__name__, raised)
            )
    elif raised is None:
        failures.append("%s: expected %s, but it raised nothing" % (example, expected))
    elif expected not in class_names(raised):
        failures.append(
            "%s: expected %s, but it raised %s: %s"
            % (example, expected, type(raised).__name__, raised)
        )

pathlib.Path(spec["report"]).write_text(
    json.dumps({"count": len(spec["examples"]), "failures": failures})
)
sys.exit(1 if failures else 0)
"""


def run_examples(
    root: Path,
    examples: list[str],
    expected: dict[str, str],
    workdir: Path,
    timeout: int = EXAMPLE_TIMEOUT,
    env: dict[str, str] | None = None,
) -> dict:
    """Run ``examples`` (paths relative to ``root``) in one child interpreter.

    Returns the child's report: ``{"count": <examples run>, "failures": [...]}``.
    Each failure line starts with the example's path relative to ``root``.
    ``env`` adds environment variables to the child's environment.
    """
    spec_path = workdir / "spec.json"
    report_path = workdir / "report.json"
    spec_path.write_text(
        json.dumps(
            {
                "root": str(root),
                "examples": examples,
                "expected": expected,
                "timeout": timeout,
                "report": str(report_path),
            }
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER, str(spec_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=workdir,
        env={**os.environ, **(env or {})},
        # The per-example limit fires first; this is the backstop for the run.
        timeout=timeout * len(examples) + 120,
    )
    assert report_path.is_file(), (
        f"the example runner crashed before writing its report "
        f"(exit {result.returncode}):\n{result.stderr}"
    )
    report = json.loads(report_path.read_text())
    assert (result.returncode == 0) == (report["failures"] == []), result.stderr
    return report


EXAMPLES = discover_examples(DOCS_SRC)
GROUPS = [None, *sorted(set(MARKERS.values()))]


def _group_params() -> list:
    return [pytest.param(None, id="core")] + [
        pytest.param(marker, id=marker, marks=getattr(pytest.mark, marker))
        for marker in GROUPS[1:]
    ]


def test_example_discovery_is_not_vacuous():
    # If the discovery matched nothing, the run below would pass while checking
    # nothing. Pin the count to an independent walk, so a broken glob fails, and
    # to a floor near the real corpus size (119 examples today), so a mass
    # deletion cannot slip under it.
    assert EXAMPLES, "discovered no examples under docs_src"
    assert len(EXAMPLES) == _independent_example_count(DOCS_SRC)
    assert len(EXAMPLES) >= 110
    assert "guides/getting-started/tutorial/bookshelf" in EXAMPLES


def test_tables_name_only_existing_examples():
    # A table entry for a file that was renamed or deleted would sit there
    # unnoticed and could hide a new file with the old name.
    stale = sorted(
        path for path in [*MARKERS, *EXPECTED_EXCEPTIONS] if path not in EXAMPLES
    )
    assert stale == [], f"table entries name no docs_src example: {stale}"


@pytest.mark.parametrize("marker", _group_params())
def test_every_example_runs_and_initializes(marker, tmp_path):
    examples = [path for path in EXAMPLES if MARKERS.get(path) == marker]
    assert examples, f"no examples in the {marker or 'core'} group"

    report = run_examples(
        DOCS_SRC,
        examples,
        EXPECTED_EXCEPTIONS,
        tmp_path,
        env=SERVICE_ENV.get(marker),
    )

    assert report["count"] == len(examples)
    assert report["failures"] == [], (
        "docs_src examples failed to run and initialize:\n"
        + "\n".join(report["failures"])
    )


# --- The include guard -------------------------------------------------------

# `--8<-- "guides/x/001.py"`, `--8<-- "guides/x/001.py:section"` or
# `--8<-- "guides/x/001.py:10:20"`. The path is everything before the first colon.
_INCLUDE = re.compile(r'--8<--\s+"([^":]+)[^"]*"')


def included_paths(docs: Path) -> set[str]:
    """Return every path a page under ``docs`` includes with ``--8<--``."""
    included = set()
    for page in docs.rglob("*.md"):
        included.update(_INCLUDE.findall(page.read_text(encoding="utf-8")))
    return included


def _imported_top_level_names(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def unincluded_files(root: Path, docs: Path) -> list[str]:
    """Return the ``.py`` files under ``root`` that no page under ``docs`` includes.

    A file counts as included when a page includes it directly. A file inside a
    package also counts when a directly included file imports that package, so
    a chapter that imports the package covers its modules.
    """
    files = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py"))
    included = {path for path in included_paths(docs) if path in files}
    imported = set()
    for path in included:
        imported |= _imported_top_level_names(root / path)

    missing = []
    for path in files:
        if path in included:
            continue
        package = next(
            (p for p in package_dirs(root) if (root / path).is_relative_to(p)), None
        )
        if package is not None and package.name in imported:
            continue
        missing.append(path)
    return missing


def test_every_docs_src_file_is_included_by_a_page():
    # The guard reads real includes: make sure it found some, so a broken
    # pattern cannot pass by matching nothing.
    included = included_paths(DOCS)
    assert "guides/getting-started/hello.py" in included

    missing = unincluded_files(DOCS_SRC, DOCS)
    assert missing == [], (
        "docs_src files that no page includes with --8<-- (include them in a "
        "page, or delete them):\n" + "\n".join(missing)
    )


# --- The runner and the guard, on synthetic files -----------------------------


def _write(root: Path, path: str, source: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)


_GOOD = """
from protean import Domain
from protean.fields import String

domain = Domain(name="Good")


@domain.aggregate
class Thing:
    name: String()
"""

# The aggregate names a child entity that does not exist. Registering it
# succeeds; only initializing the domain fails, when the reference is resolved.
_BROKEN = """
from protean import Domain
from protean.fields import HasMany, String

{name} = Domain(name="{label}")


@{name}.aggregate
class Basket:
    name: String()
    items = HasMany("Missing")
"""


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "docs_src"
    root.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()
    return root, workdir


class TestRunner:
    def test_a_clean_example_passes(self, corpus):
        root, workdir = corpus
        _write(root, "good.py", _GOOD)

        report = run_examples(root, ["good.py"], {}, workdir)

        assert report == {"count": 1, "failures": []}

    def test_a_file_that_raises_on_import_names_the_file(self, corpus):
        root, workdir = corpus
        _write(root, "good.py", _GOOD)
        _write(root, "guides/raises.py", "raise RuntimeError('boom')\n")

        report = run_examples(root, ["good.py", "guides/raises.py"], {}, workdir)

        assert report["failures"] == ["guides/raises.py: RuntimeError: boom"]

    def test_a_domain_that_fails_init_names_the_file(self, corpus):
        root, workdir = corpus
        _write(root, "broken.py", _BROKEN.format(name="domain", label="Broken"))

        report = run_examples(root, ["broken.py"], {}, workdir)

        assert len(report["failures"]) == 1
        assert report["failures"][0].startswith("broken.py: ")
        assert "Unresolved references" in report["failures"][0]

    def test_every_domain_in_a_file_is_initialized(self, corpus):
        # The first domain is clean and only the second is broken, so the
        # failure shows the runner initializes every domain, not just one.
        root, workdir = corpus
        source = _GOOD + _BROKEN.format(name="second", label="Second")
        _write(root, "two_domains.py", source)

        report = run_examples(root, ["two_domains.py"], {}, workdir)

        assert len(report["failures"]) == 1
        assert report["failures"][0].startswith("two_domains.py: ")
        assert "Unresolved references" in report["failures"][0]

    def test_a_main_block_is_never_run(self, corpus):
        # If the runner used run_name "__main__", the block would sleep past
        # the one-second limit and the example would fail with a timeout.
        root, workdir = corpus
        source = _GOOD + (
            "\nif __name__ == '__main__':\n    import time\n    time.sleep(3600)\n"
        )
        _write(root, "demo.py", source)

        report = run_examples(root, ["demo.py"], {}, workdir, timeout=5)

        assert report == {"count": 1, "failures": []}

    def test_a_blocking_example_names_itself(self, corpus):
        root, workdir = corpus
        _write(root, "blocks.py", "import time\ntime.sleep(3600)\n")

        report = run_examples(root, ["blocks.py"], {}, workdir, timeout=1)

        assert report["failures"] == [
            "blocks.py: ExampleTimeout: did not finish within 1 seconds"
        ]

    def test_an_expected_exception_that_is_raised_passes(self, corpus):
        root, workdir = corpus
        _write(
            root,
            "shows_error.py",
            "from protean.exceptions import ConfigurationError\n"
            "raise ConfigurationError('no database')\n",
        )

        report = run_examples(
            root, ["shows_error.py"], {"shows_error.py": "ConfigurationError"}, workdir
        )

        assert report == {"count": 1, "failures": []}

    def test_an_expected_exception_that_is_not_raised_fails(self, corpus):
        root, workdir = corpus
        _write(root, "good.py", _GOOD)

        report = run_examples(
            root, ["good.py"], {"good.py": "ConfigurationError"}, workdir
        )

        assert report["failures"] == [
            "good.py: expected ConfigurationError, but it raised nothing"
        ]

    def test_a_different_exception_than_expected_fails(self, corpus):
        root, workdir = corpus
        _write(root, "wrong.py", "raise ValueError('not this one')\n")

        report = run_examples(
            root, ["wrong.py"], {"wrong.py": "ConfigurationError"}, workdir
        )

        assert report["failures"] == [
            (
                "wrong.py: expected ConfigurationError, but it raised "
                "ValueError: not this one"
            )
        ]

    def test_files_written_by_an_example_stay_out_of_the_root(self, corpus):
        root, workdir = corpus
        # The SQLite adapter tests write ``test.db`` into the working folder,
        # so this example writes a name no other test uses.
        written = "docs_src_runner_probe.db"
        _write(
            root,
            "writes.py",
            _GOOD + f"\nopen({written!r}, 'w').write('x')\n",
        )

        report = run_examples(root, ["writes.py"], {}, workdir)

        assert report == {"count": 1, "failures": []}
        assert not (root / written).exists()
        assert not (workdir / written).exists()
        assert not (Path.cwd() / written).exists()

    def test_a_package_runs_as_one_example(self, corpus):
        root, workdir = corpus
        _write(
            root,
            "app/shop/__init__.py",
            "from protean import Domain\n\ndomain = Domain(name='Shop')\n",
        )
        _write(
            root,
            "app/shop/handlers.py",
            _BROKEN.replace(
                '{name} = Domain(name="{label}")', "from shop import domain"
            ).format(name="domain"),
        )

        assert discover_examples(root) == ["app/shop"]
        report = run_examples(root, ["app/shop"], {}, workdir)

        # The broken aggregate lives in a submodule, so this fails only if the
        # runner imports the package's modules before initializing its domain.
        assert len(report["failures"]) == 1
        assert report["failures"][0].startswith("app/shop: ")
        assert "Unresolved references" in report["failures"][0]


class TestIncludeGuard:
    def test_a_file_no_page_includes_is_named(self, tmp_path):
        root, docs = tmp_path / "docs_src", tmp_path / "docs"
        _write(root, "guides/shown.py", "x = 1\n")
        _write(root, "guides/orphan.py", "x = 1\n")
        _write(docs, "page.md", '```python\n--8<-- "guides/shown.py"\n```\n')

        assert unincluded_files(root, docs) == ["guides/orphan.py"]

    def test_a_section_or_line_range_include_counts(self, tmp_path):
        root, docs = tmp_path / "docs_src", tmp_path / "docs"
        _write(root, "guides/a.py", "x = 1\n")
        _write(root, "guides/b.py", "x = 1\n")
        _write(
            docs,
            "page.md",
            '--8<-- "guides/a.py:full"\n\n--8<-- "guides/b.py:3:9"\n',
        )

        assert unincluded_files(root, docs) == []

    def test_package_modules_count_through_a_chapter_that_imports_them(self, tmp_path):
        root, docs = tmp_path / "docs_src", tmp_path / "docs"
        _write(root, "t/shop/__init__.py", "domain = None\n")
        _write(root, "t/shop/models.py", "x = 1\n")
        _write(root, "t/chapter.py", "from shop.models import x\n")
        _write(docs, "page.md", '--8<-- "t/chapter.py:full"\n')

        assert unincluded_files(root, docs) == []

    def test_package_modules_are_named_when_no_included_file_imports_them(
        self, tmp_path
    ):
        root, docs = tmp_path / "docs_src", tmp_path / "docs"
        _write(root, "t/shop/__init__.py", "domain = None\n")
        _write(root, "t/shop/models.py", "x = 1\n")
        _write(root, "t/chapter.py", "import os\n")
        _write(docs, "page.md", '--8<-- "t/chapter.py:full"\n')

        assert unincluded_files(root, docs) == [
            "t/shop/__init__.py",
            "t/shop/models.py",
        ]

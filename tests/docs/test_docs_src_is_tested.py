"""Require every ``docs_src`` example to be loaded by a test.

``test_docs_src_runs.py`` proves each example runs and initializes. This guard
asks for more: a test that loads the example. It cannot tell whether the test
then checks what the example does; it finds the loaded examples by reading test
source for these calls and imports, without running it:

- a ``load_example("<path>")`` or ``run_example_tests("<path>")`` call in any
  file under ``tests/docs/`` loads the example at that path (relative to
  ``docs_src``);
- a ``run_example_tests("<path>")`` call also loads every ``conftest.py`` in
  the example's folder and the folders above it, because pytest loads them,
  and the ``docs_src`` package modules that the example and those conftests
  import;
- an import of a ``docs_src`` package in any of those files loads the modules
  it names: ``import bookshelf`` loads only ``bookshelf/__init__.py``, and
  ``import bookshelf.models`` also loads ``bookshelf/models.py``.

``ALLOWLIST`` lists the examples no test loads yet. A file that is neither
loaded nor listed fails, and so does a listed file that a test now loads, so
the list shrinks as tests are written and never hides a loaded file.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.docs.support import (
    DOCS_SRC,
    REPO_ROOT,
    imported_package_files,
    package_dirs,
)

pytestmark = pytest.mark.no_test_domain

TESTS_DOCS = REPO_ROOT / "tests" / "docs"

# Calls whose first argument names a docs_src example the test loads.
LOADERS = {"load_example", "run_example_tests"}

# docs_src examples that no test loads yet. Remove an entry when a test loads it.
ALLOWLIST: set[str] = set()


def _docs_src_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*.py")}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _string_arg(node: ast.Call, keyword: str) -> str | None:
    if node.args:
        first = node.args[0]
    else:
        first = next((kw.value for kw in node.keywords if kw.arg == keyword), None)
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _pytest_run_files(path: str, root: Path, packages: dict[str, Path]) -> set[str]:
    """Return the files a pytest run of ``path`` loads, relative to ``root``.

    Raises ``ValueError`` when ``path`` points outside ``root``, and
    ``SyntaxError`` naming the file when one of those files does not parse.
    """
    root = root.resolve()
    example = (root / path).resolve()
    if not example.is_relative_to(root):
        raise ValueError(f"run_example_tests({path!r}) points outside {root}")
    files = [example]
    folder = example.parent
    while folder.is_relative_to(root):
        conftest = folder / "conftest.py"
        if conftest.is_file():
            files.append(conftest)
        if folder == root:
            break
        folder = folder.parent

    loaded = {file.relative_to(root).as_posix() for file in files}
    for file in files:
        if file.is_file():
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
            except SyntaxError as exc:
                raise SyntaxError(f"{file} does not parse: {exc}") from exc
            loaded |= imported_package_files(tree, root, packages)
    return loaded


def loaded_examples(test_files: list[Path], root: Path) -> set[str]:
    """Return the ``root``-relative paths the given test files load.

    ``test_files`` are read for ``load_example`` and ``run_example_tests``
    calls, and a ``run_example_tests`` call also loads the conftests and
    package modules pytest would load with it. They are also read for imports
    of a package under ``root``, which load the package modules they name. A
    call that passes its own ``root=`` loads from somewhere else, so it does
    not count.
    """
    packages = package_dirs(root)
    loaded: set[str] = set()
    for test_file in test_files:
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in LOADERS and not any(
                    kw.arg == "root" for kw in node.keywords
                ):
                    path = _string_arg(node, "path")
                    if path is not None and name == "run_example_tests":
                        loaded |= _pytest_run_files(path, root, packages)
                    elif path is not None:
                        loaded.add(path)
        loaded |= imported_package_files(tree, root, packages)
    return loaded


def coverage_problems(
    root: Path, loaded: set[str], allowlist: set[str]
) -> tuple[list[str], list[str]]:
    """Return ``(untested, stale)`` for the files under ``root``.

    ``untested`` are files no test loads and the allowlist does not list.
    ``stale`` are allowlist entries a test now loads, or that name no file.
    """
    files = _docs_src_files(root)
    untested = sorted(files - loaded - allowlist)
    stale = sorted((allowlist & loaded) | (allowlist - files))
    return untested, stale


def _real_loaded() -> set[str]:
    return loaded_examples(sorted(TESTS_DOCS.rglob("*.py")), DOCS_SRC)


def test_the_loaded_set_is_read_from_real_tests():
    # A parser that matched nothing would leave every file in the allowlist and
    # pass. Pin known loads: tutorial chapters, a package import, load_example.
    loaded = _real_loaded()
    assert "guides/getting-started/tutorial/ch01.py" in loaded
    assert "guides/getting-started/es-tutorial/ch22.py" in loaded
    assert "guides/getting-started/tutorial/bookshelf/models.py" in loaded
    assert "guides/getting-started/hello.py" in loaded


def test_every_docs_src_file_is_loaded_by_a_test():
    untested, stale = coverage_problems(DOCS_SRC, _real_loaded(), ALLOWLIST)

    assert untested == [], (
        "docs_src files that no test loads (load them with load_example in a "
        "test under tests/docs/, or list them in ALLOWLIST):\n" + "\n".join(untested)
    )
    assert stale == [], (
        "ALLOWLIST entries to remove (a test loads the file now, or the file "
        "is gone):\n" + "\n".join(stale)
    )


# --- The guard, on synthetic files ---------------------------------------------


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "docs_src"
    for name in ["guides/a.py", "guides/b.py", "tut/ch01.py", "tut/ch02.py"]:
        _write(root / name, "x = 1\n")
    _write(root / "tut/shop/__init__.py", "domain = None\n")
    _write(root / "tut/shop/models.py", "x = 1\n")
    tests = tmp_path / "tests"
    return root, tests


class TestCoverageGuard:
    def test_load_example_calls_and_package_imports_count(self, layout):
        root, tests = layout
        _write(tests / "test_a.py", 'load_example("guides/a.py")\n')
        _write(
            tests / "test_tut.py",
            'import shop.models\nload_example("tut/ch01.py")\n',
        )

        loaded = loaded_examples([tests / "test_a.py", tests / "test_tut.py"], root)

        assert loaded == {
            "guides/a.py",
            "tut/ch01.py",
            "tut/shop/__init__.py",
            "tut/shop/models.py",
        }

    def test_a_load_example_call_with_its_own_root_does_not_count(self, layout):
        root, tests = layout
        _write(tests / "test_a.py", 'load_example("guides/a.py", root=tmp)\n')

        assert loaded_examples([tests / "test_a.py"], root) == set()

    def test_a_file_neither_loaded_nor_allowlisted_is_named(self, layout):
        root, tests = layout
        _write(tests / "test_a.py", 'load_example(path="guides/a.py")\n')
        loaded = loaded_examples([tests / "test_a.py"], root)

        untested, stale = coverage_problems(
            root,
            loaded,
            {
                "tut/ch01.py",
                "tut/ch02.py",
                "tut/shop/__init__.py",
                "tut/shop/models.py",
            },
        )

        assert untested == ["guides/b.py"]
        assert stale == []

    def test_an_allowlisted_file_that_is_loaded_is_named_stale(self, layout):
        root, tests = layout
        _write(tests / "test_a.py", 'load_example("guides/a.py")\n')
        loaded = loaded_examples([tests / "test_a.py"], root)
        allowlist = _docs_src_files(root)

        untested, stale = coverage_problems(root, loaded, allowlist)

        assert untested == []
        assert stale == ["guides/a.py"]

    def test_an_allowlisted_file_that_is_gone_is_named_stale(self, layout):
        root, _ = layout
        allowlist = _docs_src_files(root) | {"guides/deleted.py"}

        untested, stale = coverage_problems(root, set(), allowlist)

        assert untested == []
        assert stale == ["guides/deleted.py"]

    def test_importing_only_the_package_does_not_load_its_modules(self, layout):
        root, tests = layout
        _write(tests / "test_tut.py", "import shop\n")
        loaded = loaded_examples([tests / "test_tut.py"], root)

        untested, _ = coverage_problems(
            root, loaded, {"guides/a.py", "guides/b.py", "tut/ch01.py", "tut/ch02.py"}
        )

        assert loaded == {"tut/shop/__init__.py"}
        assert untested == ["tut/shop/models.py"]

    def test_a_from_import_of_a_package_module_loads_it(self, layout):
        root, tests = layout
        _write(tests / "test_tut.py", "from shop import models\n")

        loaded = loaded_examples([tests / "test_tut.py"], root)

        assert loaded == {"tut/shop/__init__.py", "tut/shop/models.py"}

    def test_a_run_example_tests_call_counts(self, layout):
        root, tests = layout
        _write(tests / "test_a.py", 'run_example_tests("guides/b.py")\n')

        assert loaded_examples([tests / "test_a.py"], root) == {"guides/b.py"}

    def test_a_run_example_tests_call_loads_conftests_above_and_their_imports(
        self, layout
    ):
        root, tests = layout
        _write(root / "conftest.py", "x = 1\n")
        _write(root / "guides/deep/conftest.py", "from shop import models\n")
        _write(root / "guides/deep/test_x.py", "import shop\n")
        _write(root / "guides/other/conftest.py", "x = 1\n")
        _write(tests / "test_a.py", 'run_example_tests("guides/deep/test_x.py")\n')

        assert loaded_examples([tests / "test_a.py"], root) == {
            "conftest.py",
            "guides/deep/conftest.py",
            "guides/deep/test_x.py",
            "tut/shop/__init__.py",
            "tut/shop/models.py",
        }

    def test_a_run_example_tests_path_with_dot_dot_is_normalised(self, layout):
        root, tests = layout
        _write(root / "conftest.py", "x = 1\n")
        _write(tests / "test_a.py", 'run_example_tests("tut/../guides/b.py")\n')

        assert loaded_examples([tests / "test_a.py"], root) == {
            "conftest.py",
            "guides/b.py",
        }

    @pytest.mark.parametrize("path", ["../outside/test_y.py", "/abs/test_y.py"])
    def test_a_run_example_tests_path_outside_the_root_is_rejected(self, layout, path):
        root, tests = layout
        _write(tests / "test_a.py", f"run_example_tests({path!r})\n")

        with pytest.raises(ValueError, match="points outside"):
            loaded_examples([tests / "test_a.py"], root)

    def test_a_conftest_that_does_not_parse_is_named(self, layout):
        root, tests = layout
        _write(root / "guides/conftest.py", "def broken(:\n")
        _write(tests / "test_a.py", 'run_example_tests("guides/b.py")\n')

        with pytest.raises(SyntaxError, match="guides/conftest.py does not parse"):
            loaded_examples([tests / "test_a.py"], root)

    def test_a_load_example_call_does_not_load_conftests(self, layout):
        root, tests = layout
        _write(root / "guides/conftest.py", "x = 1\n")
        _write(tests / "test_a.py", 'load_example("guides/a.py")\n')

        assert loaded_examples([tests / "test_a.py"], root) == {"guides/a.py"}

    def test_a_run_example_tests_call_with_its_own_root_does_not_count(self, layout):
        root, tests = layout
        _write(tests / "test_a.py", 'run_example_tests("guides/b.py", root=tmp)\n')

        assert loaded_examples([tests / "test_a.py"], root) == set()

    def test_a_load_example_call_through_the_module_counts(self, layout):
        root, tests = layout
        _write(tests / "test_a.py", 'support.load_example("guides/b.py")\n')

        assert loaded_examples([tests / "test_a.py"], root) == {"guides/b.py"}

    def test_two_packages_with_the_same_folder_name_are_rejected(self, layout):
        root, _ = layout
        _write(root / "other/shop/__init__.py", "domain = None\n")

        with pytest.raises(ValueError, match="share the folder name 'shop'"):
            package_dirs(root)

"""SourceProvider: module resolution, parse caching, and package enumeration."""

import ast
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

from protean import Domain
from protean.ir.analysis import SourceProvider

REAL_MODULE = "tests.ir.support.infra_import_domain"


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_package(tmp_path: Path, package: str) -> Path:
    """A package tree exercising every enumeration rule.

    Returns the package directory. Contents::

        <package>/__init__.py          -> <package>
        <package>/models.py            -> <package>.models
        <package>/notes.txt            -> excluded (not .py)
        <package>/sub/__init__.py      -> <package>.sub
        <package>/sub/thing.py         -> <package>.sub.thing
        <package>/nested/__init__.py   -> excluded (carries domain.toml)
        <package>/__pycache__/junk.py  -> excluded
    """
    root = tmp_path / package
    _write(root / "__init__.py")
    _write(root / "models.py", "VALUE = 1\n")
    _write(root / "notes.txt", "not python")
    _write(root / "sub" / "__init__.py")
    _write(root / "sub" / "thing.py", "VALUE = 2\n")
    _write(root / "nested" / "__init__.py")
    _write(root / "nested" / "domain.toml", "")
    _write(root / "__pycache__" / "junk.py", "VALUE = 3\n")
    return root


def _provider_for(root: Path, name: str = "SourceTest") -> SourceProvider:
    return SourceProvider(Domain(name=name, root_path=str(root)))


@pytest.fixture
def provider(tmp_path):
    """A provider whose domain points at an empty directory — enough for the
    name-based ``tree()`` tests, which never touch the enumeration."""
    return _provider_for(tmp_path)


class TestParseCache:
    def test_same_tree_object_is_returned_and_parsed_once(self, provider, monkeypatch):
        calls = []
        real_parse = ast.parse

        def counting_parse(source, *args, **kwargs):
            calls.append(source)
            return real_parse(source, *args, **kwargs)

        monkeypatch.setattr(
            "protean.ir.analysis.source_provider.ast.parse", counting_parse
        )

        first = provider.tree(REAL_MODULE)
        second = provider.tree(REAL_MODULE)

        assert isinstance(first, ast.Module)
        assert first is second
        assert len(calls) == 1

    def test_failed_lookup_is_cached_too(self, provider, monkeypatch):
        """A module that does not resolve is attempted exactly once — the
        ``None`` verdict is cached like a tree is."""
        calls = []
        real_find_spec = importlib.util.find_spec

        def counting_find_spec(name, *args, **kwargs):
            calls.append(name)
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(
            "protean.ir.analysis.source_provider.importlib.util.find_spec",
            counting_find_spec,
        )

        assert provider.tree("no_such_module_at_all") is None
        assert provider.tree("no_such_module_at_all") is None
        assert len(calls) == 1

    def test_cache_is_per_provider(self, provider, tmp_path):
        """Two providers do not share a cache, so a module edited between two
        builds in one process is re-read rather than served stale."""
        other = _provider_for(tmp_path, name="SourceTestOther")

        assert provider.tree(REAL_MODULE) is not other.tree(REAL_MODULE)


class TestFailOpen:
    """Every branch that cannot produce a tree returns ``None`` and does not
    raise, so a diagnostics pass is never aborted by unreadable source."""

    def test_nonexistent_module(self, provider):
        assert provider.tree("definitely_not_a_module") is None

    def test_module_whose_parent_is_not_a_package(self, provider):
        # ``os`` is a module, not a package, so find_spec raises here.
        assert provider.tree("os.no_such_sub") is None

    def test_find_spec_raising(self, provider, monkeypatch):
        def boom(name, *args, **kwargs):
            raise RuntimeError("parent __init__ blew up")

        monkeypatch.setattr(
            "protean.ir.analysis.source_provider.importlib.util.find_spec", boom
        )

        assert provider.tree(REAL_MODULE) is None

    @pytest.mark.parametrize("origin", [None, "built-in", "frozen"])
    def test_spec_without_usable_origin(self, provider, monkeypatch, origin):
        spec = importlib.util.find_spec(REAL_MODULE)
        assert spec is not None
        monkeypatch.setattr(spec, "origin", origin)
        monkeypatch.setattr(
            "protean.ir.analysis.source_provider.importlib.util.find_spec",
            lambda *a, **k: spec,
        )

        assert provider.tree(REAL_MODULE) is None

    def test_unreadable_file(self, provider, monkeypatch):
        def refuse(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr("builtins.open", refuse)

        assert provider.tree(REAL_MODULE) is None

    def test_syntax_error(self, tmp_path, monkeypatch):
        _write(tmp_path / "brokensyntaxpkg" / "__init__.py")
        _write(tmp_path / "brokensyntaxpkg" / "bad.py", "def (:\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()

        assert _provider_for(tmp_path).tree("brokensyntaxpkg.bad") is None

    def test_source_with_nul_byte(self, tmp_path, monkeypatch):
        _write(tmp_path / "nulbytepkg" / "__init__.py")
        (tmp_path / "nulbytepkg" / "bad.py").write_bytes(b"VALUE = 1\x00\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()

        assert _provider_for(tmp_path).tree("nulbytepkg.bad") is None

    def test_undecodable_source(self, tmp_path, monkeypatch):
        _write(tmp_path / "badencodingpkg" / "__init__.py")
        (tmp_path / "badencodingpkg" / "bad.py").write_bytes(b"VALUE = '\xff\xfe'\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()

        assert _provider_for(tmp_path).tree("badencodingpkg.bad") is None


class TestEnumeration:
    def test_lists_package_modules(self, tmp_path):
        root = _build_package(tmp_path, "enumpkg")

        assert _provider_for(root).modules() == (
            "enumpkg",
            "enumpkg.models",
            "enumpkg.sub",
            "enumpkg.sub.thing",
        )

    def test_excludes_pycache_non_python_and_nested_domains(self, tmp_path):
        root = _build_package(tmp_path, "exclusionpkg")

        modules = _provider_for(root).modules()

        assert not [m for m in modules if "__pycache__" in m or "junk" in m]
        assert not [m for m in modules if "notes" in m]
        # ``nested`` carries its own domain.toml — it is a separate domain.
        assert not [m for m in modules if m.startswith("exclusionpkg.nested")]

    @pytest.mark.parametrize(
        "marker", ["domain.toml", ".domain.toml", "pyproject.toml"]
    )
    def test_every_domain_marker_excludes_a_subdirectory(self, tmp_path, marker):
        root = tmp_path / f"marker{marker.replace('.', '')}pkg"
        _write(root / "__init__.py")
        _write(root / "child" / "__init__.py")
        _write(root / "child" / marker, "")

        assert not [m for m in _provider_for(root).modules() if ".child" in m]

    def test_root_path_given_as_a_file_enumerates_its_directory(self, tmp_path):
        """The ``root_path=__file__`` idiom resolves to the containing package."""
        root = _build_package(tmp_path, "filerootpkg")

        from_file = _provider_for(root / "__init__.py").modules()

        assert from_file == _provider_for(root).modules()
        assert "filerootpkg" in from_file

    def test_missing_root_directory_yields_nothing(self, tmp_path):
        assert _provider_for(tmp_path / "does_not_exist").modules() == ()

    def test_order_is_sorted_and_stable_across_providers(self, tmp_path):
        root = _build_package(tmp_path, "orderpkg")

        first = _provider_for(root).modules()
        second = _provider_for(root).modules()

        assert first == second
        assert list(first) == sorted(first)

    def test_enumeration_does_not_parse(self, tmp_path, monkeypatch):
        """Enumeration is cheap by contract: listing a domain's modules must
        not read or parse a single file."""
        root = _build_package(tmp_path, "lazypkg")
        monkeypatch.setattr(
            "protean.ir.analysis.source_provider.ast.parse",
            lambda *a, **k: pytest.fail("enumeration must not parse"),
        )

        assert len(_provider_for(root).modules()) == 4


class TestIterTrees:
    def test_yields_parsed_modules_in_enumeration_order(self, tmp_path, monkeypatch):
        root = _build_package(tmp_path, "itertreespkg")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        provider = _provider_for(root)

        yielded = list(provider.iter_trees())

        assert len(yielded) > 0, "Expected parsed modules but got none"
        assert [name for name, _ in yielded] == list(provider.modules())
        for _, tree in yielded:
            assert isinstance(tree, ast.Module)

    def test_skips_modules_without_usable_source(self, tmp_path, monkeypatch):
        root = tmp_path / "skippkg"
        _write(root / "__init__.py")
        _write(root / "fine.py", "VALUE = 1\n")
        _write(root / "bad.py", "def (:\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        provider = _provider_for(root)

        names = [name for name, _ in provider.iter_trees()]

        assert "skippkg.bad" in provider.modules()
        assert names == ["skippkg", "skippkg.fine"]

    def test_reuses_the_parse_cache(self, tmp_path, monkeypatch):
        root = _build_package(tmp_path, "reusepkg")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        provider = _provider_for(root)

        first = dict(provider.iter_trees())
        second = dict(provider.iter_trees())

        assert first and first.keys() == second.keys()
        for name, tree in first.items():
            assert tree is second[name]


@pytest.fixture(autouse=True)
def _cleanup_temp_packages():
    """Drop the temp packages the tests import, so a later test in the same
    process does not resolve a stale ``sys.modules`` entry."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.split(".")[0].endswith("pkg"):
            del sys.modules[name]

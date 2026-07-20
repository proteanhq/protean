"""SourceProvider: module resolution, parse caching, and package enumeration."""

import ast
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from protean import Domain
from protean.ir.analysis import SourceProvider
from protean.ir.analysis import source_provider as source_provider_module
from protean.ir.builder import IRBuilder

pytestmark = pytest.mark.no_test_domain

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
        <package>/weird.py/            -> excluded (a directory, not a file)
        <package>/sub/__init__.py      -> <package>.sub
        <package>/sub/thing.py         -> <package>.sub.thing
        <package>/nested/__init__.py   -> excluded (carries domain.toml)
        <package>/__pycache__/junk.py  -> excluded
    """
    root = tmp_path / package
    _write(root / "__init__.py")
    _write(root / "models.py", "VALUE = 1\n")
    _write(root / "notes.txt", "not python")
    (root / "weird.py").mkdir(parents=True)
    _write(root / "sub" / "__init__.py")
    _write(root / "sub" / "thing.py", "VALUE = 2\n")
    _write(root / "nested" / "__init__.py")
    _write(root / "nested" / "domain.toml", "")
    _write(root / "__pycache__" / "junk.py", "VALUE = 3\n")
    return root


def _provider_for(root: Path, name: str = "SourceTest") -> SourceProvider:
    return SourceProvider(Domain(name=name, root_path=str(root)))


def _importable(tmp_path: Path, monkeypatch, package: str, **files: bytes) -> str:
    """Write an importable one-module package and return the module name."""
    root = tmp_path / package
    _write(root / "__init__.py")
    for filename, content in files.items():
        (root / f"{filename}.py").write_bytes(content)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    return package


@pytest.fixture
def provider(tmp_path):
    """A provider whose domain points at an empty directory — enough for the
    name-based ``tree()`` tests, which never touch the package walk."""
    return _provider_for(tmp_path)


class TestParseCache:
    def test_same_tree_object_is_returned_and_parsed_once(self, provider):
        """Identity is the proof: a second parse would build a new object."""
        first = provider.tree(REAL_MODULE)
        second = provider.tree(REAL_MODULE)

        assert isinstance(first, ast.Module)
        assert first is second

    def test_failed_lookup_is_cached_too(self, provider, monkeypatch):
        """A module that does not resolve is attempted exactly once — the
        ``None`` verdict is cached like a tree is."""
        calls = []
        real_find_spec = source_provider_module.find_spec

        def counting_find_spec(name, *args, **kwargs):
            calls.append(name)
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(source_provider_module, "find_spec", counting_find_spec)

        assert provider.tree("no_such_module_at_all") is None
        assert provider.tree("no_such_module_at_all") is None
        assert calls == ["no_such_module_at_all"]

    def test_cache_is_per_provider(self, provider, tmp_path):
        """Two providers do not share a cache, so a module edited between two
        builds in one process is re-read rather than served stale."""
        other = _provider_for(tmp_path, name="SourceTestOther")

        assert provider.tree(REAL_MODULE) is not other.tree(REAL_MODULE)

    def test_origin_reports_the_file_the_tree_came_from(self, provider):
        origin = provider.origin(REAL_MODULE)

        assert origin is not None
        assert origin.endswith(os.path.join("support", "infra_import_domain.py"))

    def test_origin_is_none_when_the_module_does_not_resolve(self, provider):
        assert provider.origin("definitely_not_a_module") is None

    def test_origin_is_reported_even_when_the_file_does_not_parse(
        self, tmp_path, monkeypatch
    ):
        package = _importable(tmp_path, monkeypatch, "originbadpkg", bad=b"def (:\n")
        provider = _provider_for(tmp_path)

        assert provider.tree(f"{package}.bad") is None
        assert provider.origin(f"{package}.bad") == str(tmp_path / package / "bad.py")


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

        monkeypatch.setattr(source_provider_module, "find_spec", boom)

        assert provider.tree(REAL_MODULE) is None

    @pytest.mark.parametrize("origin", [None, "built-in", "frozen"])
    def test_spec_without_usable_origin_is_never_opened(
        self, provider, monkeypatch, origin
    ):
        """``built-in`` and ``frozen`` are not paths, so the guard must reject
        them before anything tries to read them as files."""
        parsed = []
        monkeypatch.setattr(
            source_provider_module,
            "find_spec",
            lambda *a, **k: SimpleNamespace(origin=origin),
        )
        monkeypatch.setattr(
            SourceProvider, "_parse", staticmethod(lambda path: parsed.append(path))
        )

        assert provider.tree(REAL_MODULE) is None
        assert parsed == []

    def test_unreadable_file(self, provider, monkeypatch, tmp_path):
        # A directory as the origin: reading it raises IsADirectoryError.
        monkeypatch.setattr(
            source_provider_module,
            "find_spec",
            lambda *a, **k: SimpleNamespace(origin=str(tmp_path)),
        )

        assert provider.tree(REAL_MODULE) is None

    def test_syntax_error(self, tmp_path, monkeypatch):
        package = _importable(tmp_path, monkeypatch, "brokensyntaxpkg", bad=b"def (:\n")

        assert _provider_for(tmp_path).tree(f"{package}.bad") is None

    def test_source_with_nul_byte(self, tmp_path, monkeypatch):
        package = _importable(
            tmp_path, monkeypatch, "nulbytepkg", bad=b"VALUE = 1\x00\n"
        )

        assert _provider_for(tmp_path).tree(f"{package}.bad") is None

    def test_undecodable_source(self, tmp_path, monkeypatch):
        package = _importable(
            tmp_path, monkeypatch, "badencodingpkg", bad=b"VALUE = '\xff\xfe'\n"
        )

        assert _provider_for(tmp_path).tree(f"{package}.bad") is None

    def test_source_the_parser_cannot_handle(self, tmp_path, monkeypatch):
        """Pathological source exhausts the parser (``MemoryError``), which is
        neither an ``OSError`` nor a ``SyntaxError`` — it still fails open."""
        bomb = ("x = " + "not " * 50000 + "1\n").encode()
        package = _importable(tmp_path, monkeypatch, "parserbombpkg", bad=bomb)

        assert _provider_for(tmp_path).tree(f"{package}.bad") is None


class TestSourceEncoding:
    """Source is decoded the way Python decodes it, not assumed to be plain
    UTF-8 — otherwise a module with a BOM or a coding declaration silently
    yields no tree and every rule reports nothing for it."""

    def test_utf8_bom_is_parsed(self, tmp_path, monkeypatch):
        package = _importable(
            tmp_path, monkeypatch, "bompkg", mod=b"\xef\xbb\xbfimport os\n"
        )

        tree = _provider_for(tmp_path).tree(f"{package}.mod")

        assert tree is not None
        assert [n.names[0].name for n in tree.body if isinstance(n, ast.Import)] == [
            "os"
        ]

    def test_pep263_coding_declaration_is_honoured(self, tmp_path, monkeypatch):
        source = b"# -*- coding: latin-1 -*-\nimport os\nS = 'caf\xe9'\n"
        package = _importable(tmp_path, monkeypatch, "latinpkg", mod=source)

        tree = _provider_for(tmp_path).tree(f"{package}.mod")

        assert tree is not None
        assert [n.names[0].name for n in tree.body if isinstance(n, ast.Import)] == [
            "os"
        ]


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

    def test_excludes_a_directory_named_like_a_module(self, tmp_path):
        """``weird.py`` is a directory; only files become modules."""
        root = _build_package(tmp_path, "dirnamepkg")

        assert not [m for m in _provider_for(root).modules() if "weird" in m]

    def test_a_file_named_only_py_is_not_a_module(self, tmp_path):
        root = tmp_path / "dotpypkg"
        _write(root / "__init__.py")
        _write(root / ".py", "VALUE = 1\n")

        assert _provider_for(root).modules() == ("dotpypkg",)

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

    def test_relative_root_path_is_resolved_against_the_working_directory(
        self, tmp_path, monkeypatch
    ):
        _build_package(tmp_path, "relativepkg")
        monkeypatch.chdir(tmp_path)

        assert _provider_for(Path("relativepkg")).modules() == (
            "relativepkg",
            "relativepkg.models",
            "relativepkg.sub",
            "relativepkg.sub.thing",
        )

    def test_symlinked_root_keeps_the_name_it_was_given(self, tmp_path):
        """Module names must match the names the domain was loaded under, so a
        symlinked root is not resolved to its target."""
        real = _build_package(tmp_path, "realpkg")
        alias = tmp_path / "aliaspkg"
        alias.symlink_to(real, target_is_directory=True)

        modules = _provider_for(alias).modules()

        assert modules[0] == "aliaspkg"
        assert not [m for m in modules if m.startswith("realpkg")]

    def test_missing_root_directory_yields_nothing(self, tmp_path):
        assert _provider_for(tmp_path / "does_not_exist").modules() == ()

    def test_empty_root_path_yields_nothing(self):
        """An empty ``root_path`` must not be read as "the current directory"
        and enumerate whatever happens to be there."""
        assert SourceProvider(Domain(name="EmptyRoot", root_path="")).modules() == ()

    def test_order_is_sorted_and_stable_across_providers(self, tmp_path):
        root = _build_package(tmp_path, "orderpkg")

        first = _provider_for(root).modules()
        second = _provider_for(root).modules()

        assert first == second
        assert list(first) == sorted(first)

    def test_the_walk_runs_once_per_provider(self, tmp_path):
        root = _build_package(tmp_path, "memopkg")
        provider = _provider_for(root)

        first = provider.modules()
        # A second walk would build a new tuple; the same object means the
        # filesystem was not listed again.
        assert provider.modules() is first

    def test_enumeration_does_not_parse(self, tmp_path, monkeypatch):
        """Enumeration is lazy by contract: listing a domain's modules must not
        read or parse a single file."""
        root = _build_package(tmp_path, "lazypkg")
        parsed = []
        monkeypatch.setattr(
            SourceProvider, "_parse", staticmethod(lambda path: parsed.append(path))
        )

        assert len(_provider_for(root).modules()) == 4
        assert parsed == []


class TestIterTrees:
    def test_yields_parsed_modules_in_enumeration_order(self, tmp_path):
        """The package is deliberately *not* on ``sys.path``: the walk parses
        the files it found, so importability is irrelevant."""
        root = _build_package(tmp_path, "itertreespkg")
        provider = _provider_for(root)

        yielded = list(provider.iter_trees())

        assert len(yielded) > 0, "Expected parsed modules but got none"
        assert [name for name, _ in yielded] == list(provider.modules())
        for _, tree in yielded:
            assert isinstance(tree, ast.Module)

    def test_reads_the_domains_own_file_not_a_module_of_the_same_name(
        self, tmp_path, monkeypatch
    ):
        """An installed package of the same name must not shadow the domain's
        source, or diagnostics would be attributed to the wrong file."""
        other = tmp_path / "other"
        _write(other / "shadowpkg" / "__init__.py")
        _write(other / "shadowpkg" / "models.py", "VALUE = 'installed'\n")
        monkeypatch.syspath_prepend(str(other))
        importlib.invalidate_caches()

        mine = tmp_path / "mine"
        _write(mine / "shadowpkg" / "__init__.py")
        _write(mine / "shadowpkg" / "models.py", "VALUE = 'domain'\n")

        trees = dict(_provider_for(mine / "shadowpkg").iter_trees())

        assert ast.literal_eval(trees["shadowpkg.models"].body[0].value) == "domain"

    def test_skips_modules_without_usable_source(self, tmp_path):
        root = tmp_path / "skippkg"
        _write(root / "__init__.py")
        _write(root / "fine.py", "VALUE = 1\n")
        _write(root / "bad.py", "def (:\n")
        provider = _provider_for(root)

        names = [name for name, _ in provider.iter_trees()]

        assert "skippkg.bad" in provider.modules()
        assert names == ["skippkg", "skippkg.fine"]

    def test_an_unparseable_module_does_not_stop_the_walk(self, tmp_path):
        """Source that exhausts the parser must not abort iteration and hide
        every module after it."""
        root = tmp_path / "bombwalkpkg"
        _write(root / "__init__.py")
        _write(root / "a.py", "VALUE = 1\n")
        (root / "bomb.py").write_bytes(("x = " + "not " * 50000 + "1\n").encode())
        _write(root / "z.py", "VALUE = 2\n")

        names = [name for name, _ in _provider_for(root).iter_trees()]

        assert names == ["bombwalkpkg", "bombwalkpkg.a", "bombwalkpkg.z"]

    def test_reuses_the_parse_cache(self, tmp_path):
        root = _build_package(tmp_path, "reusepkg")
        provider = _provider_for(root)

        first = dict(provider.iter_trees())
        second = dict(provider.iter_trees())

        assert first and first.keys() == second.keys()
        for name, tree in first.items():
            assert tree is second[name]

    def test_tree_reuses_what_the_walk_parsed(self, tmp_path, monkeypatch):
        """The two entry points share one cache when they agree on the file."""
        package = _importable(tmp_path, monkeypatch, "sharedcachepkg", mod=b"V = 1\n")
        provider = _provider_for(tmp_path / package)

        walked = dict(provider.iter_trees())

        assert provider.tree(f"{package}.mod") is walked[f"{package}.mod"]


class TestBuilderIntegration:
    """``IRBuilder`` owns one provider, created on demand."""

    def _domain(self, name):
        domain = Domain(name=name, root_path=".")
        domain.init(traverse=False)
        return domain

    def test_provider_is_not_created_until_it_is_asked_for(self):
        builder = IRBuilder(self._domain("BuilderLazy"))

        assert builder._source is None

    def test_provider_is_memoized_per_builder(self):
        domain = self._domain("BuilderMemo")
        builder = IRBuilder(domain)

        assert builder.source is builder.source
        assert builder.source is not IRBuilder(domain).source


@pytest.fixture(autouse=True)
def _cleanup_temp_packages(tmp_path_factory):
    """Drop the temp packages these tests import, so a later test in the same
    process does not resolve a stale ``sys.modules`` entry. Scoped by file
    location, not by name, so nothing outside the temp tree is evicted."""
    basetemp = str(tmp_path_factory.getbasetemp())
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        origin = getattr(sys.modules[name], "__file__", None)
        if origin and origin.startswith(basetemp):
            del sys.modules[name]
    sys.path_importer_cache.clear()
    importlib.invalidate_caches()

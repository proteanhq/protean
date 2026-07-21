"""SymbolResolver: import/def symbol tables, use-site resolution, classification."""

import ast
from pathlib import Path
from textwrap import dedent

import pytest

from protean import Domain
from protean.ir.analysis import SourceProvider, SymbolResolver
from protean.ir.builder import IRBuilder
from tests.ir.support import behavioral_domain
from tests.ir.support.behavioral_domain import elements, helpers

pytestmark = pytest.mark.no_test_domain

#: The elements module under the name Python resolves it by — the name whose
#: FQNs match what the registry recorded, which the walk's name does not.
ELEMENTS_MODULE = elements.__name__
HELPERS_MODULE = helpers.__name__

PACKAGE_ROOT = str(Path(behavioral_domain.__file__).parent)


def _use_site(expression):
    """Parse a single expression into the ``ast.expr`` a use site would be."""
    return ast.parse(expression, mode="eval").body


def _make_pkg(tmp_path, files):
    """Write a ``pkg`` package on disk and return its root directory.

    ``files`` maps a path relative to the package root to source; an
    ``__init__.py`` is added if none is given. Nothing is imported: the targets
    of the import statements need not exist, since the resolver only parses.
    """
    root = tmp_path / "pkg"
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(source), encoding="utf-8")
    init = root / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")
    return root


def _walked_resolver(root):
    """A resolver whose provider has the package cached under its walked names.

    The package walk reads the files from disk (no import machinery), so the
    trees and origins are cached under the names the walk gives them and
    ``resolve`` answers without ever calling ``find_spec``.
    """
    domain = Domain(name="Symbols", root_path=str(root))
    provider = SourceProvider(domain)
    # Force the on-disk walk so trees/origins are cached under walked names.
    dict(provider.iter_trees())
    return SymbolResolver(domain, provider)


@pytest.fixture(scope="module")
def element_domain():
    """The fixture package registered as a real domain, for classification."""
    domain = Domain(name="Behavioral", root_path=PACKAGE_ROOT)
    domain.register(elements.Wallet, event_sourced=True)
    domain.register(elements.WalletOpened, part_of=elements.Wallet)
    domain.register(elements.FundsDeposited, part_of=elements.Wallet)
    domain.register(elements.OpenWallet, part_of=elements.Wallet)
    domain.register(elements.CloseWallet, part_of=elements.Wallet)
    domain.register(elements.WalletRepository, part_of=elements.Wallet)
    domain.register(elements.WalletCommandHandler, part_of=elements.Wallet)
    domain.init(traverse=False)
    return domain


class TestImportBindings:
    def test_from_import_as_binds_the_alias(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"mod.py": "from x.y import z as w\n"})
        )

        assert resolver.symbols("pkg.mod") == {"w": "x.y.z"}

    def test_from_import_binds_the_imported_name(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"mod.py": "from a.b import c\n"})
        )

        assert resolver.symbols("pkg.mod")["c"] == "a.b.c"

    def test_plain_import_binds_the_top_name_only(self, tmp_path):
        """``import a.b.c`` binds ``a``, not ``a.b.c`` — Python binds the top
        name and the rest is reached by walking attributes off it."""
        resolver = _walked_resolver(_make_pkg(tmp_path, {"mod.py": "import a.b.c\n"}))
        table = resolver.symbols("pkg.mod")

        assert table == {"a": "a"}
        assert "a.b.c" not in table

    def test_dotted_import_as_binds_the_full_target(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"mod.py": "import a.b.c as w\n"})
        )

        assert resolver.symbols("pkg.mod") == {"w": "a.b.c"}

    def test_star_import_binds_no_name(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"mod.py": "from a.b import *\n"})
        )

        assert resolver.symbols("pkg.mod") == {}

    def test_module_level_definitions_bind_to_their_fqn(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(
                tmp_path,
                {
                    "mod.py": """
                    class Order: ...

                    def make(): ...

                    async def fetch(): ...
                    """
                },
            )
        )

        assert resolver.symbols("pkg.mod") == {
            "Order": "pkg.mod.Order",
            "make": "pkg.mod.make",
            "fetch": "pkg.mod.fetch",
        }


class TestShadowing:
    def test_a_local_class_shadows_a_same_named_import(self, tmp_path):
        """The issue's shadowing case: local definitions win over imports,
        matching Python's last-binding-wins for that shape."""
        resolver = _walked_resolver(
            _make_pkg(
                tmp_path,
                {
                    "mod.py": """
                    from other import Order

                    class Order: ...
                    """
                },
            )
        )

        assert resolver.symbols("pkg.mod")["Order"] == "pkg.mod.Order"

    def test_a_local_def_shadows_a_same_named_import(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(
                tmp_path,
                {
                    "mod.py": """
                    from other import build

                    def build(): ...
                    """
                },
            )
        )

        assert resolver.symbols("pkg.mod")["build"] == "pkg.mod.build"

    def test_an_import_after_a_definition_wins_by_source_order(self, tmp_path):
        """The reverse shape: a ``class`` followed by a same-named import binds
        the import, matching Python's last-binding-wins. Binding by source order
        (not imports-then-defs) is what keeps this from being a wrong FQN."""
        resolver = _walked_resolver(
            _make_pkg(
                tmp_path,
                {
                    "mod.py": """
                    class Order: ...

                    from other import Order
                    """
                },
            )
        )

        assert resolver.symbols("pkg.mod")["Order"] == "other.Order"

    def test_a_reassignment_degrades_a_bound_name_to_unresolved(self, tmp_path):
        """A module-level ``=`` over an imported name rebinds it to a value the
        table cannot follow, so the name is dropped and resolves to ``None`` —
        a miss, never the stale import FQN."""
        resolver = _walked_resolver(
            _make_pkg(
                tmp_path,
                {
                    "mod.py": """
                    from other import Order

                    Order = make_order()
                    """
                },
            )
        )

        assert "Order" not in resolver.symbols("pkg.mod")
        assert resolver.resolve("pkg.mod", _use_site("Order")) is None


class TestRelativeImports:
    def test_single_dot_import_anchors_on_the_package(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"sub/mod.py": "from . import z\n"})
        )

        assert resolver.symbols("pkg.sub.mod")["z"] == "pkg.sub.z"

    def test_double_dot_import_walks_up_a_package(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"sub/mod.py": "from ..other import y\n"})
        )

        assert resolver.symbols("pkg.sub.mod")["y"] == "pkg.other.y"

    def test_a_package_init_is_its_own_anchor(self, tmp_path):
        """A module whose source is an ``__init__`` file *is* its package, so a
        single-dot import stays in that package rather than its parent."""
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"sub/__init__.py": "from . import w\n"})
        )

        assert resolver.symbols("pkg.sub")["w"] == "pkg.sub.w"

    def test_an_import_that_escapes_the_top_level_binds_nothing(self, tmp_path):
        """A relative import walking past the top-level package is left
        unresolved, never bound to a fabricated FQN."""
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"sub/mod.py": "from ... import x\n"})
        )

        assert resolver.symbols("pkg.sub.mod") == {}

    def test_a_top_level_module_cannot_anchor_a_relative_import(
        self, tmp_path, monkeypatch
    ):
        """A single-file module with no parent package cannot anchor a relative
        import, so it binds nothing rather than a malformed FQN."""
        (tmp_path / "loosemod.py").write_text("from . import x\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        resolver = SymbolResolver(Domain(name="Loose", root_path=""))

        assert resolver.symbols("loosemod") == {}


class TestUseSiteResolution:
    @staticmethod
    def _resolver(tmp_path, source):
        return _walked_resolver(_make_pkg(tmp_path, {"mod.py": source}))

    def test_a_bare_name_resolves_through_the_table(self, tmp_path):
        resolver = self._resolver(tmp_path, "from a.b import c\n")

        assert resolver.resolve("pkg.mod", _use_site("c")) == "a.b.c"

    def test_an_attribute_chain_resolves_through_its_root(self, tmp_path):
        """``mixins.handle`` off ``import a.b as mixins`` appends the trailing
        segment to the root's FQN."""
        resolver = self._resolver(tmp_path, "import a.b as mixins\n")

        assert resolver.resolve("pkg.mod", _use_site("mixins.handle")) == "a.b.handle"

    def test_a_deep_attribute_chain_appends_every_segment(self, tmp_path):
        resolver = self._resolver(tmp_path, "import pkgroot\n")

        assert (
            resolver.resolve("pkg.mod", _use_site("pkgroot.a.b.Thing"))
            == "pkgroot.a.b.Thing"
        )

    def test_an_unbound_name_resolves_to_none(self, tmp_path):
        """A bare builtin that was never imported or defined has no binding, so
        it resolves to ``None`` rather than a wrong FQN."""
        resolver = self._resolver(tmp_path, "x = 1\n")

        assert resolver.resolve("pkg.mod", _use_site("filter")) is None

    def test_an_unresolved_root_yields_none_for_the_whole_chain(self, tmp_path):
        resolver = self._resolver(tmp_path, "x = 1\n")

        assert resolver.resolve("pkg.mod", _use_site("unknown.attr")) is None

    def test_a_self_attribute_resolves_to_none(self, tmp_path):
        """``self`` is never in a module's table, so ``self.x`` is unresolved."""
        resolver = self._resolver(tmp_path, "from a import b\n")

        assert resolver.resolve("pkg.mod", _use_site("self.x")) is None

    def test_a_computed_root_resolves_to_none(self, tmp_path):
        """A call result or a subscript is not a name, so nothing rooted on one
        resolves."""
        resolver = self._resolver(tmp_path, "from a import factory\n")

        assert resolver.resolve("pkg.mod", _use_site("factory().bar")) is None
        assert resolver.resolve("pkg.mod", _use_site("registry['k'].bar")) is None


class TestClassification:
    def test_framework_symbols_are_recognised(self):
        resolver = SymbolResolver(Domain(name="Empty", root_path=""))

        assert resolver.is_framework_symbol("protean")
        assert resolver.is_framework_symbol("protean.core.queryset.QuerySet.filter")

    def test_non_framework_symbols_are_rejected(self):
        resolver = SymbolResolver(Domain(name="Empty", root_path=""))

        assert not resolver.is_framework_symbol("proteanx.foo")
        assert not resolver.is_framework_symbol("my_app.orders.Order")


class TestDomainElementClassification:
    def test_a_registered_aggregate_use_site_resolves_and_classifies(
        self, element_domain
    ):
        """The issue's first case: a module-level ``Wallet`` used as ``Wallet``
        resolves to its FQN, and that FQN is a registered domain element."""
        resolver = SymbolResolver(element_domain)

        fqn = resolver.resolve(ELEMENTS_MODULE, _use_site("Wallet"))

        assert fqn == f"{ELEMENTS_MODULE}.Wallet"
        assert resolver.is_domain_element(fqn)
        assert not resolver.is_framework_symbol(fqn)

    def test_a_registered_event_is_a_domain_element(self, element_domain):
        resolver = SymbolResolver(element_domain)

        fqn = resolver.resolve(ELEMENTS_MODULE, _use_site("WalletOpened"))

        assert fqn == f"{ELEMENTS_MODULE}.WalletOpened"
        assert resolver.is_domain_element(fqn)

    def test_a_framework_import_resolves_and_classifies_as_framework(
        self, element_domain
    ):
        """A use of an imported framework symbol resolves through the import and
        reads as framework, not as a domain element."""
        resolver = SymbolResolver(element_domain)

        fqn = resolver.resolve(ELEMENTS_MODULE, _use_site("apply"))

        assert fqn == "protean.core.aggregate.apply"
        assert resolver.is_framework_symbol(fqn)
        assert not resolver.is_domain_element(fqn)

    def test_an_unregistered_name_is_not_a_domain_element(self, element_domain):
        resolver = SymbolResolver(element_domain)

        assert not resolver.is_domain_element(f"{HELPERS_MODULE}.LabelFormatter")
        assert not resolver.is_domain_element("my_app.orders.Order")

    def test_the_element_set_is_snapshotted_on_first_use(self):
        """The element FQNs are read once, matching the one-resolver-per-build
        lifetime: an element registered afterwards is not seen."""
        domain = Domain(name="Snapshot", root_path=PACKAGE_ROOT)
        domain.register(elements.Wallet, event_sourced=True)
        domain.register(elements.WalletOpened, part_of=elements.Wallet)
        domain.register(elements.FundsDeposited, part_of=elements.Wallet)
        domain.init(traverse=False)
        resolver = SymbolResolver(domain)
        assert resolver.is_domain_element(f"{ELEMENTS_MODULE}.Wallet")

        domain.register(elements.WalletRepository, part_of=elements.Wallet)

        assert not resolver.is_domain_element(f"{ELEMENTS_MODULE}.WalletRepository")
        assert SymbolResolver(domain).is_domain_element(
            f"{ELEMENTS_MODULE}.WalletRepository"
        )


class TestFailOpen:
    def test_an_unparseable_module_yields_an_empty_table(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"bad.py": "from a import (\n"})
        )

        assert resolver.symbols("pkg.bad") == {}
        assert resolver.resolve("pkg.bad", _use_site("anything")) is None

    def test_an_absent_module_yields_an_empty_table(self):
        resolver = SymbolResolver(Domain(name="Empty", root_path=""))

        assert resolver.symbols("no_such_module_xyz") == {}
        assert resolver.resolve("no_such_module_xyz", _use_site("x")) is None


class TestDeterminism:
    def test_two_resolvers_over_the_same_source_agree(self, tmp_path):
        files = {
            "mod.py": """
            from a.b import c as d
            import e.f as g
            from . import local

            class Order: ...
            """,
            "__init__.py": "",
        }
        root = _make_pkg(tmp_path, files)

        first = _walked_resolver(root)
        second = _walked_resolver(root)

        assert first.symbols("pkg.mod") == second.symbols("pkg.mod")
        assert first.resolve("pkg.mod", _use_site("Order")) == second.resolve(
            "pkg.mod", _use_site("Order")
        )

    def test_the_table_is_built_once_and_cached(self, tmp_path):
        resolver = _walked_resolver(
            _make_pkg(tmp_path, {"mod.py": "from a import b\n"})
        )

        assert resolver.symbols("pkg.mod") is resolver.symbols("pkg.mod")


class TestBuilderWiring:
    def test_resolver_shares_the_builders_provider(self):
        """A resolver built on a builder's provider reads a module the builder
        already parsed without parsing it again."""
        domain = Domain(name="Wiring", root_path=PACKAGE_ROOT)
        domain.register(elements.Wallet, event_sourced=True)
        domain.init(traverse=False)
        builder = IRBuilder(domain)
        resolver = SymbolResolver(domain, builder.source)

        tree = builder.source.tree(ELEMENTS_MODULE)
        fqn = resolver.resolve(ELEMENTS_MODULE, _use_site("Wallet"))

        assert tree is not None
        assert fqn == f"{ELEMENTS_MODULE}.Wallet"

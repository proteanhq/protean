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
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param("from x.y import z as w\n", {"w": "x.y.z"}, id="from-as"),
            pytest.param("from a.b import c\n", {"c": "a.b.c"}, id="from"),
            # ``import a.b.c`` binds ``a``, not ``a.b.c``: Python binds the top
            # name and the rest is reached by walking attributes off it.
            pytest.param("import a.b.c\n", {"a": "a"}, id="plain-dotted"),
            pytest.param("import a.b.c as w\n", {"w": "a.b.c"}, id="dotted-as"),
            pytest.param("from a.b import *\n", {}, id="star"),
            pytest.param(
                """
                class Order: ...

                def make(): ...

                async def fetch(): ...
                """,
                {
                    "Order": "pkg.mod.Order",
                    "make": "pkg.mod.make",
                    "fetch": "pkg.mod.fetch",
                },
                id="definitions",
            ),
        ],
    )
    def test_a_module_level_statement_binds_its_names(self, tmp_path, source, expected):
        resolver = _walked_resolver(_make_pkg(tmp_path, {"mod.py": source}))

        assert resolver.symbols("pkg.mod") == expected


class TestShadowing:
    @pytest.mark.parametrize(
        ("source", "name", "fqn"),
        [
            # Local definitions win over imports, matching Python's
            # last-binding-wins for that shape.
            pytest.param(
                """
                from other import Order

                class Order: ...
                """,
                "Order",
                "pkg.mod.Order",
                id="class-after-import",
            ),
            pytest.param(
                """
                from other import build

                def build(): ...
                """,
                "build",
                "pkg.mod.build",
                id="def-after-import",
            ),
            # The reverse shape: binding by source order (not imports then
            # definitions) is what keeps this from being a wrong FQN.
            pytest.param(
                """
                class Order: ...

                from other import Order
                """,
                "Order",
                "other.Order",
                id="import-after-class",
            ),
        ],
    )
    def test_the_last_binding_in_source_order_wins(self, tmp_path, source, name, fqn):
        resolver = _walked_resolver(_make_pkg(tmp_path, {"mod.py": source}))

        assert resolver.symbols("pkg.mod")[name] == fqn

    @pytest.mark.parametrize(
        ("source", "names"),
        [
            pytest.param(
                """
                from other import Order

                Order = make_order()
                """,
                ["Order"],
                id="assignment",
            ),
            pytest.param(
                """
                from other import count

                count += 1
                """,
                ["count"],
                id="augmented-assignment",
            ),
            pytest.param(
                """
                from other import Order

                Order: type = make_order()
                """,
                ["Order"],
                id="annotated-assignment-with-a-value",
            ),
            pytest.param(
                """
                from other import Order, Line

                Order, Line = make_pair()
                """,
                ["Order", "Line"],
                id="tuple-unpacking",
            ),
            pytest.param(
                """
                from other import head, tail

                head, *tail = make_sequence()
                """,
                ["head", "tail"],
                id="starred-unpacking",
            ),
        ],
    )
    def test_a_rebinding_degrades_an_imported_name_to_unresolved(
        self, tmp_path, source, names
    ):
        """A module-level rebinding over an imported name gives it a value the
        table cannot follow, so every rebound name is dropped and resolves to
        ``None``: a miss, never the stale import FQN."""
        resolver = _walked_resolver(_make_pkg(tmp_path, {"mod.py": source}))

        for name in names:
            assert name not in resolver.symbols("pkg.mod")
            assert resolver.resolve("pkg.mod", _use_site(name)) is None

    @pytest.mark.parametrize(
        "statement",
        [
            # ``x: T`` with no value binds nothing.
            pytest.param("Order: type", id="bare-annotation"),
            # ``a.b = ...`` binds no module name.
            pytest.param("Order.total = compute()", id="attribute-target"),
        ],
    )
    def test_a_statement_that_binds_no_name_keeps_the_import(self, tmp_path, statement):
        source = f"from other import Order\n\n{statement}\n"
        resolver = _walked_resolver(_make_pkg(tmp_path, {"mod.py": source}))

        assert resolver.resolve("pkg.mod", _use_site("Order")) == "other.Order"


class TestRelativeImports:
    @pytest.mark.parametrize(
        ("path", "source", "module", "name", "fqn"),
        [
            pytest.param(
                "sub/mod.py",
                "from . import z\n",
                "pkg.sub.mod",
                "z",
                "pkg.sub.z",
                id="single-dot",
            ),
            pytest.param(
                "sub/mod.py",
                "from ..other import y\n",
                "pkg.sub.mod",
                "y",
                "pkg.other.y",
                id="double-dot",
            ),
            # An ``__init__`` file *is* its package, so a single-dot import
            # stays in that package rather than its parent.
            pytest.param(
                "sub/__init__.py",
                "from . import w\n",
                "pkg.sub",
                "w",
                "pkg.sub.w",
                id="package-init",
            ),
        ],
    )
    def test_a_relative_import_anchors_on_its_package(
        self, tmp_path, path, source, module, name, fqn
    ):
        resolver = _walked_resolver(_make_pkg(tmp_path, {path: source}))

        assert resolver.symbols(module)[name] == fqn

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

    @pytest.mark.parametrize(
        ("source", "expression", "fqn"),
        [
            pytest.param("from a.b import c\n", "c", "a.b.c", id="bare-name"),
            # The trailing segment is appended to the root's FQN.
            pytest.param(
                "import a.b as mixins\n",
                "mixins.handle",
                "a.b.handle",
                id="attribute-chain",
            ),
            pytest.param(
                "import pkgroot\n",
                "pkgroot.a.b.Thing",
                "pkgroot.a.b.Thing",
                id="deep-attribute-chain",
            ),
        ],
    )
    def test_a_use_site_resolves_through_the_table(
        self, tmp_path, source, expression, fqn
    ):
        resolver = self._resolver(tmp_path, source)

        assert resolver.resolve("pkg.mod", _use_site(expression)) == fqn

    @pytest.mark.parametrize(
        ("source", "expression"),
        [
            # A bare builtin that was never imported or defined has no binding.
            pytest.param("x = 1\n", "filter", id="unbound-name"),
            pytest.param("x = 1\n", "unknown.attr", id="unresolved-root"),
            # ``self`` is never in a module's table.
            pytest.param("from a import b\n", "self.x", id="self-attribute"),
            # A call result or a subscript is not a name, so nothing rooted on
            # one resolves.
            pytest.param("from a import factory\n", "factory().bar", id="call-root"),
            pytest.param(
                "from a import factory\n", "registry['k'].bar", id="subscript-root"
            ),
        ],
    )
    def test_a_use_site_with_no_binding_resolves_to_none(
        self, tmp_path, source, expression
    ):
        """An unresolvable use site gives ``None``, never a wrong FQN."""
        resolver = self._resolver(tmp_path, source)

        assert resolver.resolve("pkg.mod", _use_site(expression)) is None


class TestMethodScope:
    @staticmethod
    def _scope(tmp_path, source):
        """The resolver and the scope of ``run``, the first function in ``mod``."""
        resolver = _walked_resolver(_make_pkg(tmp_path, {"mod.py": source}))
        tree = resolver._provider.tree("pkg.mod")
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        return resolver, resolver.method_scope("pkg.mod", method), method

    @staticmethod
    def _use(method, text):
        """The first use site in ``method`` whose source text is ``text``."""
        return next(
            n
            for n in ast.walk(method)
            if isinstance(n, (ast.Name, ast.Attribute))
            and ast.unparse(n) == text
            and isinstance(n.ctx, ast.Load)
        )

    def test_a_plain_import_binds_its_top_name(self, tmp_path):
        """``import acme.events`` binds ``acme``; a later attribute walk off it
        reconstructs the rest of the FQN."""
        _, scope, method = self._scope(
            tmp_path,
            """
            def run():
                import acme.events
                return acme.events.Closed
            """,
        )

        assert scope.resolve(self._use(method, "acme.events.Closed")) == (
            "acme.events.Closed"
        )

    def test_a_use_on_the_same_line_after_the_import_resolves(self, tmp_path):
        _, scope, method = self._scope(
            tmp_path,
            """
            def run():
                from acme.events import Closed; return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) == "acme.events.Closed"

    def test_each_name_keeps_the_position_of_its_own_first_import(self, tmp_path):
        """``Closed`` is first imported above the use of ``Opened``, but
        ``Opened`` is first imported below it, so that use stays unresolved."""
        _, scope, method = self._scope(
            tmp_path,
            """
            def run():
                from acme.events import Closed
                early = Opened
                from acme.events import Closed, Opened
                return Opened
            """,
        )
        uses = [
            n for n in ast.walk(method) if isinstance(n, ast.Name) and n.id == "Opened"
        ]
        uses.sort(key=lambda n: n.lineno)

        assert [scope.resolve(n) for n in uses] == [None, "acme.events.Opened"]

    def test_the_module_table_is_untouched(self, tmp_path):
        """The scope reads the method's imports without adding them to the
        module table, so ``resolve(module, node)`` keeps its module-only
        meaning for every other caller."""
        resolver, scope, method = self._scope(
            tmp_path,
            """
            from acme.legacy import Closed

            def run():
                from acme.events import Closed
                return Closed
            """,
        )
        use = self._use(method, "Closed")

        assert scope.resolve(use) == "acme.events.Closed"
        assert resolver.resolve("pkg.mod", use) == "acme.legacy.Closed"
        assert resolver.symbols("pkg.mod") == {
            "Closed": "acme.legacy.Closed",
            "run": "pkg.mod.run",
        }

    @pytest.mark.parametrize("keyword", ["def", "async def", "class"])
    def test_a_nested_definition_of_the_name_leaves_it_unresolved(
        self, tmp_path, keyword
    ):
        """A nested ``def`` or ``class`` named like the import rebinds the name
        in the method, so no single FQN is right for the use after both."""
        body = "pass" if keyword == "class" else "return None"
        _, scope, method = self._scope(
            tmp_path,
            f"""
            def run():
                from acme.events import Closed
                {keyword} Closed():
                    {body}
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    def test_a_bare_annotation_of_the_name_keeps_the_import(self, tmp_path):
        """``Closed: type`` with no value binds nothing at runtime, so a later
        use still gets the import's FQN."""
        _, scope, method = self._scope(
            tmp_path,
            """
            def run():
                from acme.events import Closed
                Closed: type
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) == "acme.events.Closed"

    def test_a_walrus_in_a_bare_annotation_target_leaves_it_unresolved(self, tmp_path):
        """``cache[(Closed := factory)]: int`` evaluates its subscript target,
        so the walrus rebinds the name and the later use has no single FQN."""
        _, scope, method = self._scope(
            tmp_path,
            """
            def run(cache, factory):
                from acme.events import Closed
                cache[(Closed := factory)]: int
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    @pytest.mark.parametrize("target", ["count", "self.count"])
    def test_a_walrus_in_an_annotation_keeps_the_import(self, tmp_path, target):
        """Python never evaluates a local variable's annotation, so a walrus
        inside one binds nothing and a later use keeps the import's FQN."""
        _, scope, method = self._scope(
            tmp_path,
            f"""
            def run(self, factory):
                from acme.events import Closed
                {target}: (Closed := factory)
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) == "acme.events.Closed"

    def test_an_annotated_assignment_of_the_name_leaves_it_unresolved(self, tmp_path):
        """``Closed: type = ...`` rebinds the name, so the later use has no
        single FQN."""
        _, scope, method = self._scope(
            tmp_path,
            """
            def run():
                from acme.events import Closed
                Closed: type = object
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    def test_a_parameter_of_the_same_name_does_not_block_the_import(self, tmp_path):
        """A parameter is bound before the body runs, so the import after it
        rebinds the name and a later use gets the import's FQN."""
        _, scope, method = self._scope(
            tmp_path,
            """
            def run(Closed):
                from acme.events import Closed
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) == "acme.events.Closed"

    @pytest.mark.parametrize(
        "signature",
        ["Closed", "Closed, /", "*, Closed", "*Closed", "**Closed"],
    )
    def test_a_parameter_with_a_conditional_import_leaves_it_unresolved(
        self, tmp_path, signature
    ):
        """When the import may not run, a later use can still see the argument
        the caller passed, so no single FQN is right for it."""
        _, scope, method = self._scope(
            tmp_path,
            f"""
            def run(self, {signature}):
                if self.on:
                    from acme.events import Closed
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    def test_a_parameter_with_an_import_in_a_try_leaves_it_unresolved(self, tmp_path):
        _, scope, method = self._scope(
            tmp_path,
            """
            def run(self, Closed=None):
                try:
                    from acme.events import Closed
                except ImportError:
                    pass
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    def test_a_parameter_with_a_later_unconditional_import_leaves_it_unresolved(
        self, tmp_path
    ):
        """The first import is conditional, so a use between it and the
        unconditional one can still see the argument."""
        _, scope, method = self._scope(
            tmp_path,
            """
            def run(self, Closed=None):
                if self.on:
                    from acme.events import Closed
                early = Closed
                from acme.events import Closed
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    @pytest.mark.parametrize("keyword", ["global", "nonlocal"])
    def test_a_declared_outer_name_leaves_it_unresolved(self, tmp_path, keyword):
        """The import then binds the outer name, which a path that skips the
        import still sees."""
        _, scope, method = self._scope(
            tmp_path,
            f"""
            from acme.legacy import Closed

            def run(self):
                {keyword} Closed
                if self.on:
                    from acme.events import Closed
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    @pytest.mark.parametrize(
        "nested",
        [
            "def helper(x=(Closed := 1)): pass",
            "f = lambda x=(Closed := 2): x",
            "@(Closed := staticmethod)\n                def helper(): pass",
            "class Helper((Closed := object)): pass",
            "class Helper(metaclass=(Closed := type)): pass",
            "def helper(x: (Closed := int)): pass",
            "def helper() -> (Closed := int): pass",
        ],
    )
    def test_a_walrus_in_a_nested_scope_header_leaves_it_unresolved(
        self, tmp_path, nested
    ):
        """Decorators, defaults, annotations, bases and keywords run in the
        method's own scope, so a walrus in one rebinds the method's name."""
        _, scope, method = self._scope(
            tmp_path,
            f"""
            def run():
                from acme.events import Closed
                {nested}
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    def test_a_nonlocal_rebinding_in_a_nested_def_leaves_it_unresolved(self, tmp_path):
        _, scope, method = self._scope(
            tmp_path,
            """
            def run():
                from acme.events import Closed
                def helper():
                    nonlocal Closed
                    import json as Closed
                helper()
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) is None

    def test_a_star_import_binds_no_use_site(self, tmp_path):
        """``ast.parse`` accepts a ``*`` import in a function. It binds no name
        a use site can carry, so other names keep their resolution."""
        _, scope, method = self._scope(
            tmp_path,
            """
            from acme.legacy import Closed

            def run():
                from os import *
                return Closed
            """,
        )

        assert scope.resolve(self._use(method, "Closed")) == "acme.legacy.Closed"

    def test_a_computed_use_site_resolves_to_none(self, tmp_path):
        _, scope, method = self._scope(
            tmp_path,
            """
            def run():
                from acme import factory
                return factory().bar
            """,
        )
        use = next(n for n in ast.walk(method) if isinstance(n, ast.Attribute))

        assert scope.resolve(use) is None


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
    @pytest.mark.parametrize("name", ["Wallet", "WalletOpened"])
    def test_a_registered_element_use_site_resolves_and_classifies(
        self, element_domain, name
    ):
        """A module-level element used by name resolves to its FQN, and that
        FQN is a registered domain element, not a framework symbol."""
        resolver = SymbolResolver(element_domain)

        fqn = resolver.resolve(ELEMENTS_MODULE, _use_site(name))

        assert fqn == f"{ELEMENTS_MODULE}.{name}"
        assert resolver.is_domain_element(fqn)
        assert not resolver.is_framework_symbol(fqn)

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

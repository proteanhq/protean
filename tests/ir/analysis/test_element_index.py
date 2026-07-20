"""ElementIndex: class/method indexing, element resolution, and role tags."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from textwrap import dedent

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.fields import Identifier
from protean.ir.analysis import ElementIndex, MethodRole, SourceProvider
from protean.ir.builder import IRBuilder
from tests.ir.support import behavioral_domain
from tests.ir.support.behavioral_domain import elements, helpers

pytestmark = pytest.mark.no_test_domain

#: The module the fixture elements are defined in, under the name Python
#: resolves — which is *not* the name the package walk gives the same file.
ELEMENTS_MODULE = elements.__name__
HELPERS_MODULE = helpers.__name__
#: The same two files as the package walk names them: module names are built
#: from the path relative to the root directory's parent, so the walk sees the
#: package as a top-level ``behavioral_domain``.
WALKED_ELEMENTS = "behavioral_domain.elements"
WALKED_HELPERS = "behavioral_domain.helpers"

TEST_MODULE = __name__

PACKAGE_ROOT = str(Path(behavioral_domain.__file__).parent)


class Duplicate:
    """A module-level decoy for the qualname mis-binding test.

    A class of the same name defined inside a function must resolve to *its own*
    node, not to this one.
    """

    def module_level_marker(self) -> None:
        pass


class Rebuilt:
    """A module-level decoy for the *rebuilt* element test.

    ``derive_element_class`` flattens a rebuilt element's ``__qualname__`` to
    the bare class name, so a function-local ``Rebuilt`` registered through a
    decorator arrives claiming to be this one.
    """

    def decoy(self) -> None:
        pass


class Fieldless:
    """The same decoy, for an element that carries no methods of its own and
    so cannot be told apart from this class."""

    def decoy(self) -> None:
        pass


class Wrapped:
    """The same decoy again, for an element whose only functions are hidden
    behind a ``classmethod``/``property`` descriptor."""

    def decoy(self) -> None:
        pass


@pytest.fixture(scope="module")
def domain():
    """The fixture package registered as a real domain, rooted at the package."""
    domain = Domain(name="Behavioral", root_path=PACKAGE_ROOT)
    domain.register(elements.Wallet, event_sourced=True)
    domain.register(elements.WalletOpened, part_of=elements.Wallet)
    domain.register(elements.FundsDeposited, part_of=elements.Wallet)
    domain.register(elements.OpenWallet, part_of=elements.Wallet)
    domain.register(elements.CloseWallet, part_of=elements.Wallet)
    domain.register(elements.WalletRepository, part_of=elements.Wallet)
    domain.register(elements.WalletEventSourcedRepository, part_of=elements.Wallet)
    domain.register(elements.WalletCommandHandler, part_of=elements.Wallet)
    domain.register(elements.WalletEventHandler, part_of=elements.Wallet)
    domain.register(elements.WalletProcessManager)
    domain.register(elements.WalletView)
    domain.register(
        elements.WalletProjector,
        projector_for=elements.WalletView,
        aggregates=[elements.Wallet],
    )
    domain.init(traverse=False)
    return domain


@pytest.fixture
def index(domain):
    """A fresh index per test, so caching assertions start from zero."""
    return ElementIndex(domain)


class TestElementResolution:
    def test_repository_element_resolves_to_its_class_and_method_nodes(self, index):
        """The issue's first case: element -> class node -> method nodes."""
        node = index.element_class_node(elements.WalletRepository)

        assert isinstance(node, ast.ClassDef)
        assert node.name == "WalletRepository"

        methods = index.element_methods(elements.WalletRepository)
        assert [m.name for m in methods] == ["_cache_key", "find_by_label"]
        # Node identity, not just names: these are the real nodes from the
        # class body, in the right class.
        assert all(m.node in node.body for m in methods)
        assert methods[1].node.lineno > node.lineno

    def test_methods_belong_to_the_class_that_wrote_them(self, index):
        """A function nested inside a method, or in a nested class, is not a
        method of the enclosing class."""
        names = [m.name for m in index.element_methods(elements.Wallet)]

        assert names == [
            "__str__",
            "_normalize",
            "balance_non_negative",
            "deposited",
            "describe",
            "label",
            "opened",
            "rename",
        ]
        assert "evaluate" not in names  # lives on the nested Policy class

    def test_nested_class_is_reachable_under_its_dotted_qualname(self, index):
        node = index.class_node(WALKED_ELEMENTS, "Wallet.Policy")

        assert node is not None
        assert node.name == "Policy"
        assert [m.name for m in index.methods(WALKED_ELEMENTS, "Wallet.Policy")] == [
            "evaluate"
        ]

    def test_missing_class_yields_nothing_from_every_surface(self, index):
        assert index.class_node(WALKED_ELEMENTS, "NoSuchClass") is None
        assert index.methods(WALKED_ELEMENTS, "NoSuchClass") == ()

    def test_a_registered_subclass_is_not_rebuilt_and_keeps_its_names(self, domain):
        """The easy half: an element that already subclasses its base is
        registered as-is, so ``(__module__, __qualname__)`` still names it."""
        record = domain._domain_registry._elements["AGGREGATE"][
            f"{ELEMENTS_MODULE}.Wallet"
        ]

        assert record.cls is elements.Wallet
        assert record.cls.__module__ == ELEMENTS_MODULE
        assert record.cls.__qualname__ == "Wallet"
        assert ElementIndex(domain).element_class_node(record.cls) is not None


class TestPackageScope:
    def test_helper_module_class_is_indexed_with_no_roles(self, index, domain):
        """Whole-package scope: a module that registers nothing is still read."""
        keys = [(c.module, c.qualname) for c in index.classes()]

        assert (WALKED_HELPERS, "LabelFormatter") in keys
        assert index.roles(helpers.LabelFormatter) == {}

    def test_classes_are_sorted_by_module_then_qualname(self, index):
        keys = [(c.module, c.qualname) for c in index.classes()]

        assert len(keys) > 0, "the fixture package must contribute classes"
        assert keys == sorted(keys)

    def test_classes_reports_the_package_only(self, index):
        """An element resolved on demand from outside the package does not
        leak into ``classes()``, which would make it order-dependent."""
        before = [(c.module, c.qualname) for c in index.classes()]
        assert index.element_class_node(elements.Wallet) is not None

        assert [(c.module, c.qualname) for c in index.classes()] == before
        assert all(module != ELEMENTS_MODULE for module, _ in before)

    def test_both_resolution_doors_answer_with_separate_nodes(self, index):
        """The walked name and the importable name reach the same file, but
        they are different module *names*, so the file is parsed once per name
        and the nodes are equal in position without being the same object.
        A rule joining the two surfaces has to join on
        ``(module, qualname, lineno)``, never on node identity."""
        walked = index.class_entry(WALKED_ELEMENTS, "Wallet")
        resolved = index.class_entry(ELEMENTS_MODULE, "Wallet")

        assert walked is not None and resolved is not None
        assert walked.node.lineno == resolved.node.lineno
        assert walked.node is not resolved.node

    def test_package_walk_runs_before_a_name_is_resolved(self, domain, monkeypatch):
        """Ordering matters: the provider lets the on-disk walk override what
        name resolution cached, so the index must walk first or it can hold a
        node the provider would later replace."""
        provider = SourceProvider(domain)
        calls = []
        real_iter_trees = provider.iter_trees
        real_tree = provider.tree

        def spy_iter_trees():
            calls.append("walk")
            return real_iter_trees()

        def spy_tree(module_name):
            calls.append(f"tree:{module_name}")
            return real_tree(module_name)

        monkeypatch.setattr(provider, "iter_trees", spy_iter_trees)
        monkeypatch.setattr(provider, "tree", spy_tree)

        ElementIndex(domain, provider).element_class_node(elements.Wallet)

        assert calls[0] == "walk"
        assert f"tree:{ELEMENTS_MODULE}" in calls


class TestRoleTags:
    def test_command_handler_method(self, index):
        assert (
            index.role_of(elements.WalletCommandHandler, "open_wallet")
            is MethodRole.COMMAND_HANDLER_METHOD
        )

    def test_repository_method(self, index):
        assert (
            index.role_of(elements.WalletRepository, "find_by_label")
            is MethodRole.REPOSITORY_METHOD
        )

    def test_aggregate_behavior_and_apply_are_not_swapped(self, index):
        """The one pairing that is easy to get backwards."""
        assert index.roles(elements.Wallet) == {
            "rename": MethodRole.AGGREGATE_BEHAVIOR,
            "opened": MethodRole.EVENT_APPLY,
            "deposited": MethodRole.EVENT_APPLY,
        }

    def test_apply_wins_over_a_decorator_beside_it(self, index):
        """``@apply`` stacked with an unrelated decorator is still an apply,
        and the unrelated one does not knock the method out of the vocabulary."""
        method = index.element_class_entry(elements.Wallet).method("deposited")

        assert method.decorators == ("apply", "audited")
        assert index.role_of(elements.Wallet, "deposited") is MethodRole.EVENT_APPLY

    def test_invariants_properties_and_classmethods_are_not_behavior(self, index):
        """The shallow decorator rule reads ``@invariant.post`` as ``post``,
        so the name-derived roles stand back rather than call an invariant a
        behavior. A wrong tag is worse than no tag."""
        for name in ("balance_non_negative", "label", "describe", "__str__"):
            assert index.role_of(elements.Wallet, name) is None

    def test_event_sourced_repository_methods_are_repository_methods(self, index):
        """``EVENT_SOURCED_REPOSITORY`` is a separate element type from
        ``REPOSITORY`` and carries the same role."""
        assert (
            index.role_of(elements.WalletEventSourcedRepository, "find_snapshot")
            is MethodRole.REPOSITORY_METHOD
        )

    def test_process_manager_handlers_are_event_handler_methods(self, index):
        """A process manager handles events with ``@handle``; the vocabulary
        has no separate tag for it, so it shares the event-handler role."""
        assert (
            index.role_of(elements.WalletProcessManager, "on_opened")
            is MethodRole.EVENT_HANDLER_METHOD
        )

    def test_a_private_name_does_not_block_a_decorator_derived_role(self, index):
        """Underscore keeps a method out of the two *name*-derived roles only.
        Protean registers a decorated private method as a handler, so the index
        says it is one."""
        assert (
            index.role_of(elements.WalletEventHandler, "_audit")
            is MethodRole.EVENT_HANDLER_METHOD
        )

    def test_on_reads_as_handle_off_the_projector_too(self, index):
        """``on`` is not a projector-only spelling: it is a literal alias of
        ``handle``, so a command handler written with it is a command-handler
        method, tag and all."""
        entry = index.element_class_entry(elements.WalletCommandHandler)

        assert entry.method("close_wallet").decorators == ("on",)
        assert (
            index.role_of(elements.WalletCommandHandler, "close_wallet")
            is MethodRole.COMMAND_HANDLER_METHOD
        )

    def test_projector_on_and_handle_are_the_same_role(self, index):
        """``on`` is an alias of ``handle`` for projectors."""
        assert index.roles(elements.WalletProjector) == {
            "opened": MethodRole.PROJECTOR_ON_EVENT,
            "deposited": MethodRole.PROJECTOR_ON_EVENT,
        }

    def test_async_handler_is_tagged_like_a_sync_one(self, index):
        method = index.element_class_entry(elements.WalletEventHandler).method(
            "on_deposit"
        )

        assert isinstance(method.node, ast.AsyncFunctionDef)
        assert (
            index.role_of(elements.WalletEventHandler, "on_deposit")
            is MethodRole.EVENT_HANDLER_METHOD
        )

    def test_private_methods_carry_no_role(self, index):
        assert index.role_of(elements.Wallet, "_normalize") is None
        assert index.role_of(elements.WalletRepository, "_cache_key") is None

    def test_unreducible_decorator_leaves_the_method_untagged(self, index):
        """A subscripted decorator cannot be reduced to a name — the index
        drops it rather than guessing, and the method is simply untagged."""
        method = index.element_class_entry(elements.WalletCommandHandler).method(
            "audit"
        )

        assert method is not None
        assert method.decorators == ()
        assert index.role_of(elements.WalletCommandHandler, "audit") is None

    def test_unregistered_class_carries_no_roles(self, index):
        assert index.roles(helpers.LabelFormatter) == {}
        assert index.role_of(helpers.LabelFormatter, "format") is None

    def test_internal_elements_are_not_tagged(self, index, domain):
        """Protean's own machinery is registered too (the memory event store
        registers a repository). Tagging its methods would put framework code
        in a rule's findings."""
        internal = [
            record.cls
            for records in domain._domain_registry._elements.values()
            for record in records.values()
            if record.internal
        ]

        assert len(internal) > 0, "expected the framework to register internals"
        for cls in internal:
            assert index.roles(cls) == {}

    def test_undecorated_methods_on_handler_classes_carry_no_role(self, index):
        """The negative of the two decorator-driven roles: being on a handler
        class is not enough, the decorator has to be there."""
        assert index.role_of(elements.WalletEventHandler, "summarise") is None
        assert index.role_of(elements.WalletProjector, "describe") is None

    def test_element_types_without_roles_tag_nothing(self, index):
        """An element type this vocabulary says nothing about — an event, a
        command, a projection — leaves all its methods untagged."""
        for cls in (elements.WalletOpened, elements.OpenWallet, elements.WalletView):
            assert index.roles(cls) == {}
        # ``WalletView.label`` is public and in the class body — it is the
        # element's *type* that carries no role vocabulary.
        assert index.element_class_entry(elements.WalletView).method("label")
        assert index.role_of(elements.WalletView, "label") is None

    def test_unknown_method_name_has_no_role(self, index):
        assert index.role_of(elements.Wallet, "does_not_exist") is None


class TestQualnameBinding:
    def test_function_local_class_does_not_bind_to_its_module_level_twin(self, index):
        """The mis-binding test. A naive last-segment match would answer this
        with the module-level ``Duplicate``, silently indexing the wrong class."""

        class Duplicate:
            def local_marker(self) -> None:
                pass

        entry = index.element_class_entry(Duplicate)

        assert entry is not None
        assert entry.qualname.endswith(".<locals>.Duplicate")
        assert [m.name for m in entry.methods] == ["local_marker"]

    def test_qualname_whose_function_is_absent_resolves_to_nothing(self, index):
        assert index.class_entry(TEST_MODULE, "Duplicate") is not None
        assert index.class_entry(TEST_MODULE, "no_such_fn.<locals>.Duplicate") is None

    def test_class_with_an_empty_qualname_is_skipped(self, index):
        """A dynamically built class can be nameless. Matching on its final
        name segment would then match nothing useful, so it is refused up
        front."""
        nameless = type("", (), {"__module__": TEST_MODULE})

        assert nameless.__qualname__ == ""
        assert index.element_class_entry(nameless) is None
        assert index.element_methods(nameless) == ()


class TestRebuiltElements:
    """Registering a class that does not already subclass its base rebuilds it
    with ``type()``, which resets ``__qualname__`` to the bare class name. The
    index has to find the class anyway, and must not answer with a same-named
    class that happens to sit at module level."""

    @staticmethod
    def _domain():
        return Domain(name="Rebuilt", root_path=PACKAGE_ROOT)

    def test_a_rebuilt_element_does_not_bind_to_its_module_level_twin(self):
        domain = self._domain()

        @domain.aggregate
        class Rebuilt:
            rebuilt_id = Identifier(identifier=True)

            def real_behavior(self) -> None:
                pass

        domain.init(traverse=False)
        index = ElementIndex(domain)
        entry = index.element_class_entry(Rebuilt)

        # The premise: registration really did flatten the qualname, so the
        # module-level ``Rebuilt`` in this file is a live wrong answer.
        assert Rebuilt.__qualname__ == "Rebuilt"
        assert Rebuilt.__module__ == TEST_MODULE
        assert entry is not None
        assert entry.qualname.endswith(".<locals>.Rebuilt")
        assert [m.name for m in entry.methods] == ["real_behavior"]
        assert index.roles(Rebuilt) == {"real_behavior": MethodRole.AGGREGATE_BEHAVIOR}

    def test_an_element_written_inside_a_class_body_resolves(self):
        domain = self._domain()

        class Enclosing:
            @domain.aggregate
            class Ledger:
                ledger_id = Identifier(identifier=True)

                def post_entry(self) -> None:
                    pass

        domain.init(traverse=False)
        entry = ElementIndex(domain).element_class_entry(Enclosing.Ledger)

        assert entry is not None
        assert entry.qualname.endswith(".Enclosing.Ledger")

    def test_a_rebuilt_element_is_pinned_through_descriptors(self):
        """A ``classmethod`` or ``property`` hides its function behind a
        descriptor. Not looking through it would leave the element with no
        vote at all, and the module-level decoy would win by default."""
        domain = self._domain()

        @domain.aggregate
        class Wrapped:
            wrapped_id = Identifier(identifier=True)

            @classmethod
            def build(cls) -> None:
                pass

            @property
            def shown(self) -> str:
                return "shown"

        domain.init(traverse=False)
        entry = ElementIndex(domain).element_class_entry(Wrapped)

        assert entry is not None
        assert entry.qualname.endswith(".<locals>.Wrapped")
        assert [m.name for m in entry.methods] == ["build", "shown"]

    def test_an_ambiguous_rebuilt_element_with_no_methods_resolves_to_nothing(self):
        """Nothing on the class object says which ``Fieldless`` it is, so the
        index says it does not know rather than picking the decoy."""
        domain = self._domain()

        @domain.aggregate
        class Fieldless:
            fieldless_id = Identifier(identifier=True)

        domain.init(traverse=False)
        index = ElementIndex(domain)

        assert index.element_class_entry(Fieldless) is None
        assert index.element_methods(Fieldless) == ()
        assert index.roles(Fieldless) == {}


class TestFailOpen:
    def test_element_without_source_is_skipped_without_error(self):
        """The issue's third case, on a *registered* element: a class built by
        ``type()`` whose module does not resolve."""
        ghost = type(
            "Ghost", (BaseAggregate,), {"__module__": "protean_no_such_module_xyz"}
        )
        domain = Domain(name="GhostDomain", root_path=PACKAGE_ROOT)
        domain.register(ghost)
        domain.init(traverse=False)
        index = ElementIndex(domain)

        assert index.element_class_node(ghost) is None
        assert index.element_methods(ghost) == ()
        assert index.role_of(ghost, "anything") is None
        assert index.roles(ghost) == {}

    def test_class_with_a_non_string_module_is_skipped(self, index):
        """``__module__`` is whatever the class namespace put there — a
        dynamically built class can carry a non-string, which must not be fed
        to the provider as a module name."""
        odd = type("Odd", (), {"__module__": 42})

        assert index.element_class_node(odd) is None
        assert index.element_methods(odd) == ()
        assert index.roles(odd) == {}

    def test_unparseable_module_is_skipped_and_the_package_still_indexes(
        self, tmp_path
    ):
        package = tmp_path / "brokenpkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "good.py").write_text("class Good:\n    pass\n", encoding="utf-8")
        (package / "bad.py").write_text("class Broken(\n", encoding="utf-8")

        index = ElementIndex(Domain(name="Broken", root_path=str(package)))
        keys = [(c.module, c.qualname) for c in index.classes()]

        assert keys == [("brokenpkg.good", "Good")]

    def test_empty_root_path_yields_an_empty_index(self):
        index = ElementIndex(Domain(name="NoRoot", root_path=""))

        assert index.classes() == ()
        assert index.class_entry("brokenpkg.good", "Good") is None


class TestSourceShapes:
    """Shapes that need hand-written source: duplicate definitions, and the
    decorator forms the fixture package has no natural use for."""

    @staticmethod
    def _index_for(tmp_path, source):
        package = tmp_path / "shapespkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "mod.py").write_text(dedent(source), encoding="utf-8")
        return ElementIndex(Domain(name="Shapes", root_path=str(package)))

    def test_first_definition_of_a_duplicated_class_wins(self, tmp_path):
        """Redefinition in one module resolves to the first one, so the index
        is the same whichever way the tree is walked."""
        index = self._index_for(
            tmp_path,
            """
            class Twice:
                def first(self): ...

            class Twice:
                def second(self): ...
            """,
        )

        assert [m.name for m in index.methods("shapespkg.mod", "Twice")] == ["first"]

    def test_first_definition_of_a_duplicated_method_wins(self, tmp_path):
        index = self._index_for(
            tmp_path,
            """
            class Once:
                @alpha
                def same(self): ...

                @beta
                def same(self): ...
            """,
        )
        method = index.class_entry("shapespkg.mod", "Once").method("same")

        assert method.decorators == ("alpha",)

    def test_dotted_decorator_reads_as_its_last_segment(self, tmp_path):
        index = self._index_for(
            tmp_path,
            """
            class Handler:
                @protean.handle
                def act(self): ...

                @protean.mixins.handle(Thing)
                def react(self): ...
            """,
        )
        entry = index.class_entry("shapespkg.mod", "Handler")

        assert entry.method("act").decorators == ("handle",)
        assert entry.method("react").decorators == ("handle",)

    def test_class_declared_inside_a_conditional_is_indexed(self, tmp_path):
        index = self._index_for(
            tmp_path,
            """
            if True:
                class Conditional:
                    def here(self): ...
            """,
        )

        assert index.class_node("shapespkg.mod", "Conditional") is not None

    def test_classes_in_try_with_and_else_bodies_are_indexed(self, tmp_path):
        """The statement walk has to reach every body, not just ``if``."""
        index = self._index_for(
            tmp_path,
            """
            import contextlib

            try:
                class InTry: ...
            except ImportError:
                class InExcept: ...
            else:
                class InElse: ...
            finally:
                class InFinally: ...

            with contextlib.nullcontext():
                class InWith: ...

            for _ in range(1):
                class InFor: ...
            """,
        )
        found = {c.qualname for c in index.classes()}

        assert found == {
            "InTry",
            "InExcept",
            "InElse",
            "InFinally",
            "InWith",
            "InFor",
        }

    def test_class_nested_inside_a_method_gets_both_segments(self, tmp_path):
        """A class inside a method of a class: the qualname carries the outer
        class, the method's ``<locals>``, and the inner class."""
        index = self._index_for(
            tmp_path,
            """
            class Outer:
                def build(self):
                    class Inner:
                        def deep(self): ...
                    return Inner
            """,
        )

        assert [c.qualname for c in index.classes()] == [
            "Outer",
            "Outer.build.<locals>.Inner",
        ]
        assert [m.name for m in index.methods("shapespkg.mod", "Outer")] == ["build"]
        assert [
            m.name for m in index.methods("shapespkg.mod", "Outer.build.<locals>.Inner")
        ] == ["deep"]

    def test_methods_wrapped_in_a_conditional_are_still_methods(self, tmp_path):
        """A method under ``if TYPE_CHECKING:`` or inside a ``try`` is written
        in the class body, so it is a method of the class."""
        index = self._index_for(
            tmp_path,
            """
            from typing import TYPE_CHECKING

            class Wrapped:
                def plain(self): ...

                if TYPE_CHECKING:
                    def conditional(self): ...

                try:
                    def guarded(self): ...
                except ImportError:
                    pass

                class Nested:
                    def not_mine(self): ...
            """,
        )

        assert [m.name for m in index.methods("shapespkg.mod", "Wrapped")] == [
            "conditional",
            "guarded",
            "plain",
        ]

    def test_a_deeply_nested_expression_does_not_break_the_walk(self, tmp_path):
        """The walk descends statements only. Descending expressions would put
        one long arithmetic expression past the recursion limit and take the
        whole package's index down with it."""
        index = self._index_for(
            tmp_path,
            "x = " + "+".join("1" for _ in range(2000)) + "\n\nclass After: ...\n",
        )

        assert [c.qualname for c in index.classes()] == ["After"]


class TestCachingAndDeterminism:
    def test_the_package_is_walked_once(self, domain, monkeypatch):
        provider = SourceProvider(domain)
        walks = []
        real_iter_trees = provider.iter_trees
        monkeypatch.setattr(
            provider,
            "iter_trees",
            lambda: (walks.append(1), real_iter_trees())[1],
        )
        index = ElementIndex(domain, provider)

        index.classes()
        index.classes()
        index.element_class_node(elements.Wallet)
        index.class_entry(WALKED_HELPERS, "LabelFormatter")

        assert walks == [1]

    def test_repeated_lookups_return_the_same_node(self, index):
        first = index.element_class_node(elements.Wallet)
        second = index.element_class_node(elements.Wallet)

        assert first is second

    def test_an_on_demand_module_is_indexed_once(self, domain, monkeypatch):
        """The provider caches trees, but re-indexing a cached tree on every
        lookup would rebuild every entry. The index keeps its own answer."""
        provider = SourceProvider(domain)
        asked = []
        real_tree = provider.tree
        monkeypatch.setattr(
            provider,
            "tree",
            lambda name: (asked.append(name), real_tree(name))[1],
        )
        index = ElementIndex(domain, provider)

        index.element_class_node(elements.Wallet)
        index.element_class_node(elements.WalletRepository)
        index.role_of(elements.Wallet, "rename")

        assert asked == [ELEMENTS_MODULE]

    def test_the_registry_is_read_once(self):
        """The element map is a snapshot taken on the first role query, which
        matches the one-index-per-build lifetime: an element registered after
        the build started is not part of the build being analysed."""
        partial = Domain(name="Snapshot", root_path=PACKAGE_ROOT)
        partial.register(elements.Wallet, event_sourced=True)
        partial.register(elements.WalletOpened, part_of=elements.Wallet)
        partial.register(elements.FundsDeposited, part_of=elements.Wallet)
        partial.init(traverse=False)
        index = ElementIndex(partial)
        assert index.role_of(elements.Wallet, "rename") is not None

        partial.register(elements.WalletRepository, part_of=elements.Wallet)

        assert index.roles(elements.WalletRepository) == {}
        assert ElementIndex(partial).roles(elements.WalletRepository) == {
            "find_by_label": MethodRole.REPOSITORY_METHOD
        }

    def test_entries_cannot_be_rewritten_under_a_later_rule(self, index):
        """Every rule in a build shares these entries, so an entry that could
        be reassigned would let one rule poison the next."""
        entry = index.element_class_entry(elements.Wallet)
        method = entry.method("rename")

        with pytest.raises(FrozenInstanceError):
            entry.node = None
        with pytest.raises(FrozenInstanceError):
            method.decorators = ("handle",)

    def test_two_independent_builds_agree(self, domain):
        def snapshot(index):
            return [
                (c.module, c.qualname, tuple(m.name for m in c.methods))
                for c in index.classes()
            ]

        assert snapshot(ElementIndex(domain)) == snapshot(ElementIndex(domain))


class TestBuilderWiring:
    def test_index_is_created_once_and_shares_the_builders_provider(self, domain):
        builder = IRBuilder(domain)

        assert builder.index is builder.index
        # Same provider means the file is parsed once for both layers: the node
        # the index hands out is a node of the provider's cached tree.
        tree = builder.source.tree(ELEMENTS_MODULE)
        node = builder.index.element_class_node(elements.Wallet)
        assert any(child is node for child in ast.walk(tree))

    def test_build_never_touches_the_index(self, domain):
        """The index walks the whole package, so a build whose rules never ask
        for it must not pay for it."""
        builder = IRBuilder(domain)
        builder.build()

        assert builder._index is None

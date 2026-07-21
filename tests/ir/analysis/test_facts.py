"""FactCatalog: call/attribute/construction facts, receiver roles, determinism."""

from pathlib import Path
from textwrap import dedent

import pytest

from protean import Domain
from protean.ir.analysis import (
    ElementIndex,
    FactCatalog,
    ReceiverRole,
    SourceProvider,
    SymbolResolver,
)
from protean.ir.builder import IRBuilder
from tests.ir.support import behavioral_domain
from tests.ir.support.behavioral_domain import behavior

pytestmark = pytest.mark.no_test_domain

#: The behavior module under the name Python resolves it by — the name whose
#: FQNs match what the registry recorded, which the walk's name does not.
BEHAVIOR_MODULE = behavior.__name__

PACKAGE_ROOT = str(Path(behavioral_domain.__file__).parent)


def _make_pkg(tmp_path, source):
    """Write a one-module ``pkg`` package on disk and return its root."""
    root = tmp_path / "pkg"
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "mod.py").write_text(dedent(source), encoding="utf-8")
    return root


def _walked_catalog(root):
    """A catalog whose provider has ``pkg`` cached under its walked names.

    The package walk reads the files from disk, so trees and symbol tables are
    keyed under the walked module names and nothing is imported. Returns the
    catalog and its index, so a test can fetch a method node without re-walking.
    """
    domain = Domain(name="Facts", root_path=str(root))
    provider = SourceProvider(domain)
    dict(provider.iter_trees())
    index = ElementIndex(domain, provider)
    resolver = SymbolResolver(domain, provider)
    return FactCatalog(domain, provider, index, resolver), index


def _method_facts(catalog, index, module, qualname, method_name):
    """The facts of one method, fetched through the shared index."""
    entry = index.class_entry(module, qualname)
    assert entry is not None, f"{module}:{qualname} must be indexed"
    method = entry.method(method_name)
    assert method is not None, f"{qualname}.{method_name} must be a method"
    return catalog.method_facts(module, method.node)


@pytest.fixture(scope="module")
def order_domain():
    """The behavior fixture registered as a real domain, for construction facts."""
    domain = Domain(name="Behavioral", root_path=PACKAGE_ROOT)
    domain.register(behavior.Order)
    domain.register(behavior.OrderShipped, part_of=behavior.Order)
    domain.register(behavior.OrderRepository, part_of=behavior.Order)
    domain.init(traverse=False)
    return domain


@pytest.fixture(scope="module")
def order_catalog(order_domain):
    return FactCatalog(order_domain)


class TestAttributeFacts:
    def test_a_write_and_a_read_are_told_apart(self, order_catalog):
        """The issue's second case: ``self.status = "x"`` is a write and
        ``self.total`` in a load position is a read, not the other way round."""
        facts = order_catalog.element_facts(behavior.Order)["ship"]

        assert len(facts.attributes) > 0, "ship must record attribute facts"
        writes = {a.name for a in facts.attributes if a.is_write}
        reads = {a.name for a in facts.attributes if not a.is_write}

        assert "status" in writes
        assert "status" not in reads
        assert "total" in reads
        assert "total" not in writes

    def test_the_receiver_of_a_self_attribute_is_self(self, order_catalog):
        facts = order_catalog.element_facts(behavior.Order)["ship"]

        status = next(a for a in facts.attributes if a.name == "status")

        assert status.receiver == "self"

    def test_an_augmented_assignment_is_a_write(self, order_catalog):
        """``self.stock += 1`` reads and writes, but the grammar models its
        target as a store, so it is recorded as a write — the half a lost-write
        rule keys on."""
        facts = order_catalog.element_facts(behavior.Order)["restock"]

        stock = [a for a in facts.attributes if a.name == "stock"]

        assert len(stock) == 1
        assert stock[0].is_write is True

    def test_a_subscript_write_reads_the_container(self, tmp_path):
        """The documented ctx limitation: ``self.items[0] = 5`` stores into the
        subscript, so the grammar loads ``self.items`` — it shows as a *read* of
        ``items``, not a write. A mutation rule built on this must know that."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        self.items[0] = 5
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        items = [a for a in facts.attributes if a.name == "items"]

        assert len(items) == 1
        assert items[0].is_write is False

    def test_a_nested_attribute_write_reads_the_container(self, tmp_path):
        """The documented ctx limitation: ``self.a.b = 1`` writes ``b`` (with no
        plain-name receiver) and reads ``a`` — there is no ``self.a`` write."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        self.a.b = 1
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        by_name = {a.name: a for a in facts.attributes}

        assert by_name["b"].is_write is True
        assert by_name["b"].receiver is None
        assert by_name["a"].is_write is False

    def test_a_call_method_name_is_not_an_attribute_fact(self, order_catalog):
        """``self._dao.filter`` — the ``filter`` names the call, not a data
        access, so it is not an attribute fact; ``self._dao`` still is."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["active"]

        names = {a.name for a in facts.attributes}

        assert "filter" not in names
        assert "_dao" in names


class TestCallFacts:
    def test_a_repository_query_resolves_its_role_and_field(self, order_catalog):
        """The issue's first case: ``self._dao.filter(status=...)`` is a call
        with receiver role ``REPOSITORY_QUERY`` and the ``status`` field."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["active"]

        query = next(c for c in facts.calls if c.method == "filter")

        assert query.receiver_role is ReceiverRole.REPOSITORY_QUERY
        assert "status" in query.field_names

    def test_a_raise_call_is_classified(self, order_catalog):
        """``self.raise_(OrderShipped(...))`` is a call classified ``RAISE_``."""
        facts = order_catalog.element_facts(behavior.Order)["ship"]

        raises = [c for c in facts.calls if c.method == "raise_"]

        assert len(raises) == 1
        assert raises[0].receiver_role is ReceiverRole.RAISE_

    def test_a_query_field_from_an_inline_q(self, order_catalog):
        """A ``Q(reference=...)`` passed to ``find`` names the ``reference``
        field, extracted from the inline construction."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["by_reference"]

        query = next(c for c in facts.calls if c.method == "find")

        assert query.receiver_role is ReceiverRole.REPOSITORY_QUERY
        assert "reference" in query.field_names

    def test_a_unit_of_work_receiver_is_classified(self, order_catalog):
        """``UnitOfWork().commit()`` is a call on a Unit-of-Work receiver."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["in_transaction"]

        commit = next(c for c in facts.calls if c.method == "commit")

        assert commit.receiver_role is ReceiverRole.UNIT_OF_WORK

    def test_a_dynamic_keyword_query_names_no_field(self, order_catalog):
        """``self._dao.filter(**filters)`` marks the call dynamic and fabricates
        no field name."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["dynamic"]

        query = next(c for c in facts.calls if c.method == "filter")

        assert query.dynamic_kwargs is True
        assert query.field_names == ()

    def test_the_whole_query_surface_recognises_and_extracts_fields(self, tmp_path):
        """The issue's deliverable across the full surface: ``get``, ``find_by``,
        ``add`` and ``exclude`` on a recognized ``self._dao`` are each a
        ``REPOSITORY_QUERY`` and each names its keyword field, not only the
        ``filter``/``find`` the corpus already covers."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Repo:
                    def run(self):
                        self._dao.get(order_id="1")
                        self._dao.find_by(email="a@b.c")
                        self._dao.add(item="x")
                        self._dao.exclude(status="void")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Repo", "run")

        assert len(facts.calls) >= 4
        by_method = {c.method: c for c in facts.calls}
        for name, field in (
            ("get", "order_id"),
            ("find_by", "email"),
            ("add", "item"),
            ("exclude", "status"),
        ):
            call = by_method[name]
            assert call.receiver_role is ReceiverRole.REPOSITORY_QUERY, name
            assert field in call.field_names, name

    def test_resolvable_callee_and_receiver_fqns_are_reported(self, tmp_path):
        """A module-level ``helper()`` resolves its callee FQN; an ``os.getcwd()``
        resolves both a receiver FQN and a callee FQN — the two fields the corpus
        (all self-rooted) never drives off ``None``."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                import os

                def helper():
                    pass

                class Service:
                    def run(self):
                        helper()
                        os.getcwd()
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        helper = next(c for c in facts.calls if c.method == "helper")
        getcwd = next(c for c in facts.calls if c.method == "getcwd")

        assert helper.callee_fqn == "pkg.mod.helper"
        assert helper.receiver_fqn is None
        assert getcwd.callee_fqn == "os.getcwd"
        assert getcwd.receiver_fqn == "os"

    def test_a_unit_of_work_name_receiver_is_classified(self, tmp_path):
        """A receiver whose *name* resolves to the Unit-of-Work FQN
        (``UnitOfWork.commit()`` on the imported class) is tagged
        ``UNIT_OF_WORK`` off the resolved FQN, not only the inline
        ``UnitOfWork()`` construction the corpus already covers."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                from protean.core.unit_of_work import UnitOfWork

                class Service:
                    def run(self):
                        UnitOfWork.commit()
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        commit = next(c for c in facts.calls if c.method == "commit")

        assert commit.receiver_role is ReceiverRole.UNIT_OF_WORK

    def test_a_non_q_positional_call_in_a_query_contributes_no_field(self, tmp_path):
        """A positional call argument that is not an inline ``Q``
        (``find(build(), status=...)``) is skipped, not mistaken for a field
        source; the keyword field is still the only one named."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        self._dao.find(build(), status="new")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        query = next(c for c in facts.calls if c.method == "find")

        assert query.field_names == ("status",)

    def test_a_computed_callee_has_no_method_name(self, tmp_path):
        """A call whose callee is neither a name nor an attribute
        (``funcs[0]()``) has no trailing method name, so ``method`` and
        ``callee_fqn`` are both ``None`` and the receiver stays ``UNKNOWN``."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self, funcs):
                        funcs[0]()
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        assert len(facts.calls) == 1
        call = facts.calls[0]
        assert call.method is None
        assert call.callee_fqn is None
        assert call.receiver_role is ReceiverRole.UNKNOWN


class TestConstructionFacts:
    def test_constructing_a_registered_aggregate_is_a_construction(self, order_catalog):
        """The issue's third case: ``Order(...)`` where ``Order`` is a
        registered aggregate is a construction resolved to its FQN."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["seed"]

        assert len(facts.constructions) == 1
        construction = facts.constructions[0]

        assert construction.fqn == f"{BEHAVIOR_MODULE}.Order"
        assert "status" in construction.field_names

    def test_a_construction_is_not_also_a_call(self, order_catalog):
        """A construction is recorded once, as a construction, never doubled as
        a call fact."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["seed"]

        assert len(facts.constructions) == 1
        assert [c.method for c in facts.calls if c.method == "Order"] == []

    def test_a_plain_non_domain_call_yields_no_construction(self, order_catalog):
        """The reverse of the XOR: a query call on ``self._dao`` is a call fact
        and contributes no construction — only a domain-element callee does."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["active"]

        assert len(facts.calls) > 0
        assert facts.constructions == ()

    def test_a_spread_construction_is_dynamic_and_names_no_field(self, order_catalog):
        """``Order(**data)`` is a construction whose ``**`` star marks it dynamic
        and fabricates no field name."""
        facts = order_catalog.element_facts(behavior.OrderRepository)["seed_dynamic"]

        assert len(facts.constructions) == 1
        construction = facts.constructions[0]

        assert construction.fqn == f"{BEHAVIOR_MODULE}.Order"
        assert construction.dynamic_kwargs is True
        assert construction.field_names == ()

    def test_a_nested_construction_is_recorded(self, order_catalog):
        """``self.raise_(OrderShipped(...))`` records the inner ``OrderShipped``
        construction in its own right, beside the outer ``raise_`` call."""
        facts = order_catalog.element_facts(behavior.Order)["ship"]

        assert len(facts.constructions) == 1
        assert facts.constructions[0].fqn == f"{BEHAVIOR_MODULE}.OrderShipped"


class TestReceiverConservatism:
    def test_a_variable_held_repo_is_left_unknown(self, tmp_path):
        """The negative: a ``.filter`` on a local variable needs dataflow to
        know what it holds, so its role is ``UNKNOWN`` — the field is still
        recorded, but the receiver is not fabricated as a repository."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        repo = get_repo()
                        repo.filter(status="active")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        query = next(c for c in facts.calls if c.method == "filter")

        assert query.receiver_role is ReceiverRole.UNKNOWN
        assert "status" in query.field_names

    def test_an_attribute_chain_rooted_at_a_variable_is_left_unknown(self, tmp_path):
        """A chain rooted at a local variable (``repo.query.filter``) is as
        unresolvable as the bare variable, so it too is ``UNKNOWN``."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        repo = get_repo()
                        repo.query.filter(status="active")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        query = next(c for c in facts.calls if c.method == "filter")

        assert query.receiver_role is ReceiverRole.UNKNOWN

    def test_a_variable_held_object_named_add_is_not_a_repository(self, tmp_path):
        """A method named ``add`` on a plain variable is not statically a
        repository, so it is not misclassified as a query."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        items = collect()
                        items.add(value=1)
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        add = next(c for c in facts.calls if c.method == "add")

        assert add.receiver_role is ReceiverRole.UNKNOWN

    def test_a_call_result_receiver_is_left_unknown(self, tmp_path):
        """A method on an arbitrary call result (``get_repo().filter(...)``) is
        *less* knowable than a variable, not more: its callee resolves to
        nothing, so the receiver is not waved through as a repository."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        get_repo().filter(status="active")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        query = next(c for c in facts.calls if c.method == "filter")

        assert query.receiver_role is ReceiverRole.UNKNOWN

    def test_a_subscript_receiver_is_left_unknown(self, tmp_path):
        """A receiver that is neither a name/attribute chain nor a construction
        (``handlers[0].filter(...)``) has no static root to recognize, so it is
        left ``UNKNOWN`` rather than waved through as a query."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self, handlers):
                        handlers[0].filter(status="active")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        query = next(c for c in facts.calls if c.method == "filter")

        assert query.receiver_role is ReceiverRole.UNKNOWN

    def test_a_recognized_receiver_with_a_non_surface_method_is_unknown(self, tmp_path):
        """A recognized ``self`` receiver whose method is none of the known
        surfaces (``self.compute()``) is ``UNKNOWN``, not defaulted to a role."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        self.compute()
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        compute = next(c for c in facts.calls if c.method == "compute")

        assert compute.receiver_role is ReceiverRole.UNKNOWN

    def test_a_self_rooted_generic_method_is_a_known_false_positive(self, tmp_path):
        """A documented precision limit, pinned so a later dataflow layer (#1223)
        notices when it changes: ``self.cache.get(...)`` shares a name with the
        query surface on a recognized ``self`` receiver, so it reads as
        ``REPOSITORY_QUERY`` until types tell the two apart. Not a
        reproducibility bug — the verdict is stable — but a false positive a
        consumer must know about."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        self.cache.get("k")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        get = next(c for c in facts.calls if c.method == "get")

        assert get.receiver_role is ReceiverRole.REPOSITORY_QUERY

    def test_a_programmatically_composed_q_names_no_field(self, tmp_path):
        """A ``Q`` held in a variable is not an inline ``Q(field=...)``, so a
        query passed one names no field rather than a guessed one."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self, dao, q):
                        self._dao.find(q)
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        query = next(c for c in facts.calls if c.method == "find")

        assert query.receiver_role is ReceiverRole.REPOSITORY_QUERY
        assert query.field_names == ()

    def test_fields_are_extracted_even_when_the_receiver_is_unknown(self, tmp_path):
        """Field extraction follows the query method, not the receiver role: a
        variable-held ``repo.find(Q(reference=...), status=...)`` reports both
        fields even though the receiver is left ``UNKNOWN``."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                from protean.utils.query import Q

                class Service:
                    def run(self, repo):
                        repo.find(Q(reference="r"), status="new")
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        query = next(c for c in facts.calls if c.method == "find")

        assert query.receiver_role is ReceiverRole.UNKNOWN
        assert set(query.field_names) == {"reference", "status"}


class TestScope:
    def test_a_call_in_a_nested_function_is_not_this_methods_fact(self, tmp_path):
        """A call inside a nested ``def`` is a fact of that function, not of the
        method enclosing it."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        self.outer()

                        def inner():
                            self.hidden()
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        methods = {c.method for c in facts.calls}

        assert "outer" in methods
        assert "hidden" not in methods

    def test_a_call_in_a_comprehension_is_this_methods_fact(self, tmp_path):
        """A comprehension does not open a callable boundary, so a call in one
        is lexically part of the method and is recorded."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self, rows):
                        return [transform(row) for row in rows]
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        assert "transform" in {c.method for c in facts.calls}


class TestDeterminism:
    def test_two_catalogs_over_the_same_source_agree(self):
        """Two catalogs over the same file produce equal facts in equal order."""
        first = Domain(name="First", root_path=PACKAGE_ROOT)
        first.register(behavior.Order)
        first.register(behavior.OrderShipped, part_of=behavior.Order)
        first.register(behavior.OrderRepository, part_of=behavior.Order)
        first.init(traverse=False)
        second = Domain(name="Second", root_path=PACKAGE_ROOT)
        second.register(behavior.Order)
        second.register(behavior.OrderShipped, part_of=behavior.Order)
        second.register(behavior.OrderRepository, part_of=behavior.Order)
        second.init(traverse=False)

        first_facts = FactCatalog(first).element_facts(behavior.Order)["ship"]
        second_facts = FactCatalog(second).element_facts(behavior.Order)["ship"]

        assert len(first_facts.attributes) > 0
        assert first_facts == second_facts

    def test_facts_are_computed_once_and_cached(self, order_catalog):
        entry = order_catalog._index.element_class_entry(behavior.Order)
        node = entry.method("ship").node

        assert order_catalog.method_facts(entry.module, node) is (
            order_catalog.method_facts(entry.module, node)
        )


class TestFailOpen:
    def test_an_element_with_no_resolvable_source_yields_no_facts(self, order_domain):
        """A class whose ``__module__`` resolves to nothing cannot be placed, so
        it yields an empty mapping rather than raising."""
        catalog = FactCatalog(order_domain)
        ghost = type("Ghost", (), {"method": lambda self: None})
        ghost.__module__ = "no_such_module_xyz"

        assert catalog.element_facts(ghost) == {}

    def test_method_facts_over_a_module_without_source_do_not_raise(
        self, order_catalog
    ):
        """A method node placed under a module the provider cannot locate still
        yields facts — their locations simply carry no path — never a raise."""
        entry = order_catalog._index.element_class_entry(behavior.Order)
        node = entry.method("ship").node

        facts = order_catalog.method_facts("no_such_module_xyz", node)

        assert len(facts.attributes) > 0, "the facts must still be collected"
        assert all(a.location.path is None for a in facts.attributes)

    def test_a_recursion_error_during_the_walk_fails_open(self, tmp_path, monkeypatch):
        """A method that nests an expression deeper than the interpreter's stack
        raises ``RecursionError`` mid-walk; a fail-open catalog must catch it and
        yield no facts, never let it escape. Driven deterministically by making
        the walk raise ``RecursionError`` rather than by a fixed nesting depth:
        whether a given depth trips the limit rides on the caller's ambient
        stack, which made a fixed ``.a * 1500`` chain pass in isolation and
        collect 1500 facts under the full suite."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        self.helper(x=1)
                """,
            )
        )
        node = index.class_entry("pkg.mod", "Service").method("run").node

        def boom(*args, **kwargs):
            raise RecursionError("simulated stack exhaustion mid-walk")

        monkeypatch.setattr(catalog._resolver, "resolve", boom)

        facts = catalog.method_facts("pkg.mod", node)

        assert facts.attributes == ()
        assert facts.calls == ()
        assert facts.constructions == ()


class TestOrdering:
    def test_facts_come_back_in_line_col_order(self, tmp_path):
        """The ``MethodFacts`` contract is a ``(line, col)`` order. The pre-order
        walk already emits facts in that order, so the sort is a normalization
        guard; this pins the observable contract across a multi-fact method with
        two attribute reads on one line."""
        catalog, index = _walked_catalog(
            _make_pkg(
                tmp_path,
                """
                class Service:
                    def run(self):
                        first = self.alpha
                        chosen = self.beta or self.gamma
                """,
            )
        )
        facts = _method_facts(catalog, index, "pkg.mod", "Service", "run")

        positions = [(a.location.line, a.location.col) for a in facts.attributes]

        assert len(positions) >= 3
        assert positions == sorted(positions)
        assert [a.name for a in facts.attributes] == ["alpha", "beta", "gamma"]


class TestBuilderWiring:
    def test_catalog_shares_the_builders_provider(self, order_domain):
        """A catalog built on a builder's provider and index reads a method the
        builder already parsed without re-walking."""
        builder = IRBuilder(order_domain)
        catalog = FactCatalog(order_domain, builder.source, builder.index)

        facts = catalog.element_facts(behavior.Order)["ship"]

        assert len(facts.attributes) > 0

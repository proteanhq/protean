"""BehavioralView: the three query families, the filter convenience, sharing.

The view is a read-only façade over the five substrate layers. These tests prove
it surfaces each family (elements → methods, per-method facts, dataflow), that
its ``filter_call_sites`` convenience returns the exact fields an element filters
on, that it reuses the builder's one provider/index (a module is parsed once),
and that it fails open on a class with no source. The behavior corpus is
registered as a real domain so a construction resolves and a repository query is
recognized, exactly as the fact-catalog tests do.
"""

from pathlib import Path

import pytest

import protean
import protean.ir
from protean import Domain
from protean.ir.analysis import (
    BehavioralView,
    ElementIndex,
    FilterCallSite,
    ReceiverRole,
    SourceProvider,
)
from protean.ir.analysis.dataflow import MethodFlow
from protean.ir.builder import IRBuilder
from tests.ir.support import behavioral_domain
from tests.ir.support.behavioral_domain import behavior

pytestmark = pytest.mark.no_test_domain

#: The behavior module under the name Python resolves it by — the name whose
#: FQNs match what the registry recorded, which a package walk's name does not.
BEHAVIOR_MODULE = behavior.__name__

PACKAGE_ROOT = str(Path(behavioral_domain.__file__).parent)


@pytest.fixture(scope="module")
def order_domain():
    """The behavior fixture registered as a real domain."""
    domain = Domain(name="ViewBehavioral", root_path=PACKAGE_ROOT)
    domain.register(behavior.Order)
    domain.register(behavior.OrderShipped, part_of=behavior.Order)
    domain.register(behavior.OrderRepository, part_of=behavior.Order)
    domain.init(traverse=False)
    return domain


@pytest.fixture(scope="module")
def view(order_domain):
    """A view built the way a builder builds it, over its own provider/index."""
    return IRBuilder(order_domain).view


class TestElementsToMethods:
    def test_element_methods_returns_the_written_methods(self, view):
        """The first family: an element's methods, straight from the index."""
        methods = view.element_methods(behavior.OrderRepository)

        assert len(methods) > 0, "OrderRepository must have indexed methods"
        names = {method.name for method in methods}
        assert {"active", "by_reference", "dynamic", "seed"} <= names

    def test_element_class_entry_is_the_indexed_class(self, view):
        entry = view.element_class_entry(behavior.OrderRepository)

        assert entry is not None
        assert entry.qualname == "OrderRepository"
        assert entry.module == BEHAVIOR_MODULE


class TestPerMethodFacts:
    def test_element_facts_maps_names_to_facts(self, view):
        """The second family: name -> MethodFacts, from the catalog."""
        facts = view.element_facts(behavior.OrderRepository)

        assert set(facts) >= {"active", "by_reference", "dynamic"}
        query = next(c for c in facts["active"].calls if c.method == "filter")
        assert query.receiver_role is ReceiverRole.REPOSITORY_QUERY
        assert query.field_names == ("status",)

    def test_method_facts_by_node_returns_that_bodys_facts(self, view):
        """The by-node door resolves a method node to its own body's facts.

        Asserts the concrete values ``method_facts`` computes for ``between``
        (its two repository ``filter`` calls, in source order) rather than
        comparing to ``element_facts``, which is the same cached object by
        construction and so would match under any regression.
        """
        entry = view.element_class_entry(behavior.OrderRepository)
        node = entry.method("between").node

        facts = view.method_facts(entry.module, node)

        filters = [c for c in facts.calls if c.method == "filter"]
        assert [c.field_names for c in filters] == [
            ("status", "channel"),
            ("reference",),
        ]
        assert all(c.receiver_role is ReceiverRole.REPOSITORY_QUERY for c in filters)


class TestFilterCallSites:
    def test_filter_call_sites_reports_each_site_and_its_fields_in_order(self, view):
        """The headline convenience: the element's ``filter`` sites and fields,
        in the order the contract promises — methods by name, then call-sites
        within a method in source order.

        ``active`` filters on ``status``; ``between`` filters twice
        (``status`` + ``channel``, then ``reference``), which pins both
        field-name order and call-site-within-a-method order; ``dynamic``
        filters on ``**filters`` so names no field. ``by_reference`` uses
        ``find``, not ``filter``, so it is not a filter call-site.
        """
        sites = view.filter_call_sites(behavior.OrderRepository)

        assert len(sites) > 0, "OrderRepository has filter call-sites"
        for site in sites:
            assert isinstance(site, FilterCallSite)
        # An ordered sequence, not a set: the assertion pins the view's
        # determinism contract (name order across methods, source order within
        # a method) and the source order of a multi-field filter's field names.
        pairs = [(site.method_name, site.field_names) for site in sites]
        assert pairs == [
            ("active", ("status",)),
            ("between", ("status", "channel")),
            ("between", ("reference",)),
            ("dynamic", ()),
        ]

    def test_filter_call_sites_carry_a_location(self, view):
        """Each site names where it is, so a rule can report the finding there."""
        sites = view.filter_call_sites(behavior.OrderRepository)
        active = next(s for s in sites if s.method_name == "active")

        assert active.location.line > 0
        assert active.location.path is not None
        assert active.location.path.endswith("behavior.py")

    def test_a_find_is_not_reported_as_a_filter_site(self, view):
        """``by_reference`` queries with ``find``; it names no filter site."""
        sites = view.filter_call_sites(behavior.OrderRepository)

        assert "by_reference" not in {site.method_name for site in sites}

    def test_a_non_repository_filter_is_not_reported_as_a_filter_site(self, view):
        """A ``.filter(...)`` on a plain local is a filter call but not a
        repository one, so the view excludes it.

        ``stale`` calls ``rows.filter(...)`` on a parameter, so its receiver
        role is ``UNKNOWN``, not ``REPOSITORY_QUERY``. This guards the
        ``receiver_role is REPOSITORY_QUERY`` half of the predicate: without it
        a plain-object ``.filter`` would be misreported as a repository filter
        site.
        """
        # The call really is a ``filter`` fact — only its receiver role differs,
        # so the exclusion is proven to hinge on the role, not the method name.
        stale_call = next(
            c
            for c in view.element_facts(behavior.OrderRepository)["stale"].calls
            if c.method == "filter"
        )
        assert stale_call.receiver_role is ReceiverRole.UNKNOWN

        sites = view.filter_call_sites(behavior.OrderRepository)

        assert "stale" not in {site.method_name for site in sites}


class TestDataflowSurface:
    def test_method_flow_surfaces_dataflow_for_a_body(self, view):
        """The third family: the analyzer's MethodFlow, reached through the view."""
        entry = view.element_class_entry(behavior.OrderRepository)
        node = entry.method("by_reference").node

        flow = view.method_flow(entry.module, node)

        assert isinstance(flow, MethodFlow)
        assert len(flow.statements()) > 0
        # ``by_reference(self, reference)`` — its parameters are dataflow bindings
        # the view now exposes, proving #1223 is surfaced, not re-implemented.
        assert "reference" in {param.name for param in flow.parameters}


class TestSharedProviderAndIndex:
    def test_the_view_is_cached_and_reuses_the_builders_provider_and_index(
        self, order_domain
    ):
        """ "Built once per run": one view, over the builder's one provider/index.

        If the view built its own provider a module would parse twice; the shared
        identity is what the "one parse per run" contract rests on.
        """
        builder = IRBuilder(order_domain)

        first = builder.view
        assert builder.view is first, "the view is built once and cached"
        assert first._provider is builder.source, "shares the builder's provider"
        assert first._index is builder.index, "shares the builder's index"

    def test_the_facts_and_dataflow_share_the_one_provider(self, order_domain):
        """The catalog and analyzer under the view use the same provider too."""
        builder = IRBuilder(order_domain)
        view = builder.view

        assert view._facts._provider is builder.source
        assert view._dataflow._provider is builder.source
        assert view._facts._index is builder.index

    def test_a_standalone_view_builds_its_own_provider_and_index(self, order_domain):
        """With no provider/index passed, the view builds fresh ones and still
        answers — the default path for a view with no builder to share with."""
        view = BehavioralView(order_domain)

        assert isinstance(view._provider, SourceProvider)
        assert isinstance(view._index, ElementIndex)
        assert view.filter_call_sites(behavior.OrderRepository) != ()


class TestFailOpen:
    def test_a_class_with_no_source_yields_empty_from_every_query(self, view):
        """Negative: a dynamically-created class has no source, so every element
        query returns empty rather than raising."""
        ghost = type("Ghost", (), {})

        assert view.element_class_entry(ghost) is None
        assert view.element_methods(ghost) == ()
        assert view.element_facts(ghost) == {}
        assert view.filter_call_sites(ghost) == ()


class TestInternalSurface:
    def test_the_view_is_not_re_exported_from_protean(self):
        """The view is internal: it must not leak onto ``protean``/``protean.ir``."""
        assert "BehavioralView" not in getattr(protean, "__all__", [])
        assert not hasattr(protean, "BehavioralView")
        assert not hasattr(protean.ir, "BehavioralView")

"""Diagnostics: TestCircularClusterDependency."""

from protean import Domain
from protean.fields import Reference
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.diagnostics._helpers import (
    _circular_findings,
)


class TestCircularClusterDependency:
    """CIRCULAR_CLUSTER_DEPENDENCY flags aggregate clusters whose cross-cluster
    identity references form a directed cycle, and only those."""

    def test_two_cluster_cycle_flags_both(self):
        domain = Domain(name="TwoCycle", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)
            customer = Reference("Customer")

        @domain.aggregate
        class Customer:
            name = String(max_length=50)
            latest_order = Reference("Order")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _circular_findings(ir)
        assert len(findings) == 2, "one diagnostic per participating cluster"
        assert sorted(d["element"] for d in findings) == sorted(
            [fqn(Order), fqn(Customer)]
        )
        for d in findings:
            assert d["level"] == "warning"
            assert d["category"] == "bounded_context"
            # The message names the whole mutually-dependent group.
            assert fqn(Order) in d["message"]
            assert fqn(Customer) in d["message"]
            assert d["element"] in d["message"]

    def test_three_cluster_cycle_is_deterministic(self):
        def build() -> dict:
            domain = Domain(name="ThreeCycle", root_path=".")

            @domain.aggregate
            class A:
                name = String(max_length=50)
                b = Reference("B")

            @domain.aggregate
            class B:
                name = String(max_length=50)
                c = Reference("C")

            @domain.aggregate
            class C:
                name = String(max_length=50)
                a = Reference("A")

            domain.init(traverse=False)
            return IRBuilder(domain).build()

        first = _circular_findings(build())
        assert len(first) == 3, "one diagnostic per cluster in the 3-cycle"

        # The reported chain is byte-identical across independent builds.
        second = _circular_findings(build())
        assert [d["message"] for d in first] == [d["message"] for d in second]

    def test_node_reachable_only_through_finalized_node_is_flagged(self):
        """SCC membership, not first-cycle discovery: in ``A->B, B->C, C->A,
        B->D, D->C`` every cluster is in one strongly-connected component
        (``D->C->A->B->D`` is a genuine cycle through ``D``). A plain DFS that
        only closes on an on-stack neighbour would miss ``D`` once ``C`` is
        finalized; SCC membership reports all four, each exactly once."""
        domain = Domain(name="SccReach", root_path=".")

        @domain.aggregate
        class A:
            name = String(max_length=50)
            b = Reference("B")

        @domain.aggregate
        class B:
            name = String(max_length=50)
            c = Reference("C")
            d = Reference("D")

        @domain.aggregate
        class C:
            name = String(max_length=50)
            a = Reference("A")

        @domain.aggregate
        class D:
            name = String(max_length=50)
            c = Reference("C")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _circular_findings(ir)
        elements = [d["element"] for d in findings]
        assert sorted(elements) == sorted([fqn(A), fqn(B), fqn(C), fqn(D)])
        # Each cluster reported exactly once, no duplicates.
        assert len(elements) == len(set(elements))

    def test_cluster_on_two_cycles_is_reported_once(self):
        """A figure-eight — ``A<->B`` and ``A<->C`` — puts ``A`` on two distinct
        cycles. Frozenset-per-cycle dedup would emit ``A`` twice; SCC membership
        (all three are one component) emits each exactly once."""
        domain = Domain(name="FigureEight", root_path=".")

        @domain.aggregate
        class A:
            name = String(max_length=50)
            b = Reference("B")
            c = Reference("C")

        @domain.aggregate
        class B:
            name = String(max_length=50)
            a = Reference("A")

        @domain.aggregate
        class C:
            name = String(max_length=50)
            a = Reference("A")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _circular_findings(ir)]
        assert sorted(elements) == sorted([fqn(A), fqn(B), fqn(C)])
        assert elements.count(fqn(A)) == 1, "cluster on two cycles reported once"

    def test_two_disjoint_cycles_do_not_bleed(self):
        """Two independent 2-cycles plus an acyclic bridge: each cycle is its
        own component, the bridge cluster is in neither, so exactly the four
        cyclic clusters are flagged."""
        domain = Domain(name="TwoDisjoint", root_path=".")

        @domain.aggregate
        class A:
            name = String(max_length=50)
            b = Reference("B")

        @domain.aggregate
        class B:
            name = String(max_length=50)
            a = Reference("A")
            bridge = Reference("Bridge")

        @domain.aggregate
        class Bridge:
            name = String(max_length=50)
            c = Reference("C")

        @domain.aggregate
        class C:
            name = String(max_length=50)
            d = Reference("D")

        @domain.aggregate
        class D:
            name = String(max_length=50)
            c = Reference("C")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _circular_findings(ir)]
        assert sorted(elements) == sorted([fqn(A), fqn(B), fqn(C), fqn(D)])
        assert fqn(Bridge) not in elements, "acyclic bridge is not part of a cycle"

    def test_acyclic_chain_is_not_flagged(self):
        domain = Domain(name="Acyclic", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)
            customer = Reference("Customer")

        @domain.aggregate
        class Customer:
            name = String(max_length=50)
            region = Reference("Region")

        @domain.aggregate
        class Region:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _circular_findings(ir) == []

    def test_auto_generated_back_pointer_is_not_an_edge(self):
        """The false-edge guard: an entity declared with ``part_of`` gets an
        auto-generated Reference back at its own root, targeting the entity's
        own cluster FQN. ``target != cluster_fqn`` must drop it, so no self-loop
        cycle is reported."""
        domain = Domain(name="BackPointer", root_path=".")

        @domain.entity(part_of="Order")
        class LineItem:
            sku = String(max_length=50)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _circular_findings(ir) == []

    def test_intra_cluster_explicit_reference_is_not_an_edge(self):
        """An entity holding an *explicit* Reference to its own aggregate root
        is intra-cluster (shares the root's FQN as its cluster), so it must not
        become a graph edge either."""
        domain = Domain(name="IntraRef", root_path=".")

        @domain.entity(part_of="Order")
        class LineItem:
            sku = String(max_length=50)
            parent = Reference("Order")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _circular_findings(ir) == []

    def test_per_element_suppression_removes_only_that_cluster(self):
        domain = Domain(name="CycleSuppress", root_path=".")

        @domain.aggregate(suppress_checks=["CIRCULAR_CLUSTER_DEPENDENCY"])
        class Order:
            name = String(max_length=50)
            customer = Reference("Customer")

        @domain.aggregate
        class Customer:
            name = String(max_length=50)
            latest_order = Reference("Order")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _circular_findings(ir)]
        assert fqn(Order) not in elements, "suppressed cluster is gone"
        assert elements == [fqn(Customer)], "the other cluster survives"

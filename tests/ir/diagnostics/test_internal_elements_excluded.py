"""Diagnostics: TestInternalElementsExcluded."""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestInternalElementsExcluded:
    """Internal framework elements (like Outbox) must not appear in the IR."""

    def test_internal_aggregate_excluded_from_elements_index(self):
        """An aggregate registered with internal=True should not appear
        in the elements index."""

        domain = Domain(name="InternalTest", root_path=".")

        @domain.aggregate
        class Order:
            customer_name = String(max_length=100, required=True)

        class InternalTracker(BaseAggregate):
            status = String(max_length=20)

        domain.register(InternalTracker, internal=True)
        domain.init(traverse=False)

        ir = IRBuilder(domain).build()

        agg_fqns = ir["elements"]["AGGREGATE"]
        assert any("Order" in fqn for fqn in agg_fqns)
        assert not any("InternalTracker" in fqn for fqn in agg_fqns)

    def test_internal_aggregate_excluded_from_clusters(self):
        """An aggregate registered with internal=True should not appear
        in the clusters section."""

        domain = Domain(name="InternalClusterTest", root_path=".")

        @domain.aggregate
        class Order:
            customer_name = String(max_length=100, required=True)

        class InternalTracker(BaseAggregate):
            status = String(max_length=20)

        domain.register(InternalTracker, internal=True)
        domain.init(traverse=False)

        ir = IRBuilder(domain).build()

        cluster_names = [c["aggregate"]["name"] for c in ir["clusters"].values()]
        assert "Order" in cluster_names
        assert "InternalTracker" not in cluster_names

"""Diagnostics: TestCrossAggregateReference."""

from protean import Domain
from protean.fields import HasMany, HasOne, Reference
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.diagnostics._helpers import (
    _codes_for,
)


class TestCrossAggregateReference:
    """CROSS_AGGREGATE_REFERENCE flags a ``Reference`` to a different
    aggregate's root, but never a child→own-root back-pointer."""

    def test_reference_to_other_aggregate_flagged(self):
        domain = Domain(name="CrossRef", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Customer:
            name = String()
            order = Reference(Order)  # points at a *different* aggregate's root

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "CROSS_AGGREGATE_REFERENCE"
        ]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(Customer)
        assert d["field"] == "order"
        assert d["level"] == "warning"
        # diagnostic schema
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_child_back_pointer_not_flagged(self):
        """The load-bearing compliant case: a child entity referencing its own
        aggregate root (target == own cluster key) is never flagged, and the
        root's ``HasMany`` is out of scope."""
        domain = Domain(name="PostBlog", root_path=".")

        @domain.aggregate
        class Post:
            title = String()
            comments = HasMany("Comment")  # root→child composition, out of scope

        @domain.entity(part_of=Post)
        class Comment:
            content = String()
            post = Reference(Post)  # child→own-root back-pointer, target == own

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_associations_only_not_flagged(self):
        """An aggregate holding only ``HasOne``/``HasMany`` (no ``Reference``)
        is never flagged, regardless of target."""
        domain = Domain(name="OnlyAssoc", root_path=".")

        @domain.aggregate
        class Basket:
            label = String()
            item = HasOne("BasketItem")
            extras = HasMany("BasketExtra")

        @domain.entity(part_of=Basket)
        class BasketItem:
            sku = String()

        @domain.entity(part_of=Basket)
        class BasketExtra:
            note = String()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_reference_to_entity_not_flagged(self):
        """The ``target in cluster_keys`` guard: a ``Reference`` whose target is
        another aggregate's child *entity* (not a cluster key / root) is out of
        scope and never flagged. Deleting that guard must fail this test."""
        domain = Domain(name="RefToEntity", root_path=".")

        @domain.aggregate
        class Catalog:
            name = String()
            products = HasMany("Product")

        @domain.entity(part_of=Catalog)
        class Product:
            sku = String()

        @domain.aggregate
        class Wishlist:
            product = Reference(Product)  # target is an entity, not a root

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_abstract_aggregate_not_flagged(self):
        """An abstract aggregate carrying a cross-aggregate ``Reference`` is
        skipped — the shape only exists on a non-instantiable base."""
        domain = Domain(name="CrossRefAbstract", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate(abstract=True)
        class BaseCustomer:
            name = String()
            order = Reference(Order)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_infrastructure_aggregate_not_flagged(self):
        """A framework/infrastructure aggregate (FQN under ``protean.adapters.``)
        is skipped even when it carries a cross-aggregate ``Reference``. Deleting
        the ``protean.adapters.`` guard must fail this test."""
        domain = Domain(name="CrossRefInfra", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Customer:
            name = String()
            order = Reference(Order)

        # Masquerade as an infrastructure aggregate so its cluster FQN sits under
        # ``protean.adapters.`` (real adapter aggregates are internal and never
        # clustered, so this override is how the guard is reached).
        Customer.__module__ = "protean.adapters.fake"

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="CrossRefSuppress", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate(suppress_checks=["CROSS_AGGREGATE_REFERENCE"])
        class Customer:
            name = String()
            order = Reference(Order)

        @domain.aggregate
        class Invoice:
            order = Reference(Order)  # identical shape, not suppressed

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on Customer, yet the identical shape on Invoice still fires:
        # the rule is active and suppression is selective, not a global no-op.
        assert "CROSS_AGGREGATE_REFERENCE" not in _codes_for(ir, "Customer")
        assert "CROSS_AGGREGATE_REFERENCE" in _codes_for(ir, "Invoice")

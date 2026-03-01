"""Tests that unresolved reference errors include contextual details.

When ``_check_for_unresolved_references()`` detects pending string references
it should produce a ``ConfigurationError`` whose message names the owner
element, field, target, and the kind of reference (HasOne, HasMany, Reference,
ValueObject, part_of, projector_for).
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.projector import BaseProjector
from protean.core.query import BaseQuery
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.fields import HasMany, HasOne, Reference, String, ValueObject


# ── Association resolution types ────────────────────────────────────────


class TestUnresolvedHasMany:
    @pytest.mark.no_test_domain
    def test_has_many_to_unknown_entity(self):
        domain = Domain(__name__, "Tests")

        class Catalog(BaseAggregate):
            name: String(max_length=100)
            items = HasMany("CatalogItem")

        domain.register(Catalog)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "Catalog.items" in msg
        assert "CatalogItem" in msg
        assert "HasMany" in msg


class TestUnresolvedHasOne:
    @pytest.mark.no_test_domain
    def test_has_one_to_unknown_entity(self):
        domain = Domain(__name__, "Tests")

        class Invoice(BaseAggregate):
            number: String(max_length=50)
            details = HasOne("InvoiceDetail")

        domain.register(Invoice)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "Invoice.details" in msg
        assert "InvoiceDetail" in msg
        assert "HasOne" in msg


class TestUnresolvedReference:
    @pytest.mark.no_test_domain
    def test_reference_to_unknown_aggregate(self):
        domain = Domain(__name__, "Tests")

        class Order(BaseAggregate):
            name: String(max_length=100)
            items = HasMany("LineItem")

        class LineItem(BaseEntity):
            sku: String(max_length=50)
            order = Reference("Order")
            supplier = Reference("Supplier")  # unregistered

        domain.register(Order)
        domain.register(LineItem, part_of=Order)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "LineItem.supplier" in msg
        assert "Supplier" in msg
        assert "Reference" in msg


class TestUnresolvedValueObject:
    @pytest.mark.no_test_domain
    def test_value_object_to_unknown_class(self):
        domain = Domain(__name__, "Tests")

        class Product(BaseAggregate):
            name: String(max_length=100)
            price = ValueObject("Money")  # unregistered

        domain.register(Product)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "Product.price" in msg
        assert "Money" in msg
        assert "ValueObject" in msg


# ── Meta linkage resolution types ───────────────────────────────────────


class TestUnresolvedPartOf:
    @pytest.mark.no_test_domain
    def test_entity_part_of_unknown_aggregate(self):
        domain = Domain(__name__, "Tests")

        class Orphan(BaseEntity):
            name: String(max_length=100)

        domain.register(Orphan, part_of="MissingAggregate")

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "Orphan" in msg
        assert "MissingAggregate" in msg
        assert "part_of" in msg

    @pytest.mark.no_test_domain
    def test_event_part_of_unknown_aggregate(self):
        domain = Domain(__name__, "Tests")

        class SomethingHappened(BaseEvent):
            data: String()

        domain.register(SomethingHappened, part_of="GhostAggregate")

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "SomethingHappened" in msg
        assert "GhostAggregate" in msg
        assert "part_of" in msg


class TestUnresolvedProjectorFor:
    @pytest.mark.no_test_domain
    def test_projector_for_unknown_projection(self):
        domain = Domain(__name__, "Tests")

        class SomeAggregate(BaseAggregate):
            name: String(max_length=100)

        class StaleProjector(BaseProjector):
            pass

        domain.register(SomeAggregate)
        domain.register(
            StaleProjector,
            projector_for="MissingProjection",
            stream_categories=["some_aggregate"],
        )

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "StaleProjector" in msg
        assert "MissingProjection" in msg
        assert "projector_for" in msg


class TestUnresolvedQueryPartOf:
    @pytest.mark.no_test_domain
    def test_query_part_of_unknown_projection(self):
        domain = Domain(__name__, "Tests")

        class FindStuff(BaseQuery):
            keyword = String()

        domain.register(FindStuff, part_of="MissingProjection")

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        assert "FindStuff" in msg
        assert "MissingProjection" in msg
        assert "part_of" in msg


# ── Multiple unresolved references ──────────────────────────────────────


class TestMultipleUnresolvedReferences:
    @pytest.mark.no_test_domain
    def test_multiple_unresolved_are_listed_together(self):
        """When multiple references are unresolved, all should appear
        in the same error message, separated by semicolons."""
        domain = Domain(__name__, "Tests")

        class Shipment(BaseAggregate):
            tracking: String(max_length=100)
            items = HasMany("ShipmentItem")
            destination = ValueObject("Address")

        domain.register(Shipment)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        msg = exc.value.args[0]["element"]
        assert "Unresolved references" in msg
        # Both unresolved targets should be mentioned
        assert "ShipmentItem" in msg
        assert "Address" in msg
        # Both fields should be named
        assert "Shipment.items" in msg
        assert "Shipment.destination" in msg

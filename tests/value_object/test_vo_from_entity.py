"""Tests for value_object_from_entity(), ValueObjectFromEntity field, and
BaseEntity.from_value_object() round-trip."""

from datetime import datetime, timezone

import pytest

from protean import value_object_from_entity
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import (
    DateTime,
    Float,
    HasMany,
    HasOne,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
    ValueObjectFromEntity,
)


# ---------------------------------------------------------------------------
# Domain elements for tests
# ---------------------------------------------------------------------------
class LineItem(BaseEntity):
    product_id: Identifier(required=True)
    price: Float(required=True)
    quantity: Integer(required=True)


class Address(BaseValueObject):
    street: String(required=True)
    city: String(required=True)


class ShippingDetail(BaseEntity):
    tracking_number: String(required=True)
    address: ValueObject(Address, required=True)


class Delivery(BaseEntity):
    destination: String(required=True)
    address: ValueObject(Address)


class Invoice(BaseEntity):
    invoice_number: String(identifier=True)
    amount: Float(required=True)
    note: String()


class TimestampedEntity(BaseEntity):
    label: String(required=True)
    created_at: DateTime(default=lambda: datetime.now(timezone.utc))


class Cart(BaseAggregate):
    customer_id: Identifier(required=True)
    items = HasMany(LineItem)
    shipping = HasOne(ShippingDetail)


# ---------------------------------------------------------------------------
# Tests for value_object_from_entity()
# ---------------------------------------------------------------------------
class TestValueObjectFromEntity:
    """Tests for the value_object_from_entity() utility function."""

    def test_basic_conversion(self):
        """Simple entity fields are mirrored in the generated VO."""
        VO = value_object_from_entity(LineItem)

        assert issubclass(VO, BaseValueObject)
        assert VO.__name__ == "LineItemValueObject"

        # Instantiate and verify fields
        vo = VO(product_id="P1", price=9.99, quantity=2)
        assert vo.product_id == "P1"
        assert vo.price == 9.99
        assert vo.quantity == 2

    def test_custom_name(self):
        """The generated class uses the custom name when provided."""
        VO = value_object_from_entity(LineItem, name="LineItemPayload")
        assert VO.__name__ == "LineItemPayload"

    def test_exclude_fields(self):
        """Excluded fields are omitted from the generated VO."""
        VO = value_object_from_entity(LineItem, exclude={"quantity"})

        vo = VO(product_id="P1", price=9.99)
        assert vo.product_id == "P1"
        assert vo.price == 9.99
        assert not hasattr(vo, "quantity") or "quantity" not in VO.model_fields

    def test_identifier_fields_become_optional(self):
        """Identifier fields are included but made optional with None default."""
        VO = value_object_from_entity(Invoice)

        # Can instantiate without providing the identifier field
        vo = VO(amount=100.0)
        assert vo.invoice_number is None
        assert vo.amount == 100.0

        # Can also provide it explicitly
        vo2 = VO(invoice_number="INV-001", amount=200.0)
        assert vo2.invoice_number == "INV-001"

    def test_reference_fields_excluded(self, test_domain):
        """Reference fields on a registered entity are excluded from the VO."""
        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(ShippingDetail, part_of=Cart)
        test_domain.init(traverse=False)

        # After registration, LineItem gains a Reference back to Cart.
        # The generated VO must exclude that reference field.
        VO = value_object_from_entity(LineItem)
        vo_field_names = set(VO.model_fields.keys())

        # Reference fields like cart_id (auto-injected by part_of) should not appear
        assert "cart_id" not in vo_field_names
        # Data fields should still be present
        assert "product_id" in vo_field_names
        assert "price" in vo_field_names

    def test_vo_is_immutable(self):
        """Generated VO is immutable like any BaseValueObject."""
        VO = value_object_from_entity(LineItem)
        vo = VO(product_id="P1", price=9.99, quantity=2)

        with pytest.raises(Exception):
            vo.price = 20.0

    def test_to_dict_round_trip(self):
        """Generated VO supports to_dict()."""
        VO = value_object_from_entity(LineItem)
        vo = VO(product_id="P1", price=9.99, quantity=2)
        d = vo.to_dict()

        assert d["product_id"] == "P1"
        assert d["price"] == 9.99
        assert d["quantity"] == 2

    def test_optional_fields_preserved(self):
        """Optional fields on the entity remain optional in the VO."""
        VO = value_object_from_entity(Invoice)
        vo = VO(amount=50.0)
        assert vo.note is None

    def test_required_vo_field_preserved(self, test_domain):
        """A required ValueObject field on the entity stays required in the VO."""
        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(ShippingDetail, part_of=Cart)
        test_domain.init(traverse=False)

        VO = value_object_from_entity(ShippingDetail)

        # address is required=True on ShippingDetail, so VO must require it too
        field_info = VO.model_fields["address"]
        assert field_info.is_required()

        # Valid: address provided
        vo = VO(tracking_number="T1", address={"street": "1st Ave", "city": "NYC"})
        assert vo.address.street == "1st Ave"

    def test_optional_vo_field_preserved(self, test_domain):
        """An optional ValueObject field on the entity stays optional in the VO."""
        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(ShippingDetail, part_of=Cart)
        test_domain.init(traverse=False)

        VO = value_object_from_entity(Delivery)

        # address is optional (no required=True) on Delivery
        vo = VO(destination="Warehouse")
        assert vo.address is None

    def test_field_with_callable_default(self):
        """Fields with callable defaults (default_factory) are preserved."""
        VO = value_object_from_entity(TimestampedEntity)

        # created_at should have a default_factory, so omitting it is valid
        vo = VO(label="test")
        assert vo.label == "test"
        assert vo.created_at is not None  # auto-filled by factory

    def test_recursive_has_one(self, test_domain):
        """HasOne associations are converted to nested VOs."""
        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(ShippingDetail, part_of=Cart)
        test_domain.init(traverse=False)

        VO = value_object_from_entity(Cart)

        # The shipping field should be a nested VO type
        assert "shipping" in VO.model_fields

    def test_recursive_has_many(self, test_domain):
        """HasMany associations are converted to lists of VOs."""
        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(ShippingDetail, part_of=Cart)
        test_domain.init(traverse=False)

        VO = value_object_from_entity(Cart)

        # The items field should exist and default to empty list
        assert "items" in VO.model_fields

    def test_vo_with_embedded_value_object(self, test_domain):
        """Entities with ValueObject fields preserve them in the projection."""
        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(ShippingDetail, part_of=Cart)
        test_domain.init(traverse=False)

        VO = value_object_from_entity(ShippingDetail)

        vo = VO(tracking_number="TRACK123", address={"street": "123 Main", "city": "NYC"})
        assert vo.tracking_number == "TRACK123"
        assert vo.address.street == "123 Main"


# ---------------------------------------------------------------------------
# Tests for ValueObjectFromEntity field descriptor
# ---------------------------------------------------------------------------
class TestValueObjectFromEntityField:
    """Tests for the ValueObjectFromEntity field descriptor."""

    def test_inline_usage_in_command(self, test_domain):
        """ValueObjectFromEntity can be used inline in a command."""

        class CreateCart(BaseCommand):
            cart_id: Identifier(identifier=True)
            items: List(content_type=ValueObjectFromEntity(LineItem))

        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(CreateCart, part_of=Cart)
        test_domain.init(traverse=False)

        cmd = CreateCart(
            cart_id="C1",
            items=[{"product_id": "P1", "price": 10.0, "quantity": 1}],
        )
        assert len(cmd.items) == 1
        assert cmd.items[0].product_id == "P1"
        assert isinstance(cmd.items[0], BaseValueObject)

    def test_field_produces_same_shape_as_manual_vo(self, test_domain):
        """ValueObjectFromEntity produces VOs with the same fields as a manual VO."""
        ManualVO = value_object_from_entity(LineItem)

        class CmdA(BaseCommand):
            items: List(content_type=ValueObject(ManualVO))

        class CmdB(BaseCommand):
            items: List(content_type=ValueObjectFromEntity(LineItem))

        test_domain.register(Cart)
        test_domain.register(LineItem, part_of=Cart)
        test_domain.register(CmdA, part_of=Cart)
        test_domain.register(CmdB, part_of=Cart)
        test_domain.init(traverse=False)

        data = [{"product_id": "P1", "price": 5.0, "quantity": 3}]

        cmd_a = CmdA(items=data)
        cmd_b = CmdB(items=data)

        assert cmd_a.items[0].to_dict() == cmd_b.items[0].to_dict()


# ---------------------------------------------------------------------------
# Tests for BaseEntity.from_value_object()
# ---------------------------------------------------------------------------
class TestFromValueObject:
    """Tests for the from_value_object() classmethod on BaseEntity."""

    def test_basic_round_trip(self):
        """VO → Entity conversion preserves field values."""
        VO = value_object_from_entity(LineItem)
        vo = VO(product_id="P1", price=9.99, quantity=2)

        entity = LineItem.from_value_object(vo)

        assert isinstance(entity, LineItem)
        assert entity.product_id == "P1"
        assert entity.price == 9.99
        assert entity.quantity == 2

    def test_round_trip_with_optional_fields(self):
        """Round-trip works when optional fields are None."""
        VO = value_object_from_entity(Invoice)
        vo = VO(invoice_number="INV-001", amount=100.0)

        entity = Invoice.from_value_object(vo)

        assert isinstance(entity, Invoice)
        assert entity.invoice_number == "INV-001"
        assert entity.amount == 100.0
        assert entity.note is None

    def test_entity_to_vo_to_entity(self):
        """Full cycle: entity → VO → entity preserves data."""
        VO = value_object_from_entity(LineItem)

        original = LineItem(product_id="P1", price=15.0, quantity=5)
        vo = VO(**original.to_dict())
        restored = LineItem.from_value_object(vo)

        assert restored.product_id == original.product_id
        assert restored.price == original.price
        assert restored.quantity == original.quantity

    def test_list_conversion(self):
        """Convert a list of VOs back to entities."""
        VO = value_object_from_entity(LineItem)

        vos = [
            VO(product_id="P1", price=10.0, quantity=1),
            VO(product_id="P2", price=20.0, quantity=2),
        ]

        entities = [LineItem.from_value_object(vo) for vo in vos]

        assert len(entities) == 2
        assert all(isinstance(e, LineItem) for e in entities)
        assert entities[0].product_id == "P1"
        assert entities[1].product_id == "P2"


# ---------------------------------------------------------------------------
# Tests for fact event refactoring (ensure no regression)
# ---------------------------------------------------------------------------
class TestFactEventRefactoring:
    """Ensure the refactored fact event conversion still works correctly."""

    def test_fact_event_with_entity_children(self, test_domain):
        """Fact events still correctly convert entity children to VOs."""

        class Product(BaseAggregate):
            name: String(required=True)
            price: Float(required=True)
            tags = HasMany("Tag")

        class Tag(BaseEntity):
            label: String(required=True)

        test_domain.register(Product, fact_events=True)
        test_domain.register(Tag, part_of=Product)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            product = Product(name="Widget", price=9.99)
            product.add_tags(Tag(label="sale"))
            test_domain.repository_for(Product).add(product)

            # Verify fact event was generated
            assert hasattr(Product, "_fact_event_cls")
            fact_cls = Product._fact_event_cls
            assert "tags" in fact_cls.model_fields

    def test_fact_event_with_callable_default(self, test_domain):
        """Fact events preserve fields with callable defaults (default_factory)."""

        class Order(BaseAggregate):
            customer_id: Identifier(required=True)
            total: Float(required=True)
            ordered_at: DateTime(default=lambda: datetime.now(timezone.utc))

        test_domain.register(Order, fact_events=True)
        test_domain.init(traverse=False)

        # Verify fact event class was generated and has the ordered_at field
        assert hasattr(Order, "_fact_event_cls")
        fact_cls = Order._fact_event_cls
        assert "ordered_at" in fact_cls.model_fields

        # The field should have a default_factory (not be required)
        finfo = fact_cls.model_fields["ordered_at"]
        assert finfo.default_factory is not None

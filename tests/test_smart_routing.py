"""Tests for smart decorator routing to Pydantic vs legacy base classes.

Phase 9: Factory functions route annotation-based classes to Pydantic
and legacy Field-descriptor classes to legacy base classes.
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4


from pydantic import BaseModel, Field

from protean.core.aggregate import BaseAggregate, _LegacyBaseAggregate
from protean.core.command import BaseCommand, _LegacyBaseCommand
from protean.core.entity import BaseEntity, _LegacyBaseEntity
from protean.core.event import BaseEvent, _LegacyBaseEvent
from protean.core.value_object import BaseValueObject, _LegacyBaseValueObject
from protean.fields import HasMany, Integer, Reference, String, ValueObject
from protean.utils import _has_legacy_data_fields
from protean.utils.reflection import _FIELDS, declared_fields, id_field


# ---------------------------------------------------------------------------
# Detection function tests
# ---------------------------------------------------------------------------
class TestHasLegacyDataFields:
    def test_class_with_string_field(self):
        class Foo:
            name = String(max_length=50)

        assert _has_legacy_data_fields(Foo) is True

    def test_class_with_integer_field(self):
        class Foo:
            age = Integer()

        assert _has_legacy_data_fields(Foo) is True

    def test_class_with_annotations_only(self):
        class Foo:
            name: str
            age: int = 21

        assert _has_legacy_data_fields(Foo) is False

    def test_class_with_only_has_many(self):
        class Foo:
            items = HasMany("Item")

        assert _has_legacy_data_fields(Foo) is False

    def test_class_with_only_reference(self):
        class Foo:
            ref = Reference("OtherEntity")

        assert _has_legacy_data_fields(Foo) is False

    def test_class_with_only_value_object(self):
        class Foo:
            email = ValueObject("Email")

        assert _has_legacy_data_fields(Foo) is False

    def test_empty_class(self):
        class Foo:
            pass

        assert _has_legacy_data_fields(Foo) is False

    def test_mixed_legacy_and_annotation(self):
        class Foo:
            name: str
            age = Integer()

        assert _has_legacy_data_fields(Foo) is True

    def test_annotation_with_association_descriptor(self):
        class Foo:
            name: str
            items = HasMany("Item")

        assert _has_legacy_data_fields(Foo) is False


# ---------------------------------------------------------------------------
# Aggregate routing tests
# ---------------------------------------------------------------------------
class TestAggregateRouting:
    def test_annotation_aggregate_routes_to_pydantic(self, test_domain):
        @test_domain.aggregate
        class AnnotatedUser:
            name: str
            age: int = 21

        assert issubclass(AnnotatedUser, BaseAggregate)
        assert issubclass(AnnotatedUser, BaseModel)
        user = AnnotatedUser(name="John")
        assert user.id is not None
        assert user.name == "John"
        assert user.age == 21

    def test_legacy_aggregate_routes_to_legacy(self, test_domain):
        @test_domain.aggregate
        class LegacyUser:
            name = String(max_length=50, required=True)
            age = Integer(default=21)

        assert issubclass(LegacyUser, _LegacyBaseAggregate)
        assert not issubclass(LegacyUser, BaseModel)

    def test_explicit_pydantic_inheritance(self, test_domain):
        class ExplicitUser(BaseAggregate):
            id: str = Field(
                json_schema_extra={"identifier": True},
                default_factory=lambda: str(uuid4()),
            )
            name: str

        test_domain.register(ExplicitUser)
        assert issubclass(ExplicitUser, BaseAggregate)

    def test_annotation_aggregate_gets_auto_id(self, test_domain):
        @test_domain.aggregate
        class AutoIdUser:
            name: str

        assert "id" in declared_fields(AutoIdUser)
        assert id_field(AutoIdUser).identifier is True
        user = AutoIdUser(name="John")
        assert user.id is not None

    def test_annotation_aggregate_with_explicit_identifier(self, test_domain):
        @test_domain.aggregate
        class ExplicitIdUser:
            email: str = Field(json_schema_extra={"identifier": True})
            name: str

        assert id_field(ExplicitIdUser).field_name == "email"
        user = ExplicitIdUser(email="john@example.com", name="John")
        assert user.email == "john@example.com"
        # No auto-generated 'id' field
        assert "id" not in ExplicitIdUser.model_fields

    def test_annotation_aggregate_with_annotated_identifier(self, test_domain):
        @test_domain.aggregate
        class AnnotatedIdUser:
            email: Annotated[str, Field(json_schema_extra={"identifier": True})]
            name: str

        assert id_field(AnnotatedIdUser).field_name == "email"

    def test_auto_add_id_field_false(self, test_domain):
        @test_domain.aggregate(auto_add_id_field=False)
        class NoIdAggregate:
            name: str

        assert issubclass(NoIdAggregate, BaseAggregate)
        assert "id" not in NoIdAggregate.model_fields

    def test_annotation_aggregate_with_has_many(self, test_domain):
        @test_domain.aggregate
        class Order:
            name: str

        @test_domain.entity(part_of=Order)
        class OrderItem:
            description: str

        cf = getattr(Order, _FIELDS, {})
        assert "name" in cf

    def test_empty_aggregate(self, test_domain):
        @test_domain.aggregate
        class EmptyAggregate:
            pass

        assert issubclass(EmptyAggregate, BaseAggregate)
        assert "id" in declared_fields(EmptyAggregate)


# ---------------------------------------------------------------------------
# Entity routing tests
# ---------------------------------------------------------------------------
class TestEntityRouting:
    def test_annotation_entity_routes_to_pydantic(self, test_domain):
        @test_domain.aggregate
        class Parent:
            name: str

        @test_domain.entity(part_of=Parent)
        class AnnotatedItem:
            description: str
            quantity: int = 1

        assert issubclass(AnnotatedItem, BaseEntity)
        assert issubclass(AnnotatedItem, BaseModel)

    def test_legacy_entity_routes_to_legacy(self, test_domain):
        @test_domain.aggregate
        class Parent:
            name = String(max_length=50, required=True)

        @test_domain.entity(part_of=Parent)
        class LegacyItem:
            description = String(max_length=100, required=True)

        assert issubclass(LegacyItem, _LegacyBaseEntity)


# ---------------------------------------------------------------------------
# Value Object routing tests
# ---------------------------------------------------------------------------
class TestValueObjectRouting:
    def test_annotation_vo_routes_to_pydantic(self, test_domain):
        @test_domain.value_object
        class Money:
            amount: float
            currency: str = "USD"

        assert issubclass(Money, BaseValueObject)
        assert issubclass(Money, BaseModel)
        m = Money(amount=100.0)
        assert m.amount == 100.0
        assert m.currency == "USD"

    def test_legacy_vo_routes_to_legacy(self, test_domain):
        @test_domain.value_object
        class LegacyMoney:
            amount = Integer()
            currency = String(max_length=3)

        assert issubclass(LegacyMoney, _LegacyBaseValueObject)

    def test_vo_has_no_auto_id(self, test_domain):
        @test_domain.value_object
        class Address:
            street: str
            city: str

        assert "id" not in getattr(Address, _FIELDS, {})


# ---------------------------------------------------------------------------
# Command routing tests
# ---------------------------------------------------------------------------
class TestCommandRouting:
    def test_annotation_command_routes_to_pydantic(self, test_domain):
        @test_domain.aggregate
        class Agg:
            name: str

        @test_domain.command(part_of=Agg)
        class CreateItem:
            name: str
            quantity: int = 1

        assert issubclass(CreateItem, BaseCommand)
        assert issubclass(CreateItem, BaseModel)

    def test_legacy_command_routes_to_legacy(self, test_domain):
        @test_domain.aggregate
        class Agg2:
            name = String(max_length=50, required=True)

        @test_domain.command(part_of=Agg2)
        class LegacyCreateItem:
            name = String(max_length=50, required=True)

        assert issubclass(LegacyCreateItem, _LegacyBaseCommand)


# ---------------------------------------------------------------------------
# Event routing tests
# ---------------------------------------------------------------------------
class TestEventRouting:
    def test_annotation_event_routes_to_pydantic(self, test_domain):
        @test_domain.aggregate
        class Agg:
            name: str

        @test_domain.event(part_of=Agg)
        class ItemCreated:
            name: str
            quantity: int = 1

        assert issubclass(ItemCreated, BaseEvent)
        assert issubclass(ItemCreated, BaseModel)

    def test_legacy_event_routes_to_legacy(self, test_domain):
        @test_domain.aggregate
        class Agg2:
            name = String(max_length=50, required=True)

        @test_domain.event(part_of=Agg2)
        class LegacyItemCreated:
            name = String(max_length=50, required=True)

        assert issubclass(LegacyItemCreated, _LegacyBaseEvent)


# ---------------------------------------------------------------------------
# Persistence round-trip test
# ---------------------------------------------------------------------------
class TestPydanticDecoratorPersistence:
    def test_annotation_aggregate_crud(self, test_domain):
        @test_domain.aggregate
        class Product:
            name: str
            price: float = 0.0

        test_domain.init(traverse=False)

        repo = test_domain.repository_for(Product)
        product = Product(name="Widget", price=9.99)
        repo.add(product)

        retrieved = repo.get(product.id)
        assert retrieved.name == "Widget"
        assert retrieved.price == 9.99

        retrieved.name = "Super Widget"
        repo.add(retrieved)

        updated = repo.get(product.id)
        assert updated.name == "Super Widget"

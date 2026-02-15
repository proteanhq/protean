import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, HasMany, HasOne, Identifier, String, ValueObject
from protean.utils.reflection import declared_fields


class Money(BaseValueObject):
    amount: Float(required=True)
    currency: String(required=True, max_length=3, default="USD")


class Address(BaseValueObject):
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    postal_code: String(required=True, max_length=20)


class User(BaseAggregate):
    email: String()
    name: String()
    account = HasOne("Account")
    addresses = HasMany("UserAddress")


class Account(BaseEntity):
    password_hash: String()


class UserAddress(BaseEntity):
    street: String()
    city: String()
    state: String()
    postal_code: String()


def test_commands_cannot_hold_associations():
    with pytest.raises(
        IncorrectUsageError,
        match="Commands and Events can only contain basic field types",
    ):

        class Register(BaseCommand):
            email: String()
            name: String()
            account = HasOne(Account)


class TestCommandsWithValueObjects:
    """ValueObject() descriptors should be allowed in commands."""

    def test_command_with_optional_vo(self, test_domain):
        class Order(BaseAggregate):
            order_id: Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id: Identifier(identifier=True)
            total = ValueObject(Money)

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        cmd = PlaceOrder(order_id="ORD-1")
        assert cmd.total is None

        cmd = PlaceOrder(
            order_id="ORD-1",
            total=Money(amount=99.99, currency="USD"),
        )
        assert cmd.total == Money(amount=99.99, currency="USD")
        assert cmd.total.amount == 99.99
        assert cmd.total.currency == "USD"

    def test_command_with_required_vo(self, test_domain):
        class Order(BaseAggregate):
            order_id: Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id: Identifier(identifier=True)
            total = ValueObject(Money, required=True)

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        cmd = PlaceOrder(
            order_id="ORD-1",
            total=Money(amount=149.99),
        )
        assert cmd.total.amount == 149.99

    def test_command_with_multiple_vos(self, test_domain):
        class Order(BaseAggregate):
            order_id: Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id: Identifier(identifier=True)
            total = ValueObject(Money, required=True)
            shipping_address = ValueObject(Address, required=True)
            billing_address = ValueObject(Address)

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        addr = Address(street="123 Main St", city="SF", postal_code="94102")
        cmd = PlaceOrder(
            order_id="ORD-1",
            total=Money(amount=100.0),
            shipping_address=addr,
        )
        assert cmd.shipping_address == addr
        assert cmd.billing_address is None

    def test_command_vo_serializes_to_nested_dict(self, test_domain):
        class Order(BaseAggregate):
            order_id: Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id: Identifier(identifier=True)
            total = ValueObject(Money, required=True)
            shipping_address = ValueObject(Address)

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        cmd = PlaceOrder(
            order_id="ORD-1",
            total=Money(amount=50.0, currency="EUR"),
            shipping_address=Address(
                street="456 Elm St", city="NYC", postal_code="10001"
            ),
        )
        d = cmd.to_dict()
        assert d["total"] == {"amount": 50.0, "currency": "EUR"}
        assert d["shipping_address"] == {
            "street": "456 Elm St",
            "city": "NYC",
            "postal_code": "10001",
        }

    def test_command_vo_has_no_shadow_fields(self, test_domain):
        """ValueObject fields in commands must NOT create shadow fields."""

        class Order(BaseAggregate):
            order_id: Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id: Identifier(identifier=True)
            total = ValueObject(Money)

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        df = declared_fields(PlaceOrder)
        # Should have order_id and total — NOT total_amount or total_currency
        assert "total" in df
        assert "order_id" in df
        assert "total_amount" not in df
        assert "total_currency" not in df

    def test_command_vo_from_dict(self, test_domain):
        """Commands with VOs can be reconstructed from dict data."""

        class Order(BaseAggregate):
            order_id: Identifier(identifier=True)

        class PlaceOrder(BaseCommand):
            order_id: Identifier(identifier=True)
            total = ValueObject(Money, required=True)

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.init(traverse=False)

        cmd = PlaceOrder(
            order_id="ORD-1",
            total={"amount": 75.0, "currency": "GBP"},
        )
        assert isinstance(cmd.total, Money)
        assert cmd.total.amount == 75.0
        assert cmd.total.currency == "GBP"

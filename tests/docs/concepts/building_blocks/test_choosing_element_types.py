"""Run the examples on ``docs/concepts/building-blocks/choosing-element-types.md``.

The anti-pattern blocks that fail on purpose stay inline on the page as
fragments. The tests at the end build those elements here to check the error
each block names.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from protean import Domain
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Auto, String
from protean.fields import Decimal as DecimalField
from protean.utils.reflection import id_field
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


# E-commerce examples


def test_order_is_an_aggregate_holding_money_as_a_value_object():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        order = example.Order(
            order_number="ORD-1",
            customer_id="cust-1",
            total_amount=example.Money(amount=Decimal(10), currency="USD"),
        )
        assert example.Order.element_type.name == "AGGREGATE"
        assert order.status == "pending"
        assert isinstance(order.created_at, datetime)
        assert order.total_amount == example.Money(amount=Decimal(10), currency="USD")


def test_order_rejects_a_status_outside_its_choices():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.Order(order_number="ORD-1", customer_id="cust-1", status="lost")
        assert set(exc.value.messages) == {"status"}


def test_order_item_is_an_entity_of_order_with_its_own_identity():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        first = example.OrderItem(product_id="p-1", quantity=1)
        second = example.OrderItem(product_id="p-1", quantity=1)
        assert example.OrderItem.element_type.name == "ENTITY"
        assert example.OrderItem.meta_.part_of is example.Order
        assert first.id != second.id
        assert first != second


def test_order_item_rejects_a_quantity_below_one():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.OrderItem(product_id="p-1", quantity=0)
        assert set(exc.value.messages) == {"quantity"}


def test_two_money_values_with_the_same_amount_and_currency_are_equal():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        assert example.Money(amount=10, currency="USD") == example.Money(
            amount=10, currency="USD"
        )
        assert example.Money(amount=10, currency="USD") != example.Money(
            amount=10, currency="EUR"
        )


def test_money_adds_amounts_in_the_same_currency():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        total = example.Money(amount=10, currency="USD").add(
            example.Money(amount=5, currency="USD")
        )
        assert total == example.Money(amount=15, currency="USD")


def test_money_refuses_to_add_different_currencies():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        with pytest.raises(ValueError, match="Cannot add different currencies"):
            example.Money(amount=10, currency="USD").add(
                example.Money(amount=5, currency="EUR")
            )


def test_money_rejects_a_negative_amount():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.Money(amount=-1, currency="USD")
        assert set(exc.value.messages) == {"amount"}


def test_money_is_immutable():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        money = example.Money(amount=10, currency="USD")
        with pytest.raises(IncorrectUsageError):
            money.amount = 20
        assert money.amount == 10


# Blog examples


def test_comment_belongs_to_post():
    example = load_example("concepts/building-blocks/choosing-element-types/002.py")
    with _context(example):
        post = example.Post(title="Hello", author_id="a-1")
        comment = example.Comment(content="Nice post", author_id="a-2")
        assert post.status == "draft"
        assert example.Post.element_type.name == "AGGREGATE"
        assert example.Comment.element_type.name == "ENTITY"
        assert example.Comment.meta_.part_of is example.Post
        assert isinstance(comment.created_at, datetime)


def test_comment_rejects_content_over_500_characters():
    example = load_example("concepts/building-blocks/choosing-element-types/002.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.Comment(content="x" * 501, author_id="a-2")
        assert set(exc.value.messages) == {"content"}


def test_email_accepts_an_address_with_an_at_sign():
    example = load_example("concepts/building-blocks/choosing-element-types/002.py")
    with _context(example):
        assert example.Email(address="jane@example.com").address == "jane@example.com"


def test_email_rejects_an_address_without_an_at_sign():
    example = load_example("concepts/building-blocks/choosing-element-types/002.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.Email(address="jane.example.com")
        assert exc.value.messages == {"address": ["Invalid email format"]}


# Anti-patterns that run


def test_too_many_aggregates_gives_address_and_phone_an_identity():
    example = load_example("concepts/building-blocks/choosing-element-types/003.py")
    with _context(example):
        for cls in (example.User, example.Address, example.Phone):
            assert cls.element_type.name == "AGGREGATE"
            assert id_field(cls).field_name == "id"
        assert example.Address() != example.Address()


def test_creating_the_entity_again_gives_a_different_item():
    example = load_example("concepts/building-blocks/choosing-element-types/001.py")
    with _context(example):
        data = {"product_id": "p-1", "quantity": 2}
        first = example.process_order(data)
        second = example.process_order(data)
        assert first.id != second.id
        assert first != second


def test_primitive_email_accepts_what_the_email_value_object_rejects():
    users = load_example("concepts/building-blocks/choosing-element-types/004.py")
    with _context(users):
        user = users.User(email="not-an-email", phone="call me")
        assert user.email == "not-an-email"

    blog = load_example("concepts/building-blocks/choosing-element-types/002.py")
    with _context(blog):
        with pytest.raises(ValidationError):
            blog.Email(address="not-an-email")


# Anti-patterns that fail on purpose (fragments on the page)


def test_entity_without_part_of_is_rejected():
    domain = Domain(name="MissingAggregate")
    with pytest.raises(IncorrectUsageError) as exc:

        @domain.entity
        class Comment:
            content: String(max_length=500)

    assert "needs to be associated with an Aggregate" in str(exc.value)


def test_assigning_to_a_value_object_field_is_rejected():
    domain = Domain(name="MutableValueObject")

    @domain.value_object
    class Address:
        street: String()
        city: String()

    domain.init(traverse=False)
    with domain.domain_context():
        address = Address(street="123 Main St", city="NYC")
        with pytest.raises(IncorrectUsageError):
            address.street = "456 Oak Ave"
        assert address.street == "123 Main St"


def test_value_object_with_an_identifier_field_is_rejected():
    domain = Domain(name="ValueObjectWithIdentity")
    with pytest.raises(IncorrectUsageError) as exc:

        @domain.value_object
        class Money:
            id: Auto(identifier=True)
            amount = DecimalField()
            currency: String()

    assert "cannot contain fields marked 'identifier'" in str(exc.value)

"""The examples on the value objects guide behave as the page says."""

from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from protean.exceptions import IncorrectUsageError, ValidationError
from tests.docs.support import load_example


def test_email_accepts_a_valid_address_and_compares_by_value():
    example = load_example("guides/domain-definition/009.py")

    first = example.Email(address="john.doe@gmail.com")
    second = example.Email(address="john.doe@gmail.com")

    assert first == second
    assert first != example.Email(address="jane.doe@gmail.com")


def test_email_rejects_an_address_without_an_at_sign():
    example = load_example("guides/domain-definition/009.py")

    with pytest.raises(ValidationError) as exc:
        example.Email(address="john.doegmail.com")

    assert exc.value.messages == {"address": ["Invalid email address"]}


def test_user_embeds_the_email_and_rejects_an_invalid_one():
    example = load_example("guides/domain-definition/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(
            email_address="john.doe@gmail.com",
            name="John Doe",
            timezone="America/Los_Angeles",
        )
        with pytest.raises(ValidationError) as exc:
            example.User(email_address="john.doegmail.com", name="John Doe")

    assert user.to_dict()["email"] == {"address": "john.doe@gmail.com"}
    assert "address" in exc.value.messages


def test_user_resolves_the_email_value_object_by_name():
    example = load_example("guides/domain-definition/value-objects/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(email=example.Email(address="jane@example.com"))
        with pytest.raises(ValidationError) as exc:
            example.User(email=example.Email())

    assert user.email == example.Email(address="jane@example.com")
    assert "address" in exc.value.messages


def test_account_accepts_a_balance_object_or_its_attributes():
    example = load_example("guides/domain-definition/010.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        by_object = example.Account(
            balance=example.Balance(currency="USD", amount=D("100.00")),
            name="Checking",
        )
        by_attributes = example.Account(
            balance_currency="USD", balance_amount=D("100.00"), name="Checking"
        )

    expected = {"currency": "USD", "amount": "100.00"}
    assert by_object.to_dict()["balance"] == expected
    assert by_attributes.to_dict()["balance"] == expected
    assert by_object.balance == by_attributes.balance


def test_balance_rejects_a_negative_amount_through_min_value():
    example = load_example("guides/domain-definition/010.py")

    with pytest.raises(ValidationError) as exc:
        example.Balance(currency="USD", amount=D("-1.00"))

    assert "amount" in exc.value.messages


def test_balances_with_equal_fields_are_equal():
    example = load_example("guides/domain-definition/011.py")

    bal1 = example.Balance(currency="USD", amount=D("100.00"))
    bal2 = example.Balance(currency="USD", amount=D("100.00"))
    bal3 = example.Balance(currency="CAD", amount=D("100.00"))

    assert bal1 == bal2
    assert bal1 != bal3


def test_balance_is_immutable_and_rejects_a_missing_currency():
    example = load_example("guides/domain-definition/011.py")
    balance = example.Balance(currency="USD", amount=D("100.00"))

    with pytest.raises(IncorrectUsageError):
        balance.currency = "CAD"
    with pytest.raises(ValidationError) as exc:
        example.Balance(amount=D("100.00"))

    assert "currency" in exc.value.messages


def test_balance_invariant_rejects_negative_usd_only():
    example = load_example("guides/domain-definition/012.py")

    cad = example.Balance(currency="CAD", amount=D("-100.00"))
    with pytest.raises(ValidationError) as exc:
        example.Balance(currency="USD", amount=D("-100.00"))

    assert cad.amount == D("-100.00")
    assert exc.value.messages == {"balance": ["Balance cannot be negative for USD"]}


def test_store_takes_a_nested_geolocation():
    example = load_example("guides/domain-definition/value-objects/002.py")

    assert example.store.address.city == "Springfield"
    assert example.store.address.location == example.GeoLocation(
        latitude=39.78, longitude=-89.65
    )


def test_geolocation_rejects_a_missing_latitude():
    example = load_example("guides/domain-definition/value-objects/002.py")

    with pytest.raises(ValidationError) as exc:
        example.GeoLocation(longitude=-89.65)

    assert "latitude" in exc.value.messages


def test_store_rejects_flattened_names_two_levels_deep():
    example = load_example("guides/domain-definition/value-objects/002.py")

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Store(name="Downtown", address_location_latitude=39.78)

    assert "address_location_latitude" in exc.value.messages


def test_account_converts_a_balance_dict_into_a_value_object():
    example = load_example("guides/domain-definition/value-objects/003.py")

    assert isinstance(example.account.balance, example.Balance)
    assert example.account.balance == example.Balance(
        currency="USD", amount=D("100.00")
    )


def test_account_rejects_a_balance_dict_with_a_negative_amount():
    example = load_example("guides/domain-definition/value-objects/003.py")

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Account(balance={"currency": "USD", "amount": D(-1)}, name="X")

    assert "amount" in exc.value.messages


def test_duration_defaults_total_seconds_from_start_and_end():
    example = load_example("guides/domain-definition/value-objects/004.py")
    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    derived = example.Duration(start=start, end=start.replace(hour=10))
    given = example.Duration(start=start, end=start.replace(hour=10), total_seconds=5)

    assert derived.total_seconds == 3600.0
    assert given.total_seconds == 5.0
    with pytest.raises(ValidationError) as exc:
        example.Duration(start=start)
    assert "end" in exc.value.messages


def test_replace_returns_a_new_balance_and_keeps_the_original():
    example = load_example("guides/domain-definition/value-objects/005.py")

    assert example.updated == example.Balance(currency="USD", amount=D("200.00"))
    assert example.balance == example.Balance(currency="USD", amount=D("100.00"))


def test_replace_revalidates_the_invariant(capsys):
    example = load_example("guides/domain-definition/value-objects/006.py")

    printed = capsys.readouterr().out
    assert "{'balance': ['Balance cannot be negative for USD']}" in printed

    with pytest.raises(ValidationError) as exc:
        example.balance.replace(amount=D("-1.00"))
    assert "balance" in exc.value.messages
    assert example.balance.replace(currency="CAD", amount=D("-1.00")).amount == D(
        "-1.00"
    )


def test_replace_rejects_an_unknown_field(capsys):
    example = load_example("guides/domain-definition/value-objects/006.py")

    assert "Unknown field(s) for Balance: nonexistent" in capsys.readouterr().out
    with pytest.raises(IncorrectUsageError):
        example.balance.replace(nonexistent=42)


def test_replace_with_none_clears_the_field():
    example = load_example("guides/domain-definition/value-objects/007.py")

    assert example.updated == example.Profile(name="Alice")
    assert example.profile.nickname == "Ali"
    with pytest.raises(ValidationError) as exc:
        example.profile.replace(name=None)
    assert "name" in exc.value.messages


def test_value_objects_work_as_dict_keys_and_set_members():
    example = load_example("guides/domain-definition/value-objects/008.py")

    assert example.prices[example.Balance(currency="USD", amount=D("9.99"))] == (
        "budget"
    )
    assert len(example.unique_emails | {example.Email(address="a@b.com")}) == 2


def test_order_item_vo_mirrors_the_entity_fields():
    example = load_example("guides/domain-definition/value-objects/009.py")
    example.domain.init(traverse=False)

    vo = example.value_object_from_entity(example.OrderItem)
    item = vo(product_name="Pen", quantity=2, internal_notes="fragile")

    assert item.id is None
    assert item.to_dict()["internal_notes"] == "fragile"
    assert "order" not in item.to_dict()
    with pytest.raises(ValidationError) as exc:
        vo(product_name="Pen", quantity="two")
    assert "quantity" in exc.value.messages


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="value_object_from_entity does not copy field constraints such as "
    "max_length.",
)
def test_generated_vo_keeps_the_entity_max_length():
    example = load_example("guides/domain-definition/value-objects/009.py")
    example.domain.init(traverse=False)
    vo = example.value_object_from_entity(example.OrderItem)

    try:
        vo(product_name="x" * 101, quantity=2)
    except ValidationError:
        return

    raise AssertionError("product_name over max_length=100 was accepted")


def test_custom_vo_has_the_given_name_and_drops_internal_notes():
    example = load_example("guides/domain-definition/value-objects/009.py")

    assert example.OrderItemVO.__name__ == "OrderItemPayload"
    item = example.OrderItemVO(product_name="Pen", quantity=2)
    assert "internal_notes" not in item.to_dict()


def test_place_order_handler_rebuilds_entities_from_the_command_items():
    example = load_example("guides/domain-definition/value-objects/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        command = example.PlaceOrder(
            customer_id="c-1",
            items=[{"product_name": "Pen", "quantity": 2, "unit_price": "1.50"}],
        )
        order = example.PlaceOrderHandler().handle_place_order(command)

    assert order.customer_id == "c-1"
    assert len(order.items) == 1
    assert isinstance(order.items[0], example.OrderItem)
    assert order.items[0].product_name == "Pen"
    assert order.items[0].quantity == 2
    assert order.items[0].order_id == order.id

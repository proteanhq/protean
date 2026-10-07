"""The examples on the container fields reference behave as the page says."""

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example


def test_list_of_strings_accepts_strings_and_rejects_numbers():
    example = load_example("guides/domain-definition/fields/container-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(email="john.doe@gmail.com", roles=["ADMIN", "EDITOR"])
        with pytest.raises(ValidationError) as exc:
            example.User(email="jane.doe@gmail.com", roles=[1, 2])

    assert user.roles == ["ADMIN", "EDITOR"]
    assert "roles" in exc.value.messages


def test_dict_payload_keeps_the_dictionary():
    example = load_example("guides/domain-definition/fields/container-fields/002.py")
    example.domain.init(traverse=False)
    payload = {"name": "John Doe", "email": "john.doe@example.com"}

    with example.domain.domain_context():
        event = example.UserEvent(name="UserRegistered", payload=payload)

    assert event.to_dict()["payload"] == payload


def test_value_object_field_embeds_the_balance():
    example = load_example("guides/domain-definition/fields/container-fields/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        account = example.Account(
            balance=example.Balance(currency="USD", amount=100.0), name="Checking"
        )
        with pytest.raises(ValidationError) as exc:
            example.Balance(currency="USD", amount=-1.0)

    assert account.to_dict()["balance"] == {"currency": "USD", "amount": 100.0}
    assert "amount" in exc.value.messages


def test_list_of_value_objects_is_persisted_and_updated_on_save():
    example = load_example("guides/domain-definition/fields/container-fields/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(
            customer=example.Customer(
                name="John Doe",
                email="john@doe.com",
                addresses=[
                    example.Address(
                        street="123 Main St", city="Anytown", state="CA", country="USA"
                    ),
                    example.Address(
                        street="321 Side St", city="Anytown", state="CA", country="USA"
                    ),
                ],
            )
        )
        repo = example.domain.repository_for(example.Order)
        repo.add(order)
        retrieved = repo.get(order.id)
        assert len(retrieved.customer.addresses) == 2

        retrieved.customer.addresses.append(
            example.Address(
                street="456 Side St", city="Anytown", state="CA", country="USA"
            )
        )
        assert len(repo.get(order.id).customer.addresses) == 2

        repo.add(retrieved)
        refreshed = repo.get(order.id)

    assert [address.street for address in refreshed.customer.addresses] == [
        "123 Main St",
        "321 Side St",
        "456 Side St",
    ]
    assert isinstance(refreshed.customer.addresses[0], example.Address)


def test_value_object_from_entity_validates_place_order_items():
    example = load_example("guides/domain-definition/fields/container-fields/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        command = example.PlaceOrder(
            customer_id="c1", items=[{"product_id": "p1", "quantity": 2}]
        )
        with pytest.raises(ValidationError) as exc:
            example.PlaceOrder(customer_id="c1", items=[{"quantity": 2}])

    assert len(command.items) == 1
    assert command.items[0].product_id == "p1"
    assert command.items[0].quantity == 2
    assert command.items[0].id is None
    assert "product_id" in exc.value.messages


def test_dict_of_value_objects_rebuilds_addresses_on_load():
    example = load_example("guides/domain-definition/fields/container-fields/006.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        customer = example.Customer(
            name="John",
            addresses={"home": example.Address(street="1 Main St", city="Anytown")},
        )
        repo = example.domain.repository_for(example.Customer)
        repo.add(customer)
        stored = repo.get(customer.id)
        with pytest.raises(ValidationError) as exc:
            example.Customer(name="John", addresses={"home": "1 Main St"})

    assert customer.to_dict()["addresses"] == {
        "home": {"street": "1 Main St", "city": "Anytown"}
    }
    assert isinstance(stored.addresses["home"], example.Address)
    assert stored.addresses["home"].city == "Anytown"
    assert "addresses" in exc.value.messages

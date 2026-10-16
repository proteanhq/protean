"""Run the example on ``docs/patterns/organize-by-domain-concept.md``."""

import pytest

from protean.exceptions import ObjectNotFoundError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    example = load_example("patterns/organize-by-domain-concept/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _customer_with_address(example):
    repo = example.domain.repository_for(example.Customer)
    customer = example.Customer(name="Ada")
    repo.add(customer)
    example.domain.process(
        example.AddAddress(
            customer_id=customer.id, street="1 Main St", city="Springfield"
        )
    )
    return repo.get(customer.id)


def test_the_capability_commands_belong_to_the_customer(example):
    for command in (
        example.AddAddress,
        example.RemoveAddress,
        example.SetDefaultAddress,
    ):
        assert command.meta_.part_of is example.Customer
    assert example.ManageAddressesHandler.meta_.part_of is example.Customer


def test_adding_an_address_stores_it_on_the_customer(example):
    customer = _customer_with_address(example)

    assert [(a.street, a.city) for a in customer.addresses] == [
        ("1 Main St", "Springfield")
    ]


def test_setting_and_removing_the_default_address(example):
    customer = _customer_with_address(example)
    [address] = customer.addresses
    repo = example.domain.repository_for(example.Customer)

    example.domain.process(
        example.SetDefaultAddress(customer_id=customer.id, address_id=address.id)
    )
    assert repo.get(customer.id).default_address_id == address.id

    example.domain.process(
        example.RemoveAddress(customer_id=customer.id, address_id=address.id)
    )
    customer = repo.get(customer.id)
    assert customer.addresses == []
    assert customer.default_address_id is None


def test_an_unknown_address_cannot_become_the_default(example):
    customer = _customer_with_address(example)

    with pytest.raises(ObjectNotFoundError):
        example.domain.process(
            example.SetDefaultAddress(customer_id=customer.id, address_id="missing")
        )

    repo = example.domain.repository_for(example.Customer)
    assert repo.get(customer.id).default_address_id is None

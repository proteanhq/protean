"""Run the example on ``docs/patterns/organize-by-domain-concept.md``.

The page lays the ``identity`` domain out as a package with one folder per
aggregate. Its folder goes on ``sys.path`` so the package imports by its name,
as it would in the reader's project.
"""

import sys

import pytest

from protean.exceptions import ObjectNotFoundError
from tests.docs.support import DOCS_SRC

pytestmark = pytest.mark.no_test_domain

_LAYOUT_DIR = str(DOCS_SRC / "patterns" / "organize-by-domain-concept")
if _LAYOUT_DIR not in sys.path:
    sys.path.insert(0, _LAYOUT_DIR)

import identity
import identity.customer.customer as customer_module
from identity.customer import addresses

domain = identity.domain


@pytest.fixture(scope="module", autouse=True)
def _initialized():
    domain.config["command_processing"] = "sync"
    # Traversal imports every module under the domain's folder, so this
    # checks that each file of the layout imports on its own.
    domain.init()


@pytest.fixture(autouse=True)
def _ctx():
    with domain.domain_context():
        yield


def _customer_with_address():
    repo = domain.repository_for(customer_module.Customer)
    customer = customer_module.Customer(name="Ada")
    repo.add(customer)
    domain.process(
        addresses.AddAddress(
            customer_id=customer.id, street="1 Main St", city="Springfield"
        )
    )
    return repo.get(customer.id)


def test_the_domain_finds_every_element_of_the_layout():
    assert set(domain.registry.aggregates) == {"identity.customer.customer.Customer"}
    assert set(domain.registry.commands) == {
        "identity.customer.addresses.AddAddress",
        "identity.customer.addresses.RemoveAddress",
        "identity.customer.addresses.SetDefaultAddress",
    }
    assert set(domain.registry.command_handlers) == {
        "identity.customer.addresses.ManageAddressesHandler"
    }


def test_the_capability_commands_belong_to_the_customer():
    for command in (
        addresses.AddAddress,
        addresses.RemoveAddress,
        addresses.SetDefaultAddress,
    ):
        assert command.meta_.part_of is customer_module.Customer
    assert addresses.ManageAddressesHandler.meta_.part_of is customer_module.Customer


def test_adding_an_address_stores_it_on_the_customer():
    customer = _customer_with_address()

    assert [(a.street, a.city) for a in customer.addresses] == [
        ("1 Main St", "Springfield")
    ]


def test_setting_and_removing_the_default_address():
    customer = _customer_with_address()
    [address] = customer.addresses
    repo = domain.repository_for(customer_module.Customer)

    domain.process(
        addresses.SetDefaultAddress(customer_id=customer.id, address_id=address.id)
    )
    assert repo.get(customer.id).default_address_id == address.id

    domain.process(
        addresses.RemoveAddress(customer_id=customer.id, address_id=address.id)
    )
    customer = repo.get(customer.id)
    assert customer.addresses == []
    assert customer.default_address_id is None


def test_an_unknown_address_cannot_become_the_default():
    customer = _customer_with_address()

    with pytest.raises(ObjectNotFoundError):
        domain.process(
            addresses.SetDefaultAddress(customer_id=customer.id, address_id="missing")
        )

    repo = domain.repository_for(customer_module.Customer)
    assert repo.get(customer.id).default_address_id is None

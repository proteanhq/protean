"""Tests for association persistence.

Full CRUD lifecycle through memory repository for aggregates with
HasMany, HasOne, and ValueObject associations.
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import HasMany, HasOne, Reference, ValueObject


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Address(BaseValueObject):
    street: str = ""
    city: str = ""


class Invoice(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    number: str = ""
    line_items = HasMany("tests.repository.test_association_crud.LineItem")
    billing = HasOne("tests.repository.test_association_crud.BillingInfo")
    shipping_address = ValueObject(Address)


class LineItem(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    description: str = ""
    amount: float = 0.0
    invoice = Reference("tests.repository.test_association_crud.Invoice")


class BillingInfo(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    method: str = "credit_card"
    invoice = Reference("tests.repository.test_association_crud.Invoice")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Address)
    test_domain.register(Invoice)
    test_domain.register(LineItem, part_of=Invoice)
    test_domain.register(BillingInfo, part_of=Invoice)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: Create and retrieve
# ---------------------------------------------------------------------------
class TestCreateAndRetrieve:
    def test_persist_aggregate_with_has_many(self, test_domain):
        item1 = LineItem(description="Widget", amount=10.0)
        item2 = LineItem(description="Gadget", amount=20.0)
        invoice = Invoice(number="INV-001", line_items=[item1, item2])

        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        assert retrieved.number == "INV-001"
        assert len(retrieved.line_items) == 2

    def test_persist_aggregate_with_has_one(self, test_domain):
        billing = BillingInfo(method="bank_transfer")
        invoice = Invoice(number="INV-002", billing=billing)

        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        assert retrieved.billing is not None
        assert retrieved.billing.method == "bank_transfer"

    def test_persist_aggregate_with_vo(self, test_domain):
        addr = Address(street="123 Main St", city="Springfield")
        invoice = Invoice(number="INV-003", shipping_address=addr)

        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        assert retrieved.shipping_address is not None
        assert retrieved.shipping_address.street == "123 Main St"
        assert retrieved.shipping_address.city == "Springfield"

    def test_persist_full_aggregate(self, test_domain):
        item = LineItem(description="Widget", amount=10.0)
        billing = BillingInfo(method="cash")
        addr = Address(street="456 Elm Ave", city="Shelbyville")

        invoice = Invoice(
            number="INV-004",
            line_items=[item],
            billing=billing,
            shipping_address=addr,
        )

        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        assert retrieved.number == "INV-004"
        assert len(retrieved.line_items) == 1
        assert retrieved.billing.method == "cash"
        assert retrieved.shipping_address.street == "456 Elm Ave"


# ---------------------------------------------------------------------------
# Tests: Update associations
# ---------------------------------------------------------------------------
class TestUpdateAssociations:
    def test_add_has_many_item_after_persist(self, test_domain):
        invoice = Invoice(number="INV-010")
        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        item = LineItem(description="New Item", amount=15.0)
        retrieved.add_line_items(item)
        test_domain.repository_for(Invoice).add(retrieved)

        updated = test_domain.repository_for(Invoice).get(invoice.id)
        assert len(updated.line_items) == 1
        assert updated.line_items[0].description == "New Item"

    def test_remove_has_many_item(self, test_domain):
        item1 = LineItem(description="Widget", amount=10.0)
        item2 = LineItem(description="Gadget", amount=20.0)
        invoice = Invoice(number="INV-011", line_items=[item1, item2])
        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        # Remove the first item
        first_item = retrieved.line_items[0]
        retrieved.remove_line_items(first_item)
        test_domain.repository_for(Invoice).add(retrieved)

        updated = test_domain.repository_for(Invoice).get(invoice.id)
        assert len(updated.line_items) == 1

    def test_replace_has_one(self, test_domain):
        billing1 = BillingInfo(method="credit_card")
        invoice = Invoice(number="INV-012", billing=billing1)
        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        billing2 = BillingInfo(method="bank_transfer")
        retrieved.billing = billing2
        test_domain.repository_for(Invoice).add(retrieved)

        updated = test_domain.repository_for(Invoice).get(invoice.id)
        assert updated.billing.method == "bank_transfer"

    def test_update_vo(self, test_domain):
        addr1 = Address(street="123 Main St", city="Springfield")
        invoice = Invoice(number="INV-013", shipping_address=addr1)
        test_domain.repository_for(Invoice).add(invoice)

        retrieved = test_domain.repository_for(Invoice).get(invoice.id)
        addr2 = Address(street="456 Elm Ave", city="Shelbyville")
        retrieved.shipping_address = addr2
        test_domain.repository_for(Invoice).add(retrieved)

        updated = test_domain.repository_for(Invoice).get(invoice.id)
        assert updated.shipping_address.street == "456 Elm Ave"
        assert updated.shipping_address.city == "Shelbyville"

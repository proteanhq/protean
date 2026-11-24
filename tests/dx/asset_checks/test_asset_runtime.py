"""The value objects the DX-pack examples use work at runtime.

The example runner in ``tests/dx/test_examples.py`` skips each ``__main__`` demo
block, so it never runs the code that builds and reads these value objects.
These tests run that code for the examples that use them. Each test loads its
example by path, initialises the example's domain and runs inside its context.

``tests/dx/test_examples.py`` runs this file in a child interpreter, so the
example domains stay out of the test process.
"""

from __future__ import annotations

import runpy
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain
from protean.exceptions import ObjectNotFoundError, ValidationError

SKILLS_ROOT = Path(str(dx.pack_files())) / dx.SKILLS_DIR


@contextmanager
def example(asset: str) -> Iterator[dict[str, Any]]:
    """Load *asset*, initialise its domain, and yield its names inside the
    domain's context."""
    namespace = runpy.run_path(str(SKILLS_ROOT / asset), run_name="_dx_runtime_check_")
    domain = next(value for value in namespace.values() if isinstance(value, Domain))
    domain.init(traverse=False)
    with domain.domain_context():
        yield namespace


def test_customer_holds_its_contact_info() -> None:
    with example("add-field/assets/add_simple_field.py") as names:
        contact_info = names["ContactInfo"]
        customer = names["Customer"](
            customer_id="CUST-1",
            name="Ada",
            contact=contact_info(email="ada@example.com", phone="555-0100"),
        )

        assert isinstance(customer.contact, contact_info)
        assert customer.contact.email == "ada@example.com"
        assert customer.contact.phone == "555-0100"


SCAFFOLD_ORDER = "generate-test-scaffold/assets/scaffold_aggregate_unit.py"


def test_scaffold_order_prices_a_line_item_in_money() -> None:
    with example(SCAFFOLD_ORDER) as names:
        money = names["Money"]
        order = names["Order"].create(customer_id="CUST-1")

        item = order.add_item("P1", quantity=2, unit_price=10.0)

        assert isinstance(item.unit_price, money)
        assert item.unit_price == money(amount=10.0, currency="USD")
        assert item.subtotal == 20.0


def test_scaffold_order_totals_its_line_items() -> None:
    with example(SCAFFOLD_ORDER) as names:
        order = names["Order"].create(customer_id="CUST-1")
        order.add_item("P1", quantity=2, unit_price=10.0)
        order.add_item("P2", quantity=1, unit_price=5.5)

        assert order.total == 25.5


def test_scaffold_money_adds() -> None:
    with example(SCAFFOLD_ORDER) as names:
        money = names["Money"]

        assert money(amount=1.0).add(money(amount=2.0)) == money(amount=3.0)


ES_ORDER = "event-sourced-aggregate/assets/es_aggregate_with_entities.py"
ES_ITEMS = [
    {"product_id": "P1", "quantity": 2, "unit_price": 25.0},
    {"product_id": "P2", "quantity": 1, "unit_price": 75.0},
]


def test_event_sourced_order_builds_money_on_create() -> None:
    with example(ES_ORDER) as names:
        order = names["Order"].create(
            order_id="ORD-1", customer_id="CUST-1", items=ES_ITEMS
        )

        assert all(isinstance(item.unit_price, names["Money"]) for item in order.items)
        assert order.total == 125.0


def test_event_sourced_order_rebuilds_money_on_replay() -> None:
    with example(ES_ORDER) as names:
        order_class = names["Order"]
        order = order_class.create(
            order_id="ORD-1", customer_id="CUST-1", items=ES_ITEMS
        )

        replayed = order_class.from_events(order._events)

        assert sorted(item.unit_price.amount for item in replayed.items) == [
            25.0,
            75.0,
        ]
        assert all(
            isinstance(item.unit_price, names["Money"]) for item in replayed.items
        )
        assert replayed.total == 125.0


INVOICE = "add-field/assets/add_association_fields.py"


@contextmanager
def invoice_with_one_line() -> Iterator[tuple[Any, Any]]:
    """Yield an invoice holding one two-mouse line, and that line."""
    with example(INVOICE) as names:
        invoice = names["Invoice"](invoice_number="INV-1", customer_id="CUST-1")
        line = names["InvoiceLineItem"](
            description="Mouse", quantity=2, unit_price="29.99"
        )
        invoice.add_line_items(line)
        yield invoice, line


def test_invoice_finds_a_line_by_keyword_id() -> None:
    with invoice_with_one_line() as (invoice, line):
        assert invoice.get_one_from_line_items(id=line.id) is line


def test_invoice_totals_its_lines() -> None:
    with invoice_with_one_line() as (invoice, _):
        assert invoice.total == Decimal("59.98")


def test_invoice_lookup_of_an_unknown_line_raises() -> None:
    with invoice_with_one_line() as (invoice, _):
        with pytest.raises(ObjectNotFoundError):
            invoice.get_one_from_line_items(id="missing")


def test_invoice_refuses_to_remove_an_unknown_line() -> None:
    with invoice_with_one_line() as (invoice, _):
        with pytest.raises(ValidationError) as exc:
            invoice.remove_product_line("missing")

        assert exc.value.messages == {"line_items": ["No line item with id missing"]}


def test_invoice_removes_a_line_by_id() -> None:
    with invoice_with_one_line() as (invoice, line):
        invoice.remove_product_line(line.id)

        assert invoice.line_items == []


INVARIANTS = "aggregate/assets/aggregate_with_invariants.py"


def test_failed_withdrawal_leaves_the_balance_unchanged() -> None:
    with example(INVARIANTS) as names:
        account = names["Account"](
            account_number="ACC-1", balance="100.00", overdraft_limit="50.00"
        )

        with pytest.raises(ValidationError):
            account.withdraw("200.00")

        assert account.balance == Decimal("100.00")


def test_warehouse_ships_part_of_its_reserved_stock() -> None:
    with example(INVARIANTS) as names:
        warehouse = names["Warehouse"](name="Main", max_capacity=1000.0)
        warehouse.receive_stock(100.0)
        warehouse.reserve_stock(100.0)

        warehouse.ship_stock(50.0)

        assert warehouse.current_stock == 50.0
        assert warehouse.reserved_stock == 50.0

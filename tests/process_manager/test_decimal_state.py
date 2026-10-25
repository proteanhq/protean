"""Tests for process manager state persistence with Decimal fields.

The transition event stores the PM's state as JSON. A Decimal is not
JSON-serializable, so it is stored as a string and converted back to a Decimal
when the PM is reconstituted.
"""

from decimal import Decimal as D
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.fields import Decimal, Identifier, String
from protean.utils.mixins import handle


class Invoice(BaseAggregate):
    customer_id: Identifier()


class InvoiceIssued(BaseEvent):
    invoice_id: Identifier()
    total: Decimal(precision=19, scale=4)


class PaymentReceived(BaseEvent):
    invoice_id: Identifier()
    amount: Decimal(precision=19, scale=4)


class CollectionPM(BaseProcessManager):
    invoice_id: Identifier()
    outstanding: Decimal(precision=19, scale=4)
    status: String(default="open")

    @handle(InvoiceIssued, start=True, correlate="invoice_id")
    def on_issued(self, event: InvoiceIssued) -> None:
        self.invoice_id = event.invoice_id
        self.outstanding = event.total

    @handle(PaymentReceived, correlate="invoice_id")
    def on_payment(self, event: PaymentReceived) -> None:
        self.outstanding -= event.amount
        if self.outstanding == 0:
            self.status = "paid"
            self.mark_as_complete()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Invoice)
    test_domain.register(InvoiceIssued, part_of=Invoice)
    test_domain.register(PaymentReceived, part_of=Invoice)
    test_domain.register(CollectionPM, stream_categories=["test::invoice"])
    test_domain.init(traverse=False)


def _transitions(test_domain, invoice_id: str) -> list:
    stream_name = f"{CollectionPM.meta_.stream_category}-{invoice_id}"
    return test_domain.event_store.store.read(stream_name)


def test_a_decimal_field_persists_as_a_string(test_domain):
    invoice_id = str(uuid4())

    CollectionPM._handle(InvoiceIssued(invoice_id=invoice_id, total=D("100.50")))

    transition = _transitions(test_domain, invoice_id)[0].to_domain_object()
    assert transition.state["outstanding"] == "100.50"


def test_a_decimal_field_is_a_decimal_after_reconstitution(test_domain):
    invoice_id = str(uuid4())

    CollectionPM._handle(InvoiceIssued(invoice_id=invoice_id, total=D("100.50")))

    pm = CollectionPM._load_or_create(invoice_id, is_start=False)
    assert pm is not None
    assert pm.outstanding == D("100.50")
    assert isinstance(pm.outstanding, D)


def test_a_handler_does_decimal_arithmetic_on_reconstituted_state(test_domain):
    invoice_id = str(uuid4())

    CollectionPM._handle(InvoiceIssued(invoice_id=invoice_id, total=D("100.50")))
    CollectionPM._handle(PaymentReceived(invoice_id=invoice_id, amount=D("40.25")))
    CollectionPM._handle(PaymentReceived(invoice_id=invoice_id, amount=D("60.25")))

    final = _transitions(test_domain, invoice_id)[-1].to_domain_object()
    assert final.state["outstanding"] == "0.00"
    assert final.state["status"] == "paid"
    assert final.is_complete is True


def test_a_stored_value_that_no_longer_validates_is_kept_as_stored(test_domain):
    invoice_id = str(uuid4())
    CollectionPM._handle(InvoiceIssued(invoice_id=invoice_id, total=D("100.50")))
    message = _transitions(test_domain, invoice_id)[0]

    transition = message.to_domain_object()
    transition.state["outstanding"] = "not a number"
    message_with_bad_value = type(message).from_domain_object(transition)

    pm = CollectionPM._from_transitions([message_with_bad_value], invoice_id)
    assert pm.outstanding == "not a number"

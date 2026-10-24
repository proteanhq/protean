from unittest.mock import patch

import pytest

from protean import Domain, current_domain
from protean.fields import Float, String

domain = Domain(name="Billing")


class PaymentGateway:
    """Charges a card through the payment provider's HTTP API."""

    def charge(self, amount: float) -> str:
        raise RuntimeError("calls the payment provider over the network")


gateway = PaymentGateway()


@domain.aggregate
class Invoice:
    amount = Float(required=True)
    status = String(default="OPEN")
    payment_id = String()

    def mark_paid(self, payment_id):
        self.payment_id = payment_id
        self.status = "PAID"


def pay_invoice(invoice_id):
    repo = current_domain.repository_for(Invoice)
    invoice = repo.get(invoice_id)
    invoice.mark_paid(gateway.charge(invoice.amount))
    repo.add(invoice)


@pytest.fixture(scope="module", autouse=True)
def billing():
    # The default database is the in-memory provider, so the repository
    # below stores the invoice for real without a database server.
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:mock_the_gateway]
def test_paying_an_invoice_records_the_payment_id():
    repo = current_domain.repository_for(Invoice)
    invoice = Invoice(amount=30.0)
    repo.add(invoice)

    with patch.object(gateway, "charge", return_value="pay-1") as charge:
        pay_invoice(invoice.id)

    charge.assert_called_once_with(30.0)
    paid = repo.get(invoice.id)
    assert paid.status == "PAID"
    assert paid.payment_id == "pay-1"


# --8<-- [end:mock_the_gateway]

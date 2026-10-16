"""Run the examples on ``docs/patterns/connect-concepts-across-domains.md``."""

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    domain = example.domain
    domain.init(traverse=False)
    return domain.domain_context()


def _register(example, email="ada@example.com"):
    customer = example.Customer(name="Ada", email=email)
    customer.raise_(
        example.CustomerRegistered(
            customer_id=customer.customer_id, name="Ada", email=email
        )
    )
    example.domain.repository_for(example.Customer).add(customer)
    return customer


def _accounts(example, customer_id):
    repo = example.domain.repository_for(example.BillingAccount)
    return repo.query.filter(customer_id=customer_id).all().items


def test_registering_a_customer_opens_one_billing_account():
    example = load_example("patterns/connect-concepts-across-domains/001.py")
    with _context(example):
        customer = _register(example)

        accounts = _accounts(example, customer.customer_id)
        assert [(a.email, a.account_status) for a in accounts] == [
            ("ada@example.com", "ACTIVE")
        ]


def test_a_repeated_open_command_opens_no_second_account():
    example = load_example("patterns/connect-concepts-across-domains/001.py")
    with _context(example):
        customer = _register(example)

        example.domain.process(
            example.OpenBillingAccount(
                customer_id=customer.customer_id, email="ada@example.com"
            )
        )

        assert len(_accounts(example, customer.customer_id)) == 1


def test_a_repeated_suspend_command_leaves_the_account_unchanged():
    example = load_example("patterns/connect-concepts-across-domains/001.py")
    with _context(example):
        customer = _register(example)
        customer.raise_(example.CustomerDeactivated(customer_id=customer.customer_id))
        example.domain.repository_for(example.Customer).add(customer)

        [suspended] = _accounts(example, customer.customer_id)
        assert suspended.account_status == "SUSPENDED"

        example.domain.process(
            example.SuspendBillingAccount(customer_id=customer.customer_id)
        )

        [account] = _accounts(example, customer.customer_id)
        assert account.account_status == "SUSPENDED"
        assert account._version == suspended._version


def test_the_hand_off_stays_with_the_customer():
    example = load_example("patterns/connect-concepts-across-domains/001.py")
    with _context(example):
        assert example.CustomerLifecycleHandler.meta_.part_of is example.Customer
        report = example.domain.check(traverse=False)
        codes = {entry["code"] for entry in report["errors"]} | {
            entry["code"] for entry in report["diagnostics"]
        }
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes


def test_the_sales_customer_defaults_to_the_standard_segment():
    example = load_example("patterns/connect-concepts-across-domains/002.py")
    example.sales.init(traverse=False)
    with example.sales.domain_context():
        customer = example.Customer(name="Ada", email="ada@example.com")
        repo = example.sales.repository_for(example.Customer)
        repo.add(customer)

        stored = repo.get(customer.customer_id)
        assert (stored.name, stored.email, stored.segment) == (
            "Ada",
            "ada@example.com",
            "STANDARD",
        )
        assert (
            example.Customer(
                name="Ada", email="ada@example.com", segment="PREMIUM"
            ).segment
            == "PREMIUM"
        )


def test_the_sales_customer_rejects_an_unknown_segment():
    example = load_example("patterns/connect-concepts-across-domains/002.py")
    example.sales.init(traverse=False)
    with example.sales.domain_context():
        with pytest.raises(ValidationError) as exc:
            example.Customer(name="Ada", email="ada@example.com", segment="GOLD")
        assert "segment" in exc.value.messages
        assert example.sales.repository_for(example.Customer).query.all().total == 0


def test_every_sales_event_carries_the_customer_id():
    example = load_example("patterns/connect-concepts-across-domains/002.py")
    example.sales.init(traverse=False)
    with example.sales.domain_context():
        event = example.CustomerEmailUpdated(
            customer_id="c-123", new_email="jane@example.com"
        )
        assert (event.customer_id, event.new_email) == ("c-123", "jane@example.com")

        for event_cls, values in [
            (example.CustomerRegistered, {"name": "Jane", "email": "j@example.com"}),
            (example.CustomerEmailUpdated, {"new_email": "j@example.com"}),
            (example.CustomerDeactivated, {"reason": "closed"}),
        ]:
            with pytest.raises(ValidationError) as exc:
                event_cls(**values)
            assert exc.value.messages == {"customer_id": ["is required"]}


def test_fact_events_carry_the_whole_customer():
    example = load_example("patterns/connect-concepts-across-domains/003.py")
    sales = example.sales
    sales.init(traverse=False)
    with sales.domain_context():
        customer = example.Customer(name="Jane Doe", email="jane@example.com")
        sales.repository_for(example.Customer).add(customer)

        stream = f"{example.Customer.meta_.stream_category}-fact-{customer.customer_id}"
        [message] = sales.event_store.store.read(stream)
        fact = message.to_domain_object()
        assert type(fact).__name__ == "CustomerFactEvent"
        assert (fact.customer_id, fact.name, fact.email, fact.segment) == (
            customer.customer_id,
            "Jane Doe",
            "jane@example.com",
            "STANDARD",
        )


REGISTERED = {
    "type": "Sales.CustomerRegistered.v1",
    "customer_id": "c-123",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "street": "1 Main St",
    "city": "Springfield",
    "zip_code": "12345",
}


def _recipient(example, customer_id="c-123"):
    repo = example.shipping.repository_for(example.Recipient)
    return repo.find_by(customer_id=customer_id)


def test_the_subscriber_creates_a_recipient_from_a_registration():
    example = load_example("patterns/connect-concepts-across-domains/004.py")
    example.shipping.init(traverse=False)
    with example.shipping.domain_context():
        example.CustomerEventSubscriber()(REGISTERED)

        recipient = _recipient(example)
        assert recipient.customer_id == "c-123"
        assert recipient.name == "Jane Doe"
        assert recipient.delivery_address == example.Address(
            street="1 Main St", city="Springfield", zip_code="12345"
        )


def test_the_subscriber_updates_the_address_of_the_correlated_recipient():
    example = load_example("patterns/connect-concepts-across-domains/004.py")
    example.shipping.init(traverse=False)
    with example.shipping.domain_context():
        subscriber = example.CustomerEventSubscriber()
        subscriber(REGISTERED)
        subscriber(
            {
                "type": "Sales.CustomerAddressUpdated.v1",
                "customer_id": "c-123",
                "street": "9 Elm Rd",
                "city": "Shelbyville",
                "zip_code": "67890",
            }
        )

        recipient = _recipient(example)
        assert recipient.name == "Jane Doe"
        assert recipient.delivery_address == example.Address(
            street="9 Elm Rd", city="Shelbyville", zip_code="67890"
        )
        repo = example.shipping.repository_for(example.Recipient)
        assert repo.query.all().total == 1


def test_the_subscriber_ignores_events_shipping_does_not_care_about():
    example = load_example("patterns/connect-concepts-across-domains/004.py")
    example.shipping.init(traverse=False)
    with example.shipping.domain_context():
        example.CustomerEventSubscriber()(
            {"type": "Sales.CustomerEmailUpdated.v1", "customer_id": "c-123"}
        )

        repo = example.shipping.repository_for(example.Recipient)
        assert repo.query.all().total == 0
        assert example.CustomerEventSubscriber.meta_.stream == "sales_customer_events"


def test_an_address_update_for_an_unknown_customer_fails():
    example = load_example("patterns/connect-concepts-across-domains/004.py")
    example.shipping.init(traverse=False)
    with example.shipping.domain_context():
        with pytest.raises(ObjectNotFoundError):
            example.CustomerEventSubscriber()(
                {
                    "type": "Sales.CustomerAddressUpdated.v1",
                    "customer_id": "c-404",
                    "street": "9 Elm Rd",
                    "city": "Shelbyville",
                    "zip_code": "67890",
                }
            )

        repo = example.shipping.repository_for(example.Recipient)
        assert repo.query.all().total == 0


def test_the_projector_builds_the_dashboard_and_adds_invoice_totals():
    example = load_example("patterns/connect-concepts-across-domains/005.py")
    domain = example.domain
    domain.config["event_processing"] = "sync"
    domain.init(traverse=False)
    with domain.domain_context():
        customer = example.Customer(name="Jane Doe", email="jane@example.com")
        customer.raise_(
            example.CustomerRegistered(
                customer_id=customer.customer_id,
                name="Jane Doe",
                email="jane@example.com",
            )
        )
        domain.repository_for(example.Customer).add(customer)

        account = example.BillingAccount(customer_id=customer.customer_id)
        for amount in (100.0, 25.5):
            account.raise_(
                example.InvoiceIssued(customer_id=customer.customer_id, amount=amount)
            )
        domain.repository_for(example.BillingAccount).add(account)

        dashboard = domain.repository_for(example.CustomerDashboard).get(
            customer.customer_id
        )
        assert (dashboard.name, dashboard.email, dashboard.total_invoiced) == (
            "Jane Doe",
            "jane@example.com",
            125.5,
        )


def test_the_projector_reads_both_streams():
    example = load_example("patterns/connect-concepts-across-domains/005.py")
    example.domain.init(traverse=False)
    assert example.CustomerDashboardProjector.meta_.stream_categories == [
        "customerviews::customer",
        "customerviews::billing_account",
    ]


def test_the_shipment_needs_every_correlation_id():
    example = load_example("patterns/connect-concepts-across-domains/006.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        shipment = example.Shipment(
            order_id="o-1", customer_id="c-1", warehouse_id="w-1"
        )
        assert (shipment.order_id, shipment.customer_id, shipment.warehouse_id) == (
            "o-1",
            "c-1",
            "w-1",
        )

        with pytest.raises(ValidationError) as exc:
            example.Shipment(order_id="o-1", customer_id="c-1")
        assert exc.value.messages == {"warehouse_id": ["is required"]}


def test_the_customer_reference_starts_active():
    example = load_example("patterns/connect-concepts-across-domains/006.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        repo = example.domain.repository_for(example.CustomerReference)
        repo.add(
            example.CustomerReference(
                customer_id="c-1", name="Jane Doe", email="jane@example.com"
            )
        )

        reference = repo.get("c-1")
        assert (reference.name, reference.is_active) == ("Jane Doe", True)

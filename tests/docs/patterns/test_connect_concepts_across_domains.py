"""Run the same-domain example on ``docs/patterns/connect-concepts-across-domains.md``."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

EXAMPLE = "patterns/connect-concepts-across-domains/001.py"


def _context(example):
    domain = example.domain
    domain.init(traverse=False)
    return domain.domain_context()


def _register(example, email="ada@example.com"):
    customer = example.Customer(name="Ada", email=email)
    customer.raise_(
        example.CustomerRegistered(customer_id=customer.customer_id, email=email)
    )
    example.domain.repository_for(example.Customer).add(customer)
    return customer


def _accounts(example, customer_id):
    repo = example.domain.repository_for(example.BillingAccount)
    return repo.query.filter(customer_id=customer_id).all().items


def test_registering_a_customer_opens_one_billing_account():
    example = load_example(EXAMPLE)
    with _context(example):
        customer = _register(example)

        accounts = _accounts(example, customer.customer_id)
        assert [(a.email, a.account_status) for a in accounts] == [
            ("ada@example.com", "ACTIVE")
        ]


def test_a_repeated_open_command_opens_no_second_account():
    example = load_example(EXAMPLE)
    with _context(example):
        customer = _register(example)

        example.domain.process(
            example.OpenBillingAccount(
                customer_id=customer.customer_id, email="ada@example.com"
            )
        )

        assert len(_accounts(example, customer.customer_id)) == 1


def test_a_repeated_suspend_command_leaves_the_account_unchanged():
    example = load_example(EXAMPLE)
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
    example = load_example(EXAMPLE)
    with _context(example):
        assert example.CustomerLifecycleHandler.meta_.part_of is example.Customer
        report = example.domain.check(traverse=False)
        codes = {entry["code"] for entry in report["errors"]} | {
            entry["code"] for entry in report["diagnostics"]
        }
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

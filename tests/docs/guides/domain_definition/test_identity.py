"""The examples on the identity guide behave as the page says."""

import re
import time
import uuid

import pytest

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String
from protean.utils.reflection import declared_fields, id_field
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_customer_gets_a_default_uuid_id():
    example = load_example("guides/domain-definition/identity/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        customer = example.Customer(name="Jane Doe")

    assert id_field(example.Customer).field_name == "id"
    assert isinstance(customer.id, str)
    assert uuid.UUID(customer.id)
    assert customer.to_dict() == {
        "name": "Jane Doe",
        "id": customer.id,
        "_version": -1,
    }


def test_user_identity_is_named_user_id_and_there_is_no_id_field():
    example = load_example("guides/domain-definition/identity/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(name="John Doe")

    assert id_field(example.User).field_name == "user_id"
    assert "id" not in declared_fields(example.User)
    assert uuid.UUID(user.user_id)
    assert user.to_dict() == {
        "user_id": user.user_id,
        "name": "John Doe",
        "_version": -1,
    }


def test_reading_identity_is_an_integer_value():
    example = load_example("guides/domain-definition/identity/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        reading = example.Reading(value="42")

    # The Auto field stores identities as strings, so the integer arrives in
    # its string form. It is all digits, not a hyphenated UUID.
    assert re.fullmatch(r"\d+", reading.reading_id)
    assert int(reading.reading_id) > 0


def test_domain_identity_function_gives_epoch_millisecond_ids():
    example = load_example("guides/domain-definition/identity/004.py")
    example.domain.init(traverse=False)

    before = int(time.time() * 1000)
    with example.domain.domain_context():
        event = example.Event(name="launch")
    after = int(time.time() * 1000)

    assert isinstance(event.id, int)
    assert before <= event.id <= after
    assert event.to_dict() == {"name": "launch", "id": event.id, "_version": -1}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Protean does not check the identity function's return type "
    "against identity_type.",
)
def test_a_string_identity_under_integer_identity_type_is_rejected():
    domain = Domain(
        name="Launches",
        config={"identity_strategy": "function", "identity_type": "integer"},
        identity_function=lambda: "abc",
    )

    @domain.aggregate
    class Event:
        name: String(max_length=100, required=True)

    domain.init(traverse=False)

    with domain.domain_context():
        try:
            Event(name="launch")
        except ValidationError:
            return

    raise AssertionError("Event accepted a string id")


def test_invoice_number_is_a_prefixed_business_key():
    example = load_example("guides/domain-definition/identity/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        invoice = example.Invoice(customer_name="Acme Corp")
        other = example.Invoice(customer_name="Acme Corp")

    assert re.fullmatch(r"INV-[0-9A-F]{12}", invoice.invoice_number)
    assert invoice.invoice_number != other.invoice_number
    assert invoice.to_dict() == {
        "invoice_number": invoice.invoice_number,
        "customer_name": "Acme Corp",
        "_version": -1,
    }


def test_user_takes_its_email_as_identity():
    example = load_example("guides/domain-definition/identity/006.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(email="john@example.com", name="John Doe")

    assert id_field(example.User).field_name == "email"
    assert user.to_dict() == {
        "email": "john@example.com",
        "name": "John Doe",
        "_version": -1,
    }


def test_user_without_an_email_is_rejected():
    example = load_example("guides/domain-definition/identity/006.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.User(name="John Doe")

    assert exc.value.messages["email"] == ["is required"]


def test_audit_entry_gets_its_id_when_it_is_saved():
    example = load_example("guides/domain-definition/identity/007.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.AuditEntry)
        first = example.AuditEntry(message="Signed in")
        second = example.AuditEntry(message="Signed out")

        assert first.entry_id is None

        repo.add(first)
        repo.add(second)

        assert first.entry_id == 1
        assert second.entry_id == 2
        assert repo.get(1).message == "Signed in"

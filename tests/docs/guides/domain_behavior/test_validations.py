"""The examples on the validations guide behave as the page says."""

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

NOT_A_CHOICE = "Input should be 'SAVINGS' or 'CURRENT'"


def _context(example):
    example.domain.init(traverse=False)
    return example


@pytest.fixture
def accounts():
    example = _context(load_example("guides/domain-behavior/003.py"))
    with example.domain.domain_context():
        yield example


@pytest.fixture
def people():
    example = _context(load_example("guides/domain-behavior/004.py"))
    with example.domain.domain_context():
        yield example


@pytest.fixture
def emails():
    example = _context(load_example("guides/domain-behavior/005.py"))
    with example.domain.domain_context():
        yield example


def test_a_wrong_type_and_a_wrong_choice_fail_together(accounts):
    with pytest.raises(ValidationError) as exc:
        accounts.Account(account_number="A1234", account_type="CHECKING", balance=50)

    assert exc.value.messages == {
        "account_number": [
            "Input should be a valid integer, unable to parse string as an integer"
        ],
        "account_type": [NOT_A_CHOICE],
    }


def test_an_assignment_is_checked_and_does_not_take_effect(accounts):
    account = accounts.Account(
        account_number=1234, account_type="SAVINGS", balance=500.0
    )

    with pytest.raises(ValidationError) as exc:
        account.account_type = "CHECKING"

    assert exc.value.messages == {"account_type": [NOT_A_CHOICE]}
    assert account.account_type == "SAVINGS"


def test_a_missing_required_field_fails(accounts):
    with pytest.raises(ValidationError) as exc:
        accounts.Account(account_type="SAVINGS", balance=50)

    assert exc.value.messages == {"account_number": ["is required"]}


def test_length_and_range_limits_are_enforced(people):
    with pytest.raises(ValidationError) as exc:
        people.Person(name="Ho", age=200)

    assert exc.value.messages == {
        "name": ["String should have at least 3 characters"],
        "age": ["Input should be less than or equal to 120"],
    }


def test_values_inside_the_limits_are_accepted(people):
    person = people.Person(name="Hoa", age=120)

    assert (person.name, person.age) == ("Hoa", 120)


def test_the_custom_validator_accepts_a_valid_email(emails):
    person = emails.Person(name="John", email="john.doe@gmail.com")

    assert person.email == "john.doe@gmail.com"


def test_the_custom_validator_message_is_reported_under_the_field(emails):
    with pytest.raises(ValidationError) as exc:
        emails.Person(name="Jane", email="jane.doe@.gmail.com")

    assert exc.value.messages == {
        "email": ["Invalid Email Address - jane.doe@.gmail.com"]
    }

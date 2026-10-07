"""The examples on the identity reference behave as the page says."""

import time
import uuid

import pytest

from protean.exceptions import NotSupportedError
from protean.fields import Auto, Identifier
from protean.utils.reflection import attributes, declared_fields, id_field
from tests.docs.support import load_example


def test_user_id_is_the_declared_identity_field():
    example = load_example("guides/compose-a-domain/023.py")
    example.domain.init(traverse=False)

    assert list(declared_fields(example.User)) == ["user_id", "name"]
    assert id_field(example.User).field_name == "user_id"
    assert id_field(example.User).identifier is True
    assert list(attributes(example.User)) == ["user_id", "name", "_version"]


def test_user_id_is_generated_as_a_uuid_string():
    example = load_example("guides/compose-a-domain/023.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(name="John Doe")

    data = user.to_dict()
    assert list(data) == ["user_id", "name", "_version"]
    assert isinstance(data["user_id"], str)
    assert str(uuid.UUID(data["user_id"])) == data["user_id"]
    assert data["name"] == "John Doe"
    assert data["_version"] == -1


def test_an_id_field_is_added_when_none_is_declared():
    example = load_example("guides/domain-definition/fields/simple-fields/001.py")
    example.domain.init(traverse=False)

    assert list(declared_fields(example.Person)) == ["name", "id"]
    assert id_field(example.Person).field_name == "id"
    assert id_field(example.Person).identifier is True

    with example.domain.domain_context():
        person = example.Person(name="John Doe")

    assert uuid.UUID(person.id)


def test_two_identifier_fields_are_rejected():
    example = load_example("guides/compose-a-domain/023.py")

    with pytest.raises(NotSupportedError) as exc:

        @example.domain.aggregate
        class Order:
            order_id = Auto(identifier=True)
            customer_id = Identifier(identifier=True)

    message = (
        "Multiple identifier fields found in entity Order. "
        "Only one identifier field is allowed."
    )
    assert str(exc.value) == str({"_entity": [message]})


def test_custom_function_generates_an_epoch_millisecond_identity():
    example = load_example("guides/compose-a-domain/024.py")
    example.domain.init(traverse=False)

    before = int(time.time() * 1000)
    with example.domain.domain_context():
        user = example.User(name="John Doe")
    after = int(time.time() * 1000)

    data = user.to_dict()
    assert list(data) == ["user_id", "name", "_version"]
    # The function returns an int; the Auto field holds it as a digit string.
    assert isinstance(data["user_id"], str)
    assert data["user_id"].isdigit()
    assert before <= int(data["user_id"]) <= after
    assert data["name"] == "John Doe"

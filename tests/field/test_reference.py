import pytest

from protean import BaseAggregate, BaseEntity
from protean.exceptions import ValidationError
from protean.fields import Reference, String


class Address(BaseEntity):
    postal_code = String(max_length=6)


class User(BaseAggregate):
    address = Reference(Address, required=True)


def test_required_references_throw_a_validation_error_on_empty():
    ref = Reference(Address, required=True)

    with pytest.raises(ValidationError) as exc:
        ref._load(None)

    assert exc.value.messages == {"unlinked": ["is required"]}


def test_required_references_in_entity_throw_a_validation_error_on_empty():
    with pytest.raises(ValidationError) as exc:
        User()

    assert exc.value.messages == {"address": ["is required"]}

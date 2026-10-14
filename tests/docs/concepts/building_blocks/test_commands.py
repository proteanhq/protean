"""Run the example on ``docs/concepts/building-blocks/commands.md``."""

import pytest

from protean.exceptions import IncorrectUsageError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


def test_version_set_on_the_class_goes_into_the_command_type():
    example = load_example("concepts/building-blocks/commands/001.py")
    with _context(example):
        command = example.PlaceOrder(customer_id="cust-1")
        assert example.PlaceOrder.__version__ == 2
        assert command._metadata.headers.type == "CommandsConcept.PlaceOrder.v2"


def test_version_defaults_to_one():
    example = load_example("concepts/building-blocks/commands/001.py")
    with _context(example):
        command = example.CancelOrder(order_id="order-1")
        assert command._metadata.headers.type == "CommandsConcept.CancelOrder.v1"


def test_versioned_command_still_validates_its_fields():
    example = load_example("concepts/building-blocks/commands/001.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.PlaceOrder()
        assert exc.value.messages == {"customer_id": ["is required"]}


def test_command_is_immutable():
    example = load_example("concepts/building-blocks/commands/001.py")
    with _context(example):
        command = example.PlaceOrder(customer_id="cust-1")
        with pytest.raises(IncorrectUsageError):
            command.customer_id = "cust-2"
        assert command.customer_id == "cust-1"

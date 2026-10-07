"""The examples on the element decorators reference behave as the page says."""

import pytest

from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.ir.builder import IRBuilder
from tests.docs.support import load_example


def test_decorator_options_show_up_in_meta():
    example = load_example("reference/domain-elements/element-decorators/001.py")
    example.domain.init(traverse=False)

    assert example.User.meta_.schema_name == "users"
    assert example.User.meta_.fact_events is True


def test_options_left_out_keep_their_defaults():
    example = load_example("reference/domain-elements/element-decorators/001.py")
    example.domain.init(traverse=False)

    assert example.User.meta_.abstract is False
    assert example.User.meta_.provider == "default"
    assert example.User.meta_.limit == 100
    assert example.User.meta_.suppress_checks == ()


def _codes_for(domain, element_name):
    ir = IRBuilder(domain).build()
    return {
        diagnostic["code"]
        for diagnostic in ir["diagnostics"]
        if diagnostic["element"].endswith(f".{element_name}")
    }


def test_suppress_checks_silences_the_named_code_on_that_element():
    example = load_example("reference/domain-elements/element-decorators/002.py")

    @example.domain.aggregate
    class Invoice: ...

    example.domain.init(traverse=False)

    assert example.Order.meta_.suppress_checks == ("AGGREGATE_NO_INVARIANTS",)
    # The same empty aggregate without the option still gets the diagnostic.
    assert "AGGREGATE_NO_INVARIANTS" in _codes_for(example.domain, "Invoice")
    order_codes = _codes_for(example.domain, "Order")
    assert "AGGREGATE_NO_INVARIANTS" not in order_codes
    # Only the named code is silenced.
    assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" in order_codes


def test_both_version_forms_give_version_two():
    example = load_example("reference/domain-elements/element-decorators/003.py")
    example.domain.init(traverse=False)

    assert example.OrderPlaced.meta_.part_of is example.Order
    assert example.OrderPlaced.__version__ == 2
    assert example.OrderShipped.__version__ == 2
    assert example.OrderPlaced.__type__ == "Ordering.OrderPlaced.v2"
    assert example.OrderShipped.__type__ == "Ordering.OrderShipped.v2"


def test_declaring_the_version_both_ways_is_rejected():
    example = load_example("reference/domain-elements/element-decorators/003.py")

    with pytest.raises(IncorrectUsageError) as exc:

        @example.domain.event(part_of=example.Order, version=2)
        class OrderCancelled:
            __version__ = 2
            order_id = String()

    assert "declares its version twice" in str(exc.value)

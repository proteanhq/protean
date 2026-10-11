"""The domain service examples check stock against the order's total per product."""

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _callable_class():
    example = load_example("guides/domain-behavior/006.py")
    return example, lambda order, inventories: example.place_order(order, inventories)()


def _instance_method():
    example = load_example("guides/domain-behavior/007.py")
    return example, lambda order, inventories: example.OrderPlacementService(
        order, inventories
    ).place_order()


def _class_method():
    example = load_example("guides/domain-behavior/008.py")
    return example, example.OrderPlacementService.place_order


@pytest.fixture(params=[_callable_class, _instance_method, _class_method])
def flavor(request):
    example, place = request.param()
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example, place


def _order(example, *quantities):
    return example.Order(
        customer_id="c-1",
        payment_id="p-1",
        items=[example.OrderItem(product_id="P", quantity=q) for q in quantities],
    )


def _stock(example, quantity):
    return [example.Inventory(product_id="P", quantity=quantity)]


def test_two_lines_for_one_product_cannot_exceed_its_stock(flavor):
    example, place = flavor
    order = _order(example, 3, 3)

    with pytest.raises(ValidationError) as exc:
        place(order, _stock(example, 4))

    assert exc.value.messages == {"_service": ["Product is out of stock"]}
    assert order.status == example.OrderStatus.PENDING.value


def test_two_lines_within_the_stock_confirm_the_order(flavor):
    example, place = flavor
    order = _order(example, 3, 1)

    place(order, _stock(example, 4))

    assert order.status == example.OrderStatus.CONFIRMED.value
    [confirmed] = [e for e in order._events if isinstance(e, example.OrderConfirmed)]
    assert confirmed.items == [
        {"product_id": "P", "quantity": 3},
        {"product_id": "P", "quantity": 1},
    ]

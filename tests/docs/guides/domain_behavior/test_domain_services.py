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

    inventories = _stock(example, 4)

    with pytest.raises(ValidationError) as exc:
        place(order, inventories)

    assert exc.value.messages == {"_service": ["Product is out of stock"]}
    assert order.status == example.OrderStatus.PENDING.value
    assert not [e for e in order._events if isinstance(e, example.OrderConfirmed)]
    assert [i.quantity for i in inventories] == [4]


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


@pytest.fixture(params=[_callable_class, _instance_method])
def flavor_with_invariants(request):
    example, place = request.param()
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example, place


def test_an_order_without_a_payment_method_is_not_confirmed(flavor_with_invariants):
    example, place = flavor_with_invariants
    order = example.Order(
        customer_id="c-1", items=[example.OrderItem(product_id="P", quantity=1)]
    )

    with pytest.raises(ValidationError) as exc:
        place(order, _stock(example, 4))

    assert exc.value.messages == {
        "_service": ["Order must have a valid payment method"]
    }
    assert order.status == example.OrderStatus.PENDING.value


@pytest.fixture
def handler_example():
    example = load_example("guides/domain-behavior/domain-services/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _store_order(example, stock):
    example.domain.repository_for(example.Inventory).add(
        example.Inventory(product_id="P", quantity=stock)
    )
    order = example.Order(
        customer_id="c-1",
        payment_id="p-1",
        items=[example.OrderItem(product_id="P", quantity=3)],
    )
    example.domain.repository_for(example.Order).add(order)
    return order


def test_the_handler_confirms_the_order_and_saves_only_the_order(
    handler_example, monkeypatch
):
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")
    in_memory = pytest.importorskip(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter"
    )
    example = handler_example
    domain = example.domain
    order = _store_order(example, stock=4)

    exporter = in_memory.InMemorySpanExporter()
    provider = sdk_trace.TracerProvider()
    provider.add_span_processor(export.SimpleSpanProcessor(exporter))
    monkeypatch.setattr(domain, "_otel_tracer_provider", provider, raising=False)
    monkeypatch.setattr(domain, "_otel_init_attempted", True)
    domain.process(example.PlaceOrder(order_id=order.id))

    stored = domain.repository_for(example.Order).get(order.id)
    assert stored.status == example.OrderStatus.CONFIRMED.value
    assert domain.repository_for(example.Inventory).get("P").quantity == 4
    # A save of an unchanged Inventory writes nothing, so count the
    # repository.add calls to catch a handler that saves one anyway.
    saved = [
        span.attributes["protean.aggregate.type"]
        for span in exporter.get_finished_spans()
        if span.name == "protean.repository.add"
        and span.attributes["protean.aggregate.type"] != "MemoryMessage"
    ]
    assert saved == ["Order"]


def test_the_handler_leaves_an_out_of_stock_order_pending(handler_example):
    example = handler_example
    order = _store_order(example, stock=2)

    with pytest.raises(ValidationError) as exc:
        example.domain.process(example.PlaceOrder(order_id=order.id))

    assert exc.value.messages == {"_service": ["Product is out of stock"]}
    stored = example.domain.repository_for(example.Order).get(order.id)
    assert stored.status == example.OrderStatus.PENDING.value

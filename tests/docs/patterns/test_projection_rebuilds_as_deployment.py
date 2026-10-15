"""Run the examples on ``docs/patterns/projection-rebuilds-as-deployment.md``."""

import pytest
from fastapi.testclient import TestClient

from protean import Engine
from protean.utils import fqn
from protean.utils.dlq import failed_positions_stream
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

ORDERS = [
    ("Ada", 100.0, 8.0, 5.0),
    ("Grace", 40.0, 3.2, 0.0),
]


def _in_context(module):
    with module.domain.domain_context():
        yield module


@pytest.fixture
def before():
    yield from _in_context(
        load_example("patterns/projection-rebuilds-as-deployment/001.py")
    )


@pytest.fixture
def after():
    yield from _in_context(
        load_example("patterns/projection-rebuilds-as-deployment/002.py")
    )


@pytest.fixture
def blue_green():
    yield from _in_context(
        load_example("patterns/projection-rebuilds-as-deployment/003.py")
    )


def _place_orders(example):
    repo = example.domain.repository_for(example.Order)
    ids = []
    for name, subtotal, tax, shipping in ORDERS:
        order = example.Order(
            customer_name=name, subtotal=subtotal, tax=tax, shipping=shipping
        )
        order.place()
        repo.add(order)
        ids.append(order.id)
    Engine(example.domain, test_mode=True).run()
    return ids


def _rows(example, projection_cls):
    view = example.domain.view_for(projection_cls)
    return sorted(
        (row.to_dict() for row in view.query.all().items),
        key=lambda row: row["customer_name"],
    )


def test_original_projection_holds_only_the_total(before):
    _place_orders(before)

    rows = _rows(before, before.OrderSummary)
    assert [(r["customer_name"], r["total"]) for r in rows] == [
        ("Ada", 113.0),
        ("Grace", 43.2),
    ]
    assert "subtotal" not in rows[0]


def test_rebuild_reproduces_the_rows_with_the_new_fields(after, capsys):
    _place_orders(after)
    built_live = _rows(after, after.OrderSummary)
    assert [
        (r["customer_name"], r["subtotal"], r["tax"], r["shipping"], r["total"])
        for r in built_live
    ] == [
        ("Ada", 100.0, 8.0, 5.0, 113.0),
        ("Grace", 40.0, 3.2, 0.0, 43.2),
    ]

    result = after.rebuild_order_summary()

    assert result.success
    assert result.events_dispatched == 2
    assert result.events_skipped == 0
    assert _rows(after, after.OrderSummary) == built_live
    assert "Events dispatched: 2" in capsys.readouterr().out


def test_rebuild_twice_gives_the_same_rows(after):
    _place_orders(after)
    after.rebuild_order_summary()
    first = _rows(after, after.OrderSummary)
    assert len(first) == 2

    after.rebuild_order_summary()

    assert _rows(after, after.OrderSummary) == first


def test_v2_is_built_beside_the_live_projection(blue_green):
    ids = _place_orders(blue_green)
    repo = blue_green.domain.repository_for(blue_green.Order)
    shipped = repo.get(ids[0])
    shipped.ship()
    repo.add(shipped)
    Engine(blue_green.domain, test_mode=True).run()
    live = _rows(blue_green, blue_green.OrderSummary)
    assert len(live) == 2

    result = blue_green.rebuild_v2()

    assert result.projection_name == "OrderSummaryV2"
    assert result.success
    assert result.events_dispatched == 3
    assert _rows(blue_green, blue_green.OrderSummary) == live
    v2 = _rows(blue_green, blue_green.OrderSummaryV2)
    assert [(r["customer_name"], r["status"], r["total"]) for r in v2] == [
        ("Ada", "shipped", 113.0),
        ("Grace", "placed", 43.2),
    ]
    assert v2[0]["tax"] == 8.0
    assert blue_green.OrderSummaryV2.meta_.schema_name == "order_summary_v2"
    assert blue_green.OrderSummary.meta_.schema_name == "order_summary"


def test_engine_after_a_rebuild_replays_into_v2_without_failing(blue_green):
    repo = blue_green.domain.repository_for(blue_green.Order)
    order = blue_green.Order(customer_name="Ada", subtotal=100.0, tax=8.0)
    order.place()
    repo.add(order)
    blue_green.rebuild_v2()
    order = repo.get(order.id)
    order.ship()
    repo.add(order)

    engine = Engine(blue_green.domain, test_mode=True)
    engine.run()

    assert engine.exit_code == 0
    failed = failed_positions_stream(
        fqn(blue_green.OrderSummaryV2Projector),
        blue_green.Order.meta_.stream_category,
    )
    assert blue_green.domain.event_store.store.read(failed) == []
    v2 = _rows(blue_green, blue_green.OrderSummaryV2)
    assert [(r["customer_name"], r["status"], r["total"]) for r in v2] == [
        ("Ada", "shipped", 108.0),
    ]


def test_switched_endpoint_reads_the_new_projection(blue_green):
    ids = _place_orders(blue_green)

    response = TestClient(blue_green.app).get(f"/orders/{ids[1]}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["customer_name"] == "Grace"
    assert body["subtotal"] == 40.0


def test_rebuild_result_reports_volume_and_infrastructure(blue_green, capsys):
    _place_orders(blue_green)

    result = blue_green.rebuild_and_report()

    assert result.projection_name == "OrderSummaryV2"
    assert result.projectors_processed == 1
    assert result.categories_processed == 1
    assert result.events_dispatched == 2
    assert result.errors == []
    out = capsys.readouterr().out
    assert "Projection:   OrderSummaryV2" in out
    assert "ERROR" not in out

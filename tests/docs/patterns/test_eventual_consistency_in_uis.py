"""Run the examples on ``docs/patterns/eventual-consistency-in-uis.md``."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean import Engine, handle
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String
from tests.docs.support import (
    domain_from_config,
    load_example,
    outcome_counts,
    run_example_tests,
)

pytestmark = pytest.mark.no_test_domain

ALICE = {
    "customer_id": "cust-123",
    "customer_name": "Alice",
    "total": 99.99,
    "item_count": 3,
}


@pytest.fixture
def example():
    module = load_example("patterns/eventual-consistency-in-uis/001.py")
    with module.domain.domain_context():
        yield module


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_projection_lags_the_write_until_the_engine_runs(example):
    assert example.domain.config["event_processing"] == "async"
    order = example.OrderService().place_order(ALICE)

    view = example.domain.view_for(example.OrderSummary)
    with pytest.raises(ObjectNotFoundError):
        view.get(order.order_id)

    Engine(example.domain, test_mode=True).run()

    summary = view.get(order.order_id)
    assert (summary.customer_name, summary.status, summary.total) == (
        "Alice",
        "placed",
        99.99,
    )


def test_optimistic_endpoint_returns_the_write_side_state(example):
    response = _client(example.optimistic).post("/orders", json=ALICE)

    assert response.status_code == 201
    body = response.json()
    assert (body["customer_name"], body["total"], body["status"]) == (
        "Alice",
        99.99,
        "placed",
    )
    assert body["placed_at"]


def test_write_side_result_is_ready_before_the_projection(example):
    client = _client(example.write_side)

    created = client.post("/orders", json=ALICE)
    assert created.status_code == 201
    order_id = created.json()["order_id"]
    assert created.json()["item_count"] == 3
    assert client.get(f"/orders/{order_id}").status_code == 404

    Engine(example.domain, test_mode=True).run()

    read = client.get(f"/orders/{order_id}")
    assert read.status_code == 200
    assert read.json()["status"] == "placed"


def test_version_polling_answers_202_until_the_projection_catches_up(example):
    client = _client(example.polling)

    created = client.post("/orders", json=ALICE)
    assert created.status_code == 201
    order_id, version = created.json()["order_id"], created.json()["version"]
    assert version == 0
    assert client.get(f"/orders/{order_id}?min_version=0").status_code == 202

    Engine(example.domain, test_mode=True).run()
    assert client.get(f"/orders/{order_id}?min_version=0").status_code == 200

    confirmed = client.post(f"/orders/{order_id}/confirm").json()
    assert confirmed["version"] == 1
    stale = client.get(f"/orders/{order_id}?min_version=1")
    assert (stale.status_code, stale.json()) == (202, {"status": "pending"})

    Engine(example.domain, test_mode=True).run()
    caught_up = client.get(f"/orders/{order_id}?min_version=1")
    assert caught_up.status_code == 200
    assert (caught_up.json()["status"], caught_up.json()["version"]) == (
        "confirmed",
        1,
    )


def test_unknown_order_is_404_without_min_version(example):
    assert _client(example.polling).get("/orders/missing").status_code == 404


def test_sync_processing_test_passes():
    result = run_example_tests("patterns/eventual-consistency-in-uis/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 1}


SYNC = "patterns/eventual-consistency-in-uis/sync.toml"


def _handled_after_commit(domain):
    """Raise an event inside a unit of work and return the ids the handler saw by its exit."""
    handled = []

    @domain.aggregate
    class Order:
        status: String(default="PLACED")

        def place(self):
            self.raise_(OrderPlaced(order_id=self.id))

    @domain.event(part_of=Order)
    class OrderPlaced:
        order_id: Identifier(required=True)

    @domain.event_handler(part_of=Order)
    class OrderPlacedHandler:
        @handle(OrderPlaced)
        def record(self, event):
            handled.append(event.order_id)

    domain.init(traverse=False)
    with domain.domain_context():
        order = Order()
        order.place()
        with UnitOfWork():
            domain.repository_for(Order).add(order)
        return handled, order.id


def test_sync_configuration_runs_handlers_when_the_unit_of_work_exits(tmp_path):
    domain = domain_from_config(SYNC, tmp_path)

    assert domain.config["event_processing"] == "sync"
    # The block sets events only, so commands stay asynchronous.
    assert domain.config["command_processing"] == "async"
    handled, order_id = _handled_after_commit(domain)
    assert handled == [order_id]


def test_without_the_sync_setting_handlers_wait_for_the_engine(tmp_path):
    domain = domain_from_config(SYNC, tmp_path, text="")

    assert domain.config["event_processing"] == "async"
    handled, _ = _handled_after_commit(domain)
    assert handled == []

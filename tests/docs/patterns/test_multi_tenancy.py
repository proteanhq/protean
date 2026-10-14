"""Run the examples on ``docs/patterns/multi-tenancy.md``."""

import asyncio
import re
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from protean.exceptions import ObjectNotFoundError
from protean.server import Engine
from protean.utils.eventing import Message
from protean.utils.globals import g
from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain

TENANTS = ["acme", "globex"]


def other(tenant):
    return next(t for t in TENANTS if t != tenant)


@pytest.fixture
def example():
    module = load_example("patterns/multi-tenancy/001.py")
    with module.domain.domain_context():
        yield module


def place(example, tenant, **kwargs):
    with example.domain.domain_context(tenant_id=tenant):
        order = example.Order(tenant_id=tenant, customer_id="cust-1", **kwargs)
        order.place()
    return order


@pytest.mark.parametrize("tenant", TENANTS)
def test_event_enricher_records_the_tenant_in_extensions(example, tenant):
    order = place(example, tenant, total=10.0)

    event = order._events[0]
    assert event._metadata.extensions["tenant_id"] == tenant
    assert "tenant_id" not in event.payload


def test_event_enricher_records_none_without_a_tenant(example):
    order = example.Order(tenant_id="t", customer_id="cust-1")
    order.place()

    assert order.status == "placed"
    assert order._events[0]._metadata.extensions["tenant_id"] is None


@pytest.mark.parametrize("tenant", TENANTS)
def test_command_enricher_reads_the_tenant_from_g(example, tenant):
    with example.domain.domain_context(tenant_id=tenant):
        assert example.enrich_command_with_tenant(None) == {"tenant_id": tenant}

    assert example.enrich_command_with_tenant(None) == {"tenant_id": None}


@pytest.fixture
def seeded(example):
    repo = example.domain.repository_for(example.Order)
    orders = {}
    for tenant in TENANTS:
        placed = [place(example, tenant) for _ in range(2)]
        draft = example.Order(tenant_id=tenant, customer_id="cust-2")
        for order in [*placed, draft]:
            repo.add(order)
        orders[tenant] = {"placed": placed, "draft": draft}
    return orders


@pytest.mark.parametrize("tenant", TENANTS)
def test_listing_returns_only_the_tenants_placed_orders(example, seeded, tenant):
    g.tenant_id = tenant

    found = {order.order_id for order in example.placed_orders()}

    own = {order.order_id for order in seeded[tenant]["placed"]}
    foreign = {order.order_id for order in seeded[other(tenant)]["placed"]}
    assert own
    assert found == own
    assert not found & foreign
    assert seeded[tenant]["draft"].order_id not in found


@pytest.mark.parametrize("tenant", TENANTS)
def test_get_order_finds_own_order_and_not_another_tenants(example, seeded, tenant):
    g.tenant_id = tenant
    own = seeded[tenant]["placed"][0]
    foreign = seeded[other(tenant)]["placed"][0]

    assert example.get_order(own.order_id).tenant_id == tenant
    with pytest.raises(ObjectNotFoundError):
        example.get_order(foreign.order_id)


@pytest.mark.parametrize("tenant", TENANTS)
def test_tenant_query_is_scoped_and_chainable(example, seeded, tenant):
    g.tenant_id = tenant

    everything = example.tenant_query(example.Order).all().items
    placed = example.tenant_query(example.Order).filter(status="placed").all().items

    assert len(everything) == 3
    assert {order.tenant_id for order in everything} == {tenant}
    assert {order.order_id for order in placed} == {
        order.order_id for order in seeded[tenant]["placed"]
    }


@pytest.mark.parametrize("tenant", TENANTS)
def test_middleware_sets_the_tenant_for_the_request(example, tenant):
    client = TestClient(example.app)

    response = client.post(
        "/orders",
        params={"customer_id": "cust-1", "product_id": "sku-1"},
        headers={"Authorization": f"Bearer {tenant}:alice"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant
    stored = example.domain.repository_for(example.Order).get(body["order_id"])
    assert stored.tenant_id == tenant


def test_handler_is_on_the_order_stream(example):
    assert (
        example.InventoryEventHandler.meta_.stream_category
        == example.Order.meta_.stream_category
    )


@pytest.fixture
def stock(example):
    repo = example.domain.repository_for(example.Inventory)
    for tenant in TENANTS:
        repo.add(example.Inventory(tenant_id=tenant, product_id="sku-1", available=10))
    return repo


def handle(example, message):
    engine = Engine(domain=example.domain, test_mode=True)
    return asyncio.run(engine.handle_message(example.InventoryEventHandler, message))


@pytest.mark.parametrize("tenant", TENANTS)
def test_handler_reserves_stock_only_for_the_events_tenant(example, stock, tenant):
    order = place(example, tenant, product_id="sku-1", quantity=3)

    assert handle(example, Message.from_domain_object(order._events[0])) is True

    own = stock.find_by(product_id="sku-1", tenant_id=tenant)
    foreign = stock.find_by(product_id="sku-1", tenant_id=other(tenant))
    assert (own.reserved, own.available) == (3, 7)
    assert (foreign.reserved, foreign.available) == (0, 10)


def test_handler_without_tenant_in_extensions_reserves_nothing(example, stock):
    order = example.Order(
        tenant_id="acme", customer_id="cust-1", product_id="sku-1", quantity=3
    )
    order.place()

    assert handle(example, Message.from_domain_object(order._events[0])) is False

    for tenant in TENANTS:
        assert stock.find_by(product_id="sku-1", tenant_id=tenant).reserved == 0


def test_page_tests_pass_under_pytest():
    # Run the tests the page shows the way a reader would: as a pytest module.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(DOCS_SRC / "patterns/multi-tenancy/001.py"),
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            "--import-mode=importlib",
            "-W",
            "error::pytest.PytestCollectionWarning",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b3 passed\b", result.stdout), result.stdout

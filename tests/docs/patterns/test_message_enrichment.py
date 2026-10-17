"""Run the examples on ``docs/patterns/message-enrichment.md``.

The functional-registration section splits its code into ``enrichers.py`` and
``domain.py``, so that example is the ``saasapp`` package. Its folder goes on
``sys.path`` so ``domain.py`` imports the enrichers by the package name, as it
would in the reader's project.
"""

import asyncio
import sys
from uuid import UUID

import pytest

from protean.server import Engine
from protean.utils.eventing import TraceParent
from protean.utils.globals import g
from tests.docs.support import DOCS_SRC, load_example

_PACKAGE_DIR = str(DOCS_SRC / "patterns" / "message-enrichment")
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

import saasapp.domain
import saasapp.enrichers

pytestmark = pytest.mark.no_test_domain


def _context(example):
    example.domain.init(traverse=False)
    return example, example.domain.domain_context()


def test_the_page_tests_pass_against_the_order_aggregate():
    example, context = _context(load_example("patterns/message-enrichment/001.py"))
    with context:
        tests = example.TestOrderPlacement()
        tests.test_business_logic_without_enrichment(test_domain=example.domain)
        tests.test_enrichment_with_tenant_context(test_domain=example.domain)


def test_without_context_the_enrichers_write_none_values():
    example, context = _context(load_example("patterns/message-enrichment/001.py"))
    with context:
        order = example.Order(customer_id="cust-1")
        order.add_item(product_id="prod-1", quantity=1, price=5.0)
        order.place()

    event = order._events[0]
    assert event._metadata.extensions == {
        "tenant_id": None,
        "user_id": None,
        "request_id": None,
    }
    assert event.payload == {
        "order_id": order.order_id,
        "customer_id": "cust-1",
        "items": [
            {
                "id": order.items[0].id,
                "product_id": "prod-1",
                "quantity": 1,
                "price": 5.0,
            }
        ],
        "total": 0.0,
    }


def test_the_command_enrichers_add_tenant_user_and_request():
    example, context = _context(load_example("patterns/message-enrichment/001.py"))
    with context:
        g.tenant_id = "acme-corp"
        g.user_id = "user-42"
        g.request_id = "req-abc-123"
        example.domain.process(example.PlaceOrder(order_id="ord-1"))
        [stored] = [
            message
            for message in example.domain.event_store.store.read("$all")
            if message.metadata.domain.kind == "COMMAND"
        ]

    assert stored.metadata.extensions == {
        "tenant_id": "acme-corp",
        "user_id": "user-42",
        "request_id": "req-abc-123",
    }


def test_an_order_with_no_items_cannot_be_placed():
    example, context = _context(load_example("patterns/message-enrichment/001.py"))
    with context, pytest.raises(example.ValidationError):
        example.Order(customer_id="cust-1").place()


def _call_middleware(headers):
    example = load_example("patterns/message-enrichment/002.py")
    seen = {}

    async def app(scope, receive, send):
        seen.update(tenant_id=g.tenant_id, user_id=g.user_id, request_id=g.request_id)

    _, context = _context(load_example("patterns/message-enrichment/001.py"))
    with context:
        middleware = example.TenantContextMiddleware(app)
        asyncio.run(middleware({"type": "http", "headers": headers}, None, None))
    return seen


def test_the_middleware_stores_tenant_user_and_request_in_g():
    seen = _call_middleware(
        [(b"authorization", b"acme:user-42"), (b"x-request-id", b"req-1")]
    )

    assert seen == {"tenant_id": "acme", "user_id": "user-42", "request_id": "req-1"}


def test_the_middleware_makes_up_a_request_id_when_the_header_is_missing():
    seen = _call_middleware([(b"authorization", b"acme:user-42")])

    assert UUID(seen["request_id"]).version == 4


@pytest.fixture
def placed_order():
    example, context = _context(load_example("patterns/message-enrichment/003.py"))
    with context:
        g.tenant_id = "acme"
        g.user_id = "user-42"
        g.request_id = "req-1"
        example.domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="prod-1")
        )
        order = example.Order(items=[{"product_id": "prod-1", "quantity": 2}])
        order.place()
        example.domain.repository_for(example.Order).add(order)
        [message] = example.domain.event_store.store.read(
            f"saasapp::order-{order.order_id}"
        )
        yield example, order, message


def _handle(example, handler_cls, message):
    engine = Engine(domain=example.domain, test_mode=True)
    assert asyncio.run(engine.handle_message(handler_cls, message)) is True


def test_the_stored_event_carries_the_enriched_extensions(placed_order):
    _, _, message = placed_order

    assert message.metadata.extensions == {
        "tenant_id": "acme",
        "user_id": "user-42",
        "request_id": "req-1",
    }
    assert "tenant_id" not in message.data


def test_the_inventory_handler_reserves_stock_for_the_tenant(placed_order):
    example, order, message = placed_order

    _handle(example, example.InventoryEventHandler, message)

    inventory = example.domain.repository_for(example.Inventory).get("prod-1")
    assert inventory.reservations == [
        {"order_id": order.order_id, "quantity": 2, "tenant_id": "acme"}
    ]
    assert example.InventoryEventHandler.meta_.stream_category == "saasapp::order"


def test_the_audit_projector_records_who_placed_the_order(placed_order):
    example, order, message = placed_order

    _handle(example, example.OrderAuditProjector, message)

    audit = example.domain.repository_for(example.OrderAuditProjection).get(
        order.order_id
    )
    assert (audit.action, audit.performed_by, audit.request_id, audit.tenant_id) == (
        "placed",
        "user-42",
        "req-1",
        "acme",
    )
    assert audit.timestamp == message.metadata.headers.time


def test_feature_flags_go_only_on_billing_events():
    example, context = _context(load_example("patterns/message-enrichment/004.py"))
    with context:
        invoice = example.Invoice(amount=10.0)
        invoice.generate()
        invoice.remind()

    generated, reminder = (e._metadata.extensions for e in invoice._events)
    assert generated["feature_flags"] == {"new_pricing_model": True, "tax_v2": False}
    assert "feature_flags" not in reminder


def test_the_tracing_enricher_copies_the_traceparent_ids():
    example, context = _context(load_example("patterns/message-enrichment/004.py"))
    with context:
        g.traceparent = TraceParent.build(
            "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        )
        invoice = example.Invoice(amount=10.0)
        invoice.remind()

    extensions = invoice._events[0]._metadata.extensions
    assert extensions == {
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "span_id": "b7ad6b7169203331",
    }


def test_the_tracing_enricher_writes_none_without_a_traceparent():
    example, context = _context(load_example("patterns/message-enrichment/004.py"))
    with context:
        invoice = example.Invoice(amount=10.0)
        invoice.remind()

    assert invoice._events[0]._metadata.extensions == {
        "trace_id": None,
        "span_id": None,
    }


def test_the_domain_registers_the_enrichers_imported_from_enrichers_py():
    domain = saasapp.domain.domain

    assert domain._event_enrichers == [
        saasapp.enrichers.tenant_enricher,
        saasapp.enrichers.audit_enricher,
    ]
    assert domain._command_enrichers == [saasapp.enrichers.tenant_command_enricher]


def test_functionally_registered_enrichers_reach_events_and_commands():
    example, context = _context(saasapp.domain)
    with context:
        g.tenant_id = "acme"
        g.user_id = "user-42"
        example.domain.process(example.CancelOrder(order_id="ord-1"))
        order = example.Order()
        order.cancel()

    assert example.command_tenants == [{"tenant_id": "acme"}]
    assert order._events[0]._metadata.extensions == {
        "tenant_id": "acme",
        "user_id": "user-42",
        "request_id": None,
    }

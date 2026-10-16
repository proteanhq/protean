# --8<-- [start:level3]
import pytest
from ecommerce.domain import Inventory, Order, OrderDashboard, PlaceOrder, domain

from protean.exceptions import ObjectNotFoundError
from protean.server.engine import Engine


@pytest.fixture
def async_events():
    """Process events asynchronously for the length of one test."""
    domain.config["event_processing"] = "async"
    yield
    domain.config["event_processing"] = "sync"


@pytest.mark.usefixtures("async_events")
class TestOrderFlowAsync:
    """Level 3: Test with the real async Engine in test mode."""

    def test_full_async_flow(self):
        """Command -> handler -> event -> engine processes -> projection updated."""
        domain.repository_for(Inventory).add(
            Inventory(product_id="prod-1", available_quantity=10)
        )

        # Submit the command (sync command processing, async event processing)
        domain.process(
            PlaceOrder(
                order_id="ord-async-001",
                customer_id="cust-123",
                product_id="prod-1",
                total=75.00,
            )
        )

        # Nothing has processed the event yet
        view = domain.view_for(OrderDashboard)
        with pytest.raises(ObjectNotFoundError):
            view.get("ord-async-001")

        # Run the engine in test mode until every subscription is idle
        engine = Engine(domain, test_mode=True)
        engine.run()

        # After engine.run() completes, all pending events have been processed
        dashboard = view.get("ord-async-001")

        assert dashboard.status == "placed"
        assert dashboard.total == 75.00

        # Also verify the aggregate was persisted through the chain
        order = domain.repository_for(Order).get("ord-async-001")
        assert order.status == "placed"


# --8<-- [end:level3]


# --8<-- [start:priority]
from protean.utils.processing import Priority


@pytest.fixture
def priority_lanes(async_events):
    """Route events through the outbox to broker streams, with priority lanes."""
    server = domain.config["server"]
    saved = dict(server)
    server["default_subscription_type"] = "stream"
    server["priority_lanes"] = {"enabled": True, "threshold": Priority.NORMAL}
    yield
    server.clear()
    server.update(saved)


@pytest.mark.usefixtures("priority_lanes")
class TestPriorityLanes:
    """Level 3: Verify priority-based event routing."""

    def test_low_priority_events_route_to_backfill_lane(self):
        """Events below the threshold are routed to the backfill stream."""
        domain.repository_for(Inventory).add(
            Inventory(product_id="prod-1", available_quantity=10)
        )

        domain.process(
            PlaceOrder(
                order_id="ord-pri-001",
                customer_id="cust-456",
                product_id="prod-1",
                total=50.0,
            ),
            priority=Priority.LOW,
        )

        # In test mode, backfill events are still processed (the primary
        # stream is empty, so the backfill stream is polled).
        engine = Engine(domain, test_mode=True)
        engine.run()

        broker = domain.brokers["default"]
        backfill = broker.read("ecommerce::order:backfill", "check", 10)
        primary = broker.read("ecommerce::order", "check", 10)
        assert [message["data"]["order_id"] for _, message in backfill] == [
            "ord-pri-001"
        ]
        assert primary == []

        dashboard = domain.view_for(OrderDashboard).get("ord-pri-001")
        assert dashboard.status == "placed"


# --8<-- [end:priority]

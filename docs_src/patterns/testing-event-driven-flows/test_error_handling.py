# --8<-- [start:errors]
from typing import ClassVar

import pytest
from ecommerce.domain import Inventory, OrderPlaced, PlaceOrder, domain

from protean import handle
from protean.server.engine import Engine


@domain.event_handler(part_of=Inventory, stream_category="ecommerce::order")
class FailingInventoryHandler:
    """A handler that deliberately fails, for testing error classification."""

    errors_captured: ClassVar[list[dict]] = []

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        raise ConnectionError("Database temporarily unavailable")

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        cls.errors_captured.append(
            {
                "exception": exc,
                "message_type": message.metadata.headers.type,
            }
        )


class TestErrorHandling:
    """Level 3: Verify error classification and handle_error behavior."""

    @pytest.fixture(autouse=True)
    def async_events(self):
        domain.config["event_processing"] = "async"
        FailingInventoryHandler.errors_captured.clear()
        yield
        domain.config["event_processing"] = "sync"

    def test_handle_error_receives_exception(self):
        """Verify that handle_error is called when a handler raises."""
        domain.repository_for(Inventory).add(
            Inventory(product_id="prod-1", available_quantity=10)
        )
        domain.process(
            PlaceOrder(
                order_id="ord-err-001",
                customer_id="cust-123",
                product_id="prod-1",
                total=50.0,
            )
        )

        engine = Engine(domain, test_mode=True)
        engine.run()

        # The handler failed, but handle_error captured the exception
        assert len(FailingInventoryHandler.errors_captured) > 0
        captured = FailingInventoryHandler.errors_captured[0]
        assert isinstance(captured["exception"], ConnectionError)
        assert "temporarily unavailable" in str(captured["exception"])
        assert captured["message_type"] == "Ecommerce.OrderPlaced.v1"


# --8<-- [end:errors]

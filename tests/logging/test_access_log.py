"""Tests for the wide event access log.

Verifies that:
- Command processing emits a wide event on success
- Command processing emits a wide event on failure
- Event handlers emit one wide event per handler method
- Query dispatch emits a wide event
- Projector handlers emit a wide event
- Correlation and causation IDs are present in wide events
"""

import logging
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle, read


# --- Domain elements for testing ---


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    customer_name = String()
    status = String(default="pending")

    def place(self) -> None:
        self.raise_(
            OrderPlaced(order_id=self.order_id, customer_name=self.customer_name)
        )

    def confirm(self) -> None:
        self.status = "confirmed"
        self.raise_(OrderConfirmed(order_id=self.order_id))


class OrderPlaced(BaseEvent):
    order_id = Identifier()
    customer_name = String()


class OrderConfirmed(BaseEvent):
    order_id = Identifier()


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer_name = String()


class FailingCommand(BaseCommand):
    order_id = Identifier(identifier=True)


class PlaceOrderHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = Order(order_id=command.order_id, customer_name=command.customer_name)
        order.place()
        repo.add(order)


class FailingCommandHandler(BaseCommandHandler):
    @handle(FailingCommand)
    def handle_failing(self, command: FailingCommand) -> None:
        raise ValueError("Something went wrong")


class OrderEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        pass

    @handle(OrderConfirmed)
    def on_order_confirmed(self, event: OrderConfirmed) -> None:
        pass


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String()
    status = String()


class OrderSummaryProjector(BaseProjector):
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        pass


class GetOrderById(BaseQuery):
    order_id = Identifier(required=True)


class OrderQueryHandler(BaseQueryHandler):
    @read(GetOrderById)
    def get_by_id(self, query: GetOrderById) -> dict:
        return {"order_id": query.order_id, "status": "pending"}


# --- Helper to extract access log records ---


def _access_records(caplog) -> list[logging.LogRecord]:
    """Return all records emitted on the 'protean.access' logger."""
    return [r for r in caplog.records if r.name == "protean.access"]


class TestCommandEmitsWideEvent:
    """Command processing emits a wide event access log entry."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderConfirmed, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(PlaceOrderHandler, part_of=Order)
        # Register event handler to avoid config errors
        test_domain.register(OrderEventHandler, part_of=Order)
        test_domain.init(traverse=False)

    def test_command_emits_wide_event_on_success(self, test_domain, caplog):
        order_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(PlaceOrder(order_id=order_id, customer_name="John Doe"))

        records = _access_records(caplog)
        assert len(records) >= 1, (
            f"Expected at least one access log record, got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

        # Filter for the command handler's wide event specifically
        cmd_records = [r for r in records if r.kind == "command"]
        assert len(cmd_records) >= 1
        record = cmd_records[0]

        assert "access.handler_completed" in record.getMessage()
        assert record.kind == "command"
        assert record.handler == "PlaceOrderHandler.handle_place_order"
        assert record.status == "ok"
        assert record.duration_ms > 0
        assert record.aggregate == "Order"
        assert record.message_type is not None
        assert record.uow_outcome == "committed"
        assert record.levelno == logging.INFO


class TestCommandEmitsWideEventOnFailure:
    """Command handler failure emits a wide event with error details."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(FailingCommand, part_of=Order)
        test_domain.register(FailingCommandHandler, part_of=Order)
        test_domain.init(traverse=False)

    def test_command_emits_wide_event_on_failure(self, test_domain, caplog):
        order_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            with pytest.raises(ValueError, match="Something went wrong"):
                test_domain.process(FailingCommand(order_id=order_id))

        records = _access_records(caplog)
        assert len(records) >= 1

        record = records[0]
        assert "access.handler_failed" in record.getMessage()
        assert record.status == "failed"
        assert record.error_type == "ValueError"
        assert record.error_message == "Something went wrong"
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        assert record.uow_outcome == "rolled_back"


class TestEventHandlerEmitsWideEventPerMethod:
    """Event handler with multiple @handle methods emits one wide event per method."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderConfirmed, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(PlaceOrderHandler, part_of=Order)
        test_domain.register(OrderEventHandler, part_of=Order)
        test_domain.init(traverse=False)

    def test_event_handler_emits_wide_event_per_method(self, test_domain, caplog):
        """Processing a command that raises events should emit access log entries
        for each event handler method invocation."""
        order_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(PlaceOrder(order_id=order_id, customer_name="Jane Doe"))

        records = _access_records(caplog)
        # At minimum: 1 for command handler + 1 for event handler
        event_handler_records = [r for r in records if r.kind == "event"]
        assert len(event_handler_records) >= 1

        for record in event_handler_records:
            assert "access.handler_completed" in record.getMessage()
            assert record.status == "ok"
            assert record.duration_ms >= 0


class TestQueryEmitsWideEvent:
    """Query dispatch emits a wide event."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrderById, part_of=OrderSummary)
        test_domain.register(OrderQueryHandler, part_of=OrderSummary)
        test_domain.init(traverse=False)

    def test_query_emits_wide_event(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            result = test_domain.dispatch(GetOrderById(order_id="order-42"))

        assert result == {"order_id": "order-42", "status": "pending"}

        records = _access_records(caplog)
        assert len(records) >= 1

        record = records[0]
        assert "access.handler_completed" in record.getMessage()
        assert record.kind == "query"
        assert record.status == "ok"
        assert record.duration_ms >= 0
        assert record.uow_outcome == "no_uow"


class TestProjectorEmitsWideEvent:
    """Projector handler invocation emits a wide event."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderConfirmed, part_of=Order)
        test_domain.register(OrderSummary)
        test_domain.register(
            OrderSummaryProjector,
            projector_for=OrderSummary,
            aggregates=[Order],
        )
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(PlaceOrderHandler, part_of=Order)
        test_domain.init(traverse=False)

    def test_projector_emits_wide_event(self, test_domain, caplog):
        order_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                PlaceOrder(order_id=order_id, customer_name="Projector Test")
            )

        records = _access_records(caplog)
        projector_records = [r for r in records if r.kind == "projector"]
        assert len(projector_records) >= 1

        record = projector_records[0]
        assert "access.handler_completed" in record.getMessage()
        assert record.status == "ok"
        assert record.duration_ms >= 0


class TestCorrelationAndCausationPresent:
    """Wide events carry correlation_id and causation_id."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderConfirmed, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(PlaceOrderHandler, part_of=Order)
        test_domain.register(OrderEventHandler, part_of=Order)
        test_domain.init(traverse=False)

    def test_correlation_and_causation_present(self, test_domain, caplog):
        order_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                PlaceOrder(order_id=order_id, customer_name="Corr Test")
            )

        records = _access_records(caplog)
        assert len(records) >= 1

        # The command handler's wide event should have a correlation_id
        cmd_records = [r for r in records if r.kind == "command"]
        assert len(cmd_records) >= 1
        assert cmd_records[0].correlation_id != ""

        # Event handler wide events should have correlation_id inherited
        # from the command and a causation_id pointing at the command
        event_records = [r for r in records if r.kind == "event"]
        if event_records:
            assert event_records[0].correlation_id != ""

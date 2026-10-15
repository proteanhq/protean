# --8<-- [start:errors]
from typing import ClassVar

import pytest

from protean import Domain, handle
from protean.fields import Identifier
from protean.integrations.pytest import DomainFixture
from protean.server.engine import Engine

failures = Domain(name="failures", config={"event_processing": "async"})


@failures.aggregate
class Shipment:
    order_id = Identifier(required=True)

    def dispatch(self):
        self.raise_(ShipmentDispatched(order_id=self.order_id))


@failures.event(part_of=Shipment)
class ShipmentDispatched:
    order_id = Identifier(required=True)


@failures.event_handler(part_of=Shipment)
class FailingShipmentHandler:
    """A handler that deliberately fails, for testing error classification."""

    errors_captured: ClassVar[list[dict]] = []

    @handle(ShipmentDispatched)
    def on_dispatched(self, event: ShipmentDispatched):
        raise ConnectionError("Database temporarily unavailable")

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        cls.errors_captured.append(
            {
                "exception": exc,
                "message_type": message.metadata.headers.type,
            }
        )


@pytest.fixture
def failures_ctx():
    fixture = DomainFixture(failures)
    fixture.setup()
    FailingShipmentHandler.errors_captured.clear()
    with fixture.domain_context():
        yield
    fixture.teardown()


@pytest.mark.usefixtures("failures_ctx")
class TestErrorHandling:
    """Level 3: Verify error classification and handle_error behavior."""

    def test_handle_error_receives_exception(self):
        """Verify that handle_error is called when a handler raises."""
        shipment = Shipment(order_id="ord-err-001")
        shipment.dispatch()
        failures.repository_for(Shipment).add(shipment)

        engine = Engine(failures, test_mode=True)
        engine.run()

        # The handler failed, but handle_error captured the exception
        assert len(FailingShipmentHandler.errors_captured) > 0
        captured = FailingShipmentHandler.errors_captured[0]
        assert isinstance(captured["exception"], ConnectionError)
        assert "temporarily unavailable" in str(captured["exception"])
        assert captured["message_type"] == "Failures.ShipmentDispatched.v1"


# --8<-- [end:errors]

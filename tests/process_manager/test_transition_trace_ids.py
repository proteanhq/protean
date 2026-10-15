"""A process manager transition takes its trace IDs from the message being handled."""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.fields import Identifier
from protean.utils.eventing import Message
from protean.utils.globals import g
from protean.utils.mixins import handle


class Shipment(BaseAggregate):
    shipment_id: Identifier()


class ShipmentBooked(BaseEvent):
    shipment_id: Identifier()


class ShipmentPM(BaseProcessManager):
    shipment_id: Identifier()

    @handle(ShipmentBooked, start=True, correlate="shipment_id")
    def on_booked(self, event: ShipmentBooked) -> None:
        self.shipment_id = event.shipment_id


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Shipment)
    test_domain.register(ShipmentBooked, part_of=Shipment)
    test_domain.register(ShipmentPM, stream_categories=["test::shipment"])
    test_domain.init(traverse=False)


def test_transition_inherits_trace_ids_of_message_in_context(test_domain):
    shipment_id = str(uuid4())
    booked = ShipmentBooked(shipment_id=shipment_id)
    domain = booked._metadata.domain.model_copy(
        update={"correlation_id": "corr-X", "causation_id": "cause-X"}
    )
    booked = ShipmentBooked(
        booked.payload, _metadata=booked._metadata.model_copy(update={"domain": domain})
    )
    in_context = Message.from_domain_object(booked)

    g.message_in_context = in_context
    try:
        ShipmentPM._handle(booked)
    finally:
        g.pop("message_in_context", None)

    stream = f"{ShipmentPM.meta_.stream_category}-{shipment_id}"
    messages = test_domain.event_store.store.read(stream)
    assert len(messages) == 1
    assert messages[0].metadata.domain.correlation_id == "corr-X"
    assert messages[0].metadata.domain.causation_id == in_context.metadata.headers.id

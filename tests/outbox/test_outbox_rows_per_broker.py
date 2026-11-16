"""The outbox rows of one published event, the internal row and one per
external broker, carry the same values in every column except
``target_broker``."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.utils.mixins import handle
from protean.utils.processing import processing_priority


class Shipment(BaseAggregate):
    client_id = Identifier()
    carrier = String()

    def dispatch(self) -> None:
        self.raise_(
            ShipmentDispatched(
                shipment_id=str(self.id),
                client_id=self.client_id,
                carrier=self.carrier,
            )
        )


class ShipmentDispatched(BaseEvent):
    shipment_id = Identifier(required=True)
    client_id = Identifier(required=True)
    carrier = String()


class ShipmentEventHandler(BaseEventHandler):
    @handle(ShipmentDispatched)
    def on_dispatched(self, event: ShipmentDispatched) -> None:
        pass


@pytest.fixture
def test_domain():
    domain = Domain(name="Test")
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"
    domain.config["outbox"]["external_brokers"] = ["ext1", "ext2"]
    domain.config["brokers"]["ext1"] = {"provider": "inline"}
    domain.config["brokers"]["ext2"] = {"provider": "inline"}

    domain.register(Shipment)
    domain.register(ShipmentDispatched, part_of=Shipment, published=True)
    domain.register(ShipmentEventHandler, part_of=Shipment, sequential_by="client_id")
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


def test_rows_differ_only_in_target_broker(test_domain):
    shipment = Shipment(client_id="client-7", carrier="DHL")
    shipment.dispatch()
    with processing_priority(5), UnitOfWork():
        test_domain.repository_for(Shipment).add(shipment)

    rows = test_domain._get_outbox_repo("default").find_unprocessed()
    assert sorted(row.target_broker for row in rows) == ["default", "ext1", "ext2"]

    shared = {
        (
            row.message_id,
            row.stream_name,
            row.type,
            row.priority,
            row.correlation_id,
            row.causation_id,
            row.sequence_number,
            row.partition_key,
            row.stream_category,
        )
        for row in rows
    }
    assert len(shared) == 1

    (
        message_id,
        stream_name,
        message_type,
        priority,
        _,
        _,
        sequence_number,
        partition_key,
        stream_category,
    ) = shared.pop()
    assert message_id
    assert stream_name == f"{Shipment.meta_.stream_category}-{shipment.id}"
    assert message_type == ShipmentDispatched.__type__
    assert priority == 5
    assert sequence_number == 0
    assert partition_key == "client-7"
    assert stream_category == Shipment.meta_.stream_category

    assert all(row.data == rows[0].data for row in rows)
    assert rows[0].data["carrier"] == "DHL"

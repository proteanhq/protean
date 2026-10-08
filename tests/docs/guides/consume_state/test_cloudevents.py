"""The examples on the CloudEvents guide behave as the page says."""

import pytest

from protean.utils.eventing import Message
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def orders():
    example = load_example("guides/consume-state/cloudevents/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def fulfilment():
    example = load_example("guides/consume-state/cloudevents/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def test_the_order_placed_event_serializes_to_the_shown_cloudevent(orders):
    ce = orders.cloud_event

    assert ce["specversion"] == "1.0"
    assert ce["id"] == "myapp::order-abc123-0.1"
    assert ce["type"] == "MyApp.OrderPlaced.v1"
    assert ce["source"] == "https://orders.example.com"
    assert ce["subject"] == "abc123"
    assert ce["datacontenttype"] == "application/json"
    assert ce["proteankind"] == "EVENT"
    assert ce["sequence"] == "0.1"
    assert ce["proteansequencetype"] == "DotNotation"
    assert ce["data"] == {
        "order_id": "abc123",
        "customer_id": "cust-456",
        "total": 99.99,
    }


def test_an_event_raised_outside_a_command_has_no_correlation_or_causation(orders):
    assert "proteancorrelationid" not in orders.cloud_event
    assert "proteancausationid" not in orders.cloud_event


def test_source_falls_back_to_the_domain_name_without_source_uri(orders):
    orders.domain.config["source_uri"] = None

    assert orders.Message.from_domain_object(orders.event).to_cloudevent()[
        "source"
    ] == ("urn:protean:myapp")


def test_consuming_maps_the_attributes_back_into_protean_metadata(orders):
    metadata = Message.from_cloudevent(orders.cloud_event_dict).metadata

    assert metadata.headers.id == "myapp::order-abc123-0.1"
    assert metadata.headers.type == "MyApp.OrderPlaced.v1"
    assert metadata.extensions["ce_source"] == "https://orders.example.com"
    assert metadata.extensions["ce_subject"] == "abc123"
    assert metadata.domain.kind == "EVENT"
    assert metadata.domain.sequence_id == "0.1"
    assert metadata.envelope.checksum == orders.cloud_event["proteanchecksum"]


def test_a_registered_type_reconstructs_the_domain_event(orders):
    event = orders.event

    assert isinstance(event, orders.OrderPlaced)
    assert event.order_id == "abc123"
    assert event.customer_id == "cust-456"
    assert event.total == 99.99


def test_round_tripping_keeps_data_and_id(orders):
    assert orders.restored.data == orders.original.data
    assert orders.restored.metadata.headers.id == "myapp::order-abc123-0.1"


def test_round_tripping_keeps_a_correlation_id(orders):
    # The page's event has no correlation ID, so give the message one.
    incoming = {**orders.cloud_event, "proteancorrelationid": "corr-1"}
    original = Message.from_cloudevent(incoming)

    restored = Message.from_cloudevent(original.to_cloudevent())

    assert original.metadata.domain.correlation_id == "corr-1"
    assert restored.metadata.domain.correlation_id == "corr-1"


@pytest.mark.parametrize(
    "attribute", ["specversion", "id", "type", "source"], ids=lambda a: a
)
def test_a_cloudevent_missing_a_required_attribute_is_rejected(orders, attribute):
    incoming = dict(orders.cloud_event)
    del incoming[attribute]

    with pytest.raises(ValueError, match=attribute):
        Message.from_cloudevent(incoming)


def test_a_cloudevent_with_another_specversion_is_rejected(orders):
    incoming = {**orders.cloud_event, "specversion": "0.3"}

    with pytest.raises(ValueError, match="0.3"):
        Message.from_cloudevent(incoming)


def test_the_subscriber_imports_an_external_order(fulfilment):
    payload = {
        "specversion": "1.0",
        "id": "evt-77",
        "type": "com.shop.order.created",
        "source": "https://shop.example.com",
        "subject": "orders/ord-9",
        "data": {"order_id": "ord-9"},
    }

    fulfilment.ExternalOrderSubscriber()(payload)

    imported = fulfilment.domain.repository_for(fulfilment.ImportedOrder).find_by(
        external_id="ord-9"
    )
    assert imported.source == "https://shop.example.com"
    assert imported.subject == "orders/ord-9"

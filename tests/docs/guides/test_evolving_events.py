"""Run the examples on ``docs/guides/evolving-events.md``.

The guide includes these modules via `--8<--` snippets; this test proves they
import cleanly, initialize, and that the upcaster chain actually transforms an
old payload, so the working examples in the guide stay working.
"""

import pytest

from protean.core.upcaster import BaseUpcaster
from protean.exceptions import ConfigurationError, DeserializationError
from protean.utils.eventing import Message
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _stored_message(type_string: str, version: int, data: dict) -> dict:
    """A raw message as the event store holds it."""
    return {
        "data": data,
        "metadata": {
            "headers": {
                "id": "msg-1",
                "type": type_string,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": "ordering::order-o-1",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "kind": "EVENT",
                "stream_category": "ordering::order",
                "version": version,
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }


def test_v1_baseline_initializes():
    v1 = load_example("guides/evolving-events/001.py")
    v1.domain.init(traverse=False)
    ir = v1.domain.to_ir()
    events = next(iter(ir["clusters"].values()))["events"]
    placed = next(e for e in events.values() if e["name"] == "OrderPlaced")
    assert placed["__version__"] == 1
    assert set(placed["fields"]) == {"order_id", "amount", "customer_name"}


def test_v3_domain_has_evolution_surface():
    v3 = load_example("guides/evolving-events/002.py")
    v3.domain.init(traverse=False)
    ir = v3.domain.to_ir()

    # The upcaster chain the catalog/verdict rely on.
    assert ir["upcasters"] == {
        "OrderPlaced": [
            {"from_version": 1, "to_version": 2},
            {"from_version": 2, "to_version": 3},
        ]
    }

    events = next(iter(ir["clusters"].values()))["events"]
    placed = next(e for e in events.values() if e["name"] == "OrderPlaced")
    assert placed["__version__"] == 3
    assert placed["fields"]["customer"]["renamed_from"] == ["customer_name"]

    created = next(e for e in events.values() if e["name"] == "OrderCreated")
    assert created["deprecated"] == {"since": "0.16", "removal": "0.19"}
    assert created["superseded_by"] == "OrderPlaced"


def test_upcaster_chain_transforms_a_v1_payload():
    v3 = load_example("guides/evolving-events/002.py")
    v1_to_v2 = v3.OrderPlacedV1toV2()
    v2_to_v3 = v3.OrderPlacedV2toV3()

    # A payload as written under v1 (with the old `customer_name`).
    payload = {"order_id": "o-1", "amount": 100, "customer_name": "Ada"}
    upcast = v2_to_v3.upcast(v1_to_v2.upcast(dict(payload)))

    assert upcast["customer"] == "Ada"  # renamed
    assert "customer_name" not in upcast
    assert upcast["currency"] == "USD"  # defaulted by the upcaster
    assert upcast["placed_at"] is None  # added in v3


def test_a_stored_v1_event_reads_as_the_v3_event():
    v3 = load_example("guides/evolving-events/002.py")
    v3.domain.init(traverse=False)
    with v3.domain.domain_context():
        raw = _stored_message(
            "Ordering.OrderPlaced.v1",
            1,
            {"order_id": "o-1", "amount": 100, "customer_name": "Ada"},
        )
        event = Message.deserialize(raw, validate=False).to_domain_object()

    assert isinstance(event, v3.OrderPlaced)
    assert event.order_id == "o-1"
    assert event.amount == 100
    assert event.customer == "Ada"
    assert event.currency == "USD"
    assert event.placed_at is None


def test_a_stored_payload_with_the_old_field_name_reads_into_the_new_field():
    v3 = load_example("guides/evolving-events/002.py")
    v3.domain.init(traverse=False)
    with v3.domain.domain_context():
        # Stored at the current version, so no upcaster runs: only
        # `renamed_from` maps `customer_name` to `customer`.
        raw = _stored_message(
            "Ordering.OrderPlaced.v3",
            3,
            {"order_id": "o-1", "amount": 100, "customer_name": "Ada"},
        )
        event = Message.deserialize(raw, validate=False).to_domain_object()

    assert event.customer == "Ada"


def test_raising_the_deprecated_event_warns_with_its_replacement():
    v3 = load_example("guides/evolving-events/002.py")
    v3.domain.init(traverse=False)
    with v3.domain.domain_context():
        order = v3.Order(order_id="o-1")
        with pytest.warns(DeprecationWarning, match="OrderPlaced"):
            order.raise_(v3.OrderCreated(order_id="o-1"))


def test_a_broken_upcaster_chain_is_rejected_at_init():
    v3 = load_example("guides/evolving-events/002.py")

    # A second upcaster from version 1 duplicates an edge of the chain.
    @v3.domain.upcaster(event_type=v3.OrderPlaced, from_version=1, to_version=2)
    class AnotherV1toV2(BaseUpcaster):
        def upcast(self, data: dict) -> dict:
            return data

    with pytest.raises(ConfigurationError, match="Duplicate upcaster"):
        v3.domain.init(traverse=False)


def test_a_lenient_event_drops_a_field_it_no_longer_has():
    example = load_example("guides/evolving-events/003.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        raw = _stored_message(
            "Ordering.OrderPlaced.v1",
            1,
            {"order_id": "o-1", "amount": 100, "coupon_code": "SAVE10"},
        )
        event = Message.deserialize(raw, validate=False).to_domain_object()

    assert isinstance(event, example.OrderPlaced)
    assert event.order_id == "o-1"
    assert event.amount == 100
    assert not hasattr(event, "coupon_code")


def test_a_strict_event_rejects_a_field_it_no_longer_has():
    example = load_example("guides/evolving-events/003.py")
    example.OrderPlaced.meta_.lenient = False
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        raw = _stored_message(
            "Ordering.OrderPlaced.v1",
            1,
            {"order_id": "o-1", "amount": 100, "coupon_code": "SAVE10"},
        )
        with pytest.raises(DeserializationError):
            Message.deserialize(raw, validate=False).to_domain_object()

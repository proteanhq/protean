"""Run the examples on ``docs/patterns/event-versioning-and-evolution.md``."""

import warnings

import pytest

from protean.exceptions import ProteanDeprecationWarning
from protean.utils.eventing import Message
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


def _fields(cls):
    return set(declared_fields(cls)) - {"_metadata"}


def _read(type_string: str, version: int, data: dict):
    """Read a stored payload back as a typed event, the way a handler gets it."""
    raw = {
        "data": data,
        "metadata": {
            "headers": {
                "id": f"msg-{version}",
                "type": type_string,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": "test::order-o1",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "kind": "EVENT",
                "stream_category": "test::order",
                "version": version,
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }
    return Message.deserialize(raw, validate=False).to_domain_object()


# Additive changes


def test_an_event_without_the_new_field_still_constructs_in_the_problem_example():
    example = load_example("patterns/event-versioning-and-evolution/001.py")
    with _context(example):
        event = example.OrderPlaced(
            order_id="o1", customer_id="c1", items=[], total=1.0
        )

    assert event.discount_code is None


def test_the_added_fields_take_their_defaults_on_an_old_payload():
    before = load_example("patterns/event-versioning-and-evolution/002.py")
    after = load_example("patterns/event-versioning-and-evolution/003.py")
    with _context(after):
        event = after.OrderPlaced(
            order_id="o1", customer_id="c1", items=["a"], total=10.0
        )

    assert _fields(after.OrderPlaced) - _fields(before.OrderPlaced) == {
        "discount_code",
        "channel",
    }
    assert event.discount_code is None
    assert event.channel == "web"


def test_the_new_gift_wrapping_event_needs_a_wrapping_style():
    example = load_example("patterns/event-versioning-and-evolution/003.py")

    assert _fields(example.OrderGiftWrapped) == {
        "order_id",
        "wrapping_style",
        "gift_message",
    }
    assert declared_fields(example.OrderGiftWrapped)["wrapping_style"].required


def test_renamed_from_reads_an_old_name_payload_into_customer_name():
    example = load_example("patterns/event-versioning-and-evolution/005.py")
    with _context(example):
        event = _read(
            example.OrderPlaced.__type__, 1, {"order_id": "o1", "name": "Alice"}
        )

    assert event.customer_name == "Alice"
    assert "name" not in _fields(example.OrderPlaced)


def test_the_original_event_still_carries_name():
    example = load_example("patterns/event-versioning-and-evolution/004.py")

    assert _fields(example.OrderPlaced) == {"order_id", "name"}


# Strategy 1: a new event type


@pytest.fixture
def new_type():
    example = load_example("patterns/event-versioning-and-evolution/006.py")
    with _context(example):
        yield example


def test_a_v1_event_creates_a_fulfillment_in_usd(new_type):
    event = new_type.OrderPlaced(
        order_id="o1", customer_id="c1", items=["sku-1"], total=40.0
    )
    new_type.FulfillmentEventHandler._handle(event)

    fulfillment = new_type.domain.repository_for(new_type.Fulfillment)._dao.find_by(
        order_id="o1"
    )
    assert fulfillment.items == ["sku-1"]
    assert fulfillment.total == 40.0
    assert fulfillment.currency == "USD"


def test_a_v2_event_creates_a_fulfillment_in_its_own_currency(new_type):
    event = new_type.OrderPlacedV2(
        order_id="o2",
        customer_id="c1",
        line_items=["sku-2"],
        subtotal=50.0,
        tax=5.0,
        total=55.0,
        currency="EUR",
    )
    new_type.FulfillmentEventHandler._handle(event)

    fulfillment = new_type.domain.repository_for(new_type.Fulfillment)._dao.find_by(
        order_id="o2"
    )
    assert fulfillment.items == ["sku-2"]
    assert fulfillment.total == 55.0
    assert fulfillment.currency == "EUR"


def test_raising_the_deprecated_event_warns_once_and_names_the_successor():
    example = load_example("patterns/event-versioning-and-evolution/007.py")
    with _context(example):
        order = example.Order(customer_id="c1")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            order.place(items=["a"], total=1.0)
            order.place(items=["b"], total=2.0)

    deprecations = [
        w for w in caught if issubclass(w.category, ProteanDeprecationWarning)
    ]
    assert len(deprecations) == 1
    assert "OrderPlaced" in str(deprecations[0].message)
    assert "OrderPlacedV2" in str(deprecations[0].message)
    assert len(order._events) == 2


def test_protean_check_reports_the_deprecated_event_with_its_successor():
    example = load_example("patterns/event-versioning-and-evolution/007.py")
    example.domain.init(traverse=False)

    messages = [
        d["message"]
        for d in example.domain.to_ir()["diagnostics"]
        if d["code"] == "DEPRECATED_ELEMENT"
    ]
    assert len(messages) == 1
    assert messages[0].startswith("`OrderPlaced` is deprecated since v0.16")
    assert messages[0].endswith(".OrderPlacedV2`")


# Strategy 2: upcasting on read


def test_a_stored_v1_event_reads_as_the_v3_event():
    example = load_example("patterns/event-versioning-and-evolution/008.py")
    with _context(example):
        event = _read(
            "UpcastOrders.OrderPlaced.v1",
            1,
            {"order_id": "o1", "customer_id": "c1", "items": ["a"], "total": 30.0},
        )

    assert isinstance(event, example.OrderPlaced)
    assert event.line_items == ["a"]
    assert event.subtotal == 30.0
    assert event.tax == 0.0
    assert event.total == 30.0
    assert event.currency == "USD"


def test_a_stored_v2_event_runs_only_the_last_upcaster():
    example = load_example("patterns/event-versioning-and-evolution/008.py")
    with _context(example):
        event = _read(
            "UpcastOrders.OrderPlaced.v2",
            2,
            {
                "order_id": "o1",
                "customer_id": "c1",
                "items": ["a"],
                "total": 30.0,
                "currency": "EUR",
            },
        )

    assert event.line_items == ["a"]
    assert event.currency == "EUR"


# Strategy 3: tolerant reader


def test_the_tolerant_reader_fills_defaults_for_what_the_event_lacks():
    example = load_example("patterns/event-versioning-and-evolution/009.py")
    with _context(example):
        event = example.OrderPlaced(
            order_id="o1",
            customer_id="c1",
            items=[],
            total=12.0,
            discount_code="SAVE10",
            channel="mobile",
        )
        example.AnalyticsEventHandler._handle(event)
        record = example.domain.repository_for(example.Analytics)._dao.find_by(
            order_id="o1"
        )

    assert record.total == 12.0
    assert record.channel == "mobile"
    assert record.has_discount is True
    assert record.currency == "USD"


# Fact events


def test_fact_events_pick_up_the_new_currency_field():
    example = load_example("patterns/event-versioning-and-evolution/010.py")
    with _context(example):
        example.domain.repository_for(example.Order).add(
            example.Order(order_id="o1", customer_id="c1")
        )
        messages = example.domain.event_store.store.read(
            "facteventevolution::order-fact-o1"
        )

    assert len(messages) == 1
    assert messages[0].data["currency"] == "USD"


def test_the_correcting_event_records_both_totals_and_a_reason():
    example = load_example("patterns/event-versioning-and-evolution/011.py")
    with _context(example):
        event = example.OrderTotalCorrected(
            order_id="o1", old_total=10.0, new_total=12.0, correction_reason="tax"
        )

    assert (event.old_total, event.new_total, event.correction_reason) == (
        10.0,
        12.0,
        "tax",
    )


# Replaying an event-sourced aggregate


def test_replay_with_upcasting_rebuilds_from_a_v1_event():
    example = load_example("patterns/event-versioning-and-evolution/012.py")
    with _context(example):
        event = _read(
            "ReplayWithUpcasting.OrderPlaced.v1",
            1,
            {"order_id": "o1", "customer_id": "c1", "items": ["a"], "total": 8.0},
        )
        order = example.Order.from_events([event])

    assert order.customer_id == "c1"
    assert order.items == ["a"]
    assert order.total == 8.0
    assert order.currency == "USD"


def test_replay_without_upcasting_handles_both_versions():
    example = load_example("patterns/event-versioning-and-evolution/013.py")
    with _context(example):
        v1 = example.OrderPlaced(
            order_id="o1", customer_id="c1", items=["a"], total=8.0
        )
        v2 = example.OrderPlacedV2(
            order_id="o2",
            customer_id="c2",
            line_items=["b"],
            subtotal=9.0,
            tax=1.0,
            total=10.0,
            currency="EUR",
        )
        from_v1 = example.Order.from_events([v1])
        from_v2 = example.Order.from_events([v2])

    assert (from_v1.items, from_v1.total, from_v1.currency) == (["a"], 8.0, "USD")
    assert (from_v2.items, from_v2.total, from_v2.currency) == (["b"], 10.0, "EUR")

"""Tests for trace propagation through the test DSL (``given().process()``).

Verifies that the test DSL correctly:
1. Auto-generates and propagates correlation_id through the command chain.
2. Supports explicit ``correlation_id`` via ``process(cmd, correlation_id="...")``.
3. Trace metadata is stored in the event store and accessible via Message reads.
4. Multi-command chaining preserves or isolates correlation_ids correctly.

Note: Events accessed via ``result.events`` are domain objects reconstructed
by ``to_domain_object()``, which rebuilds metadata from ``g.message_in_context``.
Since the context is not set during deserialization, trace IDs on domain event
objects may be None. We verify trace propagation at the **Message** level
(reading from the event store) where values are correctly persisted.
"""

from uuid import uuid4

import pytest

from protean.testing import given
from protean.utils.eventing import Message

from tests.tracing.elements import (
    ConfirmOrder,
    Order,
    OrderCommandHandler,
    OrderConfirmed,
    OrderPlaced,
    PlaceOrder,
    ShipOrder,
    OrderShipped,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(OrderConfirmed, part_of=Order)
    test_domain.register(OrderShipped, part_of=Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(ConfirmOrder, part_of=Order)
    test_domain.register(ShipOrder, part_of=Order)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.init(traverse=False)


@pytest.fixture
def order_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _read_events(test_domain, order_id: str) -> list[Message]:
    stream = f"{Order.meta_.stream_category}-{order_id}"
    return test_domain.event_store.store.read(stream)


def _read_commands(test_domain, order_id: str) -> list[Message]:
    stream = f"{Order.meta_.stream_category}:command-{order_id}"
    return test_domain.event_store.store.read(stream)


# ---------------------------------------------------------------------------
# Tests: Auto-generated correlation_id through the DSL
# ---------------------------------------------------------------------------
class TestDSLAutoCorrelation:
    @pytest.mark.eventstore
    def test_dsl_auto_generates_correlation_id(self, test_domain, order_id):
        """given().process() auto-generates a correlation_id for the command."""
        result = given(Order).process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0)
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, order_id)
        assert len(cmd_msgs) >= 1
        assert cmd_msgs[0].metadata.domain.correlation_id is not None

    @pytest.mark.eventstore
    def test_dsl_events_inherit_auto_correlation_id(self, test_domain, order_id):
        """Events raised via DSL inherit the auto-generated correlation_id."""
        result = given(Order).process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0)
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, order_id)
        cmd_corr = cmd_msgs[0].metadata.domain.correlation_id

        event_msgs = _read_events(test_domain, order_id)
        assert len(event_msgs) >= 1
        assert event_msgs[0].metadata.domain.correlation_id == cmd_corr

    @pytest.mark.eventstore
    def test_dsl_result_events_contain_expected_type(self, test_domain, order_id):
        """Events accessed via result.events contain the expected event type."""
        result = given(Order).process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0)
        )

        assert result.accepted
        assert OrderPlaced in result.events
        assert len(result.events) == 1

    @pytest.mark.eventstore
    def test_dsl_events_in_store_carry_causation_id(self, test_domain, order_id):
        """Events stored in the event store via DSL carry the command's causation_id."""
        result = given(Order).process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0)
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, order_id)
        cmd_id = cmd_msgs[0].metadata.headers.id

        event_msgs = _read_events(test_domain, order_id)
        assert event_msgs[0].metadata.domain.causation_id == cmd_id


# ---------------------------------------------------------------------------
# Tests: Explicit correlation_id through the DSL
# ---------------------------------------------------------------------------
class TestDSLExplicitCorrelation:
    @pytest.mark.eventstore
    def test_dsl_accepts_explicit_correlation_id(self, test_domain, order_id):
        """given().process(cmd, correlation_id="...") uses the provided ID."""
        external_id = "dsl-explicit-123"

        result = given(Order).process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=external_id,
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, order_id)
        assert cmd_msgs[0].metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_dsl_explicit_correlation_id_propagates_to_events(
        self, test_domain, order_id
    ):
        """Explicit correlation_id propagates to events via DSL."""
        external_id = "dsl-propagate-456"

        result = given(Order).process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=external_id,
        )

        assert result.accepted

        event_msgs = _read_events(test_domain, order_id)
        assert len(event_msgs) >= 1
        assert event_msgs[0].metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_dsl_explicit_correlation_id_in_stored_messages(
        self, test_domain, order_id
    ):
        """Both command and event stored by DSL carry the explicit correlation_id."""
        external_id = "dsl-event-store-789"

        result = given(Order).process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=external_id,
        )

        assert result.accepted

        # Command message
        cmd_msgs = _read_commands(test_domain, order_id)
        assert cmd_msgs[0].metadata.domain.correlation_id == external_id

        # Event message
        event_msgs = _read_events(test_domain, order_id)
        assert event_msgs[0].metadata.domain.correlation_id == external_id


# ---------------------------------------------------------------------------
# Tests: DSL with given events (seeding)
# ---------------------------------------------------------------------------
class TestDSLWithGivenEvents:
    @pytest.mark.eventstore
    def test_dsl_with_history_propagates_correlation_id(self, test_domain, order_id):
        """Commands processed after seeding history events get correct correlation_id."""
        external_id = "seeded-corr-abc"

        order_placed = OrderPlaced(order_id=order_id, customer="Alice", amount=100.0)
        result = given(Order, order_placed).process(
            ConfirmOrder(order_id=order_id),
            correlation_id=external_id,
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, order_id)
        assert len(cmd_msgs) >= 1
        assert cmd_msgs[0].metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_dsl_with_history_events_have_correlation_id_in_store(
        self, test_domain, order_id
    ):
        """Events raised after seeded history carry the correlation_id in the store."""
        external_id = "seeded-events-def"

        order_placed = OrderPlaced(order_id=order_id, customer="Alice", amount=100.0)
        result = given(Order, order_placed).process(
            ConfirmOrder(order_id=order_id),
            correlation_id=external_id,
        )

        assert result.accepted
        assert OrderConfirmed in result.events

        # Verify at the event store Message level
        event_msgs = _read_events(test_domain, order_id)
        # The seeded event is at position 0 (from _seed_events with its own metadata)
        # The new event from the command is at position 1
        confirm_msg = next(
            m for m in event_msgs if m.metadata.headers.type == OrderConfirmed.__type__
        )
        assert confirm_msg.metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_dsl_with_history_events_have_causation_id_in_store(
        self, test_domain, order_id
    ):
        """Events raised via DSL with history have causation_id in the store."""
        order_placed = OrderPlaced(order_id=order_id, customer="Alice", amount=100.0)
        result = given(Order, order_placed).process(
            ConfirmOrder(order_id=order_id),
        )

        assert result.accepted

        # Get the command's header ID
        cmd_msgs = _read_commands(test_domain, order_id)
        cmd_id = cmd_msgs[0].metadata.headers.id

        # The event's causation_id at the Message level should match the command
        event_msgs = _read_events(test_domain, order_id)
        confirm_msg = next(
            m for m in event_msgs if m.metadata.headers.type == OrderConfirmed.__type__
        )
        assert confirm_msg.metadata.domain.causation_id == cmd_id


# ---------------------------------------------------------------------------
# Tests: Multi-command chaining through the DSL
# ---------------------------------------------------------------------------
class TestDSLMultiCommandChaining:
    @pytest.mark.eventstore
    def test_chained_commands_each_get_correlation_id(self, test_domain):
        """Each .process() call in a chain gets a correlation_id."""
        oid = str(uuid4())

        result = (
            given(Order)
            .process(PlaceOrder(order_id=oid, customer="Alice", amount=100.0))
            .process(ConfirmOrder(order_id=oid))
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, oid)
        assert len(cmd_msgs) >= 2

        for msg in cmd_msgs:
            assert msg.metadata.domain.correlation_id is not None

    @pytest.mark.eventstore
    def test_chained_commands_get_independent_correlation_ids(self, test_domain):
        """Chained .process() calls without explicit correlation_id get different
        auto-generated IDs (each is an independent root call)."""
        oid = str(uuid4())

        result = (
            given(Order)
            .process(PlaceOrder(order_id=oid, customer="Alice", amount=100.0))
            .process(ConfirmOrder(order_id=oid))
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, oid)
        assert len(cmd_msgs) >= 2

        # Each process() call is independent, so correlation_ids differ
        corr_ids = [msg.metadata.domain.correlation_id for msg in cmd_msgs]
        assert corr_ids[0] != corr_ids[1]

    @pytest.mark.eventstore
    def test_chained_commands_with_same_explicit_correlation_id(self, test_domain):
        """When the same explicit correlation_id is used across chained calls,
        all commands share it."""
        oid = str(uuid4())
        external_id = "chain-shared-corr"

        result = (
            given(Order)
            .process(
                PlaceOrder(order_id=oid, customer="Alice", amount=100.0),
                correlation_id=external_id,
            )
            .process(
                ConfirmOrder(order_id=oid),
                correlation_id=external_id,
            )
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, oid)
        assert len(cmd_msgs) >= 2

        for msg in cmd_msgs:
            assert msg.metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_chained_events_carry_correct_causation_ids_in_store(self, test_domain):
        """In a chained DSL call, each event's causation_id in the store
        points to its respective command."""
        oid = str(uuid4())

        result = (
            given(Order)
            .process(PlaceOrder(order_id=oid, customer="Alice", amount=100.0))
            .process(ConfirmOrder(order_id=oid))
        )

        assert result.accepted

        cmd_msgs = _read_commands(test_domain, oid)
        event_msgs = _read_events(test_domain, oid)

        assert len(cmd_msgs) >= 2
        assert len(event_msgs) >= 2

        # OrderPlaced caused by PlaceOrder
        place_cmd_id = cmd_msgs[0].metadata.headers.id
        assert event_msgs[0].metadata.domain.causation_id == place_cmd_id

        # OrderConfirmed caused by ConfirmOrder
        confirm_cmd_id = cmd_msgs[1].metadata.headers.id
        assert event_msgs[1].metadata.domain.causation_id == confirm_cmd_id

    @pytest.mark.eventstore
    def test_chained_all_events_in_store_have_trace_metadata(self, test_domain):
        """Events from chained DSL calls all carry trace metadata in the store."""
        oid = str(uuid4())
        external_id = "all-events-trace"

        result = (
            given(Order)
            .process(
                PlaceOrder(order_id=oid, customer="Alice", amount=100.0),
                correlation_id=external_id,
            )
            .process(
                ConfirmOrder(order_id=oid),
                correlation_id=external_id,
            )
            .process(
                ShipOrder(order_id=oid, tracking_number="TRK-001"),
                correlation_id=external_id,
            )
        )

        assert result.accepted

        event_msgs = _read_events(test_domain, oid)
        assert len(event_msgs) >= 3

        for msg in event_msgs:
            assert msg.metadata.domain.correlation_id == external_id
            assert msg.metadata.domain.causation_id is not None

    @pytest.mark.eventstore
    def test_chained_dsl_result_all_events_has_correct_count(self, test_domain):
        """result.all_events contains the correct number of events across all
        chained .process() calls."""
        oid = str(uuid4())

        result = (
            given(Order)
            .process(PlaceOrder(order_id=oid, customer="Alice", amount=100.0))
            .process(ConfirmOrder(order_id=oid))
            .process(ShipOrder(order_id=oid, tracking_number="TRK-001"))
        )

        assert result.accepted
        assert len(result.all_events) == 3
        assert result.all_events.types == [OrderPlaced, OrderConfirmed, OrderShipped]

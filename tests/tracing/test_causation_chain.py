"""Tests for causation_id chain tracking through the command-processing pipeline.

Verifies that:
1. A root command (first in chain) has ``causation_id = None``.
2. Events raised by a command have ``causation_id`` equal to the command's ``headers.id``.
3. In a chain (command -> event -> command via event handler), events produced by
   the chained command carry the correct trace context.
"""

from uuid import uuid4

import pytest

from protean.utils.eventing import Message

from tests.tracing.elements import (
    ConfirmOrder,
    Order,
    OrderCommandHandler,
    OrderConfirmed,
    OrderPlaced,
    OrderPlacedAutoConfirmHandler,
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
    """Read all messages from the order's event stream."""
    stream = f"{Order.meta_.stream_category}-{order_id}"
    return test_domain.event_store.store.read(stream)


def _read_commands(test_domain, order_id: str) -> list[Message]:
    """Read all messages from the order's command stream."""
    stream = f"{Order.meta_.stream_category}:command-{order_id}"
    return test_domain.event_store.store.read(stream)


# ---------------------------------------------------------------------------
# Tests: Root command causation_id
# ---------------------------------------------------------------------------
class TestRootCommandCausation:
    @pytest.mark.eventstore
    def test_root_command_has_no_causation_id(self, test_domain, order_id):
        """The first command in a chain (a root entry point) has causation_id = None."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        command_messages = _read_commands(test_domain, order_id)
        assert len(command_messages) >= 1

        root_command = command_messages[0]
        assert root_command.metadata.domain.causation_id is None

    @pytest.mark.eventstore
    def test_independent_commands_both_have_no_causation_id(
        self, test_domain, order_id
    ):
        """Two independent domain.process() calls each have causation_id = None."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )
        test_domain.process(
            ConfirmOrder(order_id=order_id),
            asynchronous=False,
        )

        command_messages = _read_commands(test_domain, order_id)
        assert len(command_messages) >= 2

        # Both are root commands (called directly, not from an event handler)
        for cmd_msg in command_messages:
            assert cmd_msg.metadata.domain.causation_id is None


# ---------------------------------------------------------------------------
# Tests: Event causation_id
# ---------------------------------------------------------------------------
class TestEventCausation:
    @pytest.mark.eventstore
    def test_event_causation_id_equals_command_header_id(self, test_domain, order_id):
        """Events raised by a command have causation_id = the command's headers.id."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        # Get the command's message ID
        command_messages = _read_commands(test_domain, order_id)
        command_id = command_messages[0].metadata.headers.id

        # Get the event and verify its causation_id
        event_messages = _read_events(test_domain, order_id)
        assert len(event_messages) >= 1

        event_msg = event_messages[0]
        assert event_msg.metadata.domain.causation_id == command_id

    @pytest.mark.eventstore
    def test_multiple_events_from_independent_commands_have_correct_causation(
        self, test_domain, order_id
    ):
        """Events from independent commands each point to their respective command."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )
        test_domain.process(
            ConfirmOrder(order_id=order_id),
            asynchronous=False,
        )

        command_messages = _read_commands(test_domain, order_id)
        event_messages = _read_events(test_domain, order_id)

        assert len(command_messages) >= 2
        assert len(event_messages) >= 2

        # First event (OrderPlaced) -> caused by first command (PlaceOrder)
        place_cmd_id = command_messages[0].metadata.headers.id
        assert event_messages[0].metadata.domain.causation_id == place_cmd_id

        # Second event (OrderConfirmed) -> caused by second command (ConfirmOrder)
        confirm_cmd_id = command_messages[1].metadata.headers.id
        assert event_messages[1].metadata.domain.causation_id == confirm_cmd_id

    @pytest.mark.eventstore
    def test_event_causation_id_is_different_from_event_id(self, test_domain, order_id):
        """The event's causation_id is distinct from the event's own headers.id."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        event_messages = _read_events(test_domain, order_id)
        event_msg = event_messages[0]

        assert event_msg.metadata.domain.causation_id is not None
        assert event_msg.metadata.domain.causation_id != event_msg.metadata.headers.id


# ---------------------------------------------------------------------------
# Tests: Causation chain via event handler (sync path)
# ---------------------------------------------------------------------------
class TestCausationChainViaEventHandler:
    """Test the causation chain when an event handler dispatches a new command.

    In the sync processing path, when UoW.commit() fires event handlers,
    ``g.message_in_context`` still points to the original command. This means
    the chained command and its events inherit the original command's context.

    Note: In the memory event store, the chained command may not appear in the
    command stream due to nested UoW/session behavior. We verify the chain by
    checking events, which are reliably stored.
    """

    @pytest.fixture(autouse=True)
    def register_event_handler(self, test_domain):
        """Register the auto-confirm event handler for chain tests."""
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_chained_processing_produces_both_events(self, test_domain, order_id):
        """An event handler that dispatches a command produces events from both
        the original and chained commands."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        event_messages = _read_events(test_domain, order_id)
        # Should have OrderPlaced + OrderConfirmed (from auto-confirm handler)
        assert len(event_messages) >= 2

        event_types = [m.metadata.headers.type for m in event_messages]
        assert OrderPlaced.__type__ in event_types
        assert OrderConfirmed.__type__ in event_types

    @pytest.mark.eventstore
    def test_full_chain_events_share_correlation_id(self, test_domain, order_id):
        """All events in a chain share the same correlation_id."""
        external_id = "chain-events-corr-xyz"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
            correlation_id=external_id,
        )

        event_messages = _read_events(test_domain, order_id)
        assert len(event_messages) >= 2

        for msg in event_messages:
            assert msg.metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_chained_events_all_have_causation_ids(self, test_domain, order_id):
        """All events in the chain have non-None causation_ids."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        event_messages = _read_events(test_domain, order_id)
        assert len(event_messages) >= 2

        for msg in event_messages:
            assert msg.metadata.domain.causation_id is not None

    @pytest.mark.eventstore
    def test_chained_events_causation_points_to_root_command(
        self, test_domain, order_id
    ):
        """In the sync path, events from the chained command inherit the root
        command's ID as their causation_id (since g.message_in_context still
        points to the root command during UoW.commit event handler dispatch)."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        # Get the root command's ID
        command_messages = _read_commands(test_domain, order_id)
        root_cmd_id = command_messages[0].metadata.headers.id

        event_messages = _read_events(test_domain, order_id)
        assert len(event_messages) >= 2

        # The first event (OrderPlaced) is caused by the root command
        assert event_messages[0].metadata.domain.causation_id == root_cmd_id

        # The second event (OrderConfirmed) is also caused by the root command
        # in sync mode, because g.message_in_context hasn't changed
        # during UoW.commit()'s event handler invocation
        assert event_messages[1].metadata.domain.causation_id == root_cmd_id

    @pytest.mark.eventstore
    def test_chained_auto_correlation_id_propagates(self, test_domain, order_id):
        """Auto-generated correlation_id propagates through the entire chain."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        event_messages = _read_events(test_domain, order_id)
        assert len(event_messages) >= 2

        # All events should share the same (auto-generated) correlation_id
        correlation_ids = {m.metadata.domain.correlation_id for m in event_messages}
        assert len(correlation_ids) == 1
        assert None not in correlation_ids


# ---------------------------------------------------------------------------
# Tests: Causation ID persistence at the Message level
# ---------------------------------------------------------------------------
class TestCausationIdPersistence:
    @pytest.mark.eventstore
    def test_causation_id_stored_in_event_store_message(self, test_domain, order_id):
        """Causation ID is correctly stored in event store Message metadata."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        command_messages = _read_commands(test_domain, order_id)
        command_id = command_messages[0].metadata.headers.id

        event_messages = _read_events(test_domain, order_id)
        assert event_messages[0].metadata.domain.causation_id == command_id

    @pytest.mark.eventstore
    def test_causation_id_in_dict_representation(self, test_domain, order_id):
        """Causation ID appears in the dictionary representation of event metadata."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        command_messages = _read_commands(test_domain, order_id)
        command_id = command_messages[0].metadata.headers.id

        event_messages = _read_events(test_domain, order_id)
        msg_dict = event_messages[0].to_dict()

        assert msg_dict["metadata"]["domain"]["causation_id"] == command_id

    @pytest.mark.eventstore
    def test_root_command_causation_id_none_in_dict(self, test_domain, order_id):
        """Root command's causation_id is None in dict representation."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        command_messages = _read_commands(test_domain, order_id)
        msg_dict = command_messages[0].to_dict()

        assert msg_dict["metadata"]["domain"]["causation_id"] is None

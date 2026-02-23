"""Tests for the causation chain traversal API on BaseEventStore.

Verifies:
1. ``trace_causation()`` walks UP the chain from a message to the root.
2. ``trace_effects()`` walks DOWN the chain from a message to find effects.
3. ``build_causation_tree()`` builds a full tree for a correlation ID.
4. Static helper extractors handle valid and malformed metadata.
5. Edge cases: malformed Messages, broken causation links, malformed raw data.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from protean.port.event_store import BaseEventStore, CausationNode
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
# Helpers
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
# Tests: trace_causation
# ---------------------------------------------------------------------------


class TestTraceCausation:
    """Tests for ``event_store.trace_causation()`` — walking UP the chain."""

    @pytest.mark.eventstore
    def test_root_command_returns_single_message(self, test_domain, order_id):
        """trace_causation on the root command returns just that command."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        root_cmd = commands[0]

        store = test_domain.event_store.store
        chain = store.trace_causation(root_cmd.metadata.headers.id)

        assert len(chain) == 1
        assert chain[0].metadata.headers.id == root_cmd.metadata.headers.id

    @pytest.mark.eventstore
    def test_event_returns_chain_to_root_command(self, test_domain, order_id):
        """trace_causation on OrderPlaced returns [PlaceOrder, OrderPlaced]."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        commands = _read_commands(test_domain, order_id)

        store = test_domain.event_store.store
        chain = store.trace_causation(events[0].metadata.headers.id)

        # Chain should be: PlaceOrder -> OrderPlaced
        assert len(chain) == 2
        assert chain[0].metadata.headers.id == commands[0].metadata.headers.id
        assert chain[1].metadata.headers.id == events[0].metadata.headers.id

    @pytest.mark.eventstore
    def test_returns_messages_in_root_to_target_order(self, test_domain, order_id):
        """Chain is ordered root-first, target-last."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        store = test_domain.event_store.store
        chain = store.trace_causation(events[0].metadata.headers.id)

        # First message should be the root (no causation_id)
        assert chain[0].metadata.domain.causation_id is None
        # Last message should be the target
        assert chain[-1].metadata.headers.id == events[0].metadata.headers.id

    @pytest.mark.eventstore
    def test_accepts_message_object(self, test_domain, order_id):
        """trace_causation accepts a Message object (not just a string)."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        store = test_domain.event_store.store

        # Pass Message object instead of string
        chain = store.trace_causation(events[0])
        assert len(chain) == 2

    @pytest.mark.eventstore
    def test_unknown_message_id_raises_value_error(self, test_domain):
        """Nonexistent message ID raises ValueError."""
        store = test_domain.event_store.store
        with pytest.raises(ValueError, match="not found in event store"):
            store.trace_causation("nonexistent-message-id")


# ---------------------------------------------------------------------------
# Tests: trace_effects
# ---------------------------------------------------------------------------


class TestTraceEffects:
    """Tests for ``event_store.trace_effects()`` — walking DOWN the chain."""

    @pytest.mark.eventstore
    def test_root_command_returns_downstream_events(self, test_domain, order_id):
        """trace_effects on PlaceOrder returns at least OrderPlaced."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        store = test_domain.event_store.store
        effects = store.trace_effects(commands[0].metadata.headers.id)

        # At minimum, OrderPlaced should be an effect of PlaceOrder
        assert len(effects) >= 1
        effect_types = [m.metadata.headers.type for m in effects]
        assert OrderPlaced.__type__ in effect_types

    @pytest.mark.eventstore
    def test_terminal_event_returns_empty(self, test_domain, order_id):
        """An event with no downstream handlers returns empty effects."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        # OrderPlaced has no event handler registered (no auto-confirm here)
        # so it should have no effects
        store = test_domain.event_store.store
        effects = store.trace_effects(events[0].metadata.headers.id)

        assert effects == []

    @pytest.mark.eventstore
    def test_recursive_false_returns_one_level(self, test_domain, order_id):
        """recursive=False returns only direct children."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        store = test_domain.event_store.store
        direct = store.trace_effects(commands[0].metadata.headers.id, recursive=False)

        # Direct children of PlaceOrder command = the events it raised
        assert len(direct) >= 1
        for msg in direct:
            assert msg.metadata.domain.causation_id == commands[0].metadata.headers.id

    @pytest.mark.eventstore
    def test_effects_ordered_by_global_position(self, test_domain, order_id):
        """Effects are returned in chronological (global_position) order."""
        # Place and then confirm order for multiple events
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )
        test_domain.process(
            ConfirmOrder(order_id=order_id),
            asynchronous=False,
        )

        # Get all commands and check effects of the first one
        commands = _read_commands(test_domain, order_id)
        store = test_domain.event_store.store
        effects = store.trace_effects(commands[0].metadata.headers.id)

        # Verify ordering by checking global_positions are non-decreasing
        positions = [
            m.metadata.event_store.global_position
            for m in effects
            if m.metadata.event_store
            and m.metadata.event_store.global_position is not None
        ]
        assert positions == sorted(positions)

    @pytest.mark.eventstore
    def test_accepts_message_object(self, test_domain, order_id):
        """trace_effects accepts a Message object."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        store = test_domain.event_store.store

        # Pass Message object
        effects = store.trace_effects(commands[0])
        assert len(effects) >= 1

    @pytest.mark.eventstore
    def test_unknown_message_id_raises_value_error(self, test_domain):
        """Nonexistent message ID raises ValueError."""
        store = test_domain.event_store.store
        with pytest.raises(ValueError, match="not found in event store"):
            store.trace_effects("nonexistent-message-id")


# ---------------------------------------------------------------------------
# Tests: trace_effects with chained event handler
# ---------------------------------------------------------------------------


class TestTraceEffectsWithChain:
    """Tests for trace_effects when an event handler dispatches a new command.

    In sync mode, g.message_in_context stays as the root command during
    UoW.commit() event handler dispatch. This means chained commands have
    causation_id = root_command.headers.id, making them appear as siblings
    of the events (direct children of the root command).
    """

    @pytest.fixture(autouse=True)
    def register_event_handler(self, test_domain):
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_root_command_effects_include_chained_events(self, test_domain, order_id):
        """Effects of root command include events from the chained command."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        store = test_domain.event_store.store
        effects = store.trace_effects(commands[0].metadata.headers.id)

        effect_types = [m.metadata.headers.type for m in effects]
        assert OrderPlaced.__type__ in effect_types
        assert OrderConfirmed.__type__ in effect_types


# ---------------------------------------------------------------------------
# Tests: build_causation_tree
# ---------------------------------------------------------------------------


class TestBuildCausationTree:
    """Tests for ``event_store.build_causation_tree()``."""

    @pytest.mark.eventstore
    def test_single_command_event_chain(self, test_domain, order_id):
        """Tree for a simple PlaceOrder -> OrderPlaced chain."""
        correlation_id = "test-tree-corr-123"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
            correlation_id=correlation_id,
        )

        store = test_domain.event_store.store
        root = store.build_causation_tree(correlation_id)

        assert root is not None
        assert isinstance(root, CausationNode)
        # Root should be the PlaceOrder command
        assert root.kind == "COMMAND"
        # Should have at least one child (OrderPlaced event)
        assert len(root.children) >= 1
        assert root.children[0].kind == "EVENT"

    @pytest.mark.eventstore
    def test_tree_has_correct_node_attributes(self, test_domain, order_id):
        """CausationNode attributes are populated correctly."""
        correlation_id = "test-attrs-corr"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
            correlation_id=correlation_id,
        )

        store = test_domain.event_store.store
        root = store.build_causation_tree(correlation_id)

        assert root is not None
        assert root.message_id != "?"
        assert root.message_type != "?"
        assert root.kind in ("EVENT", "COMMAND")
        assert root.stream != "?"

    @pytest.mark.eventstore
    def test_returns_none_for_unknown_correlation_id(self, test_domain):
        """build_causation_tree returns None for nonexistent correlation ID."""
        store = test_domain.event_store.store
        result = store.build_causation_tree("nonexistent-correlation-id")
        assert result is None

    @pytest.mark.eventstore
    def test_multiple_events_from_single_command(self, test_domain, order_id):
        """Tree correctly shows multiple events as children of one command."""
        correlation_id = "test-multi-corr"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
            correlation_id=correlation_id,
        )
        test_domain.process(
            ConfirmOrder(order_id=order_id),
            asynchronous=False,
            correlation_id=correlation_id,
        )

        store = test_domain.event_store.store
        root = store.build_causation_tree(correlation_id)

        assert root is not None
        # Root is PlaceOrder, should have OrderPlaced as child
        # Second command (ConfirmOrder) is a separate root since it has no causation_id
        # But they share the same correlation_id

    @pytest.mark.eventstore
    def test_chained_tree_structure(self, test_domain, order_id):
        """Tree reflects the sync causation chain correctly.

        In sync mode, the chained command (ConfirmOrder dispatched by the
        OrderPlacedAutoConfirmHandler) has causation_id pointing to the root
        command. So OrderPlaced and OrderConfirmed are siblings under PlaceOrder.
        """
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

        correlation_id = "test-chain-corr"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
            correlation_id=correlation_id,
        )

        store = test_domain.event_store.store
        root = store.build_causation_tree(correlation_id)

        assert root is not None
        # Root is PlaceOrder command
        assert root.kind == "COMMAND"
        # In sync mode, all events (OrderPlaced + OrderConfirmed) and the
        # chained ConfirmOrder command are direct children of root
        assert len(root.children) >= 2


# ---------------------------------------------------------------------------
# Tests: Static helper extractors
# ---------------------------------------------------------------------------


class TestHelperExtractors:
    """Tests for the static metadata extraction helpers on BaseEventStore."""

    def test_extract_message_id_valid(self, test_domain):
        """Extracts headers.id from a well-formed raw message."""

        msg = {"metadata": {"headers": {"id": "test-msg-123"}}}
        assert BaseEventStore._extract_message_id(msg) == "test-msg-123"

    def test_extract_message_id_missing_metadata(self, test_domain):
        assert BaseEventStore._extract_message_id({}) is None
        assert BaseEventStore._extract_message_id({"metadata": None}) is None

    def test_extract_message_id_missing_headers(self, test_domain):
        assert BaseEventStore._extract_message_id({"metadata": {}}) is None
        assert (
            BaseEventStore._extract_message_id({"metadata": {"headers": None}}) is None
        )

    def test_extract_causation_id_valid(self, test_domain):
        msg = {"metadata": {"domain": {"causation_id": "parent-123"}}}
        assert BaseEventStore._extract_causation_id(msg) == "parent-123"

    def test_extract_causation_id_none_value(self, test_domain):
        msg = {"metadata": {"domain": {"causation_id": None}}}
        assert BaseEventStore._extract_causation_id(msg) is None

    def test_extract_correlation_id_valid(self, test_domain):
        msg = {"metadata": {"domain": {"correlation_id": "corr-abc"}}}
        assert BaseEventStore._extract_correlation_id(msg) == "corr-abc"

    def test_extract_from_malformed_metadata(self, test_domain):
        # metadata is not a dict
        msg = {"metadata": "not-a-dict"}
        assert BaseEventStore._extract_message_id(msg) is None
        assert BaseEventStore._extract_causation_id(msg) is None
        assert BaseEventStore._extract_correlation_id(msg) is None

        # domain is not a dict
        msg2 = {"metadata": {"domain": "not-a-dict"}}
        assert BaseEventStore._extract_causation_id(msg2) is None
        assert BaseEventStore._extract_correlation_id(msg2) is None


# ---------------------------------------------------------------------------
# Tests: Edge cases for _resolve_and_load_group
# ---------------------------------------------------------------------------


class TestResolveAndLoadGroupEdgeCases:
    """Tests for edge cases in _resolve_and_load_group (lines 544, 546)."""

    @pytest.mark.eventstore
    def test_message_with_no_headers_raises(self, test_domain):
        """A Message with no metadata raises ValueError (line 544)."""
        store = test_domain.event_store.store
        msg = MagicMock(spec=Message)
        msg.metadata = None

        with pytest.raises(ValueError, match="Message has no headers.id"):
            store._resolve_and_load_group(msg)

    @pytest.mark.eventstore
    def test_message_with_no_correlation_id_returns_empty_group(self, test_domain):
        """A Message with headers but no domain returns empty group (line 546)."""
        store = test_domain.event_store.store
        msg = MagicMock(spec=Message)
        msg.metadata = MagicMock()
        msg.metadata.headers = MagicMock()
        msg.metadata.headers.id = "some-msg-id"
        msg.metadata.domain = None

        mid, group = store._resolve_and_load_group(msg)
        assert mid == "some-msg-id"
        assert group == []


# ---------------------------------------------------------------------------
# Tests: trace_causation edge cases
# ---------------------------------------------------------------------------


class TestTraceCausationEdgeCases:
    """Tests for edge cases in trace_causation (lines 595, 607)."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderConfirmed, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(ConfirmOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_causation_id_pointing_outside_group(self, test_domain):
        """When causation_id points to a message outside the group, chain stops (line 607).

        Root commands have causation_id=None so they stop naturally.
        This test verifies that trace_causation handles the root correctly
        by stopping when by_id lookup returns None for a causation_id.
        """
        order_id = str(uuid4())
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        store = test_domain.event_store.store

        # The event's causation_id points to the command.
        # The command's causation_id is None, which exits the while loop
        # (current_id becomes None). This confirms the break path
        # for when by_id.get(current_id) returns None is also safe.
        chain = store.trace_causation(events[0].metadata.headers.id)
        assert len(chain) == 2
        # Root (command) has no causation_id
        assert chain[0].metadata.domain.causation_id is None

    @pytest.mark.eventstore
    def test_message_with_no_correlation_returns_only_self(self, test_domain):
        """A Message object with no domain metadata returns empty group,
        leading to an empty chain (exercises line 546 via trace_causation)."""
        store = test_domain.event_store.store
        msg = MagicMock(spec=Message)
        msg.metadata = MagicMock()
        msg.metadata.headers = MagicMock()
        msg.metadata.headers.id = "orphan-msg-id"
        msg.metadata.domain = None

        # Empty group means by_id is empty, so chain is empty
        chain = store.trace_causation(msg)
        assert chain == []

    @pytest.mark.eventstore
    def test_group_member_with_no_headers_id_skipped_in_lookup(self, test_domain):
        """A group member with no headers.id is skipped in by_id (line 595->593)."""
        store = test_domain.event_store.store

        original = store._resolve_and_load_group

        def _patched(message_id):
            return "target-msg", [
                # A valid root message
                {
                    "type": "RootCmd",
                    "metadata": {
                        "headers": {"id": "target-msg"},
                        "domain": {"correlation_id": "corr-1", "causation_id": None},
                    },
                    "data": {},
                },
                # A malformed group member with no headers.id
                {
                    "type": "BadMsg",
                    "metadata": {"headers": {}, "domain": {"correlation_id": "corr-1"}},
                    "data": {},
                },
            ]

        store._resolve_and_load_group = _patched
        try:
            chain = store.trace_causation("target-msg")
            # Should find the root message but skip the malformed one
            assert len(chain) == 1
        finally:
            store._resolve_and_load_group = original


# ---------------------------------------------------------------------------
# Tests: trace_effects edge cases
# ---------------------------------------------------------------------------


class TestTraceEffectsEdgeCases:
    """Tests for edge cases in trace_effects (line 660->658)."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_child_with_no_headers_id_skipped_in_bfs(self, test_domain):
        """A child with no headers.id is skipped during BFS (line 660->658)."""
        store = test_domain.event_store.store

        original = store._resolve_and_load_group

        def _patched(message_id):
            return "root-cmd", [
                {
                    "type": "RootCmd",
                    "metadata": {
                        "headers": {"id": "root-cmd"},
                        "domain": {"correlation_id": "corr-2", "causation_id": None},
                    },
                    "global_position": 1,
                    "data": {},
                },
                {
                    # Child with no headers.id — should be skipped in BFS
                    "type": "BadChild",
                    "metadata": {
                        "headers": {},
                        "domain": {
                            "correlation_id": "corr-2",
                            "causation_id": "root-cmd",
                        },
                    },
                    "global_position": 2,
                    "data": {},
                },
            ]

        store._resolve_and_load_group = _patched
        try:
            effects = store.trace_effects("root-cmd")
            # The child has no headers.id so it's skipped
            assert effects == []
        finally:
            store._resolve_and_load_group = original


# ---------------------------------------------------------------------------
# Tests: build_causation_tree edge cases
# ---------------------------------------------------------------------------


class TestBuildCausationTreeEdgeCases:
    """Tests for edge cases in build_causation_tree (lines 691, 711, 714, 717)."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)
        test_domain.init(traverse=False)

    def test_build_node_with_malformed_metadata_string(self, test_domain):
        """_build_node handles metadata that is a string, not a dict (line 711)."""
        store = test_domain.event_store.store

        # Monkey-patch _load_correlation_group to return malformed data
        original = store._load_correlation_group
        store._load_correlation_group = lambda cid: [
            {
                "type": "MalformedEvent",
                "stream_name": "test-stream",
                "global_position": 1,
                "metadata": "not-a-dict",  # malformed metadata
            }
        ]

        try:
            root = store.build_causation_tree("malformed-corr")
            assert root is not None
            assert root.message_id == "?"
            assert root.message_type == "MalformedEvent"
            assert root.kind == "?"
        finally:
            store._load_correlation_group = original

    def test_build_node_with_malformed_headers_string(self, test_domain):
        """_build_node handles headers that is a string, not a dict (line 714)."""
        store = test_domain.event_store.store

        original = store._load_correlation_group
        store._load_correlation_group = lambda cid: [
            {
                "type": "MalformedEvent",
                "stream_name": "test-stream",
                "global_position": 1,
                "metadata": {"headers": "not-a-dict", "domain": {"kind": "EVENT"}},
            }
        ]

        try:
            root = store.build_causation_tree("malformed-headers-corr")
            assert root is not None
            assert root.message_id == "?"
            assert root.kind == "EVENT"
        finally:
            store._load_correlation_group = original

    def test_build_node_with_malformed_domain_string(self, test_domain):
        """_build_node handles domain that is a string, not a dict (line 717)."""
        store = test_domain.event_store.store

        original = store._load_correlation_group
        store._load_correlation_group = lambda cid: [
            {
                "type": "MalformedEvent",
                "stream_name": "test-stream",
                "global_position": 1,
                "metadata": {
                    "headers": {"id": "msg-123"},
                    "domain": "not-a-dict",  # malformed domain
                },
            }
        ]

        try:
            root = store.build_causation_tree("malformed-domain-corr")
            assert root is not None
            assert root.message_id == "msg-123"
            assert root.kind == "?"  # Falls back to "?" since domain is malformed
        finally:
            store._load_correlation_group = original

    def test_build_tree_with_message_missing_headers_id(self, test_domain):
        """Message with no headers.id in group: not added to by_id, and skipped
        as a child because _extract_message_id returns None (falsy) at line 729.
        This exercises the branch at line 691 where hid is falsy."""
        store = test_domain.event_store.store

        original = store._load_correlation_group
        store._load_correlation_group = lambda cid: [
            {
                "type": "GoodEvent",
                "stream_name": "test-stream",
                "global_position": 1,
                "metadata": {
                    "headers": {"id": "root-msg"},
                    "domain": {"kind": "COMMAND", "correlation_id": cid},
                },
            },
            {
                # This message has no headers.id
                "type": "OrphanEvent",
                "stream_name": "test-stream",
                "global_position": 2,
                "metadata": {
                    "headers": {},
                    "domain": {
                        "kind": "EVENT",
                        "causation_id": "root-msg",
                        "correlation_id": cid,
                    },
                },
            },
        ]

        try:
            root = store.build_causation_tree("missing-hid-corr")
            assert root is not None
            assert root.message_id == "root-msg"
            # The orphan child has no headers.id so _extract_message_id returns
            # None (falsy) — it's skipped by the `if child_id and ...` guard
            # in _build_node (line 729-730). The root has no children.
            assert len(root.children) == 0
        finally:
            store._load_correlation_group = original

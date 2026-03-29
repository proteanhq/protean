"""Tests for ``domain.correlation_trace()`` and ``assert_chain()`` test helper.

Verifies that:
1. ``domain.correlation_trace(correlation_id)`` returns a flat, causally-ordered
   list of ``CausationNode`` objects for a given correlation chain.
2. ``assert_chain()`` validates message type sequences against the chain.
3. Works with event-sourced aggregates and the in-memory event store.
4. Edge cases: unknown correlation ID, empty chain.
"""

from uuid import uuid4

import pytest

from protean.port.event_store import CausationNode
from protean.testing import assert_chain

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
# Tests: domain.correlation_trace()
# ---------------------------------------------------------------------------
class TestCorrelationTrace:
    @pytest.mark.eventstore
    def test_returns_empty_list_for_unknown_correlation_id(self, test_domain):
        """Unknown correlation ID returns an empty list, not None."""
        chain = test_domain.correlation_trace("nonexistent-correlation-id")
        assert chain == []

    @pytest.mark.eventstore
    def test_single_command_event_chain(self, test_domain, order_id):
        """A single command producing one event yields a 2-node chain."""
        correlation_id = f"trace-single-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)

        assert len(chain) == 2
        assert all(isinstance(node, CausationNode) for node in chain)

        # First is the command, second is the event
        assert chain[0].kind == "COMMAND"
        assert chain[0].message_type == PlaceOrder.__type__
        assert chain[1].kind == "EVENT"
        assert chain[1].message_type == OrderPlaced.__type__

    @pytest.mark.eventstore
    def test_nodes_have_expected_fields(self, test_domain, order_id):
        """Each CausationNode has message_id, message_type, kind, and stream."""
        correlation_id = f"trace-fields-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) >= 1

        for node in chain:
            assert node.message_id is not None
            assert node.message_type is not None
            assert node.kind in ("COMMAND", "EVENT")
            assert node.stream is not None

    @pytest.mark.eventstore
    def test_chain_parent_before_children(self, test_domain, order_id):
        """The root command appears before its effect events."""
        correlation_id = f"trace-order-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) == 2
        # Command is first (parent), event is second (child)
        assert chain[0].kind == "COMMAND"
        assert chain[1].kind == "EVENT"


# ---------------------------------------------------------------------------
# Tests: Saga chain (event handler triggers new command)
# ---------------------------------------------------------------------------
class TestSagaChainTrace:
    @pytest.fixture(autouse=True)
    def register_auto_confirm(self, test_domain):
        """Register the auto-confirm event handler to create a saga chain."""
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_saga_chain_captures_all_events(self, test_domain, order_id):
        """PlaceOrder → OrderPlaced + OrderConfirmed in the chain.

        In sync mode, the auto-confirm handler fires during UoW commit.
        The chain captures the root command and all resulting events.
        """
        correlation_id = f"trace-saga-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)

        # Root command + events from the chain
        assert len(chain) >= 3

        types = [node.message_type for node in chain]
        assert PlaceOrder.__type__ in types
        assert OrderPlaced.__type__ in types
        assert OrderConfirmed.__type__ in types

    @pytest.mark.eventstore
    def test_saga_chain_root_is_command(self, test_domain, order_id):
        """The first element in a saga chain is always the root command."""
        correlation_id = f"trace-saga-root-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) >= 1
        assert chain[0].kind == "COMMAND"
        assert chain[0].message_type == PlaceOrder.__type__


# ---------------------------------------------------------------------------
# Tests: assert_chain() helper
# ---------------------------------------------------------------------------
class TestAssertChain:
    @pytest.mark.eventstore
    def test_assert_chain_passes_on_match(self, test_domain, order_id):
        """assert_chain() does not raise when the chain matches."""
        correlation_id = f"assert-pass-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) == 2

        # Should not raise
        assert_chain(chain, [PlaceOrder, OrderPlaced])

    @pytest.mark.eventstore
    def test_assert_chain_with_string_types(self, test_domain, order_id):
        """assert_chain() works with string type names."""
        correlation_id = f"assert-str-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) == 2

        assert_chain(
            chain,
            [PlaceOrder.__type__, OrderPlaced.__type__],
        )

    @pytest.mark.eventstore
    def test_assert_chain_fails_on_wrong_order(self, test_domain, order_id):
        """assert_chain() raises AssertionError when order is wrong."""
        correlation_id = f"assert-order-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) == 2

        with pytest.raises(AssertionError, match="Chain mismatch"):
            assert_chain(chain, [OrderPlaced, PlaceOrder])

    @pytest.mark.eventstore
    def test_assert_chain_fails_on_wrong_length(self, test_domain, order_id):
        """assert_chain() raises AssertionError when lengths differ."""
        correlation_id = f"assert-len-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) == 2

        with pytest.raises(AssertionError, match="Chain mismatch"):
            assert_chain(chain, [PlaceOrder])

    def test_assert_chain_with_empty_chain(self):
        """assert_chain() with empty chain and empty expected passes."""
        assert_chain([], [])

    def test_assert_chain_empty_chain_nonempty_expected_fails(self):
        """assert_chain() with empty chain but non-empty expected fails."""
        with pytest.raises(AssertionError, match="Chain mismatch"):
            assert_chain([], ["SomeCommand"])

    @pytest.mark.eventstore
    def test_assert_chain_mixed_strings_and_classes(self, test_domain, order_id):
        """assert_chain() supports mixing strings and classes."""
        correlation_id = f"assert-mix-{uuid4().hex[:8]}"

        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=100.0),
            correlation_id=correlation_id,
        )

        chain = test_domain.correlation_trace(correlation_id)
        assert len(chain) == 2

        # Mix: class for command, string for event
        assert_chain(chain, [PlaceOrder, OrderPlaced.__type__])

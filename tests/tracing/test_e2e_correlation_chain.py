"""End-to-end integration tests for correlation and causation ID propagation.

Verifies that correlation_id and causation_id flow correctly across:
1. Multi-step command → event → handler → command → event → projection chains
2. External correlation_id propagation through event handler chains
3. Command correlation_id → event context propagation (subscriber-style)
4. Event handler causation chain correctness
5. OTEL span attribute verification
"""

from uuid import uuid4

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean.utils.eventing import Message

from tests.tracing.elements import (
    ConfirmOrder,
    Order,
    OrderCommandHandler,
    OrderConfirmed,
    OrderPlaced,
    OrderPlacedAutoConfirmHandler,
    OrderShipped,
    OrderSummary,
    OrderSummaryProjector,
    PlaceOrder,
    ShipOrder,
)


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


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL exporters on the domain for testing."""
    service_name = domain.normalized_name
    resource = Resource.create({"service.name": service_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return span_exporter


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


@pytest.fixture
def span_exporter(test_domain):
    """Enable in-memory OTEL and return the span exporter."""
    return _init_telemetry_in_memory(test_domain)


# ===========================================================================
# Scenario 1: Full chain — command → event → handler → command → event →
#              projection update — all sharing the same correlation_id
# ===========================================================================
class TestFullChainCorrelationPropagation:
    """PlaceOrder → OrderPlaced → [auto-confirm handler] → ConfirmOrder →
    OrderConfirmed, with a projector creating an OrderSummary projection.

    All messages share the same correlation_id and each event's causation_id
    points to the command that produced it.
    """

    @pytest.fixture(autouse=True)
    def register_chain_elements(self, test_domain):
        """Register event handler and projector for the full chain."""
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.register(OrderSummary)
        test_domain.register(
            OrderSummaryProjector,
            projector_for=OrderSummary,
            aggregates=[Order],
        )
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_all_events_share_correlation_id(self, test_domain, order_id):
        """Every event in the chain carries the same correlation_id."""
        external_corr = "e2e-chain-corr-001"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            asynchronous=False,
            correlation_id=external_corr,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2, (
            f"Expected OrderPlaced + OrderConfirmed, got {len(events)}"
        )

        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == external_corr

    @pytest.mark.eventstore
    def test_all_events_have_causation_ids(self, test_domain, order_id):
        """Every event in the chain has a non-None causation_id."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2

        for event_msg in events:
            assert event_msg.metadata.domain.causation_id is not None

    @pytest.mark.eventstore
    def test_projection_created_from_chain(self, test_domain, order_id):
        """The projector creates the projection from the OrderPlaced event."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            asynchronous=False,
        )

        summary = test_domain.repository_for(OrderSummary).get(order_id)
        assert summary is not None
        assert summary.customer == "Alice"
        assert summary.amount == 99.99

    @pytest.mark.eventstore
    def test_auto_correlation_id_consistent_across_chain(self, test_domain, order_id):
        """When no explicit correlation_id is provided, the auto-generated one
        is consistent across all events in the chain."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2

        correlation_ids = {e.metadata.domain.correlation_id for e in events}
        assert len(correlation_ids) == 1
        assert None not in correlation_ids

    @pytest.mark.eventstore
    def test_event_types_in_chain(self, test_domain, order_id):
        """Chain produces both OrderPlaced and OrderConfirmed events."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2

        event_types = [m.metadata.headers.type for m in events]
        assert OrderPlaced.__type__ in event_types
        assert OrderConfirmed.__type__ in event_types

    @pytest.mark.eventstore
    def test_projection_traceable_to_original_command(self, test_domain, order_id):
        """The full chain from command to projection is traceable via the
        shared correlation_id across commands and events."""
        external_corr = "e2e-trace-projection"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            asynchronous=False,
            correlation_id=external_corr,
        )

        # Verify command has the correlation_id
        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        assert commands[0].metadata.domain.correlation_id == external_corr

        # Verify events have the same correlation_id
        events = _read_events(test_domain, order_id)
        assert len(events) >= 2
        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == external_corr

        # Verify the projection was created (proof the chain completed)
        summary = test_domain.repository_for(OrderSummary).get(order_id)
        assert summary is not None


# ===========================================================================
# Scenario 2: External correlation_id propagation through event handler chains
# ===========================================================================
class TestExternalCorrelationIdE2E:
    """Caller-provided correlation_id via domain.process() → command → events →
    handler-dispatched commands — the exact external ID appears on all
    messages in the event store and the causation tree.
    """

    @pytest.fixture(autouse=True)
    def register_chain_handler(self, test_domain):
        """Register the auto-confirm handler for chaining."""
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_external_id_on_all_events_in_chain(self, test_domain, order_id):
        """External correlation_id propagates through event handler chain."""
        external_id = "caller-provided-id"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Bob", amount=50.0),
            asynchronous=False,
            correlation_id=external_id,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2, (
            f"Expected OrderPlaced + OrderConfirmed, got {len(events)}"
        )

        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_external_id_on_root_command(self, test_domain, order_id):
        """The root command in the event store carries the external correlation_id."""
        external_id = "caller-provided-id"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Bob", amount=50.0),
            asynchronous=False,
            correlation_id=external_id,
        )

        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        assert commands[0].metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_external_id_consistent_with_causation_tree(self, test_domain, order_id):
        """The causation tree for the external correlation_id has the expected
        structure: root command with event children."""
        external_id = "caller-provided-id"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Bob", amount=50.0),
            asynchronous=False,
            correlation_id=external_id,
        )

        tree = test_domain.event_store.store.build_causation_tree(external_id)
        assert tree is not None, "Expected a causation tree root node"

        def _count_nodes(node):
            count = 1
            for child in node.children:
                count += _count_nodes(child)
            return count

        total = _count_nodes(tree)
        assert total >= 2, (
            f"Expected command + events in tree, got {total}"
        )


# ===========================================================================
# Scenario 3: Command correlation_id → event context propagation
#
# This scenario verifies that when a command is dispatched into the domain
# with an explicit correlation_id (as a subscriber would do after decoding a
# broker message), the generated events preserve that same correlation_id.
# ===========================================================================
class TestCommandCorrelationPropagation:
    """Verify that commands dispatched with a correlation_id (simulating a
    subscriber passing along a broker-provided ID) produce events with the
    same correlation_id.
    """

    @pytest.mark.eventstore
    def test_subscriber_style_correlation_propagation(self, test_domain, order_id):
        """Simulate a subscriber dispatching a command with a broker-provided
        correlation_id — events inherit the same ID."""
        broker_corr_id = "broker-msg-correlation-xyz"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Charlie", amount=75.0),
            asynchronous=False,
            correlation_id=broker_corr_id,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 1
        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == broker_corr_id

    @pytest.mark.eventstore
    def test_auto_generated_correlation_when_no_broker_id(self, test_domain, order_id):
        """When no correlation_id is provided (broker message without one),
        an auto-generated ID is used consistently."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Diana", amount=120.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        auto_corr = commands[0].metadata.domain.correlation_id
        assert auto_corr is not None

        events = _read_events(test_domain, order_id)
        assert len(events) >= 1
        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == auto_corr

    @pytest.mark.eventstore
    def test_chained_handler_preserves_broker_correlation(self, test_domain, order_id):
        """When a subscriber triggers a command chain, correlation_id is
        preserved through event handler dispatches."""
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

        broker_corr_id = "broker-chain-corr"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Eve", amount=200.0),
            asynchronous=False,
            correlation_id=broker_corr_id,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2, (
            f"Expected OrderPlaced + OrderConfirmed, got {len(events)}"
        )
        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == broker_corr_id


# ===========================================================================
# Scenario 4: Event handler raises new command — causation chain correctness
# ===========================================================================
class TestEventHandlerCausationChain:
    """Event handler processes Event1 (correlation_id=X, causation_id=cmd.id);
    handler dispatches NewCommand; NewCommand inherits correlation_id=X.

    In sync mode, g.message_in_context points to the root command during
    UoW.commit() event handler dispatch, so chained events inherit the
    root command's ID as their causation_id.
    """

    @pytest.fixture(autouse=True)
    def register_event_handler(self, test_domain):
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

    @pytest.mark.eventstore
    def test_chained_command_inherits_correlation_id(self, test_domain, order_id):
        """Command dispatched by event handler has same correlation_id as parent."""
        external_corr = "causation-chain-corr"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Frank", amount=150.0),
            asynchronous=False,
            correlation_id=external_corr,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2

        # Both events share the same correlation_id
        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == external_corr

    @pytest.mark.eventstore
    def test_first_event_causation_points_to_command(self, test_domain, order_id):
        """OrderPlaced event's causation_id = PlaceOrder command's headers.id."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Frank", amount=150.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        root_cmd_id = commands[0].metadata.headers.id

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2

        # First event (OrderPlaced) caused by root command
        assert events[0].metadata.domain.causation_id == root_cmd_id

    @pytest.mark.eventstore
    def test_chained_event_causation_points_to_root_command(self, test_domain, order_id):
        """OrderConfirmed (from chained ConfirmOrder) has causation_id = root command ID.

        In sync mode, g.message_in_context still points to the root command
        during UoW.commit() event handler dispatch, so the chained command and
        its events inherit the root command's ID as their causation_id.
        """
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Frank", amount=150.0),
            asynchronous=False,
        )

        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        root_cmd_id = commands[0].metadata.headers.id

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2

        confirmed_event = next(
            e for e in events if e.metadata.headers.type == OrderConfirmed.__type__
        )
        assert confirmed_event.metadata.domain.causation_id == root_cmd_id

    @pytest.mark.eventstore
    def test_chained_events_causation_ids_are_not_self_referential(
        self, test_domain, order_id
    ):
        """No event's causation_id equals its own headers.id."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Frank", amount=150.0),
            asynchronous=False,
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2

        for event_msg in events:
            assert event_msg.metadata.domain.causation_id != event_msg.metadata.headers.id


# ===========================================================================
# Scenario 5: OTEL span attribute verification
# ===========================================================================
class TestOtelSpanCorrelationAttributes:
    """Verify that OTEL spans carry the correct correlation_id attributes.

    Uses in-memory OTEL exporter — no external services required, so these
    are core tests (no adapter marker needed).
    """

    def test_handler_execute_span_has_correlation_id(
        self, test_domain, span_exporter, order_id
    ):
        """protean.handler.execute span has protean.correlation_id attribute."""
        external_corr = "otel-corr-handler"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Grace", amount=80.0),
            asynchronous=False,
            correlation_id=external_corr,
        )

        spans = span_exporter.get_finished_spans()
        handler_spans = [s for s in spans if s.name == "protean.handler.execute"]
        assert len(handler_spans) >= 1, "Expected at least one handler.execute span"

        for hs in handler_spans:
            assert hs.attributes.get("protean.correlation_id") == external_corr

    def test_uow_commit_span_has_correlation_id(
        self, test_domain, span_exporter, order_id
    ):
        """At least one protean.uow.commit span has protean.correlation_id."""
        external_corr = "otel-corr-uow"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Henry", amount=60.0),
            asynchronous=False,
            correlation_id=external_corr,
        )

        spans = span_exporter.get_finished_spans()
        uow_spans = [s for s in spans if s.name == "protean.uow.commit"]
        assert len(uow_spans) >= 1, "Expected at least one uow.commit span"

        uow_spans_with_corr = [
            s
            for s in uow_spans
            if s.attributes.get("protean.correlation_id") == external_corr
        ]
        assert len(uow_spans_with_corr) >= 1, (
            "Expected at least one uow.commit span with correlation_id"
        )

    def test_command_process_span_has_correlation_id(
        self, test_domain, span_exporter, order_id
    ):
        """protean.command.process span has protean.correlation_id attribute."""
        external_corr = "otel-corr-process"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Ivy", amount=45.0),
            asynchronous=False,
            correlation_id=external_corr,
        )

        spans = span_exporter.get_finished_spans()
        process_spans = [s for s in spans if s.name == "protean.command.process"]
        assert len(process_spans) >= 1, "Expected at least one command.process span"

        for ps in process_spans:
            assert ps.attributes.get("protean.correlation_id") == external_corr

    def test_all_spans_share_same_correlation_id(
        self, test_domain, span_exporter, order_id
    ):
        """All protean.* spans for the same request share the same correlation_id."""
        external_corr = "otel-corr-unified"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Jack", amount=30.0),
            asynchronous=False,
            correlation_id=external_corr,
        )

        spans = span_exporter.get_finished_spans()
        protean_spans = [s for s in spans if s.name.startswith("protean.")]
        assert len(protean_spans) >= 3, (
            f"Expected at least process + handler + uow spans, got {len(protean_spans)}"
        )

        spans_with_corr = [
            s
            for s in protean_spans
            if s.attributes.get("protean.correlation_id") is not None
        ]
        assert len(spans_with_corr) >= 3, (
            f"Expected at least 3 spans with correlation_id, got {len(spans_with_corr)}"
        )

        for s in spans_with_corr:
            assert s.attributes["protean.correlation_id"] == external_corr

    def test_handler_execute_span_has_causation_id(
        self, test_domain, span_exporter, order_id
    ):
        """protean.handler.execute span has both protean.correlation_id and
        protean.causation_id attributes when processing a chained command."""
        test_domain.register(OrderPlacedAutoConfirmHandler, part_of=Order)
        test_domain.init(traverse=False)

        external_corr = "otel-causation-chain"
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Kate", amount=110.0),
            asynchronous=False,
            correlation_id=external_corr,
        )

        spans = span_exporter.get_finished_spans()
        handler_spans = [s for s in spans if s.name == "protean.handler.execute"]
        assert len(handler_spans) >= 1

        # All handler spans should have correlation_id
        for hs in handler_spans:
            assert hs.attributes.get("protean.correlation_id") == external_corr

        # The chained handler (processing ConfirmOrder) should have causation_id
        # pointing to the root command's message ID
        spans_with_causation = [
            s
            for s in handler_spans
            if s.attributes.get("protean.causation_id") is not None
        ]
        assert len(spans_with_causation) >= 1, (
            "Expected at least one handler span with causation_id"
        )
        for hs in spans_with_causation:
            assert hs.attributes["protean.causation_id"] != ""

    def test_auto_generated_correlation_id_on_spans(
        self, test_domain, span_exporter, order_id
    ):
        """When no external correlation_id is provided, spans still carry
        the auto-generated one, and all spans share the same value."""
        test_domain.process(
            PlaceOrder(order_id=order_id, customer="Leo", amount=25.0),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        spans_with_corr = [
            s
            for s in spans
            if s.name.startswith("protean.")
            and s.attributes.get("protean.correlation_id") is not None
        ]
        assert len(spans_with_corr) >= 3

        # All should share the same auto-generated correlation_id
        corr_ids = {s.attributes["protean.correlation_id"] for s in spans_with_corr}
        assert len(corr_ids) == 1
        assert None not in corr_ids

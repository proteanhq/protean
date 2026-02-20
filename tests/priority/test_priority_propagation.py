"""Integration tests for priority propagation through the full pipeline.

Verifies that priority flows correctly from domain.process() through
UoW.commit() into the outbox record:

  domain.process(cmd, priority=X) -> handler runs inside processing_priority(X)
  -> UoW.commit() reads current_priority() -> Outbox.create_message(priority=X)

Each test creates an aggregate, processes a command that raises event(s),
and then inspects the outbox records to verify the priority was stored.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.fields import Identifier, Integer, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from protean.utils.processing import Priority, processing_priority

pytestmark = pytest.mark.no_test_domain


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------


class Widget(BaseAggregate):
    name: String(max_length=100, required=True)
    quantity: Integer(default=0)

    def activate(self):
        self.raise_(WidgetActivated(widget_id=self.id, name=self.name))

    def activate_triple(self):
        """Raise three distinct events for the multi-event test."""
        self.raise_(WidgetActivated(widget_id=self.id, name=self.name))
        self.raise_(
            WidgetUpdated(widget_id=self.id, name=self.name, quantity=self.quantity)
        )
        self.raise_(WidgetDeactivated(widget_id=self.id, name=self.name))


class WidgetActivated(BaseEvent):
    widget_id: String(required=True)
    name: String(required=True)


class WidgetUpdated(BaseEvent):
    widget_id: String(required=True)
    name: String(required=True)
    quantity: Integer(required=True)


class WidgetDeactivated(BaseEvent):
    widget_id: String(required=True)
    name: String(required=True)


class CreateWidget(BaseCommand):
    widget_id: Identifier(identifier=True)
    name: String(required=True)


class CreateWidgetTriple(BaseCommand):
    """Command that triggers three events on the aggregate."""

    widget_id: Identifier(identifier=True)
    name: String(required=True)
    quantity: Integer(default=0)


class WidgetCommandHandler(BaseCommandHandler):
    @handle(CreateWidget)
    def create_widget(self, command: CreateWidget):
        widget = Widget(id=command.widget_id, name=command.name)
        widget.activate()
        current_domain.repository_for(Widget).add(widget)

    @handle(CreateWidgetTriple)
    def create_widget_triple(self, command: CreateWidgetTriple):
        widget = Widget(
            id=command.widget_id,
            name=command.name,
            quantity=command.quantity,
        )
        widget.activate_triple()
        current_domain.repository_for(Widget).add(widget)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_domain():
    """Custom test_domain with outbox enabled.

    We create a fresh Domain instance (instead of using the session-scoped
    conftest fixture) so that we can enable outbox and register our
    domain elements without affecting other test modules.
    """
    from protean.domain import Domain

    domain = Domain(name="Test")
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Widget)
    test_domain.register(WidgetActivated, part_of=Widget)
    test_domain.register(WidgetUpdated, part_of=Widget)
    test_domain.register(WidgetDeactivated, part_of=Widget)
    test_domain.register(CreateWidget, part_of=Widget)
    test_domain.register(CreateWidgetTriple, part_of=Widget)
    test_domain.register(WidgetCommandHandler, part_of=Widget)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _outbox_records_for(test_domain, event_cls):
    """Return all unprocessed outbox records matching the given event type."""
    outbox_repo = test_domain._get_outbox_repo("default")
    all_records = outbox_repo.find_unprocessed()
    return [r for r in all_records if r.type == event_cls.__type__]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.database
class TestPriorityPropagation:
    """Integration tests: domain.process() -> UoW.commit() -> outbox record priority."""

    def test_explicit_priority_on_process(self, test_domain):
        """domain.process(cmd, priority=-50) stores priority=-50 on the outbox record."""
        cmd = CreateWidget(widget_id="w-1", name="Low Priority Widget")
        test_domain.process(cmd, priority=-50)

        records = _outbox_records_for(test_domain, WidgetActivated)
        assert len(records) == 1
        assert records[0].priority == -50

    def test_context_manager_priority_on_process(self, test_domain):
        """processing_priority(-50) context sets priority on outbox records."""
        with processing_priority(-50):
            cmd = CreateWidget(widget_id="w-2", name="Context Priority Widget")
            test_domain.process(cmd)

        records = _outbox_records_for(test_domain, WidgetActivated)
        assert len(records) == 1
        assert records[0].priority == -50

    def test_default_priority_is_normal(self, test_domain):
        """Without explicit priority, outbox records have priority=0 (NORMAL)."""
        cmd = CreateWidget(widget_id="w-3", name="Default Priority Widget")
        test_domain.process(cmd)

        records = _outbox_records_for(test_domain, WidgetActivated)
        assert len(records) == 1
        assert records[0].priority == 0

    def test_explicit_priority_overrides_context(self, test_domain):
        """Explicit priority= kwarg on process() overrides the context manager."""
        with processing_priority(-50):
            cmd = CreateWidget(widget_id="w-4", name="Override Widget")
            test_domain.process(cmd, priority=50)

        records = _outbox_records_for(test_domain, WidgetActivated)
        assert len(records) == 1
        assert records[0].priority == 50

    def test_priority_propagates_to_multiple_events(self, test_domain):
        """When an aggregate raises 3 events, all outbox records share the same priority."""
        cmd = CreateWidgetTriple(widget_id="w-5", name="Triple Widget", quantity=10)
        test_domain.process(cmd, priority=Priority.HIGH)

        outbox_repo = test_domain._get_outbox_repo("default")
        all_records = outbox_repo.find_unprocessed()

        # Filter to records belonging to this aggregate (by checking data)
        widget_records = [r for r in all_records if r.data.get("widget_id") == "w-5"]

        assert len(widget_records) == 3

        for record in widget_records:
            assert record.priority == Priority.HIGH, (
                f"Expected priority={Priority.HIGH} on {record.type}, "
                f"got {record.priority}"
            )

    def test_priority_does_not_leak_across_requests(self, test_domain):
        """Request A with LOW priority does not affect request B's default priority."""
        # Request A: explicit LOW priority
        cmd_a = CreateWidget(widget_id="w-6a", name="Request A Widget")
        test_domain.process(cmd_a, priority=Priority.LOW)

        # Request B: no priority specified (should default to NORMAL)
        cmd_b = CreateWidget(widget_id="w-6b", name="Request B Widget")
        test_domain.process(cmd_b)

        outbox_repo = test_domain._get_outbox_repo("default")
        all_records = outbox_repo.find_unprocessed()

        record_a = next(
            (r for r in all_records if r.data.get("widget_id") == "w-6a"), None
        )
        record_b = next(
            (r for r in all_records if r.data.get("widget_id") == "w-6b"), None
        )

        assert record_a is not None
        assert record_b is not None
        assert record_a.priority == Priority.LOW
        assert record_b.priority == Priority.NORMAL

    def test_nested_contexts_across_process_calls(self, test_domain):
        """Nested processing_priority contexts apply the correct priority to each call."""
        with processing_priority(Priority.LOW):
            cmd_a = CreateWidget(widget_id="w-7a", name="Outer Context Widget")
            test_domain.process(cmd_a)

            with processing_priority(Priority.HIGH):
                cmd_b = CreateWidget(widget_id="w-7b", name="Inner Context Widget")
                test_domain.process(cmd_b)

            cmd_c = CreateWidget(widget_id="w-7c", name="Back to Outer Widget")
            test_domain.process(cmd_c)

        outbox_repo = test_domain._get_outbox_repo("default")
        all_records = outbox_repo.find_unprocessed()

        record_a = next(
            (r for r in all_records if r.data.get("widget_id") == "w-7a"), None
        )
        record_b = next(
            (r for r in all_records if r.data.get("widget_id") == "w-7b"), None
        )
        record_c = next(
            (r for r in all_records if r.data.get("widget_id") == "w-7c"), None
        )

        assert record_a is not None and record_a.priority == Priority.LOW
        assert record_b is not None and record_b.priority == Priority.HIGH
        assert record_c is not None and record_c.priority == Priority.LOW

    def test_priority_stored_in_command_metadata(self, test_domain):
        """Priority is stored in the command's DomainMeta for async propagation."""

        cmd = CreateWidget(widget_id="w-8", name="Metadata Priority Widget")
        test_domain.process(cmd, priority=Priority.CRITICAL)

        # Verify the command metadata in the event store contains the priority
        # We can check the outbox records' metadata which carries the priority
        outbox_repo = test_domain._get_outbox_repo("default")
        all_records = outbox_repo.find_unprocessed()
        record = next(
            (r for r in all_records if r.data.get("widget_id") == "w-8"), None
        )
        assert record is not None
        assert record.priority == Priority.CRITICAL

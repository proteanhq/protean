"""Tests for trace context propagation in synchronous mode.

Verifies that in sync mode (asynchronous=False):
1. ``domain.process()`` -> command handler -> ``aggregate.raise_()`` -> events
   correctly propagates trace context.
2. ``g.message_in_context`` is set during handler execution and cleaned up after.
3. Events raised during handler execution pick up trace IDs from the context.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.utils.eventing import Message
from protean.utils.globals import current_domain, g
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Captured context for assertions
# ---------------------------------------------------------------------------
_captured_context: dict = {}


def _reset_captured():
    _captured_context.clear()


# ---------------------------------------------------------------------------
# Domain elements with context-capturing command handler
# ---------------------------------------------------------------------------
class TaskCreated(BaseEvent):
    task_id = Identifier(required=True)
    title = String(required=True)


class TaskCompleted(BaseEvent):
    task_id = Identifier(required=True)


class CreateTask(BaseCommand):
    task_id = Identifier(identifier=True)
    title = String(required=True)


class CompleteTask(BaseCommand):
    task_id = Identifier(identifier=True)


class Task(BaseAggregate):
    task_id = Identifier(identifier=True)
    title = String(required=True)
    status = String(default="PENDING")

    @classmethod
    def create(cls, task_id: str, title: str) -> "Task":
        task = cls._create_new(task_id=task_id)
        task.raise_(TaskCreated(task_id=task_id, title=title))
        return task

    def complete(self) -> None:
        self.raise_(TaskCompleted(task_id=self.task_id))

    @apply
    def on_created(self, event: TaskCreated) -> None:
        self.task_id = event.task_id
        self.title = event.title
        self.status = "CREATED"

    @apply
    def on_completed(self, event: TaskCompleted) -> None:
        self.status = "COMPLETED"


class ContextCapturingHandler(BaseCommandHandler):
    """Command handler that captures ``g.message_in_context`` during execution."""

    @handle(CreateTask)
    def handle_create(self, command: CreateTask) -> str:
        # Capture the message_in_context during handler execution
        if hasattr(g, "message_in_context"):
            msg = g.message_in_context
            _captured_context["during_handler"] = {
                "has_context": True,
                "message_type": msg.metadata.headers.type,
                "correlation_id": msg.metadata.domain.correlation_id,
                "causation_id": msg.metadata.domain.causation_id,
                "headers_id": msg.metadata.headers.id,
            }
        else:
            _captured_context["during_handler"] = {"has_context": False}

        task = Task.create(task_id=command.task_id, title=command.title)
        current_domain.repository_for(Task).add(task)
        return task.task_id

    @handle(CompleteTask)
    def handle_complete(self, command: CompleteTask) -> None:
        # Capture context during the second command
        if hasattr(g, "message_in_context"):
            msg = g.message_in_context
            _captured_context["during_second_handler"] = {
                "has_context": True,
                "correlation_id": msg.metadata.domain.correlation_id,
            }
        else:
            _captured_context["during_second_handler"] = {"has_context": False}

        repo = current_domain.repository_for(Task)
        task = repo.get(command.task_id)
        task.complete()
        repo.add(task)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Task, is_event_sourced=True)
    test_domain.register(TaskCreated, part_of=Task)
    test_domain.register(TaskCompleted, part_of=Task)
    test_domain.register(CreateTask, part_of=Task)
    test_domain.register(CompleteTask, part_of=Task)
    test_domain.register(ContextCapturingHandler, part_of=Task)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def reset_context():
    _reset_captured()
    yield
    _reset_captured()


@pytest.fixture
def task_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _read_events(test_domain, task_id: str) -> list[Message]:
    stream = f"{Task.meta_.stream_category}-{task_id}"
    return test_domain.event_store.store.read(stream)


def _read_commands(test_domain, task_id: str) -> list[Message]:
    stream = f"{Task.meta_.stream_category}:command-{task_id}"
    return test_domain.event_store.store.read(stream)


# ---------------------------------------------------------------------------
# Tests: g.message_in_context lifecycle
# ---------------------------------------------------------------------------
class TestMessageInContextLifecycle:
    @pytest.mark.eventstore
    def test_message_in_context_is_set_during_handler(self, test_domain, task_id):
        """g.message_in_context is set to the command Message during handler execution."""
        test_domain.process(
            CreateTask(task_id=task_id, title="Test task"),
            asynchronous=False,
        )

        assert _captured_context["during_handler"]["has_context"] is True

    @pytest.mark.eventstore
    def test_message_in_context_has_correct_type(self, test_domain, task_id):
        """The message_in_context has the correct message type."""
        test_domain.process(
            CreateTask(task_id=task_id, title="Test task"),
            asynchronous=False,
        )

        ctx = _captured_context["during_handler"]
        assert ctx["message_type"] == CreateTask.__type__

    @pytest.mark.eventstore
    def test_message_in_context_cleaned_up_after_processing(self, test_domain, task_id):
        """g.message_in_context is cleaned up after domain.process() completes."""
        test_domain.process(
            CreateTask(task_id=task_id, title="Test task"),
            asynchronous=False,
        )

        # After domain.process() returns, message_in_context should be removed
        assert not hasattr(g, "message_in_context")

    @pytest.mark.eventstore
    def test_message_in_context_contains_correlation_id(self, test_domain, task_id):
        """The message_in_context has the correlation_id set during handler execution."""
        external_id = "ctx-corr-123"

        test_domain.process(
            CreateTask(task_id=task_id, title="Test task"),
            asynchronous=False,
            correlation_id=external_id,
        )

        ctx = _captured_context["during_handler"]
        assert ctx["correlation_id"] == external_id

    @pytest.mark.eventstore
    def test_message_in_context_root_command_no_causation(self, test_domain, task_id):
        """For a root command, the message_in_context has causation_id = None."""
        test_domain.process(
            CreateTask(task_id=task_id, title="Test task"),
            asynchronous=False,
        )

        ctx = _captured_context["during_handler"]
        assert ctx["causation_id"] is None


# ---------------------------------------------------------------------------
# Tests: Trace propagation through the full sync pipeline
# ---------------------------------------------------------------------------
class TestSyncPipelinePropagation:
    @pytest.mark.eventstore
    def test_correlation_flows_from_process_to_handler_to_event(
        self, test_domain, task_id
    ):
        """Correlation ID flows: domain.process() -> command -> handler -> event."""
        external_id = "e2e-corr-abc"

        test_domain.process(
            CreateTask(task_id=task_id, title="End-to-end test"),
            asynchronous=False,
            correlation_id=external_id,
        )

        # 1. Handler saw the correlation_id
        assert _captured_context["during_handler"]["correlation_id"] == external_id

        # 2. Command in event store has the correlation_id
        cmd_msgs = _read_commands(test_domain, task_id)
        assert cmd_msgs[0].metadata.domain.correlation_id == external_id

        # 3. Event in event store has the same correlation_id
        event_msgs = _read_events(test_domain, task_id)
        assert len(event_msgs) >= 1
        assert event_msgs[0].metadata.domain.correlation_id == external_id

    @pytest.mark.eventstore
    def test_causation_flows_from_command_to_event(self, test_domain, task_id):
        """Causation ID flows: command's headers.id becomes event's causation_id."""
        test_domain.process(
            CreateTask(task_id=task_id, title="Causation test"),
            asynchronous=False,
        )

        # The handler's context headers.id should match the command's ID
        cmd_msgs = _read_commands(test_domain, task_id)
        command_id = cmd_msgs[0].metadata.headers.id

        # Verify the handler saw this as the message ID
        assert _captured_context["during_handler"]["headers_id"] == command_id

        # Verify the event's causation_id matches
        event_msgs = _read_events(test_domain, task_id)
        assert event_msgs[0].metadata.domain.causation_id == command_id

    @pytest.mark.eventstore
    def test_auto_generated_correlation_id_flows_through_entire_pipeline(
        self, test_domain, task_id
    ):
        """When no external correlation_id is provided, the auto-generated one
        flows consistently through command -> handler -> event."""
        test_domain.process(
            CreateTask(task_id=task_id, title="Auto-corr test"),
            asynchronous=False,
        )

        handler_corr = _captured_context["during_handler"]["correlation_id"]
        assert handler_corr is not None

        cmd_msgs = _read_commands(test_domain, task_id)
        assert cmd_msgs[0].metadata.domain.correlation_id == handler_corr

        event_msgs = _read_events(test_domain, task_id)
        assert event_msgs[0].metadata.domain.correlation_id == handler_corr

    @pytest.mark.eventstore
    def test_sequential_process_calls_have_independent_contexts(
        self, test_domain, task_id
    ):
        """Each domain.process() call gets its own message_in_context
        and correlation_id (when not provided externally)."""
        test_domain.process(
            CreateTask(task_id=task_id, title="First call"),
            asynchronous=False,
        )
        first_corr = _captured_context["during_handler"]["correlation_id"]

        test_domain.process(
            CompleteTask(task_id=task_id),
            asynchronous=False,
        )
        second_corr = _captured_context["during_second_handler"]["correlation_id"]

        # Both should have correlation IDs, but they should differ
        # since each is a separate root call
        assert first_corr is not None
        assert second_corr is not None
        assert first_corr != second_corr

    @pytest.mark.eventstore
    def test_context_cleanup_between_process_calls(self, test_domain, task_id):
        """g.message_in_context is cleaned up between sequential domain.process() calls."""
        test_domain.process(
            CreateTask(task_id=task_id, title="First"),
            asynchronous=False,
        )

        # After first call completes, context should be clean
        assert not hasattr(g, "message_in_context")

        test_domain.process(
            CompleteTask(task_id=task_id),
            asynchronous=False,
        )

        # After second call completes, context should be clean again
        assert not hasattr(g, "message_in_context")

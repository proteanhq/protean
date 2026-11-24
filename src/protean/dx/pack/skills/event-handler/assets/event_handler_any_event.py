"""
Event handler using @handle("$any") to catch all events on a stream.

This example demonstrates:
- The $any catch-all handler pattern
- Using @handle("$any") to process any event on the stream
- Useful for logging, metrics, auditing, or event forwarding
- Only one $any handler method is allowed per event handler class
- $any acts as a fallback: specific handlers take precedence
- Keying each audit entry on the event's id, so a redelivered event adds nothing

Usage:
    task = Task(task_id="TASK-001", title="Write docs", assignee="alice")
    task.create()
    domain.repository_for(Task).add(task)
    # TaskAuditor processes TaskCreated via $any handler
"""

from protean import Domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String, Text

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="Task")
class TaskCreated:
    """Event raised when a task is created."""

    task_id: Identifier(required=True)
    title: String(required=True)
    assignee: String(required=True)


@domain.event(part_of="Task")
class TaskCompleted:
    """Event raised when a task is completed."""

    task_id: Identifier(required=True)


@domain.aggregate
class Task:
    """Task aggregate for tracking work items."""

    task_id: Identifier(identifier=True)
    title: String(required=True)
    assignee: String(required=True)
    status: String(default="pending")

    def create(self):
        """Create the task, raising TaskCreated event."""
        self.status = "open"
        self.raise_(
            TaskCreated(
                task_id=self.task_id,
                title=self.title,
                assignee=self.assignee,
            )
        )

    def complete(self):
        """Complete the task, raising TaskCompleted event."""
        if self.status != "open":
            raise ValueError(f"Cannot complete task in '{self.status}' status")
        self.status = "completed"
        self.raise_(TaskCompleted(task_id=self.task_id))


@domain.aggregate
class AuditLog:
    """Audit log aggregate for recording all domain activity.

    `entry_id` is the id of the audited event. Events are delivered at least
    once, so the same event can arrive again, and its id tells the handler the
    entry exists.
    """

    entry_id: Identifier(identifier=True)
    event_type: String(required=True)
    details: Text(required=True)


@domain.event_handler(part_of=AuditLog, stream_category=Task.meta_.stream_category)
class TaskAuditor:
    """Event handler that audits ALL events on the Task stream.

    Uses @handle("$any") to catch any event published on the Task stream,
    regardless of event type. This is useful for:

    - Audit logging: Record all events for compliance
    - Metrics: Count events for monitoring
    - Event forwarding: Relay events to external systems
    - Debugging: Log all events during development

    Only ONE @handle("$any") method is allowed per event handler class.
    If a specific @handle(EventClass) method exists for an event type,
    it takes precedence over the $any handler for that event.
    """

    @handle("$any")
    def on_any_task_event(self, event):
        """Handle any event on the Task stream.

        Creates one audit log entry per event, capturing the event type and
        a text representation. A redelivered event finds its entry and adds
        nothing.
        """
        repository = domain.repository_for(AuditLog)
        entry_id = event._metadata.headers.id
        try:
            repository.get(entry_id)
        except ObjectNotFoundError:
            repository.add(
                AuditLog(
                    entry_id=entry_id,
                    event_type=event.__class__.__name__,
                    details=(
                        f"Event received: {event.__class__.__name__}"
                        f" - {event.to_dict()}"
                    ),
                )
            )
        else:
            return  # already recorded; a redelivered event must not log twice


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a task - auditor catches TaskCreated
        task = Task(
            task_id="TASK-001",
            title="Write documentation",
            assignee="alice",
        )
        task.create()
        domain.repository_for(Task).add(task)
        print("Task created - audit log entry created")

        # Complete the task - auditor catches TaskCompleted
        task.complete()
        domain.repository_for(Task).add(task)
        print("Task completed - audit log entry created")

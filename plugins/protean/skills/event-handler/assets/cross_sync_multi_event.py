"""
Cross-aggregate sync with multiple events from one source.

This example demonstrates:
- Multiple events from the same source aggregate (Task)
- Event handler reacting to different events with different behavior
- Target aggregate (TeamMember) tracks workload from task events
- Handler incrementing and decrementing counts based on events

Domain: A project management system where TeamMember aggregate
tracks workload (assigned_count, completed_count) based on
Task lifecycle events.
"""

from protean import Domain, handle
from protean.fields import Identifier, Integer, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Task")
class TaskAssigned:
    """Raised when a task is assigned to a team member."""

    task_id: Identifier(required=True)
    assignee_id: Identifier(required=True)


@domain.event(part_of="Task")
class TaskCompleted:
    """Raised when a task is completed."""

    task_id: Identifier(required=True)
    assignee_id: Identifier(required=True)


@domain.event(part_of="Task")
class TaskUnassigned:
    """Raised when a task is unassigned from a team member."""

    task_id: Identifier(required=True)
    assignee_id: Identifier(required=True)


# --- Source Aggregate: Task ---


@domain.aggregate
class Task:
    """Task aggregate (source of events)."""

    title: String(required=True, max_length=200)
    assignee_id: Identifier()
    status: String(default="open")

    def assign_to(self, assignee_id):
        """Assign this task to a team member."""
        self.assignee_id = assignee_id
        self.status = "assigned"
        self.raise_(TaskAssigned(task_id=self.id, assignee_id=assignee_id))

    def complete(self):
        """Mark this task as completed."""
        self.status = "completed"
        self.raise_(TaskCompleted(task_id=self.id, assignee_id=self.assignee_id))

    def unassign(self):
        """Unassign this task."""
        previous_assignee = self.assignee_id
        self.assignee_id = None
        self.status = "open"
        self.raise_(TaskUnassigned(task_id=self.id, assignee_id=previous_assignee))


# --- Target Aggregate: TeamMember ---


@domain.aggregate
class TeamMember:
    """TeamMember aggregate tracking workload (target of sync)."""

    member_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    assigned_count: Integer(default=0)
    completed_count: Integer(default=0)


# --- Cross-Aggregate Event Handler ---


@domain.event_handler(
    part_of=TeamMember,
    stream_category=Task.meta_.stream_category,
)
class WorkloadSyncHandler:
    """Syncs TeamMember workload from Task lifecycle events.

    Handles multiple event types from the Task aggregate:
    - TaskAssigned: increment assigned_count
    - TaskCompleted: decrement assigned, increment completed
    - TaskUnassigned: decrement assigned_count
    """

    @handle(TaskAssigned)
    def on_task_assigned(self, event: TaskAssigned):
        """Increment workload when task is assigned."""
        repo = domain.repository_for(TeamMember)
        member = repo.get(event.assignee_id)
        member.assigned_count += 1
        repo.add(member)

    @handle(TaskCompleted)
    def on_task_completed(self, event: TaskCompleted):
        """Move task from assigned to completed count."""
        repo = domain.repository_for(TeamMember)
        member = repo.get(event.assignee_id)
        member.assigned_count -= 1
        member.completed_count += 1
        repo.add(member)

    @handle(TaskUnassigned)
    def on_task_unassigned(self, event: TaskUnassigned):
        """Decrement workload when task is unassigned."""
        repo = domain.repository_for(TeamMember)
        member = repo.get(event.assignee_id)
        member.assigned_count -= 1
        repo.add(member)

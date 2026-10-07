"""
Cross-aggregate sync with multiple events from one source.

This example demonstrates:
- Multiple events from the same source aggregate (Task)
- One event handler in Task's own cluster (part_of=Task) reacting to
  different events with different behavior
- Each event becomes a different command to the target aggregate
  (TeamMember), whose command handler does the write
- TeamMember counts go up and down based on the events
- A redelivered event is a no-op: each command carries the id of the event
  that caused it, and TeamMember records the ids it has already applied

Domain: A project management system where TeamMember aggregate
tracks workload (assigned_count, completed_count) based on
Task lifecycle events.

Usage:
    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(TeamMember).add(
            TeamMember(member_id="M-1", name="Alice")
        )
        task = Task(title="Write docs")
        domain.repository_for(Task).add(task)
        domain.process(AssignTask(task_id=task.id, assignee_id="M-1"))
        # Alice's assigned_count is now 1.
"""

from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

domain = Domain(__name__)

# Run the hop in-process: each Task event reaches the event handler as soon as
# the task is saved, and each command reaches its handler as soon as it is
# issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


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


# --- Commands to Task ---


@domain.command(part_of="Task")
class AssignTask:
    """Assign a task to a team member."""

    task_id: Identifier(required=True)
    assignee_id: Identifier(required=True)


@domain.command(part_of="Task")
class CompleteTask:
    """Mark a task as completed."""

    task_id: Identifier(required=True)


@domain.command(part_of="Task")
class UnassignTask:
    """Take a task away from its assignee."""

    task_id: Identifier(required=True)


# --- Commands to TeamMember ---
#
# `change_id` is the id of the Task event that caused the command. Every
# delivery of one event carries the same id, so TeamMember can tell a repeat
# from a new change. A task can be assigned, unassigned and assigned again, so
# the task id alone cannot tell them apart.


@domain.command(part_of="TeamMember")
class RecordAssignment:
    """Add one task to a member's open workload."""

    member_id: Identifier(required=True)
    change_id: Identifier(required=True)


@domain.command(part_of="TeamMember")
class RecordCompletion:
    """Move one task from a member's open workload to completed."""

    member_id: Identifier(required=True)
    change_id: Identifier(required=True)


@domain.command(part_of="TeamMember")
class RecordUnassignment:
    """Remove one task from a member's open workload."""

    member_id: Identifier(required=True)
    change_id: Identifier(required=True)


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
    """TeamMember aggregate tracking workload (target of sync).

    `applied_change_ids` records which Task events have already changed the
    counts. Changing a count is an update, so the counts alone cannot show
    whether a given event was applied; this list can.
    """

    member_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    assigned_count: Integer(default=0)
    completed_count: Integer(default=0)
    applied_change_ids: List(content_type=String)

    def record_assignment(self, change_id):
        self.assigned_count += 1
        self._mark_applied(change_id)

    def record_completion(self, change_id):
        self.assigned_count -= 1
        self.completed_count += 1
        self._mark_applied(change_id)

    def record_unassignment(self, change_id):
        self.assigned_count -= 1
        self._mark_applied(change_id)

    def _mark_applied(self, change_id):
        self.applied_change_ids = [*self.applied_change_ids, change_id]


# --- Command handlers (the write path for each aggregate) ---


@domain.command_handler(part_of=Task)
class TaskCommandHandler:
    """The write path for Task."""

    @handle(AssignTask)
    def assign_task(self, command: AssignTask):
        repo = current_domain.repository_for(Task)
        task = repo.get(command.task_id)
        task.assign_to(command.assignee_id)
        repo.add(task)

    @handle(CompleteTask)
    def complete_task(self, command: CompleteTask):
        repo = current_domain.repository_for(Task)
        task = repo.get(command.task_id)
        task.complete()
        repo.add(task)

    @handle(UnassignTask)
    def unassign_task(self, command: UnassignTask):
        repo = current_domain.repository_for(Task)
        task = repo.get(command.task_id)
        task.unassign()
        repo.add(task)


@domain.command_handler(part_of=TeamMember)
class TeamMemberCommandHandler:
    """The write path for TeamMember.

    Each method returns without changes when the member has already applied
    the command's change. A redelivered Task event reissues its command, and
    applying it again would count the task twice.
    """

    @handle(RecordAssignment)
    def record_assignment(self, command: RecordAssignment):
        repo = current_domain.repository_for(TeamMember)
        member = repo.get(command.member_id)
        if command.change_id in member.applied_change_ids:
            return
        member.record_assignment(command.change_id)
        repo.add(member)

    @handle(RecordCompletion)
    def record_completion(self, command: RecordCompletion):
        repo = current_domain.repository_for(TeamMember)
        member = repo.get(command.member_id)
        if command.change_id in member.applied_change_ids:
            return
        member.record_completion(command.change_id)
        repo.add(member)

    @handle(RecordUnassignment)
    def record_unassignment(self, command: RecordUnassignment):
        repo = current_domain.repository_for(TeamMember)
        member = repo.get(command.member_id)
        if command.change_id in member.applied_change_ids:
            return
        member.record_unassignment(command.change_id)
        repo.add(member)


# --- The cross-aggregate link: an event handler in Task's cluster ---


@domain.event_handler(part_of=Task)
class WorkloadSyncHandler:
    """Turn Task lifecycle events into TeamMember workload commands.

    The handler sits in Task's cluster because the events belong to Task (a
    handler that reacts to another cluster's event is what `check` reports as
    EVENT_HANDLER_FOREIGN_EVENT). Each event maps to a different command:
    - TaskAssigned: RecordAssignment (increment assigned_count)
    - TaskCompleted: RecordCompletion (decrement assigned, increment completed)
    - TaskUnassigned: RecordUnassignment (decrement assigned_count)

    `event._metadata.headers.id` is the event's own id, the same on every
    delivery of that event.
    """

    @handle(TaskAssigned)
    def on_task_assigned(self, event: TaskAssigned):
        """Ask TeamMember to count the newly assigned task."""
        current_domain.process(
            RecordAssignment(
                member_id=event.assignee_id,
                change_id=event._metadata.headers.id,
            )
        )

    @handle(TaskCompleted)
    def on_task_completed(self, event: TaskCompleted):
        """Ask TeamMember to move the task from assigned to completed."""
        current_domain.process(
            RecordCompletion(
                member_id=event.assignee_id,
                change_id=event._metadata.headers.id,
            )
        )

    @handle(TaskUnassigned)
    def on_task_unassigned(self, event: TaskUnassigned):
        """Ask TeamMember to drop the task from the open workload."""
        current_domain.process(
            RecordUnassignment(
                member_id=event.assignee_id,
                change_id=event._metadata.headers.id,
            )
        )

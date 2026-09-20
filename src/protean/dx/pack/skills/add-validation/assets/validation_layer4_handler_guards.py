"""
Layer 4: Handler/Service Guards

This example demonstrates:
- Authorization guards in command handlers
- Existence checks before aggregate operations
- Context-dependent validation (not inherent to the aggregate)
- Raising ValidationError with clear field-level messages
- Separating handler guards from business rules

Scenario:
    A TaskBoard aggregate with commands to create and assign tasks.
    Handler guards check:
    - Only managers can create tasks
    - Tasks must exist before assignment
    - Assignees must be active team members

Usage:
    domain.process(
        CreateTask(
            board_id="TB-001",
            task_title="Build feature",
            requested_by_role="manager",
        ),
        asynchronous=False,
    )
"""

from protean import Domain, handle
from protean.exceptions import ValidationError
from protean.fields import Auto, HasMany, Identifier, String

# Domain setup
domain = Domain(__name__)


@domain.aggregate
class TaskBoard:
    """Task board aggregate for managing tasks."""

    board_id: Auto(identifier=True)
    name: String(required=True, max_length=100)
    tasks = HasMany("Task")

    def add_task(self, title, description=""):
        """Add a new task to the board."""
        self.add_tasks(Task(title=title, description=description, status="open"))

    def assign_task(self, task_id, assignee):
        """Assign a task to a team member."""
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task is None:
            raise ValidationError(
                {"task_id": [f"Task '{task_id}' not found on this board"]}
            )
        task.assignee = assignee
        task.status = "assigned"


@domain.entity(part_of="TaskBoard")
class Task:
    """Task entity within a task board."""

    title: String(required=True, max_length=200)
    description: String(max_length=1000)
    status: String(max_length=20, default="open")
    assignee: String(max_length=100)


# --- Commands ---


@domain.command(part_of="TaskBoard")
class CreateTask:
    """Command to create a new task on a board."""

    board_id: Identifier(required=True)
    task_title: String(required=True, max_length=200)
    task_description: String(max_length=1000)
    requested_by_role: String(required=True)


@domain.command(part_of="TaskBoard")
class AssignTask:
    """Command to assign a task to a team member."""

    board_id: Identifier(required=True)
    task_id: Identifier(required=True)
    assignee: String(required=True, max_length=100)
    assignee_is_active: String(required=True)  # "true" or "false"


# --- Command Handler with Guards ---

ALLOWED_ROLES = {"manager", "admin", "lead"}


@domain.command_handler(part_of=TaskBoard)
class TaskBoardCommandHandler:
    """Handler with Layer 4 guards for authorization and context checks."""

    @handle(CreateTask)
    def handle_create_task(self, command: CreateTask):
        """Create a task on a board.

        Guards:
        - Only managers/admins/leads can create tasks (authorization)
        - Board must exist (existence check)
        """
        # Guard 1: Authorization check
        if command.requested_by_role not in ALLOWED_ROLES:
            raise ValidationError(
                {
                    "authorization": [
                        f"Role '{command.requested_by_role}' cannot create tasks. "
                        f"Required: {sorted(ALLOWED_ROLES)}"
                    ]
                }
            )

        # Guard 2: Board existence check
        repo = domain.repository_for(TaskBoard)
        board = repo.get(command.board_id)
        # If board doesn't exist, repo.get raises ObjectNotFoundError

        # Proceed with business logic (Layers 1-3 validate automatically)
        board.add_task(
            title=command.task_title,
            description=command.task_description or "",
        )
        repo.add(board)

    @handle(AssignTask)
    def handle_assign_task(self, command: AssignTask):
        """Assign a task to a team member.

        Guards:
        - Board must exist (existence check)
        - Assignee must be active (context-dependent check)
        """
        # Guard 1: Assignee must be active
        if command.assignee_is_active != "true":
            raise ValidationError(
                {
                    "assignee": [
                        f"Cannot assign to '{command.assignee}': team member is not active"
                    ]
                }
            )

        # Guard 2: Board existence
        repo = domain.repository_for(TaskBoard)
        board = repo.get(command.board_id)

        # Proceed with business logic
        board.assign_task(
            task_id=command.task_id,
            assignee=command.assignee,
        )
        repo.add(board)


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Create a board first
        board = TaskBoard(name="Sprint Board")
        domain.repository_for(TaskBoard).add(board)
        board_id = board.board_id

        # Create task with authorized role
        domain.process(
            CreateTask(
                board_id=board_id,
                task_title="Build feature",
                requested_by_role="manager",
            ),
            asynchronous=False,
        )
        print("Task created by manager")

        # Try with unauthorized role
        try:
            domain.process(
                CreateTask(
                    board_id=board_id,
                    task_title="Hack system",
                    requested_by_role="intern",
                ),
                asynchronous=False,
            )
        except ValidationError as e:
            print(f"Unauthorized: {e}")

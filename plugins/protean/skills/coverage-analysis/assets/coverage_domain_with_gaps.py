"""
Domain for coverage analysis demonstration: Issue Tracker.

This example provides a Protean domain with multiple testable elements
across all categories:
- Aggregate with factory method, state transitions, invariants, and event raising
- Value object with custom operation
- Command + command handler
- Event handler for cross-aggregate side effects
- Business rules guarding invalid transitions

Used to demonstrate coverage gap identification and missing test generation.
"""

from protean import Domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Identifier, String, Text, ValueObject

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Value Object ---


@domain.value_object
class Priority:
    """Priority value object with escalation operation.

    The escalate() method is user-defined business logic that should be tested.
    """

    level: String(max_length=10, default="low")

    def escalate(self):
        """Escalate priority: low -> medium -> high -> critical."""
        levels = ["low", "medium", "high", "critical"]
        current_idx = levels.index(self.level)
        if current_idx >= len(levels) - 1:
            raise ValueError(f"Cannot escalate beyond '{self.level}'")
        return Priority(level=levels[current_idx + 1])


# --- Events ---


@domain.event(part_of="Ticket")
class TicketCreated:
    """Raised when a ticket is created."""

    ticket_id: Identifier(required=True)
    title: String(required=True)
    priority_level: String(required=True)


@domain.event(part_of="Ticket")
class TicketAssigned:
    """Raised when a ticket is assigned."""

    ticket_id: Identifier(required=True)
    assignee: String(required=True)


@domain.event(part_of="Ticket")
class TicketClosed:
    """Raised when a ticket is closed."""

    ticket_id: Identifier(required=True)
    resolution: String(required=True)


# --- Aggregate: Ticket ---


@domain.aggregate
class Ticket:
    """Ticket aggregate with business rules, invariants, and event raising."""

    title: String(required=True, max_length=200)
    description: Text()
    status: String(default="open")
    assignee: String(max_length=100)
    priority = ValueObject(Priority)

    # --- Invariants ---

    @invariant.post
    def assigned_ticket_must_have_assignee(self):
        """Assigned tickets must have an assignee set."""
        if self.status == "assigned" and not self.assignee:
            raise ValidationError(
                {"_entity": ["Assigned tickets must have an assignee"]}
            )

    # --- Factory method ---

    @classmethod
    def create(cls, title, description="", priority_level="low"):
        """Factory: create a new open ticket and raise TicketCreated."""
        ticket = cls(
            title=title,
            description=description,
            priority=Priority(level=priority_level),
        )
        ticket.raise_(
            TicketCreated(
                ticket_id=ticket.id,
                title=ticket.title,
                priority_level=priority_level,
            )
        )
        return ticket

    # --- State-change methods ---

    def assign(self, assignee):
        """Assign the ticket. Business rule: cannot assign a closed ticket."""
        if self.status == "closed":
            raise ValueError("Cannot assign a closed ticket")
        self.assignee = assignee
        self.status = "assigned"
        self.raise_(
            TicketAssigned(
                ticket_id=self.id,
                assignee=assignee,
            )
        )

    def close(self, resolution):
        """Close the ticket. Business rule: cannot close an unassigned ticket."""
        if self.status == "open":
            raise ValueError("Cannot close an unassigned ticket")
        self.status = "closed"
        self.raise_(
            TicketClosed(
                ticket_id=self.id,
                resolution=resolution,
            )
        )

    def escalate_priority(self):
        """Escalate the ticket priority using the Priority value object."""
        self.priority = self.priority.escalate()


# --- Notification aggregate (event handler target) ---


@domain.aggregate
class NotificationLog:
    """Simple aggregate to record notifications triggered by ticket events."""

    ticket_id: Identifier(required=True)
    message: String(required=True, max_length=500)


# --- Command ---


@domain.command(part_of="Ticket")
class CreateTicket:
    """Command to create a new ticket."""

    title: String(required=True, max_length=200)
    description: Text()
    priority_level: String(max_length=10, default="low")


# --- Command Handler ---


@domain.command_handler(part_of=Ticket)
class TicketCommandHandler:
    """Handles ticket-related commands."""

    @handle(CreateTicket)
    def handle_create(self, command: CreateTicket):
        """Create ticket via factory, persist, return ID."""
        ticket = Ticket.create(
            title=command.title,
            description=command.description,
            priority_level=command.priority_level,
        )
        domain.repository_for(Ticket).add(ticket)
        return ticket.id


# --- Event Handler (cross-aggregate) ---


@domain.event_handler(
    part_of=NotificationLog, stream_category=Ticket.meta_.stream_category
)
class TicketNotificationHandler:
    """Handles Ticket events to create notification log entries.

    Belongs to NotificationLog aggregate but listens to Ticket's event stream.
    """

    @handle(TicketCreated)
    def on_ticket_created(self, event: TicketCreated):
        """When a ticket is created, log a notification."""
        notification = NotificationLog(
            ticket_id=event.ticket_id,
            message=f"New ticket: {event.title} (priority: {event.priority_level})",
        )
        domain.repository_for(NotificationLog).add(notification)

"""
Domain for coverage analysis demonstration: Issue Tracker.

This example provides a Protean domain with multiple testable elements
across all categories:
- Aggregate with factory method, state transitions, invariants, and event raising
- Value object with custom operation
- Commands + command handlers
- Event handler for a cross-aggregate side effect: it sits in Ticket's cluster,
  reacts to TicketCreated, and issues a RecordNotification command that
  NotificationLog's command handler writes
- A redelivered event is a no-op: the notification log uses the ticket id as
  its identity, so the handler can tell the entry already exists
- Business rules guarding invalid transitions

Used to demonstrate coverage gap identification and missing test generation.
"""

from protean import Domain, current_domain, handle, invariant
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields import Identifier, String, Text, ValueObject

domain = Domain(__name__)

# Run the hop in-process: TicketCreated reaches the event handler when the unit
# of work that saves the ticket commits, and RecordNotification reaches its
# handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


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
    """Simple aggregate to record notifications triggered by ticket events.

    The ticket id is the identity, so there is one entry per created ticket.
    """

    ticket_id: Identifier(identifier=True)
    message: String(required=True, max_length=500)


# --- Commands ---


@domain.command(part_of="Ticket")
class CreateTicket:
    """Command to create a new ticket."""

    title: String(required=True, max_length=200)
    description: Text()
    priority_level: String(max_length=10, default="low")


@domain.command(part_of="NotificationLog")
class RecordNotification:
    """Record the notification for one created ticket.

    `ticket_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell the entry already exists.
    """

    ticket_id: Identifier(required=True)
    message: String(required=True, max_length=500)


# --- Command Handlers ---


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


@domain.command_handler(part_of=NotificationLog)
class NotificationLogCommandHandler:
    """The write path for NotificationLog."""

    @handle(RecordNotification)
    def record_notification(self, command: RecordNotification):
        """Add the notification entry unless it already exists."""
        repo = current_domain.repository_for(NotificationLog)
        try:
            repo.get(command.ticket_id)
        except ObjectNotFoundError:
            repo.add(
                NotificationLog(ticket_id=command.ticket_id, message=command.message)
            )
        else:
            # The entry already exists. A redelivered TicketCreated reissues
            # RecordNotification, and adding again would log it twice.
            return


# --- Event Handler (the cross-aggregate link, in Ticket's cluster) ---


@domain.event_handler(part_of=Ticket)
class TicketNotificationHandler:
    """React to Ticket's own TicketCreated event and record a notification.

    The handler sits in Ticket's cluster, because it reacts to Ticket's own
    event. It hands off to NotificationLog with a command, and NotificationLog's
    command handler does the write.
    """

    @handle(TicketCreated)
    def on_ticket_created(self, event: TicketCreated):
        """When a ticket is created, ask NotificationLog to record it."""
        current_domain.process(
            RecordNotification(
                ticket_id=event.ticket_id,
                message=f"New ticket: {event.title} (priority: {event.priority_level})",
            )
        )

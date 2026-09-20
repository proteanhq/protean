"""
Use case with update and event handler: Load → Mutate → Persist → React.

This example demonstrates:
- Two commands on the same aggregate (create + update pattern)
- Aggregate factory method for creation
- Aggregate instance method for updates
- Event handler reacting to events from the same aggregate
- Full lifecycle: create ticket → assign ticket → event handler logs assignment

Domain: A support ticket system where tickets can be created and assigned,
with an audit log tracking assignments.
"""

from protean import Domain, handle
from protean.fields import Auto, Identifier, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Ticket")
class TicketCreated:
    """Raised when a new support ticket is created."""

    ticket_id: Identifier(required=True)
    title: String(required=True)
    reporter: String(required=True)


@domain.event(part_of="Ticket")
class TicketAssigned:
    """Raised when a ticket is assigned to an agent."""

    ticket_id: Identifier(required=True)
    assignee: String(required=True)


# --- Aggregate ---


@domain.aggregate
class Ticket:
    """Support ticket aggregate."""

    title: String(required=True, max_length=200)
    reporter: String(required=True, max_length=100)
    assignee: String(max_length=100)
    status: String(default="open")

    @classmethod
    def create(cls, title, reporter):
        """Factory: create a new ticket and raise TicketCreated."""
        ticket = cls(title=title, reporter=reporter)
        ticket.raise_(
            TicketCreated(
                ticket_id=ticket.id,
                title=ticket.title,
                reporter=ticket.reporter,
            )
        )
        return ticket

    def assign(self, assignee):
        """Assign the ticket to an agent."""
        self.assignee = assignee
        self.status = "assigned"
        self.raise_(
            TicketAssigned(
                ticket_id=self.id,
                assignee=assignee,
            )
        )


# --- Commands ---


@domain.command(part_of="Ticket")
class CreateTicket:
    """Command to create a new support ticket."""

    title: String(required=True, max_length=200)
    reporter: String(required=True, max_length=100)


@domain.command(part_of="Ticket")
class AssignTicket:
    """Command to assign a ticket to an agent."""

    ticket_id: Identifier(required=True)
    assignee: String(required=True, max_length=100)


# --- Command Handler ---


@domain.command_handler(part_of=Ticket)
class TicketCommandHandler:
    """Handles ticket-related commands."""

    @handle(CreateTicket)
    def handle_create(self, command: CreateTicket):
        """Create a new ticket."""
        ticket = Ticket.create(title=command.title, reporter=command.reporter)
        domain.repository_for(Ticket).add(ticket)

    @handle(AssignTicket)
    def handle_assign(self, command: AssignTicket):
        """Assign a ticket to an agent (update pattern)."""
        ticket = domain.repository_for(Ticket).get(command.ticket_id)
        ticket.assign(assignee=command.assignee)
        domain.repository_for(Ticket).add(ticket)


# --- Audit Log (side effect aggregate) ---


@domain.aggregate
class AuditEntry:
    """Audit log entry for tracking ticket assignments."""

    entry_id: Auto(identifier=True)
    ticket_id: Identifier(required=True)
    action: String(required=True, max_length=50)
    detail: String(max_length=500)


# --- Event Handler ---


@domain.event_handler(part_of=AuditEntry, stream_category=Ticket.meta_.stream_category)
class TicketAuditHandler:
    """Event handler that logs ticket assignments to the audit log."""

    @handle(TicketAssigned)
    def on_ticket_assigned(self, event: TicketAssigned):
        """Log the assignment in the audit trail."""
        entry = AuditEntry(
            ticket_id=event.ticket_id,
            action="assigned",
            detail=f"Assigned to {event.assignee}",
        )
        domain.repository_for(AuditEntry).add(entry)

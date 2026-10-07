"""
Use case with update and event handler: Load → Mutate → Persist → React.

This example demonstrates:
- Two commands on the same aggregate (create + update pattern)
- Aggregate factory method for creation
- Aggregate instance method for updates
- Event handler in Ticket's cluster reacting to Ticket's own event
- The event handler hands off to AuditEntry by issuing a RecordAudit command
- Full lifecycle: create ticket → assign ticket → event handler logs assignment

Domain: A support ticket system where tickets can be created and assigned,
with an audit log tracking assignments.

Events are delivered at least once, so each audit entry takes its id from the
event's own id, and the command handler skips an entry that already exists.
"""

from protean import Domain, current_domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String

domain = Domain(__name__)

# Run the hop in-process: TicketAssigned reaches the event handler as soon as
# the ticket is saved, and RecordAudit reaches its handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


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

    entry_id: Identifier(identifier=True)
    ticket_id: Identifier(required=True)
    action: String(required=True, max_length=50)
    detail: String(max_length=500)


@domain.command(part_of="AuditEntry")
class RecordAudit:
    """Command to record one audit entry.

    `entry_id` is the id of the event being audited, so a redelivered event
    reissues the same command and the handler can tell the entry exists.
    """

    entry_id: Identifier(required=True)
    ticket_id: Identifier(required=True)
    action: String(required=True, max_length=50)
    detail: String(max_length=500)


@domain.command_handler(part_of=AuditEntry)
class AuditCommandHandler:
    """The write path for AuditEntry."""

    @handle(RecordAudit)
    def handle_record(self, command: RecordAudit):
        """Add the audit entry unless it is already recorded."""
        repo = current_domain.repository_for(AuditEntry)
        try:
            repo.get(command.entry_id)
        except ObjectNotFoundError:
            repo.add(
                AuditEntry(
                    entry_id=command.entry_id,
                    ticket_id=command.ticket_id,
                    action=command.action,
                    detail=command.detail,
                )
            )
        else:
            return  # already recorded; a redelivered event must not log twice


# --- Event Handler (in the cluster that owns the event) ---


@domain.event_handler(part_of=Ticket)
class TicketAuditHandler:
    """Event handler that logs ticket assignments to the audit log.

    The handler sits in Ticket's cluster, because it reacts to Ticket's own
    event (a handler that reacts to another cluster's event is what `check`
    reports as EVENT_HANDLER_FOREIGN_EVENT). It hands off to AuditEntry with a
    command, and AuditEntry's command handler does the write.
    """

    @handle(TicketAssigned)
    def on_ticket_assigned(self, event: TicketAssigned):
        """Ask the audit log to record the assignment."""
        current_domain.process(
            RecordAudit(
                entry_id=event._metadata.headers.id,
                ticket_id=event.ticket_id,
                action="assigned",
                detail=f"Assigned to {event.assignee}",
            )
        )

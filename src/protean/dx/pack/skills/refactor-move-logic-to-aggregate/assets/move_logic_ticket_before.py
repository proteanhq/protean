"""
Ticket system with logic leaked into handlers (before refactoring).

Anti-patterns present:
- Handler validates state transitions
- Handler sets fields directly on aggregate
- Handler calculates derived values
- Aggregate is anemic (no methods, no invariants)
"""

from datetime import UTC, datetime

from protean import Domain, handle
from protean.fields import DateTime, Integer, String

domain = Domain()


@domain.aggregate
class Ticket:
    """Anemic aggregate — just a data container."""

    title = String(required=True, max_length=200)
    description = String(max_length=2000)
    status = String(default="OPEN")
    priority = Integer(default=1, min_value=1, max_value=5)
    assignee_id = String()
    resolution = String(max_length=500)
    closed_at = DateTime()


@domain.command(part_of="Ticket")
class AssignTicket:
    ticket_id = String(required=True, identifier=True)
    assignee_id = String(required=True)


@domain.command(part_of="Ticket")
class CloseTicket:
    ticket_id = String(required=True, identifier=True)
    resolution = String(required=True, max_length=500)


@domain.command(part_of="Ticket")
class EscalateTicket:
    ticket_id = String(required=True, identifier=True)


@domain.command_handler(part_of=Ticket)
class TicketCommandHandler:
    @handle(AssignTicket)
    def assign_ticket(self, command: AssignTicket) -> None:
        """Fat handler: validates + mutates directly."""
        ticket = domain.repository_for(Ticket).get(command.ticket_id)

        # Logic leak: state guard in handler
        if ticket.status == "CLOSED":
            raise ValueError("Cannot assign a closed ticket")

        # Logic leak: direct field mutation
        ticket.assignee_id = command.assignee_id
        ticket.status = "ASSIGNED"

        domain.repository_for(Ticket).add(ticket)

    @handle(CloseTicket)
    def close_ticket(self, command: CloseTicket) -> None:
        """Fat handler: multiple validations + mutations."""
        ticket = domain.repository_for(Ticket).get(command.ticket_id)

        # Logic leak: state guard in handler
        if ticket.status == "CLOSED":
            raise ValueError("Already closed")
        if ticket.status == "OPEN":
            raise ValueError("Must be assigned before closing")

        # Logic leak: multiple field mutations
        ticket.status = "CLOSED"
        ticket.resolution = command.resolution
        ticket.closed_at = datetime.now(UTC)

        domain.repository_for(Ticket).add(ticket)

    @handle(EscalateTicket)
    def escalate_ticket(self, command: EscalateTicket) -> None:
        """Fat handler: calculation in handler."""
        ticket = domain.repository_for(Ticket).get(command.ticket_id)

        # Logic leak: business rule in handler
        if ticket.priority >= 5:
            raise ValueError("Already at maximum priority")

        # Logic leak: calculation
        ticket.priority = min(ticket.priority + 1, 5)

        domain.repository_for(Ticket).add(ticket)


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        ticket = Ticket(title="Bug in login", priority=2)
        domain.repository_for(Ticket).add(ticket)

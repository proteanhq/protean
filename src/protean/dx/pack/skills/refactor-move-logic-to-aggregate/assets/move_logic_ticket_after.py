"""
Ticket system with rich aggregate methods (after refactoring).

Changes from move_logic_ticket_before.py:
1. Moved state guards into aggregate methods
2. Moved field mutations into aggregate methods
3. Added invariants for cross-field business rules
4. Handlers are now 3 lines: load, call, persist
5. Added domain events for state changes
"""

from datetime import UTC, datetime

from protean import Domain, handle, invariant
from protean.fields import DateTime, Identifier, Integer, String

domain = Domain()


# --- Events ---


@domain.event(part_of="Ticket")
class TicketAssigned:
    ticket_id = Identifier(required=True)
    assignee_id = String(required=True)


@domain.event(part_of="Ticket")
class TicketClosed:
    ticket_id = Identifier(required=True)
    resolution = String(required=True)


@domain.event(part_of="Ticket")
class TicketEscalated:
    ticket_id = Identifier(required=True)
    new_priority = Integer(required=True)


# --- Rich Aggregate ---


@domain.aggregate
class Ticket:
    """Rich aggregate with business logic in methods."""

    title = String(required=True, max_length=200)
    description = String(max_length=2000)
    status = String(default="OPEN")
    priority = Integer(default=1, min_value=1, max_value=5)
    assignee_id = String()
    resolution = String(max_length=500)
    closed_at = DateTime()

    def assign(self, assignee_id: str) -> None:
        """Assign the ticket to someone."""
        if self.status == "CLOSED":
            raise ValueError("Cannot assign a closed ticket")

        self.assignee_id = assignee_id
        self.status = "ASSIGNED"

        self.raise_(TicketAssigned(ticket_id=self.id, assignee_id=assignee_id))

    def close(self, resolution: str) -> None:
        """Close the ticket with a resolution."""
        if self.status == "CLOSED":
            raise ValueError("Already closed")
        if self.status == "OPEN":
            raise ValueError("Must be assigned before closing")

        self.status = "CLOSED"
        self.resolution = resolution
        self.closed_at = datetime.now(UTC)

        self.raise_(TicketClosed(ticket_id=self.id, resolution=resolution))

    def escalate(self) -> None:
        """Increase priority by one level."""
        if self.priority >= 5:
            raise ValueError("Already at maximum priority")

        self.priority = min(self.priority + 1, 5)

        self.raise_(TicketEscalated(ticket_id=self.id, new_priority=self.priority))

    @invariant.post
    def assigned_ticket_must_have_assignee(self):
        """An assigned ticket must have an assignee."""
        if self.status == "ASSIGNED" and not self.assignee_id:
            from protean.exceptions import ValidationError

            raise ValidationError(
                {"assignee_id": ["Assigned ticket must have an assignee"]}
            )


# --- Commands ---


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


# --- Thin Handlers ---


@domain.command_handler(part_of=Ticket)
class TicketCommandHandler:
    @handle(AssignTicket)
    def assign_ticket(self, command: AssignTicket) -> None:
        ticket = domain.repository_for(Ticket).get(command.ticket_id)
        ticket.assign(assignee_id=command.assignee_id)
        domain.repository_for(Ticket).add(ticket)

    @handle(CloseTicket)
    def close_ticket(self, command: CloseTicket) -> None:
        ticket = domain.repository_for(Ticket).get(command.ticket_id)
        ticket.close(resolution=command.resolution)
        domain.repository_for(Ticket).add(ticket)

    @handle(EscalateTicket)
    def escalate_ticket(self, command: EscalateTicket) -> None:
        ticket = domain.repository_for(Ticket).get(command.ticket_id)
        ticket.escalate()
        domain.repository_for(Ticket).add(ticket)


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        ticket = Ticket(title="Bug in login", priority=2)
        domain.repository_for(Ticket).add(ticket)

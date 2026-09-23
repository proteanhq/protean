"""
Counting and null-aware queries with a custom repository.

This example demonstrates the QuerySet features for efficient reads:
- count() — a flat COUNT(*) that returns just the number of matching rows
  without projecting columns or materializing entities. Prefer it over
  len(query.all()) when you only need the count.
- all(with_total=False) — fetch only the page of items and skip the separate
  total-count round-trip (a wrapped COUNT on SQL adapters) when
  ResultSet.total is not needed.
- the isnull lookup — filter on whether a field is set:
  filter(field__isnull=True)  -> field IS NULL
  filter(field__isnull=False) -> field IS NOT NULL

Usage:
    repo = domain.repository_for(Ticket)
    open_tickets = repo.open_count()
    unassigned = repo.unassigned()
"""

from protean import Domain
from protean.fields import Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Ticket:
    """A support ticket. `assignee` is optional — unset means unassigned."""

    ticket_id: Identifier(identifier=True)
    subject: String(required=True, max_length=200)
    status: String(default="open", max_length=20)
    assignee: String(max_length=80)  # optional -> None when unassigned

    def assign_to(self, agent: str):
        """Assign the ticket to an agent."""
        self.assignee = agent

    def close(self):
        """Close the ticket."""
        self.status = "closed"


@domain.repository(part_of=Ticket)
class TicketRepository:
    """Read-optimized queries over tickets.

    Repositories take a class reference for part_of (the aggregate must be
    defined first); unlike handlers, they do not accept a string reference.
    """

    def count_by_status(self, status: str) -> int:
        """Number of tickets in a status — a flat COUNT, no rows loaded."""
        return self.query.filter(status=status).count()

    def open_count(self) -> int:
        """Convenience: number of open tickets."""
        return self.query.filter(status="open").count()

    def unassigned(self):
        """Tickets with no assignee (assignee IS NULL).

        Uses with_total=False: only the items are needed, so the adapter may
        skip the separate total-count query.
        """
        return self.query.filter(assignee__isnull=True).all(with_total=False).items

    def assigned(self):
        """Tickets that have an assignee (assignee IS NOT NULL)."""
        return self.query.filter(assignee__isnull=False).all(with_total=False).items

    def unassigned_count(self) -> int:
        """How many tickets are unassigned — COUNT over the isnull filter."""
        return self.query.filter(assignee__isnull=True).count()


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        repo = domain.repository_for(Ticket)

        repo.add(Ticket(ticket_id="T-1", subject="Login fails", status="open"))
        repo.add(
            Ticket(
                ticket_id="T-2", subject="Slow page", status="open", assignee="alice"
            )
        )
        repo.add(
            Ticket(ticket_id="T-3", subject="Typo", status="closed", assignee="bob")
        )
        repo.add(Ticket(ticket_id="T-4", subject="Crash", status="open"))

        print("open:", repo.open_count())  # 3
        print("closed:", repo.count_by_status("closed"))  # 1
        print("unassigned:", len(repo.unassigned()))  # 2 (T-1, T-4)
        print("assigned:", len(repo.assigned()))  # 2 (T-2, T-3)
        print("unassigned_count:", repo.unassigned_count())  # 2

from datetime import UTC, datetime

from protean import Domain, UnitOfWork, current_domain
from protean.fields import DateTime, Identifier, String

domain = Domain(name="OneAggregatePerTransactionBulk")


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(max_length=20, default="pending")
    deadline: DateTime(required=True)
    close_reason: String(max_length=100)

    def close(self, reason):
        self.status = "closed"
        self.close_reason = reason


# --8<-- [start:bulk]
@domain.application_service(part_of=Order)
class OrderMaintenanceService:
    def close_expired(self) -> list[str]:
        repo = current_domain.repository_for(Order)
        now = datetime.now(UTC)
        expired_ids = [
            order.order_id
            for order in repo.query.filter(status="pending", deadline__lt=now).all()
        ]

        closed = []
        for order_id in expired_ids:
            # Each order gets its own transaction. If one order fails,
            # the orders closed before it stay committed.
            with UnitOfWork():
                order = repo.get(order_id)
                # The order may have shipped or had its deadline moved
                # since the scan, so check again on the fresh copy.
                if order.status != "pending" or order.deadline >= now:
                    continue
                order.close("Expired past deadline")
                repo.add(order)
            closed.append(order_id)
        return closed


# --8<-- [end:bulk]

# --8<-- [start:notification_imports]
from datetime import UTC, datetime

# --8<-- [end:notification_imports]
from protean import Domain, handle

# --8<-- [start:inventory_imports]
from protean.exceptions import ValidationError

# --8<-- [end:inventory_imports]
from protean.fields import (
    Auto,
    DateTime,
    Dict,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
)
from protean.utils.globals import current_domain

domain = Domain(name="IdempotentWorkedExamples")


# The same Order and OrderPlaced as in 001.py, which the page shows.
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    customer_name: String()
    total: Float(required=True)
    items: List(content_type=Dict)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String()
    total: Float(required=True)
    items: List(content_type=Dict)
    placed_at: DateTime()


# --8<-- [start:loyalty]
@domain.entity(part_of="CustomerLoyalty")
class PointTransaction:
    source_id: Identifier(required=True)
    amount: Integer(required=True)
    type: String(required=True)


@domain.aggregate
class CustomerLoyalty:
    customer_id: Identifier(identifier=True)
    points: Integer(default=0)
    point_transactions = HasMany(PointTransaction)

    def award_points(self, order_id: str, amount: int) -> None:
        """Award loyalty points for an order, idempotently."""
        # Check if points were already awarded for this order
        for txn in self.point_transactions:
            if txn.source_id == order_id:
                return  # Already awarded

        self.points += amount
        self.add_point_transactions(
            PointTransaction(
                source_id=order_id,
                amount=amount,
                type="earned",
            )
        )


@domain.event_handler(part_of=Order)
class LoyaltyEventHandler:
    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)
        # The aggregate method handles idempotency internally
        loyalty.award_points(
            order_id=event.order_id,
            amount=int(event.total),
        )
        repo.add(loyalty)


# --8<-- [end:loyalty]


# --8<-- [start:inventory]
@domain.event(part_of="Inventory")
class InventoryReserved:
    product_id: Identifier(required=True)
    order_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.entity(part_of="Inventory")
class Reservation:
    order_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    available_quantity: Integer(default=0)
    reservations = HasMany(Reservation)

    def reserve(self, order_id: str, quantity: int) -> None:
        """Reserve inventory for an order, idempotently."""
        # Check if already reserved for this order
        for reservation in self.reservations:
            if reservation.order_id == order_id:
                return  # Already reserved

        if self.available_quantity < quantity:
            raise ValidationError(
                {
                    "quantity": [
                        f"Insufficient inventory. Available: {self.available_quantity}"
                    ]
                }
            )

        self.available_quantity -= quantity
        self.add_reservations(
            Reservation(
                order_id=order_id,
                quantity=quantity,
            )
        )

        self.raise_(
            InventoryReserved(
                product_id=self.product_id,
                order_id=order_id,
                quantity=quantity,
            )
        )


@domain.event_handler(part_of=Order)
class InventoryEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(
                order_id=event.order_id,
                quantity=item["quantity"],
            )
            repo.add(inventory)


# --8<-- [end:inventory]


# --8<-- [start:notification]
@domain.aggregate
class Notification:
    notification_id: Auto(identifier=True)
    recipient_id: Identifier(required=True)
    type: String(required=True)
    source_event_id: Identifier(required=True)
    status: String(default="pending")
    sent_at: DateTime()

    def mark_sent(self) -> None:
        self.status = "sent"
        self.sent_at = datetime.now(UTC)


@domain.repository(part_of=Notification)
class NotificationRepository:
    def find_by_source_event_id(self, event_id: str) -> Notification | None:
        return self.query.filter(source_event_id=event_id).first

    def pending(self) -> list[Notification]:
        return self.query.filter(status="pending").all().items


@domain.event_handler(part_of=Order)
class NotificationEventHandler:
    @handle(OrderPlaced)
    def send_confirmation(self, event: OrderPlaced):
        repo = current_domain.repository_for(Notification)

        # Use event ID as the deduplication key
        event_id = event._metadata.headers.id
        existing = repo.find_by_source_event_id(event_id)

        if existing and existing.status == "sent":
            return  # Already sent

        if not existing:
            notification = Notification(
                recipient_id=event.customer_id,
                type="order_confirmation",
                source_event_id=event_id,
                status="pending",
            )
            repo.add(notification)

        # The actual sending happens in a separate process
        # that picks up pending notifications


# --8<-- [end:notification]


# --8<-- [start:sender]
def send_email(recipient_id: str, template: str) -> None:
    """Hand the message to your email provider."""
    print(f"Sending {template} to {recipient_id}")


def send_pending_notifications() -> None:
    repo = current_domain.repository_for(Notification)
    for notification in repo.pending():
        send_email(notification.recipient_id, notification.type)
        # Marked as sent, so the next run and a redelivered event both skip it
        notification.mark_sent()
        repo.add(notification)


# --8<-- [end:sender]

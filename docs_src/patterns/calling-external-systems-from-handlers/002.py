# --8<-- [start:model]
from datetime import UTC, datetime

import httpx

from protean import Domain, current_domain, handle
from protean.fields import DateTime, Identifier, String

domain = Domain(name="Orders")

PARTNER_URL = "https://partner.example.com/webhooks/orders"


def post_to_partner(payload: dict) -> None:
    httpx.post(PARTNER_URL, json=payload).raise_for_status()


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)
    confirmed_at: DateTime(required=True)


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(default="PLACED")
    fulfilment_status: String(default="PENDING")
    confirmed_at: DateTime()

    @classmethod
    def place(cls, order_id):
        order = cls(order_id=order_id)
        order.raise_(OrderPlaced(order_id=order_id))
        return order

    def start_fulfilment(self):
        self.fulfilment_status = "STARTED"

    def confirm(self):
        self.status = "CONFIRMED"
        self.confirmed_at = datetime.now(UTC)
        self.raise_(
            OrderConfirmed(order_id=self.order_id, confirmed_at=self.confirmed_at)
        )


# --8<-- [end:model]

domain.config["event_processing"] = "sync"


# --8<-- [start:siblings]
@domain.event_handler(part_of=Order)
class OrderReactions:
    @handle(OrderPlaced)
    def start_fulfilment(self, event):
        repo = current_domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.start_fulfilment()
        repo.add(order)

    @handle(OrderPlaced)
    def notify_partner(self, event):
        # No repository access, so this method runs no transaction.
        post_to_partner({"order_id": event.order_id})


# --8<-- [end:siblings]

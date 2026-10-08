"""
Endpoints with URL path parameters for targeting specific aggregates.

This example demonstrates:
- A path parameter that names the target aggregate
  (``PUT /orders/{order_id}/cancel``)
- A command built from both the path and the request body
- A PUT endpoint for a state change on an existing aggregate
- A handler that loads the aggregate with ``repository.get``, so an unknown id
  raises ``ObjectNotFoundError`` and the client gets a 404
- An aggregate that raises ``InvalidStateError`` for a wrong state, which the
  client gets as a 409

This file holds the router only. Build the app the way the ``create_app``
factory in ``api_endpoint_complete_router.py`` does, and include this router.
Pass the factory this file's ``domain``, which registers the router's commands.

Usage, once the app is running:
    # POST to create an order first
    curl -X POST http://localhost:8000/orders \\
        -H "Content-Type: application/json" \\
        -d '{"order_id": "ORD-001", "customer_id": "CUST-123", "total_amount": 99.99}'

    # PUT to cancel the order using path parameter
    curl -X PUT http://localhost:8000/orders/ORD-001/cancel \\
        -H "Content-Type: application/json" \\
        -d '{"reason": "Customer changed mind"}'
"""

from datetime import UTC, datetime

from fastapi import APIRouter

from protean import Domain, handle
from protean.exceptions import InvalidStateError
from protean.fields import DateTime, Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain()


@domain.aggregate
class Order:
    """Order aggregate with place and cancel operations."""

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="draft")
    placed_at: DateTime()
    cancelled_at: DateTime()
    cancel_reason: String()

    def place(self, total_amount: float):
        """Place the order."""
        self.total_amount = total_amount
        self.status = "placed"
        self.placed_at = datetime.now(UTC)

    def cancel(self, reason: str):
        """Cancel the order."""
        if self.status not in ("draft", "placed"):
            raise InvalidStateError(f"Cannot cancel order in '{self.status}' status")
        self.status = "cancelled"
        self.cancelled_at = datetime.now(UTC)
        self.cancel_reason = reason


@domain.command(part_of="Order")
class PlaceOrder:
    """Command to place a new order."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


@domain.command(part_of="Order")
class CancelOrder:
    """Command to cancel an existing order."""

    order_id: Identifier(required=True)
    reason: String(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """Handler for all order commands."""

    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        """Create and place a new order."""
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
        )
        order.place(total_amount=command.total_amount)
        current_domain.repository_for(Order).add(order)
        return order.order_id

    @handle(CancelOrder)
    def handle_cancel_order(self, command: CancelOrder):
        """Load an existing order and cancel it."""
        order = current_domain.repository_for(Order).get(command.order_id)
        order.cancel(reason=command.reason)
        current_domain.repository_for(Order).add(order)
        return order.order_id


router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=201)
def create_order(payload: dict):
    """Create a new order from the JSON body."""
    command = PlaceOrder(
        order_id=payload.get("order_id"),
        customer_id=payload.get("customer_id"),
        total_amount=payload.get("total_amount"),
    )
    result = current_domain.process(command, asynchronous=False)
    return {"order_id": result, "status": "placed"}


@router.put("/{order_id}/cancel")
def cancel_order(order_id: str, payload: dict):
    """Cancel an existing order.

    The order id comes from the URL path and the reason from the body. Both go
    into one command.
    """
    command = CancelOrder(order_id=order_id, reason=payload.get("reason"))
    result = current_domain.process(command, asynchronous=False)
    return {"order_id": result, "status": "cancelled"}

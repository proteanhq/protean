"""
Simple POST endpoint that constructs a command and processes it synchronously.

This example demonstrates:
- A FastAPI ``APIRouter`` with one POST endpoint
- Constructing a domain command from the JSON request body
- Synchronous command processing via
  ``current_domain.process(command, asynchronous=False)``
- A plain ``def`` endpoint, which FastAPI runs in its thread pool so the
  blocking ``process`` call stays off the event loop
- Returning 201 with the created id

This file holds the router only. Build the app with the ``create_app`` factory
in ``api_endpoint_complete_router.py``: it adds ``DomainContextMiddleware`` and
``register_exception_handlers``. Add ``app.include_router(router)`` there.

Usage, once the app is running:
    # POST /orders with JSON payload
    curl -X POST http://localhost:8000/orders \\
        -H "Content-Type: application/json" \\
        -d '{"order_id": "ORD-001", "customer_id": "CUST-123", "total_amount": 99.99}'
"""

from datetime import UTC, datetime

from fastapi import APIRouter

from protean import Domain, handle
from protean.fields import DateTime, Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain()


@domain.aggregate
class Order:
    """Order aggregate."""

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="draft")
    placed_at: DateTime()

    def place(self, total_amount: float):
        """Place the order with the given total amount."""
        self.total_amount = total_amount
        self.status = "placed"
        self.placed_at = datetime.now(UTC)


@domain.command(part_of="Order")
class PlaceOrder:
    """Command to place a new order."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """Handler that processes the PlaceOrder command."""

    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        """Create a new Order aggregate and persist it."""
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
        )
        order.place(total_amount=command.total_amount)
        current_domain.repository_for(Order).add(order)
        return order.order_id


router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=201)
def create_order(payload: dict):
    """Create a new order.

    A missing or invalid field makes the ``PlaceOrder`` constructor raise
    ``ValidationError``, which the registered exception handlers turn into a
    400 with the messages for each field.
    """
    command = PlaceOrder(
        order_id=payload.get("order_id"),
        customer_id=payload.get("customer_id"),
        total_amount=payload.get("total_amount"),
    )
    result = current_domain.process(command, asynchronous=False)
    return {"order_id": result, "status": "placed"}

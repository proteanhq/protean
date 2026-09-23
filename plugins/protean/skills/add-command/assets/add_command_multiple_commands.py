"""
Multiple commands for one aggregate with a shared handler and complete router.

This example demonstrates adding several command flows to a single aggregate:
- Multiple command classes, all part_of the same aggregate
- A single command handler with multiple @handle methods
- A FastAPI router with endpoints for each command
- Mix of create (POST) and update (PUT) operations
- Path parameters combined with request bodies

This is the typical pattern when an aggregate supports multiple operations
(e.g., an Order that can be placed, confirmed, and cancelled).

Workflow:
    POST /orders          → PlaceOrder     → create Order, persist
    PUT  /orders/{id}/pay → PayOrder       → load Order, pay, persist
    PUT  /orders/{id}/cancel → CancelOrder → load Order, cancel, persist

Usage:
    # Place an order
    curl -X POST http://localhost:8000/orders \\
        -H "Content-Type: application/json" \\
        -d '{"order_id": "ORD-001", "customer_id": "CUST-1", "total_amount": 99.99}'

    # Pay for the order
    curl -X PUT http://localhost:8000/orders/ORD-001/pay \\
        -H "Content-Type: application/json" \\
        -d '{"payment_method": "credit_card"}'

    # Cancel the order
    curl -X PUT http://localhost:8000/orders/ORD-001/cancel \\
        -H "Content-Type: application/json" \\
        -d '{"reason": "Changed my mind"}'
"""

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import Domain, handle
from protean.fields import DateTime, Float, Identifier, String
from protean.utils.globals import current_domain

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """Order aggregate with multiple state transitions."""

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="draft")
    payment_method: String()
    placed_at: DateTime()
    paid_at: DateTime()
    cancelled_at: DateTime()
    cancel_reason: String()

    def place(self, total_amount: float):
        """Place the order with a total amount."""
        self.total_amount = total_amount
        self.status = "placed"
        self.placed_at = datetime.now(UTC)

    def pay(self, payment_method: str):
        """Record payment for the order."""
        if self.status != "placed":
            raise ValueError(f"Cannot pay for order in '{self.status}' status")
        self.payment_method = payment_method
        self.status = "paid"
        self.paid_at = datetime.now(UTC)

    def cancel(self, reason: str):
        """Cancel the order."""
        if self.status in ("paid", "cancelled"):
            raise ValueError(f"Cannot cancel order in '{self.status}' status")
        self.status = "cancelled"
        self.cancel_reason = reason
        self.cancelled_at = datetime.now(UTC)


# --- Commands (all part_of the same aggregate) ---


@domain.command(part_of="Order")
class PlaceOrder:
    """Command to place a new order."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


@domain.command(part_of="Order")
class PayOrder:
    """Command to record payment for an order."""

    order_id: Identifier(required=True)
    payment_method: String(required=True)


@domain.command(part_of="Order")
class CancelOrder:
    """Command to cancel an order."""

    order_id: Identifier(required=True)
    reason: String(required=True)


# --- Single Command Handler with multiple @handle methods ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """Handler for all order-related commands.

    One handler class per aggregate, with one @handle method per command.
    All commands must be part_of the same aggregate as the handler.
    """

    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        """Handle PlaceOrder - creates a new Order aggregate."""
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
        )
        order.place(total_amount=command.total_amount)
        domain.repository_for(Order).add(order)
        return order.order_id

    @handle(PayOrder)
    def handle_pay_order(self, command: PayOrder):
        """Handle PayOrder - loads existing order and records payment."""
        order = domain.repository_for(Order).get(command.order_id)
        order.pay(payment_method=command.payment_method)
        domain.repository_for(Order).add(order)
        return order.order_id

    @handle(CancelOrder)
    def handle_cancel_order(self, command: CancelOrder):
        """Handle CancelOrder - loads existing order and cancels it."""
        order = domain.repository_for(Order).get(command.order_id)
        order.cancel(reason=command.reason)
        domain.repository_for(Order).add(order)
        return order.order_id


# --- FastAPI Router with endpoints for each command ---

app = FastAPI(title="Order API")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Middleware to provide domain context for every request."""
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/orders", status_code=201)
async def place_order(request: Request):
    """Place a new order.

    POST /orders - creates a new Order aggregate.
    All data comes from the request body.
    """
    payload = await request.json()

    command = PlaceOrder(
        order_id=payload["order_id"],
        customer_id=payload["customer_id"],
        total_amount=payload["total_amount"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        status_code=201,
        content={"order_id": result, "status": "placed"},
    )


@app.put("/orders/{order_id}/pay")
async def pay_order(order_id: str, request: Request):
    """Record payment for an order.

    PUT /orders/{id}/pay - ID from path, payment details from body.
    """
    payload = await request.json()

    command = PayOrder(
        order_id=order_id,
        payment_method=payload["payment_method"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        content={"order_id": result, "status": "paid"},
    )


@app.put("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request):
    """Cancel an order.

    PUT /orders/{id}/cancel - ID from path, reason from body.
    """
    payload = await request.json()

    command = CancelOrder(
        order_id=order_id,
        reason=payload["reason"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        content={"order_id": result, "status": "cancelled"},
    )


# Example usage
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    domain.init(traverse=False)
    uvicorn.run(app, host="127.0.0.1", port=8000)

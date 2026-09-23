"""
Endpoint with URL path parameters for targeting specific aggregates.

This example demonstrates:
- FastAPI endpoint with path parameters (e.g., /orders/{order_id}/cancel)
- Using path parameters to identify the target aggregate
- Constructing a command that includes data from both path and body
- PUT endpoint pattern for state-change operations on existing aggregates
- Synchronous command processing via domain.process()

Usage:
    # Start the server
    python api_endpoint_path_params.py

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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import Domain, handle
from protean.fields import DateTime, Float, Identifier, String
from protean.utils.globals import current_domain

# Domain setup
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
            raise ValueError(f"Cannot cancel order in '{self.status}' status")
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
        domain.repository_for(Order).add(order)
        return order.order_id

    @handle(CancelOrder)
    def handle_cancel_order(self, command: CancelOrder):
        """Load an existing order and cancel it."""
        order = domain.repository_for(Order).get(command.order_id)
        order.cancel(reason=command.reason)
        domain.repository_for(Order).add(order)
        return order.order_id


# FastAPI app setup
app = FastAPI(title="Path Parameters Endpoint Example")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Middleware to provide domain context for every request."""
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/orders", status_code=201)
async def create_order(request: Request):
    """Create a new order from JSON payload."""
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


@app.put("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request):
    """Cancel an existing order.

    The order_id comes from the URL path parameter,
    while the cancellation reason comes from the request body.
    This shows how path parameters and body data combine
    into a single command.
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

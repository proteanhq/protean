"""
Simple POST endpoint that constructs a command and processes it synchronously.

This example demonstrates:
- Basic FastAPI POST endpoint integrated with Protean
- Domain context middleware setup for request handling
- Constructing a domain command from JSON request payload
- Synchronous command processing via domain.process(command, asynchronous=False)
- Returning an appropriate HTTP response with status code 201

Usage:
    # Start the server
    python api_endpoint_simple.py

    # POST /orders with JSON payload
    curl -X POST http://localhost:8000/orders \\
        -H "Content-Type: application/json" \\
        -d '{"order_id": "ORD-001", "customer_id": "CUST-123", "total_amount": 99.99}'
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
        domain.repository_for(Order).add(order)
        return order.order_id


# FastAPI app setup
app = FastAPI(title="Simple API Endpoint Example")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Middleware to provide domain context for every request."""
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/orders", status_code=201)
async def create_order(request: Request):
    """Create a new order.

    Accepts a JSON payload, constructs a PlaceOrder command,
    and processes it synchronously via the domain.
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


# Example usage
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    domain.init(traverse=False)
    uvicorn.run(app, host="127.0.0.1", port=8000)

# --8<-- [start:model]
from datetime import UTC, datetime

from protean import Domain, current_domain, handle
from protean.core.application_service import use_case
from protean.fields import Auto, DateTime, Float, Identifier, Integer, String

domain = Domain(name="Shop")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    customer_name = String(required=True)
    total = Float(required=True)
    item_count = Integer(required=True)
    placed_at = DateTime(required=True)
    version = Integer(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id = Identifier(required=True)
    version = Integer(required=True)


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    customer_name = String(required=True)
    total = Float(default=0.0)
    item_count = Integer(default=0)
    status = String(default="draft")
    placed_at = DateTime()

    def place(self) -> None:
        self.status = "placed"
        self.placed_at = datetime.now(UTC)
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                customer_name=self.customer_name,
                total=self.total,
                item_count=self.item_count,
                placed_at=self.placed_at,
                # Saving an aggregate stored as state moves _version up by
                # one, so the event carries the version the order will have
                # once it is saved.
                version=self._version + 1,
            )
        )

    def confirm(self) -> None:
        self.status = "confirmed"
        self.raise_(OrderConfirmed(order_id=self.order_id, version=self._version + 1))


@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    customer_name = String()
    total = Float()
    item_count = Integer()
    status = String()
    placed_at = DateTime()
    version = Integer()


@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(
            OrderSummary(
                order_id=event.order_id,
                customer_id=event.customer_id,
                customer_name=event.customer_name,
                total=event.total,
                item_count=event.item_count,
                status="placed",
                placed_at=event.placed_at,
                version=event.version,
            )
        )

    @handle(OrderConfirmed)
    def on_order_confirmed(self, event: OrderConfirmed) -> None:
        repo = current_domain.repository_for(OrderSummary)
        summary = repo.get(event.order_id)
        summary.status = "confirmed"
        summary.version = event.version
        repo.add(summary)


# --8<-- [end:model]


# --8<-- [start:service]
@domain.application_service(part_of=Order)
class OrderService:
    @use_case
    def place_order(self, order_data: dict) -> Order:
        order = Order(**order_data)
        order.place()
        repo = current_domain.repository_for(Order)
        repo.add(order)
        return order

    @use_case
    def confirm_order(self, order_id: str) -> Order:
        repo = current_domain.repository_for(Order)
        order = repo.get(order_id)
        order.confirm()
        repo.add(order)
        return order


# --8<-- [end:service]


# --8<-- [start:request]
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from protean.exceptions import ObjectNotFoundError


class OrderData(BaseModel):
    customer_id: str
    customer_name: str
    total: float
    item_count: int


# --8<-- [end:request]


# --8<-- [start:optimistic_api]
optimistic = APIRouter()


@optimistic.post("/orders", status_code=201)
def create_order(data: OrderData):
    service = OrderService()
    order = service.place_order(data.model_dump())

    # Return enough data for the frontend to display immediately
    return {
        "order_id": order.order_id,
        "customer_name": order.customer_name,
        "total": order.total,
        "status": order.status,
        "placed_at": order.placed_at.isoformat(),
    }


# --8<-- [end:optimistic_api]


# --8<-- [start:write_side_api]
write_side = APIRouter()


@write_side.post("/orders", status_code=201)
def place_and_return_order(data: OrderData):
    service = OrderService()
    order = service.place_order(data.model_dump())

    # Return the write-side state directly
    return {
        "order_id": order.order_id,
        "customer_name": order.customer_name,
        "total": order.total,
        "item_count": order.item_count,
        "status": order.status,
        "placed_at": order.placed_at.isoformat(),
    }


@write_side.get("/orders/{order_id}")
def get_order(order_id: str):
    """Normal read path -- from the projection."""
    try:
        summary = domain.view_for(OrderSummary).get(order_id)
    except ObjectNotFoundError:
        raise HTTPException(status_code=404) from None
    return summary.to_dict()


# --8<-- [end:write_side_api]


# --8<-- [start:polling_api]
polling = APIRouter()


@polling.post("/orders", status_code=201)
def place_order_with_version(data: OrderData):
    order = OrderService().place_order(data.model_dump())
    return {
        "order_id": order.order_id,
        "status": order.status,
        "version": order._version,
    }


@polling.post("/orders/{order_id}/confirm")
def confirm_order(order_id: str):
    order = OrderService().confirm_order(order_id)
    return {
        "order_id": order.order_id,
        "status": order.status,
        "version": order._version,
    }


@polling.get("/orders/{order_id}")
def get_order_at_version(order_id: str, min_version: int | None = None):
    """Read from projection, optionally waiting for a minimum version.

    If min_version is provided and the projection has not caught up,
    return 202 Accepted to signal the client to retry.
    """
    pending = JSONResponse(status_code=202, content={"status": "pending"})
    try:
        summary = domain.view_for(OrderSummary).get(order_id)
    except ObjectNotFoundError:
        if min_version is not None:
            # Projection has not created this record yet
            return pending
        raise HTTPException(status_code=404) from None

    if min_version is not None and summary.version < min_version:
        return pending

    return summary.to_dict()


# --8<-- [end:polling_api]


# --8<-- [start:sync_fixture]
import pytest

from protean.integrations.pytest import DomainFixture


@pytest.fixture
def sync_domain():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    with fixture.domain_context():
        yield domain
    fixture.teardown()


# --8<-- [end:sync_fixture]


# --8<-- [start:sync_test]
def test_order_appears_in_projection_immediately(sync_domain):
    # Arrange
    service = OrderService()

    # Act -- place the order (projector runs synchronously)
    order = service.place_order(
        {
            "customer_id": "cust-123",
            "customer_name": "Alice",
            "total": 99.99,
            "item_count": 3,
        }
    )

    # Assert -- projection is already updated
    view = sync_domain.view_for(OrderSummary)
    summary = view.get(order.order_id)
    assert summary.status == "placed"
    assert summary.total == 99.99


# --8<-- [end:sync_test]


domain.init(traverse=False)

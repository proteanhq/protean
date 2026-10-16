# --8<-- [start:model]
from protean import Domain, apply, current_domain, handle
from protean.fields import Dict, Identifier, List, String

domain = Domain(name="MyApp", config={"command_processing": "sync"})


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.event(part_of="Order")
class InventoryReserved:
    order_id: Identifier(required=True)


@domain.event(part_of="Order")
class PaymentConfirmed:
    order_id: Identifier(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    customer_id: Identifier()
    items: List(content_type=Dict)
    status: String(default="NEW")

    @apply
    def when_placed(self, event: OrderPlaced) -> None:
        self.id = event.order_id
        self.customer_id = event.customer_id
        self.items = event.items
        self.status = "PLACED"

    @apply
    def when_reserved(self, event: InventoryReserved) -> None:
        self.status = "RESERVED"

    @apply
    def when_paid(self, event: PaymentConfirmed) -> None:
        self.status = "PAID"


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.command(part_of=Order)
class ReserveInventory:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class ConfirmPayment:
    order_id: Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder):
        order = Order()
        order.raise_(
            OrderPlaced(
                order_id=order.id,
                customer_id=command.customer_id,
                items=command.items,
            )
        )
        current_domain.repository_for(Order).add(order)
        return order.id

    @handle(ReserveInventory)
    def reserve(self, command: ReserveInventory):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.raise_(InventoryReserved(order_id=order.id))
        repo.add(order)

    @handle(ConfirmPayment)
    def confirm_payment(self, command: ConfirmPayment):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.raise_(PaymentConfirmed(order_id=order.id))
        repo.add(order)


@domain.event_handler(part_of=Order)
class InventoryEventHandler:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced) -> None:
        current_domain.process(ReserveInventory(order_id=event.order_id))


# --8<-- [end:model]


# --8<-- [start:endpoint]
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header
from pydantic import BaseModel

router = APIRouter()


class PlaceOrderRequest(BaseModel):
    customer_id: str
    items: list[dict]


@router.post("/orders", status_code=201)
def place_order(
    body: PlaceOrderRequest,
    x_correlation_id: Annotated[str | None, Header()] = None,
):
    # Fallback: generate at the API boundary
    correlation_id = x_correlation_id or uuid4().hex
    order_id = domain.process(
        PlaceOrder(**body.model_dump()),
        correlation_id=correlation_id,
    )
    return {"order_id": order_id, "correlation_id": correlation_id}


# --8<-- [end:endpoint]


# --8<-- [start:causation_api]
def explain(event_message, command_message, correlation_id: str):
    store = domain.event_store.store

    # Walk UP from a message to the root command
    chain = store.trace_causation(event_message)
    # Returns [root_command, ..., target_message]

    # Walk DOWN from a command to find all its effects
    effects = store.trace_effects(command_message)
    # Returns downstream events/commands in chronological order

    # Build the full tree for a correlation ID
    root = store.build_causation_tree(correlation_id)
    # Returns a CausationNode with .children recursively populated

    return chain, effects, root


# --8<-- [end:causation_api]


# --8<-- [start:subscriber]
@domain.subscriber(stream="payments")
class PaymentSubscriber:
    def __call__(self, message: dict) -> None:
        # A message from a system outside Protean may have no domain metadata,
        # a null one, or a blank correlation ID
        metadata = message.get("metadata") or {}
        domain_metadata = metadata.get("domain") or {}
        correlation_id = domain_metadata.get("correlation_id") or None

        current_domain.process(
            ConfirmPayment(order_id=message["data"]["order_id"]),
            correlation_id=correlation_id,
        )


# --8<-- [end:subscriber]


# --8<-- [start:dsl_generated]
from protean.testing import given


def place_order_with_generated_ids():
    result = given(Order).process(
        PlaceOrder(customer_id="cust-1", items=[{"sku": "BOOK-1", "qty": 2}])
    )
    assert result.events.types == [OrderPlaced]

    # Verify correlation_id was generated
    corr_id = result.events[0]._metadata.domain.correlation_id
    assert corr_id is not None
    assert len(corr_id) == 32  # UUID4 hex

    # Verify causation chain
    assert result.events[0]._metadata.domain.causation_id is not None
    return result


# --8<-- [end:dsl_generated]


# --8<-- [start:dsl_forward]
def reserve_in_the_same_operation(result):
    corr_id = result.events[0]._metadata.domain.correlation_id
    first_cause = result.events[0]._metadata.domain.causation_id

    result2 = result.process(
        ReserveInventory(order_id=result.aggregate.id),
        correlation_id=corr_id,
    )

    # Same correlation_id, different causation_id
    assert result2.events[0]._metadata.domain.correlation_id == corr_id
    assert result2.events[0]._metadata.domain.causation_id != first_cause
    return result2


# --8<-- [end:dsl_forward]

domain.init(traverse=False)

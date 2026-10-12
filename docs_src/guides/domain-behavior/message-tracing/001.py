from protean import Domain, apply, current_domain, handle
from protean.fields import Dict, Identifier, List, String

domain = Domain(name="MyApp")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.event(part_of="Order")
class InventoryReserved:
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


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.command(part_of=Order)
class ReserveInventory:
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


@domain.event_handler(part_of=Order)
class InventoryEventHandler:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced) -> None:
        current_domain.process(ReserveInventory(order_id=event.order_id))


# --8<-- [start:external]
def place_order(request, items):
    # Accept correlation_id from the HTTP request header
    correlation_id = request.headers.get("X-Correlation-ID")

    domain.process(
        PlaceOrder(customer_id="cust-123", items=items),
        correlation_id=correlation_id,
    )


# --8<-- [end:external]


# --8<-- [start:access]
def trace_ids(event, message):
    # On a command or event object
    object_ids = (
        event._metadata.domain.correlation_id,
        event._metadata.domain.causation_id,
    )

    # On a deserialized Message
    message_ids = (
        message.metadata.domain.correlation_id,
        message.metadata.domain.causation_id,
    )
    return object_ids, message_ids


# --8<-- [end:access]


# --8<-- [start:dsl]
from protean.testing import given


def place_and_reserve():
    result = given(Order).process(
        PlaceOrder(customer_id="cust-1", items=[{"sku": "BOOK-1", "qty": 2}]),
        correlation_id="checkout-42",
    )
    assert result.events.types == [OrderPlaced]

    # Group the next command under the same correlation_id
    result.process(
        ReserveInventory(order_id=result.aggregate.id),
        correlation_id="checkout-42",
    )
    return result


# --8<-- [end:dsl]


# --8<-- [start:trace_causation]
def show_causation(message_id, some_message):
    store = domain.event_store.store

    # From a message ID string, such as "myapp::order-abc123-0.1"
    chain = store.trace_causation(message_id)

    # From a Message object
    chain = store.trace_causation(some_message)

    # chain = [root_command, ..., target_message]
    for msg in chain:
        print(
            f"{msg.metadata.headers.type} (caused by {msg.metadata.domain.causation_id})"
        )
    return chain


# --8<-- [end:trace_causation]


# --8<-- [start:trace_effects]
def show_effects(store, command_id):
    # All downstream effects (recursive)
    effects = store.trace_effects(command_id)

    # Only direct children (one level)
    direct = store.trace_effects(command_id, recursive=False)
    return effects, direct


# --8<-- [end:trace_effects]


# --8<-- [start:tree]
from protean.port.event_store import CausationNode


def show_tree(store, correlation_id):
    root: CausationNode | None = store.build_causation_tree(correlation_id)

    if root:
        print(f"{root.kind} {root.message_type}")  # e.g., "COMMAND App.PlaceOrder.v1"
        for child in root.children:
            print(f"  {child.kind} {child.message_type}")


# --8<-- [end:tree]

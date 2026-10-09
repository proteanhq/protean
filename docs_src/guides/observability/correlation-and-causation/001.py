# --8<-- [start:model]
from protean import Domain, current_domain, handle
from protean.fields import Dict, Identifier, List, String

domain = Domain(name="Shipping")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)
    status: String(default="PLACED")


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class ConfirmOrder:
    order_id: Identifier(required=True)


@domain.event(part_of=Order)
class OrderConfirmed:
    order_id: Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        order = Order(customer_id=command.customer_id, items=command.items)
        order.raise_(OrderPlaced(order_id=order.id))
        current_domain.repository_for(Order).add(order)

    @handle(ConfirmOrder)
    def confirm(self, command: ConfirmOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.status = "CONFIRMED"
        order.raise_(OrderConfirmed(order_id=order.id))
        repo.add(order)


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def confirm_order(self, event: OrderPlaced) -> None:
        current_domain.process(ConfirmOrder(order_id=event.order_id))


# --8<-- [end:model]


# --8<-- [start:process]
def place_order(items):
    # This is all you need. Both IDs are set automatically.
    domain.process(PlaceOrder(customer_id="cust-123", items=items))


# --8<-- [end:process]


# --8<-- [start:explicit]
def place_order_from_gateway(items):
    domain.process(
        PlaceOrder(customer_id="cust-123", items=items),
        correlation_id="req-abc-123-from-gateway",
    )


# --8<-- [end:explicit]


# --8<-- [start:ids]
def trace_ids(event, message):
    # On a command or event object
    event_ids = (
        event._metadata.domain.correlation_id,  # "ext-123"
        event._metadata.domain.causation_id,  # "myapp::order:command-abc123-0"
    )

    # On a deserialized Message
    message_ids = (
        message.metadata.domain.correlation_id,
        message.metadata.domain.causation_id,
    )
    return event_ids, message_ids


# --8<-- [end:ids]


# --8<-- [start:traverse]
def traverse(some_message, command_message):
    store = domain.event_store.store

    # Walk UP from a message to the root command
    chain = store.trace_causation(some_message)
    # Returns [root_command, ..., target_message]

    # Walk DOWN from a command to find all its effects
    effects = store.trace_effects(command_message)
    # Returns downstream events/commands in chronological order

    # Build the full tree for a correlation ID
    root = store.build_causation_tree("ext-123")
    # Returns a CausationNode with .children recursively populated

    return chain, effects, root


# --8<-- [end:traverse]


# --8<-- [start:correlation-trace]
def print_chain():
    chain = domain.correlation_trace("ext-123")
    for node in chain:
        print(f"{node.kind}: {node.message_type}")
    # Returns [] when no messages match the correlation ID.


# --8<-- [end:correlation-trace]


# --8<-- [start:assert-chain]
from protean.testing import assert_chain


def check_order_chain(correlation_id):
    chain = domain.correlation_trace(correlation_id)

    # Compare against element classes...
    assert_chain(chain, [PlaceOrder, OrderPlaced, ConfirmOrder, OrderConfirmed])

    # ...or against fully-qualified type strings:
    assert_chain(
        chain,
        [
            "Shipping.PlaceOrder.v1",
            "Shipping.OrderPlaced.v1",
            "Shipping.ConfirmOrder.v1",
            "Shipping.OrderConfirmed.v1",
        ],
    )


# --8<-- [end:assert-chain]

from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:cross_aggregate]
@domain.aggregate
class Order: ...


@domain.aggregate
class Inventory: ...


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    """Issues ReduceStock to Inventory when an order ships."""


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    """Applies ReduceStock to Inventory and skips an order already applied."""


# --8<-- [end:cross_aggregate]

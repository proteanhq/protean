# --8<-- [start:full]
from protean import Domain
from protean.fields import HasOne, Integer, String

domain = Domain()


@domain.entity(part_of="Warehouse")
class InventoryManager:
    name = String(max_length=100)
    warehouse_ref = String()


@domain.aggregate
class Warehouse:
    name = String(max_length=100, required=True)
    capacity = Integer(min_value=0)
    manager = HasOne("InventoryManager", via="warehouse_ref")


# --8<-- [end:full]

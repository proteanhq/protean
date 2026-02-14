from protean import Domain
from protean.fields import String, Integer, HasOne

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

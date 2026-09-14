"""A slice whose aggregate factory raises its event, defined at module level.

The IR builder derives ``method_edges`` by reading an element's source and matching
an event construction against the registry's recorded qualname, so the classes have
to live at a module's top level: defined inside a test function their qualnames carry
``<locals>`` and the derivation finds nothing, which would make a test asserting the
key's presence pass for the wrong reason.

Used by ``test_aggregate_with_a_raising_factory_still_emits`` to check that the
emitter treats that derived key as droppable rather than refusing the slice.
"""

from protean import Domain
from protean.fields.simple import String

domain = Domain(name="Ordering", root_path=".")


@domain.event(part_of="Order")
class OrderCreated:
    order_id = String(max_length=None, required=True)
    name = String(max_length=100, required=True)


@domain.aggregate
class Order:
    name = String(max_length=100, required=True)

    @classmethod
    def create(cls, name):
        order = cls(name=name)
        event = OrderCreated(order_id=order.id, name=name)
        order.raise_(event)
        return order


@domain.command(part_of="Order")
class CreateOrder:
    name = String(max_length=100, required=True)


def build_ir() -> dict:
    domain.init(traverse=False)
    return domain.to_ir()

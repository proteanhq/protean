"""Test domain with only INFO-level diagnostics (no errors or warnings).

- EVENT_WITHOUT_DATA (info): OrderNudged has no fields
- Has a command handler so AGGREGATE_WITHOUT_COMMAND_HANDLER doesn't fire
- Command is handled so UNUSED_COMMAND doesn't fire
"""

from protean import Domain
from protean.fields import String
from protean.utils.mixins import handle

domain = Domain(name="TEST27")


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.command(part_of=Order)
class PlaceOrder:
    name = String(required=True)


@domain.event(part_of=Order)
class OrderNudged:
    pass


@domain.command_handler(part_of=Order)
class OrderHandler:
    @handle(PlaceOrder)
    def place(self, command):
        pass


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderNudged)
    def on_nudged(self, event):
        pass

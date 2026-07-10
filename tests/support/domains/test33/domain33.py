"""Test domain with only INFO diagnostics, gating on info via [lint].level.

Same shape as test27 (EVENT_WITHOUT_DATA info only, no warnings) but sets
``[lint].level = "info"`` so ``protean check`` exits 2 on the info finding.
"""

from protean import Domain
from protean.fields import String
from protean.utils.mixins import handle

domain = Domain(name="TEST33")
domain.config["lint"] = {"level": "info"}


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

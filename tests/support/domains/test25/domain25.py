"""Test domain with diagnostics at multiple severity levels.

- AGGREGATE_WITHOUT_COMMAND_HANDLER (warning): Order has no command handler
- UNUSED_COMMAND (warning): PlaceOrder has no handler
- EVENT_WITHOUT_DATA (info): OrderNudged has no fields
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST25")


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.command(part_of=Order)
class PlaceOrder:
    name = String(required=True)


@domain.event(part_of=Order)
class OrderNudged:
    pass

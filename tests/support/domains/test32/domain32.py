"""Test domain with warnings, opting out of warning gating via [lint].level.

Same shape as test25 (AGGREGATE_WITHOUT_COMMAND_HANDLER + UNUSED_COMMAND
warnings, EVENT_WITHOUT_DATA info) but sets ``[lint].level = "error"`` so
``protean check`` exits 0 — only errors gate CI.
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST32")
domain.config["lint"] = {"level": "error"}


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.command(part_of=Order)
class PlaceOrder:
    name = String(required=True)


@domain.event(part_of=Order)
class OrderNudged:
    pass

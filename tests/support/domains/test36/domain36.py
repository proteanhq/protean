"""Test domain with a malformed ``[lint].suppressions`` value.

The count must be a non-negative integer; a string here would otherwise crash
the IR build. ``protean check`` must reject it with a clean CLI error (exit 1),
mirroring the ``[lint].level`` validation.
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST36")
domain.config["lint"] = {"suppressions": {"AGGREGATE_WITHOUT_COMMAND_HANDLER": "3"}}


@domain.aggregate
class Order:
    name = String(max_length=100)

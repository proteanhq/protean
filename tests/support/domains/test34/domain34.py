"""Test domain with an invalid ``[lint].level`` value.

``protean check`` must reject the value with a CLI error (exit 1) before
running any diagnostics, mirroring the ``--level`` flag validation.
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST34")
domain.config["lint"] = {"level": "critical"}


@domain.aggregate
class Order:
    name = String(max_length=100)

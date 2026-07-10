"""Test domain with a malformed ``[lint]`` value (not a table at all).

``[lint]`` itself must be a table; a scalar here would otherwise crash the
very first ``[lint]``-scoped config read with a bare ``AttributeError``.
``protean check`` must reject it with a clean CLI error (exit 1), mirroring
the ``[lint].suppressions`` validation.
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST37")
domain.config["lint"] = 5


@domain.aggregate
class Order:
    name = String(max_length=100)

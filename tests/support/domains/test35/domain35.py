"""Test domain with a structural error *and* ``[lint].level = "error"``.

Confirms the error floor is an invariant: even when the operator opts out of
warning gating (``level = "error"``), a structural error still exits 1. Same
error as test26 (identity strategy misconfiguration), but with the level set so
the interaction is actually exercised.
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST35")
domain.config["identity_strategy"] = "function"
domain.config["lint"] = {"level": "error"}


@domain.aggregate
class Order:
    name = String(max_length=100)

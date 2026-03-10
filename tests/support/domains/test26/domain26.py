"""Test domain with a structural error (identity strategy misconfiguration).

Used by CLI tests to exercise error exit code and error display in rich output.
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST26")
domain.config["identity_strategy"] = "function"


@domain.aggregate
class Order:
    name = String(max_length=100)

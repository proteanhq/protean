"""Fixture: the Custom field factory resolves to its first argument's type."""

from protean.domain import Domain
from protean.fields import Custom, String
from protean.integrations.pytest.custom_field_conformance import (
    run_custom_field_conformance,
)

domain = Domain(__file__, "CustomFieldDomain")


class Color:
    """A plain Python class, the kind Custom() exists for."""

    def __init__(self, value: str) -> None:
        self.hex = value


# Custom(X) → X | None
c = Custom(Color)
reveal_type(c)  # E: Revealed type is "tests.ext.fixtures.custom_field.Color | None"

# Custom(X, required=True) → X
c_required = Custom(Color, required=True)
reveal_type(c_required)  # E: Revealed type is "tests.ext.fixtures.custom_field.Color"

# A default makes the field non-optional, as with every built-in factory
c_default = Custom(Color, default=Color("#FFFFFF"))
reveal_type(c_default)  # E: Revealed type is "tests.ext.fixtures.custom_field.Color"


# Assignment style in a decorated element: the attribute carries the custom type
# and the synthesized __init__ accepts it.
@domain.aggregate
class Brand:
    name = String(max_length=50, required=True)
    color = Custom(Color, required=True)


brand = Brand(name="acme", color=Color("#FF0000"))
reveal_type(brand.color)  # E: Revealed type is "tests.ext.fixtures.custom_field.Color"


# The conformance harness takes the Custom() field a type checker sees as the
# custom type itself, so this call must type-check.
run_custom_field_conformance(
    c_required,
    valid_input="#FF0000",
    expected=Color("#FF0000"),
    invalid_input="nope",
)

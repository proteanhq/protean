import re

from protean import Domain

domain = Domain(name="Palettes")


class Color:
    """An RGB color stored as a ``#RRGGBB`` hex string."""

    __slots__ = ("hex",)

    def __init__(self, value: str) -> None:
        normalized = str(value).upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized):
            raise ValueError(f"{value!r} is not a '#RRGGBB' hex color")
        self.hex = normalized

    def to_dict(self) -> str:
        return self.hex

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Color) and other.hex == self.hex

    def __hash__(self) -> int:
        return hash(self.hex)

    def __repr__(self) -> str:
        return f"Color({self.hex!r})"


def parse_color(value: object) -> Color:
    """Parse a raw value into a Color, accepting an existing Color unchanged."""
    if isinstance(value, Color):
        return value
    return Color(value)  # type: ignore[arg-type]


# --8<-- [start:conformance]
from pydantic import PlainSerializer, PlainValidator

from protean.fields import Custom
from protean.integrations.pytest.custom_field_conformance import (
    run_custom_field_conformance,
)


def test_color_field_conformance():
    field = Custom(
        Color,
        validators=[PlainValidator(parse_color)],
        serializers=[PlainSerializer(lambda c: c.hex, return_type=str)],
        required=True,
    )
    run_custom_field_conformance(
        field,
        valid_input="#3366ff",
        expected=Color("#3366FF"),
        invalid_input="not-a-color",
    )


# --8<-- [end:conformance]

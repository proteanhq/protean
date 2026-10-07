# --8<-- [start:color]
import re


class Color:
    """An RGB color stored as a ``#RRGGBB`` hex string."""

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


def parse_color(value: object) -> Color:
    if isinstance(value, Color):
        return value
    return Color(value)


# --8<-- [end:color]


# --8<-- [start:test]
from pydantic import PlainSerializer, PlainValidator

from protean.fields import Custom


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


# --8<-- [end:test]


# The test above calls this name at run time, so the import can sit last.
# --8<-- [start:import]
from protean.integrations.pytest.custom_field_conformance import (
    run_custom_field_conformance,
)
# --8<-- [end:import]

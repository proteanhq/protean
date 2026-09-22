# --8<-- [start:full]
import re

from pydantic import PlainSerializer, PlainValidator

from protean import Domain
from protean.fields import Custom, String

domain = Domain()


# --8<-- [start:type]
class Color:
    """An RGB color stored as a ``#RRGGBB`` hex string."""

    __slots__ = ("hex",)

    def __init__(self, value: str) -> None:
        normalized = str(value).upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized):
            raise ValueError(f"{value!r} is not a '#RRGGBB' hex color")
        self.hex = normalized

    def to_dict(self) -> str:
        # ResolvedField.as_dict() calls this on the persistence and event path,
        # so the stored form is a plain string that round-trips.
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


# --8<-- [end:type]


# --8<-- [start:field]
@domain.aggregate(fact_events=True)
class Palette:
    name: String(required=True)
    brand: Custom(
        Color,
        validators=[PlainValidator(parse_color)],
        serializers=[PlainSerializer(lambda color: color.hex, return_type=str)],
        required=True,
    )


# --8<-- [end:field]
# --8<-- [end:full]

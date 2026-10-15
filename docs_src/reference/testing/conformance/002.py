import importlib.util
from pathlib import Path

# The Color type is the one the custom-fields guide defines. Its folder name
# has a hyphen, so it loads by file path.
_spec = importlib.util.spec_from_file_location(
    "custom_fields_example",
    Path(__file__).parents[3] / "guides/domain-definition/fields/custom-fields/001.py",
)
_example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_example)
Color = _example.Color
parse_color = _example.parse_color


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
